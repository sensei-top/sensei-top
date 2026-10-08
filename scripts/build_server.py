"""Freeze the server with PyInstaller, then smoke-test the result.

    uv run python scripts/build_server.py               # web build if stale, freeze, smoke
    uv run python scripts/build_server.py --smoke-only  # only smoke-test an existing dist

The output is ``desktop/server/dist/sensei-top/`` (a PyInstaller ``--onedir``
build; both work directories are gitignored). The smoke test is the test for
this step (``docs/architecture.md``, "The frozen server"); it is not part of
``pytest -q`` because the build takes minutes. It writes only inside a temporary
directory: its own database, config home and working directory, and a
fixture log from ``tests/fixtures``. Its child processes get a temporary
config home, a failing keyring backend (the real keyring is never opened
except by the Windows ``doctor`` check, which reads no credential), no API
keys and no refresh jobs. Windows and Linux alike.

Between the freeze and the smoke test, ``collect_licences`` writes
``licenses/`` beside the executable: the licence files of every runtime Python
distribution (``uv export --no-dev``, environment markers evaluated here), of
CPython, PyInstaller and its contributed run-time hooks
(pyinstaller-hooks-contrib), and the vendored texts in ``desktop/server/licenses``
(``docs/attribution.md``). It fails when a distribution yields no file, and
when the freeze bundled a module from a distribution outside the runtime set
(read from PyInstaller's own TOCs), so nothing ships without its notice. The
smoke test checks the folder is there.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.request
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "desktop" / "server"
SPEC = SERVER_DIR / "sensei-top.spec"
DEFAULT_DIST = SERVER_DIR / "dist"
WORK = SERVER_DIR / "build" / "work"
WEB = ROOT / "web"
WEB_DIST = ROOT / "src" / "sensei_top" / "web_dist"
FIXTURE = ROOT / "tests" / "fixtures" / "match_session.log"

READY_TIMEOUT = 60  # D6: the shell waits this long for the ready line
EXIT_TIMEOUT = 30

LICENCES = SERVER_DIR / "licenses"  # vendored by hand; copied into the dist
# The python-build-standalone releases whose dependency licences were compared
# against LICENCES / "cpython-deps"; a runtime from any other release stops the build.
VENDORED_PBS_TAGS = ("20260623", "20260807")
LICENCE_NAMES = ("LICEN", "COPYING", "NOTICE")
# Top-level names the freeze bundles that belong to no installed distribution,
# compared in lower case: the project itself (an editable install has none to
# map), libgcc (the libgcc notice), and the runtime CPython ships with.
# CPython's notice and cpython-deps cover that runtime: its generated sysconfig
# data and shared library, PyInstaller's python3.X/ folder of extension
# modules, and on Windows python-build-standalone 20260623's DLLs.
UNMAPPED_OK_NAMES = {
    "sensei_top", "libgcc_s",
    "python312", "python3", "vcruntime140", "vcruntime140_1",
    "libcrypto-3-x64", "libssl-3-x64", "libffi-8",
}
UNMAPPED_OK_PREFIXES = ("_sysconfigdata_", "libpython3", "python3")

README = """\
Licence texts for the software the Sensei Top server is built from.

python/                 One folder per Python library, holding every licence
                        file the library ships. INDEX.txt lists each library
                        with its version and licence.
cpython-<version>/      The Python runtime's licence, and in deps/ the
                        licences of the libraries compiled into it.
pyinstaller-<version>/  PyInstaller, which packages the server.
pyinstaller-hooks-contrib-<version>/
                        Run-time hooks from PyInstaller's contributed
                        hooks, run when the server starts.
libgcc/                 GCC's runtime library (Linux only).

The licences of the libraries built into the dashboard are in its
third-party-notices.txt, shown under Credits in the dashboard's Settings.
Electron's and Chromium's are LICENSE.electron.txt and LICENSES.chromium.html,
in the folder the app is installed in. Sensei Top's own licence, the GNU Affero
General Public License version 3, is the LICENSE file in the app's resources
folder.
"""


def _step(text: str) -> None:
    print(f"==> {text}", flush=True)


def _fail(text: str) -> None:
    sys.exit(f"FAILED: {text}")


def web_is_stale() -> bool:
    """True when ``web_dist`` is missing or older than the dashboard's sources."""
    built = WEB_DIST / "index.html"
    if not built.is_file():
        return True
    newest = 0.0
    for folder in (WEB / "src", WEB / "public"):
        if folder.is_dir():
            for path in folder.rglob("*"):
                if path.is_file():
                    newest = max(newest, path.stat().st_mtime)
    for name in ("index.html", "package.json", "vite.config.ts", "tsconfig.json"):
        path = WEB / name
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    return newest > built.stat().st_mtime


