"""scripts/publish_snapshot.py, against repositories built under tmp_path.

Each test makes a "private" repository (two commits on `main`, a tag) and a
"public" clone of an empty bare repository whose origin URL is then set to the
real public address, which the script insists on. Nothing reaches the
network: `GIT_ALLOW_PROTOCOL=file` makes git refuse anything but a local path,
and the one test that pushes rewrites the public address to the bare
repository with the clone's own `url.<base>.insteadOf`. The global git
configuration is a file under tmp_path (`GIT_CONFIG_GLOBAL`), never the
user's. The privacy scan is replaced by a recording stub: it reads this
machine's identity and config by design, so it never runs for real here.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "publish_snapshot.py"

PUBLIC_URL = "https://github.com/sensei-top/sensei-top.git"
NOREPLY = "1234+qzxsynthhandle@users.noreply.github.com"
TAG = "v1.2.3"


def _load():
    spec = importlib.util.spec_from_file_location("publish_snapshot", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c", "user.name=Qzxprivate",
        "-c", "user.email=qzxprivate@example.invalid",
        "commit", "-q", "-m", message,
    )


@pytest.fixture
def git_env(tmp_path, monkeypatch):
    global_config = tmp_path / "gitconfig"
    global_config.write_text(
        "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n[tag]\n\tgpgsign = false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def private(tmp_path, git_env) -> Path:
    """Two commits on main and the tag on the second. Then, untagged and
    uncommitted: an untracked file and an ignored one, neither of which may
    reach the public tree."""
    repo = tmp_path / "private"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("data/\n", encoding="utf-8")
    (repo / "README.md").write_text("first\n", encoding="utf-8")
    _commit(repo, "first")
    (repo / "src").mkdir()
    (repo / "src" / "planted.py").write_text("TRACKED = True\n", encoding="utf-8")
    (repo / "README.md").write_text("second\n", encoding="utf-8")
    _commit(repo, "second")
    _git(repo, "tag", TAG)
    (repo / "untracked.txt").write_text("not committed\n", encoding="utf-8")
    (repo / "data").mkdir()
    (repo / "data" / "ignored.txt").write_text("gitignored\n", encoding="utf-8")
    return repo


@pytest.fixture
def bare(tmp_path, git_env) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    return origin


@pytest.fixture
def public(tmp_path, bare) -> Path:
    """An empty clone of the bare repository, pointed at the public address
    and given the public identity in its own configuration."""
    clone = tmp_path / "public"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(clone)], check=True, capture_output=True
    )
    _git(clone, "remote", "set-url", "origin", PUBLIC_URL)
    _git(clone, "config", "--local", "user.name", "Qzxpublic")
    _git(clone, "config", "--local", "user.email", NOREPLY)
    return clone


@pytest.fixture
def scans(monkeypatch):
    """The module, with the scan replaced by a stub that records each
    command and the terms file's content at the time of the call."""
    module = _load()
    calls: list[dict] = []

    def stub(args: list[str]) -> int:
        terms = None
        if "--terms-file" in args:
            terms = Path(args[args.index("--terms-file") + 1]).read_text(encoding="utf-8")
        calls.append({"args": args, "terms": terms, "code": 0})
        return 0

    monkeypatch.setattr(module, "_run_scan_command", stub)
    return module, calls


def _run(module, private: Path, public: Path, *extra: str) -> int:
    return module.main(["--repo", str(private), "--public", str(public), "--tag", TAG, *extra])


def _refs(repo: Path) -> str:
    return _git(repo, "for-each-ref", "--format=%(refname)")


# --- refusals ------------------------------------------------------------


def test_refuses_a_clone_without_a_local_identity(private, public, scans):
    """The commit must carry the clone's own identity; without one, git
    would fall back to the global (personal) one."""
    module, calls = scans
    _git(public, "config", "--local", "--unset", "user.email")
    assert _run(module, private, public) == 1
    assert _refs(public) == ""
    assert calls == []


def test_refuses_an_email_that_is_not_the_noreply_address(private, public, scans):
    module, calls = scans
    _git(public, "config", "--local", "user.email", "qzxpersonal@example.invalid")
    assert _run(module, private, public) == 1
    assert _refs(public) == ""
    assert calls == []


