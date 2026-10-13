"""scripts/privacy_scan.py, exercised as a subprocess against synthetic git
repos built under tmp_path -- never the real repo, never a real database.

Every test builds its own throwaway repo with `git -C <path> ...` (never a
shell `cd`, so a test can never bleed into the process's own working
directory) and passes `--no-local`, which makes the automatic local sources
(this machine's config, git identity, the default database) categorically
unreachable rather than merely filtered -- the property that makes running
this suite from the real project checkout safe. Every synthetic term is an
obviously-fake marker (`Qzx...`, `Synth...`) and every test asserts that
marker appears nowhere in the tool's own stdout or stderr, mirroring the
script's own header contract: categories, paths and counts only, never a
term value.

Two tests break that `--no-local`/subprocess pattern on purpose, each for a
reason the pattern itself can't accommodate:
`test_hermetic_run_without_no_local_suppresses_config_loader_warnings` runs
the script *without* `--no-local`, since that flag is exactly what it has to
prove is not required for a clean run -- it substitutes a fully synthetic
HOME/XDG_CONFIG_HOME/git-identity environment instead, so every local source
`--no-local` would otherwise skip has nothing real to find either way.
`test_unexpected_exception_exits_2_without_a_traceback_or_absolute_paths`
loads the script as a module in-process instead of running it as a
subprocess, since it needs to force an unhandled exception at one precise,
otherwise-unreachable point -- not something a subprocess boundary can do
without its own elaborate fault injection.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "privacy_scan.py"

_GIT_CONFIG_FLAGS = [
    "-c", "user.name=Test",
    "-c", "user.email=test@example.invalid",
    "-c", "commit.gpgsign=false",
    "-c", "init.defaultBranch=main",
]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *_GIT_CONFIG_FLAGS, "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")


def _write(repo: Path, rel: str, content: str) -> Path:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _commit_all(repo: Path, message: str = "commit") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _run_scan(
    repo: Path,
    *extra_args: str,
    terms_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the script as a subprocess with this same interpreter
    (`sys.executable`, not `uv run` -- the process already running this test
    has every dependency the script needs), `--no-local` always included.
    `cwd` is the real project checkout; nothing here depends on that
    functionally, since `--repo` and `--db`/`--terms-file` below are always
    absolute paths under tmp_path, but it fixes `cwd` at a location that
    always exists rather than wherever pytest happened to be invoked from.
    `--no-local` means nothing in the process ever reads this machine's own
    config or the real project's own database."""
    args = [sys.executable, str(SCRIPT), "--repo", str(repo), "--no-local"]
    if terms_file is not None:
        args += ["--terms-file", str(terms_file)]
    args.extend(extra_args)

    env = dict(os.environ)
    env["XDG_CONFIG_HOME"] = str(repo.parent / "unused-xdg-config")
    for key in (
        "MTGO_LOG_DIR", "MTGO_HANDLE", "ANTHROPIC_API_KEY",
        "TOPDECK_API_KEY", "MTGA_LOG", "SENSEI_TOP_BACKUP_DIR",
    ):
        env.pop(key, None)

    return subprocess.run(
        args, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=60,
    )


def _make_db(path: Path, *, auth: dict | None = None, matches: list[tuple] | None = None,
             cards: list[str] | None = None) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE raw_events (label TEXT, payload TEXT);
        CREATE TABLE matches (opponent_name TEXT, opponent_user_id TEXT);
        CREATE TABLE cards (name TEXT);
        """
    )
    if auth is not None:
        conn.execute(
            "INSERT INTO raw_events (label, payload) VALUES ('AuthenticateResponse', ?)",
            (json.dumps({"authenticateResponse": auth}),),
        )
    for opponent_name, opponent_user_id in matches or []:
        conn.execute(
            "INSERT INTO matches (opponent_name, opponent_user_id) VALUES (?, ?)",
            (opponent_name, opponent_user_id),
        )
    for name in cards or []:
        conn.execute("INSERT INTO cards (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()


# --- tree scanning -----------------------------------------------------


def test_clean_tree_exits_0_with_no_hit_lines(tmp_path):
    """A term that is nowhere in the tree: no hit line, exit 0, and the term
    still never appears in either stream."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "Nothing interesting here.\n")
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxAbsentTermQQQ\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "QzxAbsentTermQQQ" not in result.stdout
    assert "QzxAbsentTermQQQ" not in result.stderr


def test_tracked_file_with_mixed_case_term_is_reported(tmp_path):
    """A term embedded as a true substring inside a larger token (no word
    boundary on either side) must still be found, case-insensitively, since
    terms-file entries always match as a substring."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "src/foo.py", "token = 'prefixQzxSynthCasesuffix'\n")
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    # Stored case differs from the file's case on purpose.
    terms_file.write_text("mtgo-handle\tQZXSYNTHCASE\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 1
    assert result.stdout.strip() == "mtgo-handle\tsrc/foo.py\t1"
    assert "qzxsynthcase" not in result.stdout.lower()
    assert "qzxsynthcase" not in result.stderr.lower()


def test_term_is_found_when_encoded_utf16le(tmp_path):
    """Some Windows tools write UTF-16LE text by default rather than UTF-8 --
    Windows PowerShell 5.1's `>` redirection and a `regedit` `.reg` export
    both do -- so a file committed from a Windows checkout can carry a term
    in UTF-16LE even though neither of this project's own log formats does
    (MTGO's `.dat` is a .NET BinaryWriter stream: length-prefixed UTF-8, not
    UTF-16). A tracked file holding only a UTF-16LE encoding of the term, at
    a clean 2-byte alignment, must still be caught by the UTF-16LE decoding
    pass (gated on the data containing a NUL byte, which this encoding
    always produces for ASCII-range text). A string starting at an odd byte
    offset is a separate case, covered by
    test_term_is_found_in_odd_offset_utf16."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    target = repo / "src" / "utf16_blob.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes("marker QzxUtf16TermRST here".encode("utf-16-le"))
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxUtf16TermRST\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 1
    assert result.stdout.strip() == "mtgo-handle\tsrc/utf16_blob.bin\t1"
    assert "QzxUtf16TermRST" not in result.stdout
    assert "QzxUtf16TermRST" not in result.stderr


