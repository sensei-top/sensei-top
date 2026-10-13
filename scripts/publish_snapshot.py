"""Publish one release of this repository as one commit of the public one.

    uv run python scripts/publish_snapshot.py --tag vX.Y.Z --public PATH          # dry run
    uv run python scripts/publish_snapshot.py --tag vX.Y.Z --public PATH --push   # publish

This repository's history cannot be made public (`docs/branching.md`, "The
public repository"), so `github.com/sensei-top/sensei-top` holds one commit
per release instead: the tree at the release tag, nothing else. ``--public``
is a clone of that repository; ``--repo`` is the private one to snapshot,
this script's own repository by default. Every git command names its
repository with ``git -C``, never the current directory, and nothing is
written to the private repository: it is only read (``rev-parse``,
``merge-base``, ``archive``, ``config``).

Checks, in order, each refusing before anything changes:

1. ``--tag`` is ``vX.Y.Z``, exists in the private repository and points at a
   commit on its local ``main``.
2. ``--public`` is the top of a git working tree, not the private repository,
   and its ``remote.origin.url`` is the public repository's address.
3. The clone sets ``user.name`` and ``user.email`` in its **own** configuration
   (``git config --local``), and the email is GitHub's no-reply address. The
   commit is made with that identity; the variables that would override it
   (``GIT_AUTHOR_*``, ``GIT_COMMITTER_*``) are dropped from every git call.
4. The clone's working tree is clean: no change, no untracked file and no
   ignored one either, since replacing the tree deletes everything but
   ``.git`` and an ignored file would go with it unseen.
5. The clone is on ``main``, or has no commit yet (its branch is then named
   ``main``).

Then the clone's tree is replaced by ``git archive`` of the tag (which honours
``export-ignore`` and never carries an untracked or ignored file), committed
unsigned as ``Release vX.Y.Z`` with a body naming the tag and no private
commit hash, checked to hold exactly the tag's tree, and tagged ``vX.Y.Z``, an
unsigned lightweight tag, so no tagger identity or key is written where the
history scan does not read. If the clone already holds that tag on
its ``HEAD``, an earlier dry run made it, and it is reused: this is how the
second invocation, with ``--push``, publishes exactly what the first one let
the user inspect.

`scripts/privacy_scan.py` then runs against the clone, the tree and then
``--history``. The clone has no database and its origin names the project, not
the maintainer, so the scan is also given the private repository's
``data/sensei-top.db`` when it exists and the account in the private
repository's own origin URL as a ``git-account`` term, which keeps the scan as
strict as it is in the working repository. Any finding stops the run before a
push, and the commit stays in the clone to be inspected; delete the tag and
move ``main`` back before running again.

``--push`` pushes ``main`` and the tag to ``origin``. Without it the script
says what it would push and pushes nothing.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PRIVACY_SCAN = SCRIPTS / "privacy_scan.py"
DEFAULT_REPO = SCRIPTS.parent

PUBLIC_REPOSITORY = "sensei-top/sensei-top"
PUBLIC_URLS = frozenset(
    {
        f"https://github.com/{PUBLIC_REPOSITORY}",
        f"https://github.com/{PUBLIC_REPOSITORY}.git",
        f"git@github.com:{PUBLIC_REPOSITORY}",
        f"git@github.com:{PUBLIC_REPOSITORY}.git",
        f"ssh://git@github.com/{PUBLIC_REPOSITORY}",
        f"ssh://git@github.com/{PUBLIC_REPOSITORY}.git",
    }
)
NOREPLY_SUFFIX = "@users.noreply.github.com"
MAIN = "main"
TAG = re.compile(r"v\d+\.\d+\.\d+")
DATABASE = Path("data") / "sensei-top.db"

# Each would point a `git -C` call somewhere else, or commit under another
# identity than the clone's own configuration.
_GIT_ENV_OVERRIDES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_DATE",
)


class SnapshotError(Exception):
    """A refusal. The message names the flag or the check, never a path or
    a configured value: either could be this machine's home folder or the
    maintainer's personal address."""


def _env() -> dict[str, str]:
    env = dict(os.environ)
    for key in _GIT_ENV_OVERRIDES:
        env.pop(key, None)
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=_env()
    )


def _git_out(repo: Path, *args: str) -> str | None:
    """Stripped stdout, or ``None`` when git fails or prints nothing."""
    result = _git(repo, *args)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_or_fail(repo: Path, what: str, *args: str) -> str:
    result = _git(repo, *args)
    if result.returncode != 0:
        raise SnapshotError(f"{what} failed (git {args[0]} exited {result.returncode})")
    return result.stdout.strip()