def test_refuses_a_dirty_clone_and_deletes_nothing(private, public, scans):
    """Replacing the tree deletes everything beside .git, so an untracked
    file in the clone must stop the run while it still exists."""
    module, calls = scans
    stray = public / "stray.txt"
    stray.write_text("work in progress\n", encoding="utf-8")
    assert _run(module, private, public) == 1
    assert stray.read_text(encoding="utf-8") == "work in progress\n"
    assert _refs(public) == ""
    assert calls == []


def test_refuses_a_tag_that_is_not_on_main(private, public, scans):
    module, calls = scans
    _git(private, "switch", "-q", "-c", "side")
    (private / "side.txt").write_text("side\n", encoding="utf-8")
    _commit(private, "side")
    _git(private, "tag", "v9.9.9")
    _git(private, "switch", "-q", "main")
    assert module.main(
        ["--repo", str(private), "--public", str(public), "--tag", "v9.9.9"]
    ) == 1
    assert _refs(public) == ""
    assert calls == []


def test_refuses_a_clone_whose_origin_is_not_the_public_repository(private, public, scans):
    module, calls = scans
    _git(public, "remote", "set-url", "origin", "https://github.com/qzxsomeone/sensei-top.git")
    assert _run(module, private, public) == 1
    assert _refs(public) == ""
    assert calls == []