def test_untracked_file_is_ignored(tmp_path):
    """The tool scans `git ls-files`, not the filesystem -- a file sitting in
    the working tree but never added must not be scanned."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "Nothing here.\n")
    _commit_all(repo)
    _write(repo, "scratch/untracked.txt", "QzxUntrackedTermXYZ mentioned here.\n")

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxUntrackedTermXYZ\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "QzxUntrackedTermXYZ" not in result.stdout
    assert "QzxUntrackedTermXYZ" not in result.stderr


def test_path_term_matches_a_relative_mention_without_leading_separator(tmp_path):
    """A path-shaped term (as an automatic source like steam-library would
    produce, with a leading separator) must still match a relative mention of
    that same path with no leading separator -- the universal strip applied
    to every term's value, not just ones this script derived itself."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "notes/paths.md", "See some/mount/QzxSteamLibraryXYZ for details.\n")
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("steam-library\t/some/mount/QzxSteamLibraryXYZ\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 1
    assert result.stdout.strip() == "steam-library\tnotes/paths.md\t1"
    assert "QzxSteamLibraryXYZ" not in result.stdout
    assert "QzxSteamLibraryXYZ" not in result.stderr


# --- filtering -----------------------------------------------------------


def test_three_character_term_is_dropped_as_short(tmp_path):
    """A term under 4 characters is dropped before it is ever compiled --
    counted in the summary's "short" bucket, never checked against a file."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "Contains zzq the short token.\n")
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tzzq\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "dropped 1 short, 0 generic, 0 card-word" in result.stderr
    assert "zzq" not in result.stderr


def test_opponent_name_matching_a_card_word_is_dropped_and_counted(tmp_path):
    """An opponent handle that happens to equal a whole word from a real card
    name is filtered out before it ever becomes a searchable term, and the
    drop is counted, not silently absorbed -- the mechanism from the spec's
    card-word filter, proven with a synthetic collision rather than a real
    card name so the test needs no real cards-table fixture."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/mentions.md", "We fought Widget today.\n")
    _commit_all(repo)

    db_path = tmp_path / "scratch.db"
    _make_db(db_path, matches=[("Widget", None)], cards=["Widget, Friendly Helper"])

    result = _run_scan(repo, "--db", str(db_path))
    assert result.returncode == 0
    assert result.stdout == ""
    assert "dropped 0 short, 0 generic, 1 card-word" in result.stderr
    assert "Widget" not in result.stdout
    assert "Widget" not in result.stderr


# --- the database (amendment 2, 3, 7) -----------------------------------


def test_explicit_db_yields_arena_name_arena_id_and_opponent_hits(tmp_path):
    """One `--db`, built entirely in tmp_path, exercises every db-derived
    category at once: arena-name's own two-terms-from-one-value split (the
    full '#'-suffixed screenName as a substring, the bare name before '#' as
    a word), arena-id, and both forms of opponent (name as a word, user id as
    a substring). The word-vs-substring distinction is the point of the
    first two files: the bare word form requires a boundary and the full
    form does not, from the very same source value."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    # Bare word term ("SynthName") is glued to 'x' on the left -- a real
    # word-to-word run, no boundary there -- so it does not match here, even
    # though '#' on the right is itself a non-word character and would not
    # have blocked a match by itself; only the full substring term (with the
    # literal '#40021' included) should match.
    _write(repo, "src/word_boundary_check.py", "token = 'xsynthname#40021x'\n")
    # Here the bare word IS boundary-delimited (surrounded by spaces), so the
    # word term matches; the full '#40021' form is absent from this text.
    _write(repo, "docs/notes.md", "Beat synthname in game 2.\n")
    _write(repo, "src/id_check.py", "raw = 'prefixSYNTHCLIENTID999suffix'\n")
    _write(repo, "src/opponent_check.py", "log('Lost to SYNTHOPPONENT today')\n")
    _write(repo, "src/opponent_id_check.py", "raw = 'xsynthoppuid77x'\n")
    _commit_all(repo)

    db_path = tmp_path / "scratch.db"
    _make_db(
        db_path,
        auth={"screenName": "SynthName#40021", "clientId": "SynthClientId999"},
        matches=[("SynthOpponent", "SynthOppUid77")],
    )

    result = _run_scan(repo, "--db", str(db_path))
    assert result.returncode == 1
    lines = set(result.stdout.strip().splitlines())

    assert "arena-name\tdocs/notes.md\t1" in lines
    assert "arena-name\tsrc/word_boundary_check.py\t1" in lines
    assert "arena-id\tsrc/id_check.py\t1" in lines
    assert "opponent\tsrc/opponent_check.py\t1" in lines
    assert "opponent\tsrc/opponent_id_check.py\t1" in lines
    # exactly these five hit lines -- nothing extra, e.g. no double count
    # from the bare word term also matching the unbounded file.
    assert lines == {
        "arena-name\tdocs/notes.md\t1",
        "arena-name\tsrc/word_boundary_check.py\t1",
        "arena-id\tsrc/id_check.py\t1",
        "opponent\tsrc/opponent_check.py\t1",
        "opponent\tsrc/opponent_id_check.py\t1",
    }

    for value in (
        "SynthName", "SynthName#40021", "synthname", "SynthClientId999",
        "SynthOpponent", "SynthOppUid77",
    ):
        assert value not in result.stdout
        assert value not in result.stderr


def test_handles_in_an_mtgo_game_log_are_terms_without_a_match_row(tmp_path):
    """The MTGO fixture's two players (Player1 and Player2000, from
    `scripts/mtgo_probe.py tests/fixtures/mtgo_match_session.log`) become
    `mtgo-player` terms from the raw event alone: no `matches` row names
    them, as for a game log the projector skipped."""
    import base64

    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/notes.md", "Lost to Player2000 in game 2.\n")
    _commit_all(repo)

    db_path = tmp_path / "scratch.db"
    _make_db(db_path)
    payload = (REPO_ROOT / "tests" / "fixtures" / "mtgo_match_session.log").read_bytes()
    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE raw_events ADD COLUMN source TEXT")
    conn.execute(
        "INSERT INTO raw_events (label, payload, source) VALUES ('MtgoGameLog', ?, 'mtgo')",
        (base64.b64encode(payload).decode("ascii"),),
    )
    conn.commit()
    conn.close()

    result = _run_scan(repo, "--db", str(db_path))
    assert result.returncode == 1
    assert result.stdout.strip().splitlines() == ["mtgo-player\tdocs/notes.md\t1"]
    assert "Player2000" not in result.stdout + result.stderr


def test_screen_name_without_hash_suffix_is_a_word_term(tmp_path):
    """A screenName with no '#'-suffix (the split in amendment 2 only
    applies when one is present) is still a real identifier -- it must be
    checked as a plain word term, not silently dropped for lacking the
    suffix most Arena accounts have."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/notes.md", "Beat SynthNoHash in game 1.\n")
    _commit_all(repo)

    db_path = tmp_path / "scratch.db"
    _make_db(db_path, auth={"screenName": "SynthNoHash", "clientId": None})

    result = _run_scan(repo, "--db", str(db_path))
    assert result.returncode == 1
    assert result.stdout.strip() == "arena-name\tdocs/notes.md\t1"
    assert "SynthNoHash" not in result.stdout
    assert "SynthNoHash" not in result.stderr