def build_web() -> None:
    pnpm = shutil.which("pnpm")  # pnpm.cmd on Windows
    if pnpm is None:
        _fail("web_dist is missing or stale and pnpm is not on PATH")
    _step("pnpm build (web_dist is stale)")
    subprocess.run([pnpm, "build"], cwd=WEB, check=True)


def freeze(dist: Path) -> None:
    _step("PyInstaller")
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller", str(SPEC),
            "--noconfirm", "--clean",
            "--workpath", str(WORK), "--distpath", str(dist),
        ],
        cwd=ROOT,
        check=True,
    )


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _runtime_requirements() -> list[str]:
    """Names of the runtime distributions that apply on this platform."""
    from packaging.markers import Marker  # a PyInstaller dependency

    uv = shutil.which("uv")
    if uv is None:
        _fail("uv is not on PATH; it lists the runtime distributions")
    done = subprocess.run(
        [uv, "export", "--no-dev", "--no-hashes", "--no-emit-project",
         "--format", "requirements-txt"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    names = []
    for line in done.stdout.splitlines():
        if line.startswith("-e"):
            _fail(f"an editable requirement in the runtime set: {line!r}")
        if not line.strip() or line[0] in " #-":
            continue
        requirement, _, marker = line.partition(";")
        name = re.split(r"[=<>!~ \[]", requirement.strip(), maxsplit=1)[0]
        if marker.strip() and not Marker(marker.strip()).evaluate():
            continue
        if _normalize(name) != "sensei-top":
            names.append(name)
    return names


def _dist_info(dist: metadata.Distribution) -> Path:
    for entry in dist.files or []:
        for part in entry.parts:
            if part.endswith(".dist-info"):
                return Path(dist.locate_file(part))
    _fail(f"{dist.metadata['Name']} has no dist-info folder")


def _licence_files(dist: metadata.Distribution) -> list[Path]:
    """The files named by ``License-File`` headers, else any licence-looking
    file in the dist-info folder."""
    info = _dist_info(dist)
    declared = dist.metadata.get_all("License-File") or []
    found = []
    for value in declared:
        # PEP 639 (Metadata 2.4) puts them under licenses/; older wheels
        # put them beside METADATA.
        for path in (info / "licenses" / value, info / value):
            if path.is_file():
                found.append(path)
                break
        else:
            _fail(f"{dist.metadata['Name']} declares {value} but it is not in {info}")
    if not declared:
        found = sorted(
            path for path in info.rglob("*")
            if path.is_file() and path.name.upper().startswith(LICENCE_NAMES)
        )
    return found


def _copy_flat(files: list[Path], base: Path, target: Path) -> list[str]:
    """Copy into ``target`` by file name; on a collision use the path relative
    to ``base`` with its separators replaced."""
    target.mkdir(parents=True, exist_ok=True)
    names = []
    for path in files:
        name = path.name
        if name in names:
            name = "__".join(path.relative_to(base).parts)
        shutil.copy2(path, target / name)
        names.append(name)
    return names


def _licence_text(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    text = (meta.get("License") or "").strip()
    if text:
        return text.splitlines()[0]
    classifiers = [
        c.split(" :: ")[-1] for c in meta.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    return " / ".join(classifiers) or "unknown"


def _bundled_top_levels() -> set[str]:
    """Top-level module names the freeze bundled, from PyInstaller's TOCs:
    PYZ for pure Python, COLLECT for extension modules and binaries. It also
    reads the PKG's PYSOURCE entries (run-time hooks), which it fails on when
    they come from anywhere but PyInstaller, its contributed hooks or the
    spec's generated entry script."""
    import ast

    work = WORK / "sensei-top"
    names: set[str] = set()
    pyz = ast.literal_eval((work / "PYZ-00.toc").read_text(encoding="utf-8"))
    for entry in pyz[1]:
        names.add(entry[0].split(".")[0])
    collect = ast.literal_eval((work / "COLLECT-00.toc").read_text(encoding="utf-8"))
    for entry in collect[0]:
        if entry[-1] in ("EXTENSION", "BINARY"):
            names.add(Path(entry[0]).parts[0].split(".")[0])
    # The executable embeds run-time hooks as PYSOURCE entries of the PKG.
    # Attribute those by where the source file lives.
    pkg = ast.literal_eval((work / "PKG-00.toc").read_text(encoding="utf-8"))
    for name, source, kind in pkg[2]:
        if kind != "PYSOURCE":
            continue
        parts = Path(source).parts
        if "PyInstaller" in parts or "_pyinstaller_hooks_contrib" in parts:
            continue  # both have their notices collected
        if Path(source).resolve() == (SERVER_DIR / "build" / "entry.py").resolve():
            continue  # written by the spec
        _fail(f"the executable embeds {name!r} from {source}, which has no notice")
    return names


def _check_bundled(runtime: set[str]) -> None:
    owners = metadata.packages_distributions()
    for name in sorted(_bundled_top_levels()):
        if name in sys.stdlib_module_names:
            continue
        dists = owners.get(name)
        if not dists:
            lower = name.lower()
            if lower not in UNMAPPED_OK_NAMES and not lower.startswith(UNMAPPED_OK_PREFIXES):
                print(f"WARNING: bundled module {name!r} belongs to no distribution", flush=True)
            continue
        allowed = runtime | {"sensei-top", "pyinstaller", "pyinstaller-hooks-contrib"}
        # A name passes when any one of its owners is a runtime distribution.
        if not any(_normalize(d) in allowed for d in dists):
            _fail(
                f"the freeze bundled {name!r} from {dists}, which is not a runtime "
                "distribution; exclude it in sensei-top.spec or collect its notice"
            )


def collect_licences(dist: Path) -> None:
    _step("licence notices")
    out = dist / "sensei-top" / "licenses"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    (out / "README.txt").write_text(README, encoding="utf-8", newline="\n")

    rows = []
    versions = {}
    requirements = _runtime_requirements()
    _check_bundled({_normalize(name) for name in requirements})
    for name in requirements:
        try:
            installed = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            _fail(f"{name} is a runtime requirement but is not installed")
        version = installed.version
        versions[_normalize(name)] = version
        files = _licence_files(installed)
        if not files:
            _fail(f"{name} {version} ships no licence file")
        folder = out / "python" / f"{_normalize(name)}-{version}"
        names = _copy_flat(files, _dist_info(installed), folder)
        if _normalize(name) == "anthropic":
            # The SDK bundles httpx_aiohttp; a future SDK that drops these
            # files must be noticed, not shipped without them.
            vendored = Path(installed.locate_file("anthropic/_vendor/httpx_aiohttp"))
            extra = [vendored / "LICENSE", vendored / "NOTICE.md"]
            missing = [p.name for p in extra if not p.is_file()]
            if missing:
                _fail(f"anthropic {version} no longer ships httpx_aiohttp {missing}")
            _copy_flat(extra, vendored, folder / "vendor-httpx_aiohttp")
            names.append("vendor-httpx_aiohttp/")
        rows.append((name, version, _licence_text(installed), ", ".join(names)))
    rows.sort(key=lambda row: _normalize(row[0]))
    lines = ["\t".join(row) for row in rows]
    lines += [
        "",
        "orjson is in part under the Mozilla Public License 2.0, unmodified. Its "
        f"source is at https://github.com/ijl/orjson/releases/tag/{versions.get('orjson', '?')} "
        "and in its source distribution on PyPI.",
    ]
    if "orjson" not in versions:
        _fail("orjson is not a runtime requirement; the INDEX paragraph is stale")
    (out / "python" / "INDEX.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    prefix = Path(sys.base_prefix)
    major, minor, micro = sys.version_info[:3]
    if sys.platform == "win32":
        source = prefix / "LICENSE.txt"
    else:
        source = prefix / "lib" / f"python{major}.{minor}" / "LICENSE.txt"
    if not source.is_file():
        _fail(f"CPython's licence is not at {source}")
    cpython = out / f"cpython-{major}.{minor}.{micro}"
    cpython.mkdir()
    shutil.copy2(source, cpython / "LICENSE.txt")
    shutil.copytree(LICENCES / "cpython-deps", cpython / "deps")
    build = prefix / "BUILD"
    tag = build.read_text(encoding="utf-8").strip() if build.is_file() else None
    if tag not in VENDORED_PBS_TAGS:
        _fail(
            f"the Python runtime's build tag is {tag!r} but the vendored "
            f"dependency licences were compared for {', '.join(VENDORED_PBS_TAGS)}; "
            "the build stops until the folder is re-checked and the tags updated "
            "(desktop/server/licenses/cpython-deps/SOURCE.txt)"
        )

    for tool in ("pyinstaller", "pyinstaller-hooks-contrib"):
        installed = metadata.distribution(tool)
        files = _licence_files(installed)
        if not files:
            _fail(f"{tool} {installed.version} ships no licence file")
        _copy_flat(files, _dist_info(installed), out / f"{tool}-{installed.version}")

    if any((dist / "sensei-top" / "_internal").rglob("libgcc_s*")):
        shutil.copytree(LICENCES / "libgcc", out / "libgcc")


def check_licences(dist: Path) -> None:
    out = dist / "sensei-top" / "licenses"
    for path in (out / "README.txt", out / "python" / "INDEX.txt"):
        if not path.is_file():
            _fail(f"{path} is missing; the licence step did not run")
    if not list(out.glob("pyinstaller-hooks-contrib-*/*")):
        _fail("no pyinstaller-hooks-contrib-* folder in the dist's licenses folder")
    if not list(out.glob("cpython-*/LICENSE.txt")):
        _fail("no cpython-*/LICENSE.txt in the dist's licenses folder")


def executable(dist: Path) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return dist / "sensei-top" / f"sensei-top{suffix}"


def _run(exe: Path, args: list[str], env: dict[str, str], cwd: Path) -> str:
    done = subprocess.run(
        [str(exe), *args], env=env, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300, stdin=subprocess.DEVNULL,
    )
    if done.returncode != 0:
        _fail(f"{' '.join(args)} exited {done.returncode}\n{done.stdout}\n{done.stderr}")
    return done.stdout


def _read_ready_line(proc: subprocess.Popen) -> int:
    """The port from the first line of stdout that parses as the ready line."""
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + READY_TIMEOUT
    seen: list[str] = []
    while True:
        try:
            line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
        except queue.Empty:
            line = ""
        if line is None:
            _fail(f"serve exited before its ready line; stdout was {seen!r}")
        if time.monotonic() > deadline:
            _fail(f"no ready line in {READY_TIMEOUT} s; stdout was {seen!r}")
        seen.append(line)
        try:
            return int(json.loads(line)["listening"])
        except (ValueError, KeyError, TypeError):
            continue


def _frozen_processes(dist: Path) -> list[int]:
    """Pids of running processes whose executable is the frozen one (Linux
    only: /proc; elsewhere nothing is checked and the list is empty)."""
    root = str((dist / "sensei-top").resolve())
    found = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if entry.name.isdigit():
            try:
                if os.readlink(entry / "exe").startswith(root):
                    found.append(int(entry.name))
            except OSError:
                continue
    return found


def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read())


def _serve_check(
    dist: Path, args: list[str], env: dict[str, str], cwd: Path, expected: str, watch: bool,
) -> None:
    exe = executable(dist)
    before = set(_frozen_processes(dist))
    proc = subprocess.Popen(
        [str(exe), *args, "serve", "--port", "0", "--ready-line", "--exit-on-stdin-close",
         "--no-archetype-refresh", "--no-reference-refresh", "--no-corpus-refresh",
         *(["--watch", "--file", str(FIXTURE), "--no-mtgo"] if watch else [])],
        env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    try:
        port = _read_ready_line(proc)
        base = f"http://127.0.0.1:{port}"
        health = _get_json(f"{base}/api/health")
        if health.get("status") != "ok":
            _fail(f"/api/health reported {health!r}")
        # The app's version comes from importlib.metadata: it is the
        # frozen build's dist-info that this proves is there.
        served = _get_json(f"{base}/openapi.json")["info"]["version"]
        if served != expected:
            _fail(f"the API reports version {served!r}, expected {expected}")
        with urllib.request.urlopen(f"{base}/", timeout=15) as response:
            if b'<div id="root"' not in response.read():
                _fail("/ did not serve the bundled dashboard")
        if watch:
            # In this fresh database only the watcher child writes
            # raw_events (serve never ingests), so events > 0 proves the
            # child ran its target and read the fixture. `watching` alone is
            # is_alive(), which a spawned child still booting (or about to
            # run the CLI again for lack of freeze_support) satisfies.
            deadline = time.monotonic() + 30
            live = _get_json(f"{base}/api/live")
            while not live.get("events"):
                if time.monotonic() > deadline:
                    _fail("the watcher child ingested nothing in 30 s")
                time.sleep(0.5)
                live = _get_json(f"{base}/api/live")
            if not live.get("watching") or live.get("watcher_stopped"):
                _fail(f"the watcher is not running after ingesting: {live!r}")
        _step("closing stdin")
        proc.stdin.close()
        try:
            code = proc.wait(timeout=EXIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            _fail(f"serve still running {EXIT_TIMEOUT} s after stdin closed")
        if code != 0:
            _fail(f"serve exited {code} after stdin closed")
        time.sleep(1)
        orphans = set(_frozen_processes(dist)) - before
        if orphans:
            _fail(f"{len(orphans)} frozen process(es) outlived serve")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def smoke(dist: Path) -> None:
    exe = executable(dist)
    if not exe.is_file():
        _fail(f"{exe} does not exist; build first")
    check_licences(dist)
    with open(ROOT / "pyproject.toml", "rb") as handle:
        expected = tomllib.load(handle)["project"]["version"]

    with tempfile.TemporaryDirectory(
        prefix="sensei-top-smoke-", ignore_cleanup_errors=True,
    ) as tmp_name:
        tmp = Path(tmp_name)
        cwd = tmp / "cwd"
        cwd.mkdir()
        db = tmp / "smoke.db"
        dropped = ("MTGA_LOG", "SENSEI_TOP_SESSION", "ANTHROPIC_API_KEY", "TOPDECK_API_KEY")
        env = {
            k: v for k, v in os.environ.items()
            if k not in dropped and not k.startswith("MTGO_")
        }
        # The same isolation tests/conftest.py gives a test: no config, no
        # real keyring, nothing under the real home directory.
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
        env["XDG_CONFIG_HOME"] = str(tmp / "config")
        env["APPDATA"] = str(tmp / "config")
        env["LOCALAPPDATA"] = str(tmp / "localappdata")
        env["HOME"] = str(tmp / "home")
        env["USERPROFILE"] = str(tmp / "home")
        env["SENSEI_TOP_BACKUP_DIR"] = str(tmp / "backups")

        _step("--version")
        got = _run(exe, ["--version"], env, cwd).strip()
        if got != expected:
            _fail(f"--version printed {got!r}, pyproject says {expected!r}")

        _step("doctor --json")
        report = json.loads(_run(
            exe, ["--db", str(db), "doctor", "--json", "--file", str(FIXTURE)], env, cwd,
        ))
        if not isinstance(report, dict):
            _fail("doctor --json did not print an object")
        if sys.platform == "win32":
            # Credential Manager's backend must import in the frozen build.
            # Naming it reads no credential (doctor only reports its name).
            _step("doctor --json with the Windows keyring backend")
            win_env = dict(env, PYTHON_KEYRING_BACKEND="keyring.backends.Windows.WinVaultKeyring")
            win = json.loads(_run(
                exe, ["--db", str(db), "doctor", "--json", "--file", str(FIXTURE)], win_env, cwd,
            ))
            if not win.get("keyring_backend"):
                _fail("doctor reported no keyring backend under WinVaultKeyring")

        _step("ingest + project a fixture (the frozen executable itself)")
        _run(exe, ["--db", str(db), "ingest", "--file", str(FIXTURE), "--locale", "mdy"], env, cwd)
        _run(exe, ["--db", str(db), "project"], env, cwd)

        _step("serve --port 0 --ready-line --exit-on-stdin-close")
        _serve_check(dist, ["--db", str(db)], env, cwd, expected, watch=False)

        _step("serve --watch --file FIXTURE (the watcher child)")
        _serve_check(dist, ["--db", str(tmp / "watch.db")], env, cwd, expected, watch=True)
    _step("smoke test passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--smoke-only", action="store_true",
        help="skip the web and PyInstaller builds; smoke-test the existing dist",
    )
    parser.add_argument(
        "--dist", type=Path, default=DEFAULT_DIST,
        help="PyInstaller's distpath (default: desktop/server/dist)",
    )
    args = parser.parse_args()
    started = time.monotonic()
    if not args.smoke_only:
        if web_is_stale():
            build_web()
        freeze(args.dist)
        collect_licences(args.dist)
    smoke(args.dist)
    print(f"total {time.monotonic() - started:.0f} s")


if __name__ == "__main__":
    main()