def test_refuses_a_clone_holding_an_ignored_file_and_deletes_nothing(private, public, scans):
    """An ignored file is invisible to a plain status but would be deleted
    with the rest of the tree, so it refuses the run like an untracked one."""
    module, calls = scans
    with (public / ".git" / "info" / "exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("*.secret\n")
    kept = public / "notes.secret"
    kept.write_text("local only\n", encoding="utf-8")
    assert _run(module, private, public) == 1
    assert kept.read_text(encoding="utf-8") == "local only\n"
    assert _refs(public) == ""
    assert calls == []


def test_refuses_a_tag_the_clone_already_holds_on_another_commit(private, public, scans):
    """Only a tag on HEAD is an earlier dry run to reuse; elsewhere it is a
    release already published, and nothing may be stacked on it."""
    module, calls = scans
    _git(public, "commit", "-q", "--allow-empty", "-m", "Release v1.2.3")
    _git(public, "tag", TAG)
    _git(public, "commit", "-q", "--allow-empty", "-m", "Release v1.2.4")
    assert _run(module, private, public) == 1
    assert _git(public, "rev-list", "--count", "HEAD") == "2"
    assert calls == []


# --- the snapshot ----------------------------------------------------------


def test_dry_run_leaves_one_commit_holding_the_tag_tree_and_pushes_nothing(
    private, public, bare, scans
):
    """The public commit's tree is the private tag's tree, byte for byte
    (same tree hash), so neither the private repository's .git, nor its
    untracked or ignored files, nor anything the clone held before can be
    in it. The message names the tag and no private commit."""
    module, calls = scans
    assert _run(module, private, public) == 0

    assert _git(public, "rev-list", "--count", "HEAD") == "1"
    assert _git(public, "rev-parse", "HEAD^{tree}") == _git(private, "rev-parse", f"{TAG}^{{tree}}")
    assert _git(public, "rev-parse", f"{TAG}^{{commit}}") == _git(public, "rev-parse", "HEAD")
    assert _git(public, "symbolic-ref", "HEAD") == "refs/heads/main"

    files = set(_git(public, "ls-files").splitlines())
    assert files == {".gitignore", "README.md", "src/planted.py"}
    assert (public / "src" / "planted.py").read_text(encoding="utf-8") == "TRACKED = True\n"
    assert not (public / "untracked.txt").exists()
    assert not (public / "data").exists()
    assert _git(public, "status", "--porcelain", "--ignored") == ""

    message = _git(public, "log", "-1", "--format=%B")
    assert message.splitlines()[0] == f"Release {TAG}"
    for sha in _git(private, "rev-list", "--all").splitlines():
        assert sha[:7] not in message
    assert _git(public, "log", "-1", "--format=%an|%ae|%cn|%ce") == (
        f"Qzxpublic|{NOREPLY}|Qzxpublic|{NOREPLY}"
    )

    assert _refs(bare) == ""
    assert [call["args"][-1] == "--history" for call in calls] == [False, True]
    assert all(call["args"][call["args"].index("--repo") + 1] == str(public) for call in calls)


def test_private_repository_is_left_as_it_was(private, public, scans):
    module, _calls = scans
    before = (_refs(private), _git(private, "status", "--porcelain", "--ignored"))
    assert _run(module, private, public) == 0
    assert (_refs(private), _git(private, "status", "--porcelain", "--ignored")) == before


def test_push_after_a_dry_run_publishes_the_inspected_commit(private, public, bare, scans):
    """The documented sequence is a dry run, then --push: the second run
    must reuse the commit the first one left rather than refuse its tag."""
    module, calls = scans
    _git(public, "config", "--local", f"url.{bare}.insteadOf", PUBLIC_URL)
    assert _run(module, private, public) == 0
    inspected = _git(public, "rev-parse", "HEAD")

    assert _run(module, private, public, "--push") == 0
    assert _git(public, "rev-list", "--count", "HEAD") == "1"
    assert _git(bare, "rev-parse", "refs/heads/main") == inspected
    assert _git(bare, "rev-parse", f"refs/tags/{TAG}") == inspected
    assert len(calls) == 4


def test_a_scan_finding_stops_the_push(private, public, bare, scans, monkeypatch):
    module, _calls = scans
    _git(public, "config", "--local", f"url.{bare}.insteadOf", PUBLIC_URL)
    seen: list[list[str]] = []

    def finding(args: list[str]) -> int:
        seen.append(args)
        return 1

    monkeypatch.setattr(module, "_run_scan_command", finding)
    assert _run(module, private, public, "--push") == 1
    assert len(seen) == 1  # the tree scan failed; --history never ran
    assert _refs(bare) == ""


def test_scan_gets_the_private_database_and_origin_account(private, public, scans):
    """The clone has no database and its origin names the project, so the
    scan would lose the database's terms and the maintainer's handle unless
    both come from the private repository."""
    module, calls = scans
    _git(private, "remote", "add", "origin", "https://github.com/qzxsynthowner/private.git")
    database = private / "data" / "sensei-top.db"
    database.write_bytes(b"")
    assert _run(module, private, public) == 0
    for call in calls:
        args = call["args"]
        assert args[args.index("--db") + 1] == str(database)
        assert call["terms"] == "git-account\tqzxsynthowner\n"


def test_scan_gets_no_database_or_terms_when_the_private_repository_has_neither(
    private, public, scans
):
    module, calls = scans
    assert _run(module, private, public) == 0
    for call in calls:
        assert "--db" not in call["args"]
        assert "--terms-file" not in call["args"]


def test_global_excludes_do_not_drop_a_tracked_file(private, public, tmp_path, scans):
    """A global excludes file matching a tracked path (a `*.log` pattern
    would drop every fixture) must not keep that file out of the commit."""
    module, _calls = scans
    excludes = tmp_path / "global-excludes"
    excludes.write_text("*.py\n", encoding="utf-8")
    # POSIX form: git's config parser reads a backslash as an escape, so a
    # Windows path written as-is makes the whole global config unparsable.
    with (tmp_path / "gitconfig").open("a", encoding="utf-8") as config:
        config.write(f"[core]\n\texcludesFile = {excludes.as_posix()}\n")
    assert _run(module, private, public) == 0
    assert "src/planted.py" in _git(public, "ls-files").splitlines()
    assert _git(public, "rev-parse", "HEAD^{tree}") == _git(private, "rev-parse", f"{TAG}^{{tree}}")


def test_configured_signing_is_not_applied(private, public, scans):
    """A signature would name a key the scan never reads, and a signed tag
    is an annotated one: the tag stays lightweight, pointing at the commit."""
    module, _calls = scans
    _git(public, "config", "--local", "commit.gpgsign", "true")
    _git(public, "config", "--local", "tag.gpgsign", "true")
    assert _run(module, private, public) == 0
    assert _git(public, "cat-file", "-t", TAG) == "commit"
    assert "gpgsig" not in _git(public, "cat-file", "commit", "HEAD")