def test_missing_explicit_db_exits_2(tmp_path):
    """A `--db` the user typed but that does not exist is an error, unlike a
    missing *default* db, which is silently skipped -- an explicit argument
    is a claim about a real file, so a missing one is reported, not guessed
    past (non-negotiable #4)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "hello\n")
    _commit_all(repo)

    missing_db = tmp_path / "does_not_exist.db"
    result = _run_scan(repo, "--db", str(missing_db))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert "--db" in result.stderr
    assert str(missing_db) not in result.stderr


# --- --history ------------------------------------------------------------


def test_history_finds_a_term_that_was_committed_then_removed(tmp_path):
    """A term that only ever existed in a file that was later deleted is
    invisible to a tree-only scan (exit 0) but must surface under `--history`
    (exit 1), labeled by its historical blob rather than a current path."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "initial\n")
    _commit_all(repo, "initial commit")

    secret_path = _write(repo, "scratch/old_note.txt", "QzxHistoricalTermABC lives here.\n")
    _commit_all(repo, "add a note")

    secret_path.unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "remove the note")

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxHistoricalTermABC\n", encoding="utf-8")

    tree_result = _run_scan(repo, terms_file=terms_file)
    assert tree_result.returncode == 0
    assert tree_result.stdout == ""
    assert "QzxHistoricalTermABC" not in tree_result.stderr

    history_result = _run_scan(repo, "--history", terms_file=terms_file)
    assert history_result.returncode == 1
    hit_lines = [
        line for line in history_result.stdout.splitlines() if line.startswith("mtgo-handle\t")
    ]
    assert len(hit_lines) == 1
    _category, path, count = hit_lines[0].split("\t")
    assert path.startswith("history:scratch/old_note.txt@")
    assert count == "1"
    assert "QzxHistoricalTermABC" not in history_result.stdout
    assert "QzxHistoricalTermABC" not in history_result.stderr


def test_history_finds_a_term_in_a_commit_message(tmp_path):
    """A term that appears only in a commit message (never in any tracked
    file's content) is invisible to both the tree scan and the blob scan --
    only the separate `git log` pass (`history:log`) catches it."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "initial\n")
    _commit_all(repo, "initial commit")
    _write(repo, "src/thing.py", "value = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Debug session for QzxCommitMsgTermDEF today")

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxCommitMsgTermDEF\n", encoding="utf-8")

    result = _run_scan(repo, "--history", terms_file=terms_file)
    assert result.returncode == 1
    assert "mtgo-handle\thistory:log\t1" in result.stdout.splitlines()
    assert "QzxCommitMsgTermDEF" not in result.stdout
    assert "QzxCommitMsgTermDEF" not in result.stderr


def test_history_finds_a_renamed_files_old_path(tmp_path):
    """`git rev-list --objects` lists each blob once, under only the first
    path it happens to see it at during traversal -- a file renamed with
    unchanged content keeps the exact same blob, so that command can drop
    its old, possibly leaky name the moment the new name is the one attached
    to the object. `git log --name-only --no-renames` fills the gap: with
    rename detection off, the rename is reported as a delete of the old path
    plus an add of the new one, so the old name still gets checked. The
    file's content here carries no term at all -- only its old *name* did --
    so this also proves the fix is about path coverage, not content."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "initial\n")
    _commit_all(repo, "initial commit")

    _write(repo, "notes/QzxOldNameTerm.md", "nothing sensitive in here\n")
    _commit_all(repo, "add the note")

    _git(repo, "mv", "notes/QzxOldNameTerm.md", "notes/renamed.md")
    _commit_all(repo, "rename the note")

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxOldNameTerm\n", encoding="utf-8")

    tree_result = _run_scan(repo, terms_file=terms_file)
    assert tree_result.returncode == 0
    assert tree_result.stdout == ""
    assert "QzxOldNameTerm" not in tree_result.stderr

    history_result = _run_scan(repo, "--history", terms_file=terms_file)
    assert history_result.returncode == 1
    assert history_result.stdout.strip() == "mtgo-handle\thistory:name:notes/[redacted].md\t1"
    assert "QzxOldNameTerm" not in history_result.stdout
    assert "QzxOldNameTerm" not in history_result.stderr


# --- the one public identity: git-account in AUTHORS ------------------------


def _authors_terms(tmp_path: Path) -> Path:
    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text(
        "git-account\tQzxPublicHandleABC\ngit-email\tqzx.public@example.invalid\n",
        encoding="utf-8",
    )
    return terms_file