def _tag_commit(repo: Path, tag: str) -> str | None:
    return _git_out(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")


def _check_tag(repo: Path, tag: str) -> None:
    if not TAG.fullmatch(tag):
        raise SnapshotError("--tag is not vX.Y.Z")
    if _git_out(repo, "rev-parse", "--is-inside-work-tree") != "true":
        raise SnapshotError("--repo is not a git repository")
    commit = _tag_commit(repo, tag)
    if commit is None:
        raise SnapshotError(f"{tag} does not exist in --repo")
    if _git_out(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{MAIN}") is None:
        raise SnapshotError(f"--repo has no {MAIN} branch")
    on_main = _git(repo, "merge-base", "--is-ancestor", commit, f"refs/heads/{MAIN}")
    if on_main.returncode != 0:
        raise SnapshotError(f"{tag} is not on {MAIN} in --repo (update {MAIN} after the merge)")


def _check_clone(repo: Path, public: Path) -> None:
    if not public.is_dir():
        raise SnapshotError("--public is not a directory")
    top = _git_out(public, "rev-parse", "--show-toplevel")
    if top is None or Path(top).resolve() != public.resolve():
        # The tree replacement deletes everything beside .git under --public.
        raise SnapshotError("--public is not the top of a git working tree")
    if public.resolve() == repo.resolve():
        raise SnapshotError("--public is the private repository itself")
    if _git_out(public, "config", "--get", "remote.origin.url") not in PUBLIC_URLS:
        raise SnapshotError(f"--public's origin is not github.com/{PUBLIC_REPOSITORY}")


def _check_identity(public: Path) -> None:
    name = _git_out(public, "config", "--local", "--get", "user.name")
    email = _git_out(public, "config", "--local", "--get", "user.email")
    if name is None or email is None:
        raise SnapshotError(
            "--public sets no user.name and user.email of its own (git config --local)"
        )
    if not email.endswith(NOREPLY_SUFFIX):
        raise SnapshotError(f"--public's local user.email is not a {NOREPLY_SUFFIX} address")


def _check_clean(public: Path) -> None:
    status = _git(public, "status", "--porcelain", "--untracked-files=all", "--ignored")
    if status.returncode != 0:
        raise SnapshotError("git status failed in --public")
    if status.stdout.strip():
        raise SnapshotError("--public has changes, untracked or ignored files; it must be clean")


def _check_branch(public: Path) -> None:
    branch = _git_out(public, "symbolic-ref", "--quiet", "HEAD")
    if branch == f"refs/heads/{MAIN}":
        return
    if _git_out(public, "rev-parse", "--verify", "--quiet", "HEAD") is None:
        _git_or_fail(public, "naming the branch", "symbolic-ref", "HEAD", f"refs/heads/{MAIN}")
        return
    raise SnapshotError(f"--public is not on {MAIN}")


def _replace_tree(repo: Path, tag: str, public: Path) -> None:
    for child in public.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    archive = subprocess.Popen(
        ["git", "-C", str(repo), "archive", "--format=tar", f"refs/tags/{tag}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_env(),
    )
    assert archive.stdout is not None
    # "data" refuses absolute paths, links out of the destination and device files.
    with tarfile.open(fileobj=archive.stdout, mode="r|") as tar:
        tar.extractall(public, filter="data")
    if archive.wait() != 0:
        raise SnapshotError(f"git archive {tag} failed")


def _commit_and_tag(repo: Path, tag: str, public: Path) -> None:
    """``--force``: a plain ``add`` honours the clone's ignore rules, this
    machine's global excludes file among them, and would silently leave out
    a file the tag tracks (a ``*.log`` pattern drops every fixture). Every
    file the archive extracted is tracked at the tag by construction.
    ``--no-gpg-sign`` / ``--no-sign``: a configured ``commit.gpgSign`` or
    ``tag.gpgSign`` would attach a signature naming a key the scan never
    reads, and turn the tag into an annotated one."""
    _git_or_fail(public, "staging the tree", "add", "--all", "--force")
    _git_or_fail(
        public,
        "the commit",
        "commit",
        "--quiet",
        "--no-gpg-sign",
        "-m",
        f"Release {tag}",
        "-m",
        f"The source tree at {tag}.",
    )
    # Equal tree hashes hold while .gitattributes has no export-ignore and the
    # tree holds no submodule; either would make the archive differ from the tag.
    committed = _git_out(public, "rev-parse", "HEAD^{tree}")
    if committed is None or committed != _git_out(repo, "rev-parse", f"refs/tags/{tag}^{{tree}}"):
        raise SnapshotError(
            f"the commit in --public does not hold {tag}'s tree; it is left untagged to "
            f"inspect. Move {MAIN} back before running again."
        )
    _git_or_fail(public, "the tag", "tag", "--no-sign", tag)


def _scan_args(public: Path, repo: Path, terms_file: Path | None, *, history: bool) -> list[str]:
    args = [sys.executable, str(PRIVACY_SCAN), "--repo", str(public)]
    database = repo / DATABASE
    if database.is_file():
        args += ["--db", str(database)]
    if terms_file is not None:
        args += ["--terms-file", str(terms_file)]
    if history:
        args.append("--history")
    return args


def _run_scan_command(args: list[str]) -> int:
    """The one call the tests replace: the scan reads this machine's config
    and identity by design, which no test may do."""
    return subprocess.run(args, env=_env()).returncode


def _private_account(repo: Path) -> str | None:
    """The account in the private repository's origin URL, parsed the way
    the scan parses its own repository's (``_parse_git_account``)."""
    url = _git_out(repo, "remote", "get-url", "origin")
    if url is None:
        return None
    spec = importlib.util.spec_from_file_location("_snapshot_privacy_scan", PRIVACY_SCAN)
    assert spec is not None and spec.loader is not None
    privacy_scan = importlib.util.module_from_spec(spec)
    # Its dataclasses resolve their string annotations through sys.modules.
    sys.modules[spec.name] = privacy_scan
    spec.loader.exec_module(privacy_scan)
    return privacy_scan._parse_git_account(url)


def _scan(public: Path, repo: Path) -> int:
    """The tree scan, then ``--history``: 0 when both are clean, else the
    first one's exit code (1 a finding, 2 an error)."""
    account = _private_account(repo)
    with tempfile.TemporaryDirectory() as scratch:
        terms_file = None
        if account:
            terms_file = Path(scratch) / "terms.tsv"
            terms_file.write_text(f"git-account\t{account}\n", encoding="utf-8")
        for history in (False, True):
            code = _run_scan_command(_scan_args(public, repo, terms_file, history=history))
            if code != 0:
                return code
    return 0


def publish(repo: Path, tag: str, public: Path, *, push: bool) -> int:
    _check_tag(repo, tag)
    _check_clone(repo, public)
    _check_identity(public)
    _check_clean(public)
    _check_branch(public)

    existing = _tag_commit(public, tag)
    if existing is None:
        _replace_tree(repo, tag, public)
        _commit_and_tag(repo, tag, public)
        print(f"committed and tagged {tag} in --public")
    elif existing == _git_out(public, "rev-parse", "--verify", "--quiet", "HEAD"):
        print(f"{tag} is already --public's HEAD (an earlier run); scanning it again")
    else:
        raise SnapshotError(f"{tag} already exists in --public on another commit")

    code = _scan(public, repo)
    if code != 0:
        print(
            f"the privacy scan did not pass (exit {code}): nothing pushed. The commit and "
            f"the tag stay in --public to be inspected; delete {tag} there and move {MAIN} "
            "back before running again.",
            file=sys.stderr,
        )
        return 1

    head = _git_or_fail(public, "reading HEAD", "rev-parse", "--short", "HEAD")
    if not push:
        print(f"dry run: would push {MAIN} ({head}) and {tag} to origin. Run again with --push.")
        return 0
    _git_or_fail(
        public,
        "the push",
        "push",
        "origin",
        f"refs/heads/{MAIN}:refs/heads/{MAIN}",
        f"refs/tags/{tag}:refs/tags/{tag}",
    )
    print(f"pushed {MAIN} ({head}) and {tag} to origin")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="the release tag, vX.Y.Z")
    parser.add_argument("--public", required=True, type=Path, help="the public repository's clone")
    parser.add_argument(
        "--repo",
        type=Path,
        default=DEFAULT_REPO,
        help="the private repository to snapshot (default: the one this script is in)",
    )
    parser.add_argument("--push", action="store_true", help="push main and the tag to origin")
    args = parser.parse_args(argv)
    try:
        return publish(args.repo, args.tag, args.public, push=args.push)
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
