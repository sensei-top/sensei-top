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
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.request
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
    smoke(args.dist)
    print(f"total {time.monotonic() - started:.0f} s")


if __name__ == "__main__":
    main()