def test_git_account_in_root_authors_is_not_a_hit(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "AUTHORS", "Maintainer: QzxPublicHandleABC\n")
    _commit_all(repo)

    result = _run_scan(repo, terms_file=_authors_terms(tmp_path))
    assert result.returncode == 0
    assert result.stdout == ""
    assert "QzxPublicHandleABC" not in result.stderr


def test_git_account_in_another_file_is_still_a_hit(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "AUTHORS", "Maintainer: QzxPublicHandleABC\n")
    _write(repo, "README.md", "By QzxPublicHandleABC.\n")
    _commit_all(repo)

    result = _run_scan(repo, terms_file=_authors_terms(tmp_path))
    assert result.returncode == 1
    assert result.stdout.strip() == "git-account\tREADME.md\t1"
    assert "QzxPublicHandleABC" not in result.stdout


def test_other_category_in_authors_is_still_a_hit(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "AUTHORS", "Mail: qzx.public@example.invalid\n")
    _commit_all(repo)

    result = _run_scan(repo, terms_file=_authors_terms(tmp_path))
    assert result.returncode == 1
    assert result.stdout.strip() == "git-email\tAUTHORS\t1"
    assert "qzx.public" not in result.stdout


def test_authors_in_a_subdirectory_is_not_exempt(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/AUTHORS", "Maintainer: QzxPublicHandleABC\n")
    _commit_all(repo)

    result = _run_scan(repo, terms_file=_authors_terms(tmp_path))
    assert result.returncode == 1
    assert result.stdout.strip() == "git-account\tdocs/AUTHORS\t1"


def test_authors_below_a_subdirectory_repo_is_not_exempt(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/AUTHORS", "Maintainer: QzxPublicHandleABC\n")
    _commit_all(repo)

    result = _run_scan(repo / "docs", terms_file=_authors_terms(tmp_path))
    assert result.returncode == 1
    assert result.stdout.strip() == "git-account\tAUTHORS\t1"


def test_history_blob_scan_exempts_root_authors_the_same_way(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "AUTHORS", "Maintainer: QzxPublicHandleABC\n")
    _write(repo, "docs/AUTHORS", "Mail: qzx.public@example.invalid\n")
    _commit_all(repo)

    result = _run_scan(repo, "--history", terms_file=_authors_terms(tmp_path))
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert len(lines) == 2  # the tree hit and the blob hit, both docs/AUTHORS
    assert not any(
        line.startswith("git-account\t") and "history:AUTHORS@" in line for line in lines
    )
    assert any(line.startswith("git-email\t") and "history:docs/AUTHORS@" in line for line in lines)
    assert "QzxPublicHandleABC" not in result.stdout


# --- errors ----------------------------------------------------------------


def test_repo_on_non_git_directory_exits_2(tmp_path):
    """`--repo` pointing at a plain directory (no `.git`) is an error, caught
    before any term is even gathered."""
    plain_dir = tmp_path / "not_a_repo"
    plain_dir.mkdir()

    result = _run_scan(plain_dir)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert "--repo" in result.stderr
    assert str(plain_dir) not in result.stderr


def test_malformed_terms_file_line_exits_2_without_echoing_it(tmp_path):
    """A terms-file line with no tab separator is a fatal, exit-2 error --
    and the error names the flag and a line number, never the file's own
    path or the line's text, per the script's own never-print-a-path-or-term
    contract (amendment G)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "hello\n")
    _commit_all(repo)

    terms_file = tmp_path / "bad_terms.tsv"
    terms_file.write_text("QzxNoTabHereAtAll12345\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "QzxNoTabHereAtAll12345" not in result.stdout
    assert "QzxNoTabHereAtAll12345" not in result.stderr
    assert "Traceback" not in result.stderr
    assert "--terms-file" in result.stderr
    assert "line 1" in result.stderr
    assert str(terms_file) not in result.stderr


# --- amendment A: warnings/logging suppression without --no-local ---------


def test_hermetic_run_without_no_local_suppresses_config_loader_warnings(
    tmp_path, monkeypatch, caplog
):
    """Without --no-local, the automatic local sources run for real --
    including sensei_top.llm.config's own loader, which logs a warning
    naming this machine's absolute config path when a config file exists but
    has no [claude] table. That warning must never reach this process's own
    stderr, since the path it names sits under the real home directory
    (amendment A). Proven two ways: first, that the crafted config.toml
    really does trigger the warning in-process (so the subprocess assertion
    below is not vacuously true against a file that was never going to warn
    at all), then that a subprocess run against that very same file, in a
    fully synthetic environment standing in for "this machine", never prints
    it.

    A run with every local source silently producing zero terms would pass
    every assertion below just as well as one that actually searched for
    something -- so this also plants a real, predictable identifier: the
    synthetic OS user name below (LOGNAME/USER, both "synthuser") is read by
    getpass.getuser() the same way the real os-user source reads this
    machine's own account name, and "synthuser" sits in the tracked README.
    A hit line naming exactly that source and file is proof the local
    sources ran and were actually checked against tracked content, not just
    that the process happened not to crash."""
    xdg_config = tmp_path / "xdg-config"
    config_dir = xdg_config / "sensei-top"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("[other]\nkey = 'value'\n", encoding="utf-8")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from sensei_top.llm import config as llm_config

    with caplog.at_level(logging.WARNING):
        assert llm_config.load() is None
    assert "[claude] table" in caplog.text

    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "mentions synthuser in passing.\n")
    _commit_all(repo)

    home_dir = tmp_path / "home"
    home_dir.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home_dir)
    env["XDG_CONFIG_HOME"] = str(xdg_config)
    env["USER"] = "synthuser"
    env["LOGNAME"] = "synthuser"
    # Neutralize this machine's real git identity: the repo above never sets
    # user.name/user.email in its own local config (only as transient -c
    # overrides while building the fixture), so without this, the script's
    # own `git config user.name` would fall back to the real global config.
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    for key in (
        "LNAME", "USERNAME", "MTGO_HANDLE", "MTGO_LOG_DIR", "ANTHROPIC_API_KEY",
        "TOPDECK_API_KEY", "MTGA_LOG", "SENSEI_TOP_BACKUP_DIR",
    ):
        env.pop(key, None)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 1
    assert result.stdout.strip() == "os-user\tREADME.md\t1"
    stderr_lines = result.stderr.splitlines()
    assert len(stderr_lines) == 1
    assert stderr_lines[0].startswith("privacy_scan: ")
    assert "synthuser" not in result.stderr
    assert "[claude] table" not in result.stderr
    assert "config.toml" not in result.stderr
    assert str(xdg_config) not in result.stderr
    assert str(home_dir) not in result.stderr
    assert "Warning" not in result.stderr
    assert "warning" not in result.stderr.lower()
    assert "Traceback" not in result.stderr


# --- amendment B: word-boundary correctness --------------------------------


def test_word_term_with_non_word_edges_matches_when_delimited(tmp_path):
    """A word term's own edge can itself be a non-word character -- a
    bracket, say -- glued to another non-word character (a space) rather
    than a word character. \\b requires a transition between a word and a
    non-word character, which does not exist there even though the match is
    otherwise cleanly delimited on both sides; the fix checks only "not a
    word character immediately outside the match" instead, which has no such
    gap (amendment B). Paired with a negative case in the same run: the very
    same term glued to a word character on *both* sides (no delimiter at
    all) must still be rejected, proving the fix does not overcorrect into
    matching everything regardless of context."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "src/edge.py", "log('warning [QzxEdgeTermUVW] seen')\n")
    _write(repo, "src/glued.py", "value = 'x[QzxEdgeTermUVW]x'\n")
    _commit_all(repo)

    db_path = tmp_path / "scratch.db"
    _make_db(db_path, matches=[("[QzxEdgeTermUVW]", None)])

    result = _run_scan(repo, "--db", str(db_path))
    assert result.returncode == 1
    assert result.stdout.strip() == "opponent\tsrc/edge.py\t1"
    assert "QzxEdgeTermUVW" not in result.stdout
    assert "QzxEdgeTermUVW" not in result.stderr


# --- amendment C: path masking and path-name scanning ----------------------


def test_term_in_path_name_is_reported_under_a_masked_path(tmp_path):
    """A directory or file named after a handle is itself a leak, even if
    nothing inside it mentions that handle again -- content scanning alone
    would never catch this, since it never looks at the name a file is
    stored under (amendment C)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "notes/QzxPathNameTermABC/log.txt", "nothing interesting\n")
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxPathNameTermABC\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 1
    assert result.stdout.strip() == "mtgo-handle\tname:notes/[redacted]/log.txt\t1"
    assert "QzxPathNameTermABC" not in result.stdout
    assert "QzxPathNameTermABC" not in result.stderr


def test_sibling_file_content_hit_reports_under_the_same_masked_path(tmp_path):
    """A path is masked against every term, not just the one that matched
    inside it (amendment C): a hit found in a file's content must not print
    a *different* term's value just because that value happens to also be
    sitting in that same file's own directory name."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "notes/QzxDirTermDEF/log.txt", "mentions QzxContentTermGHI here\n")
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text(
        "mtgo-handle\tQzxDirTermDEF\nopponent\tQzxContentTermGHI\n", encoding="utf-8"
    )

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 1
    lines = set(result.stdout.strip().splitlines())
    assert "mtgo-handle\tname:notes/[redacted]/log.txt\t1" in lines
    assert "opponent\tnotes/[redacted]/log.txt\t1" in lines
    assert "QzxDirTermDEF" not in result.stdout
    assert "QzxContentTermGHI" not in result.stdout
    assert "QzxDirTermDEF" not in result.stderr
    assert "QzxContentTermGHI" not in result.stderr


def test_masking_handles_a_term_nested_inside_a_longer_one(tmp_path):
    """Substituting one pattern at a time into progressively-modified text
    breaks here: with the shorter term's own line first in the terms file,
    masking it first turns "QzxAlpha QzxBeta.md" into "[redacted]
    QzxBeta.md", and the longer term's own pattern ("QzxAlpha QzxBeta") no
    longer matches that already-modified text at all, leaking "QzxBeta" in
    both hit lines. Collecting every pattern's match spans against the
    *original* path text first, then merging the two overlapping spans
    before substituting once, catches the whole nested span regardless of
    which term's line came first in the file -- the real-world version of
    this is a screen name's bare form (gathered before the database) and its
    full '#'-suffixed value, or a first name gathered before the full name
    that contains it."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "notes/QzxAlpha QzxBeta.md", "irrelevant content\n")
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text(
        "short-first\tQzxAlpha\nfull-second\tQzxAlpha QzxBeta\n", encoding="utf-8"
    )

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 1
    lines = result.stdout.strip().splitlines()
    assert lines == [
        "full-second\tname:notes/[redacted].md\t1",
        "short-first\tname:notes/[redacted].md\t1",
    ]
    assert "QzxAlpha" not in result.stdout
    assert "QzxBeta" not in result.stdout
    assert "QzxAlpha" not in result.stderr
    assert "QzxBeta" not in result.stderr


def test_masking_merges_two_overlapping_term_spans(tmp_path):
    """Two terms that overlap without either containing the other -- neither
    is a substring of the other -- defeat even a longest-first masking
    order, since neither span is a subset of the other to begin with. Both
    spans must be merged into one before substitution, or whichever pattern
    is applied second finds its own match already half-consumed by the
    first substitution and leaks its own non-overlapping half."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "QzxOverAB_QzxLapCD_QzxEndEF.md", "irrelevant content\n")
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text(
        "term-one\tQzxOverAB_QzxLapCD\nterm-two\tQzxLapCD_QzxEndEF\n", encoding="utf-8"
    )

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 1
    lines = result.stdout.strip().splitlines()
    assert lines == [
        "term-one\tname:[redacted].md\t1",
        "term-two\tname:[redacted].md\t1",
    ]
    assert "QzxOverAB" not in result.stdout
    assert "QzxLapCD" not in result.stdout
    assert "QzxEndEF" not in result.stdout
    assert "QzxOverAB" not in result.stderr
    assert "QzxLapCD" not in result.stderr
    assert "QzxEndEF" not in result.stderr


def test_history_path_and_content_hit_are_both_masked(tmp_path):
    """The same masking applies under --history: a historical path (removed
    since) is checked by name, and a historical blob's content hit is
    labeled by that same masked path (amendment C)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "initial\n")
    _commit_all(repo, "initial commit")

    secret_path = _write(repo, "QzxHistDirTermJKL/note.txt", "signed QzxHistContentTermMNO\n")
    _commit_all(repo, "add a note")
    secret_path.unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "remove the note")

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text(
        "mtgo-handle\tQzxHistDirTermJKL\nopponent\tQzxHistContentTermMNO\n",
        encoding="utf-8",
    )

    result = _run_scan(repo, "--history", terms_file=terms_file)
    assert result.returncode == 1
    lines = result.stdout.splitlines()

    # The removed directory's own name is a hit, masked, under history:name:.
    assert "mtgo-handle\thistory:name:[redacted]/note.txt\t1" in lines

    # The removed file's content is a separate hit, labeled by its blob, with
    # the very same directory name masked out of that label too.
    content_hits = [
        line for line in lines if line.startswith("opponent\thistory:[redacted]/note.txt@")
    ]
    assert len(content_hits) == 1
    assert content_hits[0].endswith("\t1")

    assert "QzxHistDirTermJKL" not in result.stdout
    assert "QzxHistContentTermMNO" not in result.stdout
    assert "QzxHistDirTermJKL" not in result.stderr
    assert "QzxHistContentTermMNO" not in result.stderr


# --- amendment D: UTF-16 offset correctness --------------------------------


def test_term_is_found_in_odd_offset_utf16(tmp_path):
    """A UTF-16LE string embedded inside a binary blob does not necessarily
    start on an even byte -- decoding only from offset 0 would misalign
    every code unit for the rest of the string. The second UTF-16LE
    decoding, from offset 1, catches it (amendment D)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    target = repo / "src" / "shifted.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x00" + "QzxOddUtf16Term".encode("utf-16-le"))
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxOddUtf16Term\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 1
    assert result.stdout.strip() == "mtgo-handle\tsrc/shifted.bin\t1"
    assert "QzxOddUtf16Term" not in result.stdout
    assert "QzxOddUtf16Term" not in result.stderr


# --- amendment E: symlink-safe scanning ------------------------------------


def test_dangling_symlink_target_text_is_scanned_under_its_own_path(tmp_path):
    """git tracks a symlink's target text as its blob content regardless of
    whether that target exists -- scanning it must not require resolving it
    (amendment E)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "link_to_nowhere").symlink_to("QzxSymlinkTargetGHI")
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxSymlinkTargetGHI\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 1
    assert result.stdout.strip() == "mtgo-handle\tlink_to_nowhere\t1"
    assert "QzxSymlinkTargetGHI" not in result.stdout
    assert "QzxSymlinkTargetGHI" not in result.stderr


def test_symlink_to_a_file_outside_the_repo_reports_nothing(tmp_path):
    """A tracked symlink is never followed (amendment E): its target's own
    content is not this repo's content, and reading through it could reach
    anything on the filesystem the symlink happens to point at."""
    outside_file = tmp_path / "outside_target.txt"
    outside_file.write_text("QzxOutsideTermJKL is only here.\n", encoding="utf-8")

    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "link_to_outside").symlink_to(outside_file)
    _commit_all(repo)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxOutsideTermJKL\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "QzxOutsideTermJKL" not in result.stdout
    assert "QzxOutsideTermJKL" not in result.stderr


# --- amendment F: a safe top-level exception handler -----------------------


def test_unexpected_exception_exits_2_without_a_traceback_or_absolute_paths(
    tmp_path, monkeypatch, capsys
):
    """Any exception this script did not anticipate must still exit 2
    without a raw traceback (which could quote a source line, an absolute
    path under this machine's own home directory, or the exception's own
    message) -- proven in-process, since forcing an arbitrary crash at a
    precise point is not something a subprocess boundary can do without its
    own elaborate fault injection (amendment F).

    The crash is injected into `_gather_terms`, called from inside `_run`,
    rather than into `_run` itself: `_run` calls `_check_git_repo` first and
    `_gather_terms` second, so a crash here still passes through two real
    frames (`_run`'s own call site, then `main`'s) on its way to
    `_print_crash`, rather than replacing the only frame that would exist if
    `_run` itself were the mock. `--repo` must therefore point at a real git
    repository (via `_init_repo`) rather than a bare tmp_path -- otherwise
    `_check_git_repo` raises its own PrivacyScanError first and this test
    would pass without ever reaching the crash handler at all.

    This also pins amendment A's own restore rule: `main` must restore the
    *previous* logging.disable level (INFO here, set before calling it)
    rather than unconditionally resetting to NOTSET, since NOTSET would
    clobber a caller's own prior suppression instead of leaving it alone."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    spec = importlib.util.spec_from_file_location("privacy_scan_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["privacy_scan_under_test"] = module
    logging.disable(logging.INFO)
    try:
        spec.loader.exec_module(module)

        def _boom(_args, _repo):
            raise RuntimeError("synthetic failure QzxCrashTermJKL for the crash-handling test")

        monkeypatch.setattr(module, "_gather_terms", _boom)
        exit_code = module.main(["--repo", str(repo)])
        assert logging.root.manager.disable == logging.INFO
    finally:
        sys.modules.pop("privacy_scan_under_test", None)
        logging.disable(logging.NOTSET)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Traceback" not in captured.err
    assert "synthetic failure" not in captured.err
    assert "QzxCrashTermJKL" not in captured.err
    assert str(repo) not in captured.err
    assert str(tmp_path) not in captured.err
    assert str(REPO_ROOT) not in captured.err
    assert str(Path.home()) not in captured.err
    assert "RuntimeError" in captured.err


# --- amendment H: the unreadable-tracked-file taxonomy ---------------------


def test_file_missing_from_working_tree_is_skipped_and_counted(tmp_path):
    """git still lists a tracked file that was deleted from disk but never
    `git rm`ed or re-added -- there is no content left to check, so it is
    skipped rather than either silently treated as clean or crashing, and
    the skip is counted in the summary so a scan never claims to have
    checked a file it could not actually read (amendment H)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    target = _write(repo, "src/gone.py", "value = 'QzxGoneTermMNO'\n")
    _commit_all(repo)
    target.unlink()

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxGoneTermMNO\n", encoding="utf-8")

    result = _run_scan(repo, terms_file=terms_file)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "1 missing from the working tree" in result.stderr
    assert "QzxGoneTermMNO" not in result.stderr


def test_unreadable_tracked_file_exits_2_with_a_masked_relative_path(tmp_path):
    """Any OSError reading a tracked file other than "missing" or "a
    directory" is fatal (amendment H): silently skipping it would let a scan
    finish "clean" without ever having read every tracked file. The message
    names a repo-relative path, masked the same way any other printed path
    is (amendment C), never an absolute one."""
    if sys.platform == "win32":
        pytest.skip("relies on POSIX permission bits, which Windows does not have")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores file permission bits")

    repo = tmp_path / "repo"
    _init_repo(repo)
    target = _write(repo, "src/QzxLockedTermPQR_file.py", "value = 1\n")
    _commit_all(repo)
    target.chmod(0o000)

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxLockedTermPQR\n", encoding="utf-8")
    try:
        result = _run_scan(repo, terms_file=terms_file)
    finally:
        target.chmod(0o644)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "src/[redacted]_file.py" in result.stderr
    assert "QzxLockedTermPQR" not in result.stderr
    assert "QzxLockedTermPQR" not in result.stdout
    assert "Traceback" not in result.stderr


def test_unreadable_tracked_file_in_unsearchable_directory_exits_2(tmp_path):
    """A tracked file inside a directory with no execute permission on that
    *directory* (not the file) cannot be `lstat()`ed at all -- the kernel
    needs search permission on every path segment before the file's own
    permissions ever come into play, so this raises PermissionError purely
    from traversal. That distinction matters because the old
    `is_symlink()`/`.exists()`/`.is_dir()` chain called `is_symlink()`
    first, outside any try/except in this function -- and on Python 3.12,
    `Path.is_symlink()` only swallows ENOENT/ENOTDIR/EBADF/ELOOP, so this
    exact PermissionError escaped uncaught to the top-level crash handler
    instead of this function's own "could not read tracked file" message.
    (On Python 3.13+, `is_symlink()`/`.exists()` swallow every OSError
    instead and silently miscount the file as missing -- a different way to
    violate the same rule.) A single `lstat()`, wrapped in one try/except
    from the very first filesystem call, has neither gap."""
    if sys.platform == "win32":
        pytest.skip("relies on POSIX permission bits, which Windows does not have")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores file permission bits")

    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "locked/QzxLockedDirTermSTU.py", "value = 1\n")
    _commit_all(repo)
    locked_dir = repo / "locked"

    terms_file = tmp_path / "terms.tsv"
    terms_file.write_text("mtgo-handle\tQzxLockedDirTermSTU\n", encoding="utf-8")
    locked_dir.chmod(0o000)
    try:
        result = _run_scan(repo, terms_file=terms_file)
    finally:
        locked_dir.chmod(0o755)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "could not read tracked file locked/[redacted].py" in result.stderr
    assert "QzxLockedDirTermSTU" not in result.stderr
    assert "QzxLockedDirTermSTU" not in result.stdout
    assert "Traceback" not in result.stderr
    assert "missing from the working tree" not in result.stderr


# --- the declared identity and the global one -------------------------------

_DECLARED_NAME = "Qzxdeclname"
_DECLARED_EMAIL = "1234+qzxdeclhandle@users.noreply.github.com"
_GLOBAL_NAME = "Qzxglobalname"
_GLOBAL_EMAIL = "qzxglobal@example.invalid"


def _global_config(tmp_path: Path) -> Path:
    """A global git configuration under tmp_path standing in for the
    user's: the scan reads `git config --global`, which must never reach the
    real one."""
    path = tmp_path / "global-gitconfig"
    path.write_text(
        f"[user]\n\tname = {_GLOBAL_NAME}\n\temail = {_GLOBAL_EMAIL}\n"
        "[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n",
        encoding="utf-8",
    )
    return path


def _identity_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg-config")
    env["USER"] = "synthuser"
    env["LOGNAME"] = "synthuser"
    env["GIT_CONFIG_GLOBAL"] = str(_global_config(tmp_path))
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
    for key in (
        "LNAME", "USERNAME", "MTGO_HANDLE", "MTGO_LOG_DIR", "ANTHROPIC_API_KEY",
        "TOPDECK_API_KEY", "MTGA_LOG", "SENSEI_TOP_BACKUP_DIR", "GIT_DIR", "GIT_WORK_TREE",
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
    ):
        env.pop(key, None)
    return env


def _declared_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A repository whose own configuration declares the public identity,
    the way the public repository's clone does."""
    env = _identity_env(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["init", "-q"],
        ["config", "--local", "user.name", _DECLARED_NAME],
        ["config", "--local", "user.email", _DECLARED_EMAIL],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)
    return repo, env


def _commit_as_declared(repo: Path, env: dict[str, str], message: str, *config: str) -> None:
    """No `-c user.*` here unless asked: the commit takes the repository's
    own identity, which `_git` above would override."""
    base = ["git", *config, "-C", str(repo)]
    subprocess.run([*base, "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run([*base, "commit", "-q", "-m", message], check=True, capture_output=True, env=env)


def _scan_with_identity(repo: Path, env: dict[str, str], *args: str):
    """Without --no-local, since the git identity is a local source; every
    other local source is pointed at tmp_path by `_identity_env`."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=60,
    )


def _assert_no_identity_echoed(result: subprocess.CompletedProcess[str]) -> None:
    for value in (_DECLARED_NAME, _DECLARED_EMAIL, _GLOBAL_NAME, _GLOBAL_EMAIL, "qzxdeclhandle"):
        assert value not in result.stdout
        assert value not in result.stderr


def test_declared_identity_is_accepted_in_history_log_fields_and_nowhere_else(tmp_path):
    """Every commit of the public repository carries the declared identity
    as author and committer, so those four fields are set aside. The same
    email in a tracked file, its history blob and a message body is still a
    finding: one body mention, not three, in history:log."""
    repo, env = _declared_repo(tmp_path)
    _write(repo, "notes/contact.txt", f"write to {_DECLARED_EMAIL} for help\n")
    _commit_as_declared(repo, env, f"Release v1.0.0\n\nAsk {_DECLARED_EMAIL}.")

    result = _scan_with_identity(repo, env, "--history")
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert "git-email\tnotes/contact.txt\t1" in lines
    assert any(
        line.startswith("git-email\thistory:notes/contact.txt@") and line.endswith("\t1")
        for line in lines
    )
    assert "git-email\thistory:log\t1" in lines
    assert not [line for line in lines if line.startswith(("git-name\t", "git-first-name\t"))]
    assert "declared identity accepted in history:log: name, email" in result.stderr
    _assert_no_identity_echoed(result)


def test_history_log_field_that_only_contains_the_declared_email_still_counts(tmp_path):
    """Exact equality only: a commit made under an address that merely
    contains the declared one is scanned like any other field, and the
    summary names only what it set aside -- here, the name."""
    repo, env = _declared_repo(tmp_path)
    _write(repo, "README.md", "nothing personal\n")
    _commit_as_declared(repo, env, "chore: start", "-c", f"user.email=x-{_DECLARED_EMAIL}")

    result = _scan_with_identity(repo, env, "--history")
    assert result.returncode == 1
    assert result.stdout.splitlines() == ["git-email\thistory:log\t2"]
    assert "declared identity accepted in history:log: name\n" in result.stderr
    _assert_no_identity_echoed(result)


def test_global_identity_is_a_term_even_when_a_local_one_is_set(tmp_path):
    """The clone's local identity hides the global one from `git config`;
    the global one is the personal address, so it must still be a term."""
    repo, env = _declared_repo(tmp_path)
    _write(repo, "docs/credits.md", f"Thanks to {_GLOBAL_NAME} <{_GLOBAL_EMAIL}>.\n")
    _commit_as_declared(repo, env, "docs: credits")

    result = _scan_with_identity(repo, env)
    assert result.returncode == 1
    assert sorted(result.stdout.splitlines()) == [
        "git-email\tdocs/credits.md\t1",
        "git-first-name\tdocs/credits.md\t1",
        "git-name\tdocs/credits.md\t1",
    ]
    assert "declared identity" not in result.stderr
    _assert_no_identity_echoed(result)


def test_declared_identity_in_a_tracked_file_is_a_finding(tmp_path):
    """The declared values are terms like any identity: only history:log's
    author and committer fields are let through."""
    repo, env = _declared_repo(tmp_path)
    _write(repo, "AUTHORS.md", f"{_DECLARED_NAME}\n")
    _commit_as_declared(repo, env, "docs: authors")

    result = _scan_with_identity(repo, env, "--history")
    lines = result.stdout.splitlines()
    assert "git-name\tAUTHORS.md\t1" in lines
    assert "git-first-name\tAUTHORS.md\t1" in lines
    assert not [line for line in lines if "history:log" in line]
    _assert_no_identity_echoed(result)


def test_declared_name_in_root_authors_is_not_a_finding(tmp_path):
    """The public clone's declared name is the handle, and AUTHORS is where
    the handle lives: a git-name / git-first-name hit there that equals the
    declared name is set aside, in the tree and in the history blob."""
    repo, env = _declared_repo(tmp_path)
    _write(repo, "AUTHORS", f"Maintainer\n----------\n\n{_DECLARED_NAME}\n")
    _commit_as_declared(repo, env, "docs: authors")

    result = _scan_with_identity(repo, env, "--history")
    assert result.returncode == 0
    assert result.stdout == ""
    _assert_no_identity_echoed(result)


def test_declared_name_pass_is_authors_only_and_declared_only(tmp_path):
    """Only AUTHORS, only the declared value: the same name in another file
    is still a finding, and the global, personal name in AUTHORS is too."""
    repo, env = _declared_repo(tmp_path)
    _write(repo, "AUTHORS", f"{_DECLARED_NAME}\nThanks to {_GLOBAL_NAME}.\n")
    _write(repo, "README.md", f"By {_DECLARED_NAME}.\n")
    _commit_as_declared(repo, env, "docs: authors")

    result = _scan_with_identity(repo, env)
    assert result.returncode == 1
    assert sorted(result.stdout.splitlines()) == [
        "git-first-name\tAUTHORS\t1",
        "git-first-name\tREADME.md\t1",
        "git-name\tAUTHORS\t1",
        "git-name\tREADME.md\t1",
    ]
    _assert_no_identity_echoed(result)


def test_declared_first_name_in_root_authors_is_not_a_finding(tmp_path):
    """A two-word declared name makes its first word a git-first-name term;
    that word alone in AUTHORS is set aside like the whole name."""
    repo, env = _declared_repo(tmp_path)
    subprocess.run(
        ["git", "-C", str(repo), "config", "--local", "user.name", "Qzxdeclfirst Qzxdeclsecond"],
        check=True, capture_output=True, env=env,
    )
    _write(repo, "AUTHORS", "Qzxdeclfirst\n")
    _write(repo, "README.md", "By Qzxdeclfirst.\n")
    _commit_as_declared(repo, env, "docs: authors")

    result = _scan_with_identity(repo, env)
    assert result.returncode == 1
    assert result.stdout.splitlines() == ["git-first-name\tREADME.md\t1"]
    assert "Qzxdecl" not in result.stdout
