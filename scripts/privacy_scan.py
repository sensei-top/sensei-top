"""Scan the tracked git tree -- or, on request, the whole history, the
commits a push sends, or one file of text -- for this machine's own
identifiers, without ever printing one.

Every term this checks for is derived at run time from local sources: an
Arena database's own auth events and opponent list, every handle its MTGO
game logs name (`mtgo-player`), this machine's MTGO/
Claude/TopDeck config, git identity and remote, the OS user, the home
directory, the Steam library, and `privacy-terms.tsv` in the same config
directory as the MTGO/Claude/TopDeck config, read the way --terms-file is
when it exists. That file is where a term no other source can still derive
lives -- the personal account, once `origin` names the organisation instead.
None of it is hard-coded here, because a hard-coded identifier in this file
would be exactly the leak the file exists to catch.

Four modes, one set of terms:

- the default scans every tracked file in the working tree;
- --history adds every blob and path reachable from any ref, and every
  commit's identity fields and message (`rev-list --all`, `log --all`);
- --pre-push REMOTE reads git's pre-push lines on stdin and scans exactly
  what the push sends: for each ref it updates, the commits
  `rev-list <local sha> --not --remotes=REMOTE` names, their blobs and
  paths, identity fields and messages -- the same walk and the same log read
  as --history, over that range instead of `--all`. The working tree is not
  scanned, since it is not what is pushed. A deleted ref, or a tag on a
  commit the remote already holds, sends nothing to scan. It refuses, exit
  1, a repository with no `user.name` of its own, since that clone would
  commit under the global name;
- --text FILE scans one file's text, for a pull-request body or a comment
  before it is sent.

Output is categories, paths and counts only: one line per (category, path)
hit on stdout, `<category>\\t<path>\\t<count>`, then a summary line on stderr
with the number of terms checked (broken down by category), what was
scanned (files, plus blobs under --history; commits, blobs and tags under
--pre-push; one text under --text), how many tracked files were missing
from the working tree, how many candidate terms were dropped and why, and
what the log read set aside (below), as counts. The
identifier value itself, and any line it matched, are never printed on any
path -- including inside a path. A directory or file named after a handle
would otherwise print the handle just by being listed as a hit's own
location, so every printed path -- a live tracked path or a
`history:<path>@<blob7>` -- has every term masked out of it first (as
`[redacted]`), and a path's own name is itself a scan target, reported as
`name:<masked path>` (or, under --history, `history:name:<masked path>`).
Under --pre-push the same labels start `push:` instead of `history:`
(`push:<path>@<blob7>`, `push:name:<path>`, `push:log`). Under --text a hit
is `<category>\\ttext\\t<count>`: the file's own path is never printed, since a
scratch file's path can name the home directory. A bad --terms-file or
`privacy-terms.tsv` line is reported by line number, never by its content or
the file's own path.

Two decodings, always: UTF-8 (errors="replace"), which reads a plain source
file. UTF-16 only when the data holds a NUL byte -- every UTF-16 encoding of
ASCII-range text has one and an ordinary text file never does, so this skips
two decodings for the common case. It runs at two byte offsets, 0 and 1,
since an embedded UTF-16 string inside a binary blob can start at either
alignment; decoding only from 0 would misalign the rest of a string that
starts one byte in. The offset-1 decoding also happens to catch ASCII-range
UTF-16BE, which for that range is just UTF-16LE shifted by one byte (each
character's zero byte and value byte swap sides). A cheap lowercase
substring pre-check runs before each term's compiled regex, since a
full-tree run can carry a few hundred terms across a few hundred files and
the regex is the expensive step.

A tracked symlink is never followed: git stores its target text as the
blob's own content, not whatever the target resolves to, so that is what
gets scanned, under the link's own path -- this also means a symlink to a
file outside the repo is never read through, whether or not it resolves. A
tracked path missing from the working tree (deleted, not yet staged) is
skipped and counted, not treated as unreadable; a directory (a submodule's
own gitlink) is skipped with no count; anything else that fails to read is a
fatal, exit-2 error, since silently skipping it would let a scan finish
"clean" without ever having read every tracked file.

--no-local skips every automatic source, including `privacy-terms.tsv` and
the default --db (<repo>/data/sensei-top.db); a --db passed explicitly is
still read, and a missing explicit --db is an error while a missing default
one is silently skipped. That is what makes a hermetic run possible: pass
--no-local and supply synthetic terms with --terms-file or a throwaway --db
instead of this machine's own. What only narrows is still read, and used
only to set log fields aside, never as a term: the clone's declared
identity, and under --history or --pre-push the global `user.email` to
accept (below), so a hermetic run points `GIT_CONFIG_GLOBAL` at a file of
its own. Run without --no-local, this process also silences the local-source
loaders' own `logging` warnings and Python's `warnings` for the run (both
restored before returning, however it returns), since either could otherwise
print an absolute path naming this machine's own home directory or
OS user -- exactly what this script exists to avoid printing in the first
place.

One file is exempt for one category: `AUTHORS` at the repo root may carry the
maintainer's public handle (`git-account`), in the tree and in history blobs
(where a blob is exempt by the one path `rev-list` names it under, so a
byte-identical copy elsewhere passes, harmlessly), and every other category
there, and the handle anywhere else, is still a hit. The one addition: when
the scanned repository declares a local identity (below), its `user.name`
is a `git-name` term and its first word a `git-first-name` term, and in
`AUTHORS` a hit of either that *equals* that declared name is set aside
too -- the public clone's declared name is the handle, and AUTHORS is where
the handle lives. The global, personal name gets no such pass: only the
declared value, only in AUTHORS, only those two categories.

The git name is read twice: the repository's effective `user.name` and the
global one (`git config --global`). The public repository's clone sets a
public identity in its own configuration, which hides the global one from a
plain `git config`, and the global name is the personal one that must stay a
term there (`git-name`, and its first word `git-first-name`). No email is
derived: the personal address is already public, so `user.email` is never a
term of its own -- a `git-email` line in a terms file still is. That clone's
local identity (`git config --local`), when one is set, is the *declared*
identity: under --history and --pre-push, a commit's author or committer
name or email that equals it exactly is set aside before `history:log` (or
`push:log`) is scanned, because every commit the public repository holds
carries it by design. Only those four fields (and an annotated tag's
tagger, two more), on an exact match, and a `Signed-off-by:` or
`Co-Authored-By:` trailer line (key in any case, at a line's start) whose
whole name part -- before ` <`, trimmed -- equals the declared name, since
`git commit -s` writes it there: a trailer naming someone whose name merely
starts with it, the same name elsewhere in a message body, in a blob, a
tracked file or a field that merely contains it is still a hit. The summary
line says which of the two it set aside ("declared identity accepted in
history:log: name, email"), so a run says what it let through.

Two addresses are *accepted* in the log read: the declared `user.email` and
the global one, case-insensitively, each only if it is a bare address
(letters, digits and `_.%+-`, one `@`, then letters, digits and `_.-`, at
least as long as a term may be -- no space, angle brackets or name); one
that is not is not accepted, and the summary says so ("global email
not accepted: not an address") without the value. Every occurrence of an
accepted one as a whole address -- no address character beside it, so one
inside a longer address-like token is still matched -- is set aside
before `history:log` or `push:log` is matched -- identity fields, message
bodies, `Signed-off-by` and `Co-Authored-By` trailers, tag messages --
because the personal address contains the account and the first name, which
stay terms, and a GitHub merge carries it as its author's email. The
summary counts them by source ("accepted emails set aside in push:log:
global 2"), never the value. The global name gets no such pass, and blob text none at
all: the same address in a file is matched like any other text, by whatever
terms it contains. The working repository gets no exemption of
its own from this: a local identity there would be the personal one, set
aside the same way and reported the same way, and that repository is never
published.

The project's own name, `sensei-top`, is a generic word: it is the public
repository's owner, so a clone of it would otherwise make every mention of
the project a `git-account` hit.

Opponent names (`opponent`, and `mtgo-player`, which also holds the user's
own MTGO handle) are filtered against the `cards` table's own vocabulary before
being checked -- an opponent whose handle happens to equal an ordinary word
that is also a card name would otherwise flood the result with matches no
text search can tell apart from a real leak. The user's own terms (every
other category) are never filtered this way.

    uv run python scripts/privacy_scan.py [--history | --pre-push REMOTE | --text FILE]
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import stat
import subprocess
import sys
import traceback
import warnings
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

_MIN_TERM_LENGTH = 4
# "sensei-top" is the public repository's owner (github.com/sensei-top/), not a person.
_GENERIC_WORDS = frozenset({"mtga", "arena", "tracker", "sensei-top"})
# The maintainer's public handle lives in AUTHORS and nowhere else (AGENTS.md, "Privacy").
_PUBLIC_IDENTITY = {"AUTHORS": frozenset({"git-account"})}
# The two categories the declared local name produces (`_terms_from_git_identity`).
_DECLARED_NAME_CATEGORIES = frozenset({"git-name", "git-first-name"})
# Other players' names, checked against card-name words first (module docstring).
_CARD_WORD_FILTERED = frozenset({"opponent", "mtgo-player"})
# Read beside config.toml when it exists, in the --terms-file format (module docstring).
_PRIVACY_TERMS_FILE = "privacy-terms.tsv"
# What a revision range's labels start with: `history:` under --history, `push:` under --pre-push.
_HISTORY_LABEL = "history"
_PUSH_LABEL = "push"
# A pre-push line's object name: hex only, so nothing on stdin can reach git as an option.
_OBJECT_NAME = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


class MatchKind(StrEnum):
    WORD = "word"
    SUBSTRING = "substring"


@dataclass(frozen=True, slots=True)
class Term:
    category: str
    value: str
    match: MatchKind


@dataclass(frozen=True, slots=True)
class DeclaredIdentity:
    """The scanned repository's own local ``user.name`` / ``user.email``,
    either ``None`` when unset. Never a term source: it only sets fields
    aside in ``history:log`` and ``push:log`` (its email anywhere in them,
    as an accepted email), and its name aside in ``AUTHORS``. Under
    --pre-push, a ``None`` name refuses the push."""

    name: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class Exemption:
    """What one file may carry: whole categories (``git-account`` in
    AUTHORS), and the lowercase values a ``git-name`` / ``git-first-name``
    hit may equal there (the declared name and its first word, in AUTHORS).
    ``NO_EXEMPTION`` for every other file."""

    categories: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()

    def covers(self, candidate: Term, value_lower: str) -> bool:
        if candidate.category in self.categories:
            return True
        return candidate.category in _DECLARED_NAME_CATEGORIES and value_lower in self.names


NO_EXEMPTION = Exemption()


def _exemption(path: str, declared: DeclaredIdentity) -> Exemption:
    """``path`` is repo-relative (``AUTHORS``, or ``docs/AUTHORS``, which
    gets nothing), as both the tree walk and ``rev-list`` label it."""
    categories = _PUBLIC_IDENTITY.get(path)
    if categories is None:
        return NO_EXEMPTION
    names: set[str] = set()
    if declared.name:
        names.add(declared.name.lower())
        tokens = declared.name.split()
        if tokens:
            names.add(tokens[0].lower())
    return Exemption(categories=categories, names=frozenset(names))


class PrivacyScanError(Exception):
    """A user-facing, exit-2 condition. The message never carries a term
    value, a matched line, or a path -- a path can itself contain this
    machine's own home directory or OS user, which is exactly what this
    script exists to avoid printing. It names the flag whose argument caused
    the error (--repo, --db, --terms-file, --text) instead, plus a line
    number for a malformed --terms-file or ``privacy-terms.tsv`` line or
    --pre-push stdin line, or the git command that failed in a history or
    push walk (``rev-list``, ``log``, ``cat-file``). The one exception is
    an unreadable tracked file: that message carries its own path,
    repo-relative and masked the same way any printed path is, never
    absolute -- that path is the user's own repository content, not a
    location on this machine."""


def _term(category: str, value: str, match: MatchKind) -> Term | None:
    """Build one term, applying the leading/trailing-separator strip a path
    value needs (amendment 4) to every value regardless of category -- a
    no-op for a non-path value (a handle or email has no leading slash to
    strip), so one rule covers both cases instead of branching on which of
    the five path categories this happens to be. ``None`` if nothing is left
    after stripping (an empty or separator-only value), which none of the
    real sources this script reads ever actually produce."""
    text = str(value).strip("/\\")
    if not text:
        return None
    return Term(category=category, value=text, match=match)


def _terms(specs: list[tuple[str, str, MatchKind]]) -> list[Term]:
    result: list[Term] = []
    for category, value, match in specs:
        built = _term(category, value, match)
        if built is not None:
            result.append(built)
    return result


# --- local sources (each imports sensei_top lazily, so --no-local never
# touches a config file: these functions are simply never called) ----------


def _terms_from_mtgo_handle() -> list[Term]:
    from sensei_top.mtgo.config import load_handle

    handle = load_handle()
    if not handle:
        return []
    return _terms([("mtgo-handle", handle, MatchKind.WORD)])


def _terms_from_os_user() -> list[Term]:
    import getpass

    try:
        user = getpass.getuser()
    except OSError:
        return []
    if not user:
        return []
    return _terms([("os-user", user, MatchKind.WORD)])


def _terms_from_home() -> list[Term]:
    home = str(Path.home())
    if not home:
        return []
    return _terms([("home", home, MatchKind.SUBSTRING)])


def _terms_from_git_identity(repo: Path) -> list[Term]:
    """The effective name and the global one: a clone with a local identity
    answers a plain ``git config`` with the local value, which would
    otherwise drop the personal name from the terms entirely. Where the two
    agree, ``_filter_terms`` keeps one of each. No ``user.email``: the
    personal address is public (module docstring)."""
    terms: list[Term] = []
    for scope in ((), ("--global",)):
        name = _git_config_value(repo, "user.name", *scope)
        if name:
            terms += _terms([("git-name", name, MatchKind.WORD)])
            tokens = name.split()
            if tokens:
                terms += _terms([("git-first-name", tokens[0], MatchKind.WORD)])
    return terms


def _declared_identity(repo: Path) -> DeclaredIdentity:
    """Read whether or not --no-local is given: it is the scanned
    repository's own configuration, not this machine's, and it can only
    narrow ``history:log`` and ``push:log``, or refuse a push, never add a
    term."""
    return DeclaredIdentity(
        name=_git_config_value(repo, "user.name", "--local"),
        email=_git_config_value(repo, "user.email", "--local"),
    )


def _terms_from_git_account(repo: Path) -> list[Term]:
    url = _git_remote_origin_url(repo)
    if not url:
        return []
    account = _parse_git_account(url)
    if not account:
        return []
    return _terms([("git-account", account, MatchKind.WORD)])


def _terms_from_claude_key() -> list[Term]:
    from sensei_top.llm.config import load

    config = load()
    if config is None or not config.api_key:
        return []
    return _terms([("claude-key", config.api_key, MatchKind.SUBSTRING)])


def _terms_from_topdeck_key() -> list[Term]:
    from sensei_top.metagame.config import load

    config = load()
    if config is None or not config.api_key:
        return []
    return _terms([("topdeck-key", config.api_key, MatchKind.SUBSTRING)])


def _terms_from_mtgo_dir() -> list[Term]:
    from sensei_top.mtgo.config import resolve_log_dir

    resolved = resolve_log_dir()
    if resolved is None:
        return []
    path, _source = resolved
    return _terms([("mtgo-dir", str(path), MatchKind.SUBSTRING)])


def _terms_from_arena_log_dir() -> list[Term]:
    from sensei_top.reader.ingest import default_log_path

    log_path = default_log_path()
    if log_path is None:
        return []
    return _terms([("arena-log-dir", str(log_path.parent), MatchKind.SUBSTRING)])


def _terms_from_backup_dir(db_path: Path) -> list[Term]:
    from sensei_top.backup.config import resolve

    config = resolve(db_path)
    if config.dir_source == "default":
        # The default sits beside the database inside the repo and says
        # nothing "home" doesn't already cover (amendment 4).
        return []
    return _terms([("backup-dir", str(config.directory), MatchKind.SUBSTRING)])


def _terms_from_privacy_terms_file() -> list[Term]:
    """``privacy-terms.tsv`` beside the config file the MTGO, Claude and
    TopDeck loaders read, resolved the same way; absent, nothing. Its errors
    name the file by that bare name, never by its path."""
    from sensei_top.llm.config import config_path

    path = config_path().with_name(_PRIVACY_TERMS_FILE)
    if not path.exists():
        return []
    return _read_terms_file(path, _PRIVACY_TERMS_FILE)


def _terms_from_steam_library() -> list[Term]:
    from sensei_top.steam import library_roots

    return _terms(
        [("steam-library", str(root), MatchKind.SUBSTRING) for root in library_roots()]
    )


# --- git plumbing -----------------------------------------------------------


def _git(
    repo: Path, args: list[str], *, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_bytes,
        capture_output=True,
    )


def _check_git_repo(repo: Path) -> None:
    if not repo.is_dir():
        raise PrivacyScanError("--repo is not a directory")
    result = _git(repo, ["rev-parse", "--is-inside-work-tree"])
    if result.returncode != 0 or result.stdout.strip() != b"true":
        raise PrivacyScanError("--repo is not a git repository")


def _list_tracked_files(repo: Path) -> list[Path]:
    """Decoded with os.fsdecode, not errors="replace": a non-UTF-8 tracked
    name must round-trip to the exact bytes the filesystem holds (via
    surrogateescape), or ``repo / rel_path`` would look for a path that does
    not exist (amendment H)."""
    result = _git(repo, ["ls-files", "-z"])
    if result.returncode != 0:
        raise PrivacyScanError("git ls-files failed")
    return [Path(os.fsdecode(p)) for p in result.stdout.split(b"\0") if p]


def _repo_prefix(repo: Path) -> str:
    """``--show-prefix``: where ``--repo`` sits below the repository root
    ("" at the root, "docs/" in a subdirectory), since tracked labels are
    relative to ``--repo``, not to the root. A failure raises rather than
    falling back to "": that is the root, the one prefix that grants the
    exemption."""
    result = _git(repo, ["rev-parse", "--show-prefix"])
    if result.returncode != 0:
        raise PrivacyScanError("git rev-parse --show-prefix failed")
    return result.stdout.decode("utf-8", errors="replace").strip()


def _git_config_value(repo: Path, key: str, *scope: str) -> str | None:
    result = _git(repo, ["config", *scope, "--get", key])
    if result.returncode != 0:
        return None
    value = result.stdout.decode("utf-8", errors="replace").strip()
    return value or None


def _git_remote_origin_url(repo: Path) -> str | None:
    result = _git(repo, ["remote", "get-url", "origin"])
    if result.returncode != 0:
        return None
    value = result.stdout.decode("utf-8", errors="replace").strip()
    return value or None


def _parse_git_account(url: str) -> str | None:
    """The account segment of an origin URL, for exactly the two forms
    amendment 6 names -- ``git@host:account/repo(.git)`` and
    ``https://host/account/repo(.git)``. Anything else (a bare local path
    remote, a deeper subgroup path) yields ``None``, silently skipped, same
    as "no origin" (amendment 6's own last line): guessing at an unlisted
    shape would risk pulling in something that is not an account segment at
    all, which non-negotiable #4 rules out anyway."""
    url = url.strip()
    if url.endswith(".git"):
        url = url[: -len(".git")]
    url = url.rstrip("/")

    if "://" in url:
        _scheme, _sep, rest = url.partition("://")
        _host, _sep, path = rest.partition("/")
    elif "@" in url and ":" in url:
        _user_host, _sep, path = url.partition(":")
    else:
        return None

    parts = path.split("/")
    if len(parts) != 2 or not parts[0]:
        return None
    return parts[0]


# --- the database (amendment 7: mode=ro, minimal schema, missing table skips
# that source silently) -------------------------------------------------------


def _terms_from_db(db_path: Path) -> tuple[list[Term], frozenset[str]]:
    # resolve().as_uri() rather than an f-string: a path containing '?', '#'
    # or '%' would otherwise be misread as URI query/fragment/escape syntax
    # instead of a literal path character (amendment I).
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        terms = _terms_from_auth(conn) + _terms_from_matches(conn) + _terms_from_mtgo_events(conn)
        card_words = _card_words(conn)
    finally:
        conn.close()
    return terms, card_words


def _terms_from_auth(conn: sqlite3.Connection) -> list[Term]:
    """Every distinct screenName/clientId ever seen (amendment 2) -- a past
    screen name is still an identifier, not just the newest. A screenName
    with a ``#12345`` suffix yields both the full value (substring) and the
    part before ``#`` (word); without a suffix, the one value is a word
    term. ``json_valid`` in the WHERE clause means one malformed payload is
    excluded, not the whole query -- a single bad row must not blind this
    source to every other one (amendment I)."""
    try:
        rows = conn.execute(
            "SELECT DISTINCT "
            "json_extract(payload, '$.authenticateResponse.screenName'), "
            "json_extract(payload, '$.authenticateResponse.clientId') "
            "FROM raw_events "
            "WHERE label = 'AuthenticateResponse' AND json_valid(payload)"
        ).fetchall()
    except sqlite3.OperationalError:
        # No raw_events table -- this source is simply absent, same as a
        # missing config file.
        return []

    terms: list[Term] = []
    for screen_name, client_id in rows:
        if client_id:
            terms += _terms([("arena-id", client_id, MatchKind.SUBSTRING)])
        if screen_name:
            if "#" in screen_name:
                bare, _sep, _discriminator = screen_name.partition("#")
                terms += _terms([("arena-name", screen_name, MatchKind.SUBSTRING)])
                terms += _terms([("arena-name", bare, MatchKind.WORD)])
            else:
                terms += _terms([("arena-name", screen_name, MatchKind.WORD)])
    return terms


def _terms_from_matches(conn: sqlite3.Connection) -> list[Term]:
    try:
        names = conn.execute(
            "SELECT DISTINCT opponent_name FROM matches WHERE opponent_name IS NOT NULL"
        ).fetchall()
        ids = conn.execute(
            "SELECT DISTINCT opponent_user_id FROM matches WHERE opponent_user_id IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    terms = _terms([("opponent", name, MatchKind.WORD) for (name,) in names])
    terms += _terms([("opponent", uid, MatchKind.SUBSTRING) for (uid,) in ids])
    return terms


def _terms_from_mtgo_events(conn: sqlite3.Connection) -> list[Term]:
    """Every handle an MTGO game log in ``raw_events`` names, the user's own
    included. ``matches`` holds only the opponents of the matches the
    projector resolved; a game log it skipped (the configured handle not
    among its players, a third one) names players no other source here
    knows. Decoded the projector's way, since the payload is the client's
    own binary string stream, base64-encoded."""
    import base64
    import binascii

    from sensei_top.projector.mtgo.decode import decode_strings
    from sensei_top.projector.mtgo.parse import parse_strings

    try:
        rows = conn.execute(
            "SELECT payload FROM raw_events WHERE source = 'mtgo' AND payload IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    handles: set[str] = set()
    for (payload,) in rows:
        try:
            data = base64.b64decode(payload)
        except (ValueError, TypeError, binascii.Error):
            continue
        handles |= parse_strings(decode_strings(data)).handles
    return _terms([("mtgo-player", handle, MatchKind.WORD) for handle in sorted(handles)])


def _card_words(conn: sqlite3.Connection) -> frozenset[str]:
    """Every lowercase word appearing in any card name, so an opponent
    handle that collides with one can be told apart from a genuine leak
    (amendment 3). Empty -- meaning the filter never drops anything -- when
    there is no cards table at all."""
    try:
        rows = conn.execute("SELECT name FROM cards").fetchall()
    except sqlite3.OperationalError:
        return frozenset()
    words: set[str] = set()
    for (name,) in rows:
        if name:
            words.update(match.lower() for match in re.findall(r"\w+", name))
    return frozenset(words)


# --- --terms-file -------------------------------------------------------


def _read_terms_file(path: Path, source: str = "--terms-file") -> list[Term]:
    """``label<TAB>value`` lines, always matched as a substring -- the most
    inclusive of the two kinds, since a hand-added past handle or second
    account has no automatic-source category telling this script which of
    the two it should be. Never echoes a line, and never echoes the path
    either (amendment G): a bad one is named by ``source`` (--terms-file, or
    ``privacy-terms.tsv``) and a line number only."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PrivacyScanError(
            f"{source} could not be read ({exc.__class__.__name__})"
        ) from exc

    terms: list[Term] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if "\t" not in line:
            raise PrivacyScanError(f"{source} line {lineno}: expected label<TAB>value")
        label, _sep, value = line.partition("\t")
        label = label.strip()
        value = value.strip()
        if not label or not value:
            raise PrivacyScanError(f"{source} line {lineno}: empty label or value")
        built = _term(label, value, MatchKind.SUBSTRING)
        if built is not None:
            terms.append(built)
    return terms


# --- filtering (amendments 3 and 8, plus the original spec's length/generic
# rules) -- order is length, then generic, then card-word, then dedup, so a
# term that would qualify for more than one reason is counted under exactly
# one, deterministically -----------------------------------------------------


def _filter_terms(
    terms: list[Term], card_words: frozenset[str], dropped: dict[str, int]
) -> list[Term]:
    kept: list[Term] = []
    seen: set[Term] = set()
    for candidate in terms:
        if len(candidate.value) < _MIN_TERM_LENGTH:
            dropped["short"] += 1
            continue
        if candidate.value.lower() in _GENERIC_WORDS:
            dropped["generic"] += 1
            continue
        if (
            candidate.category in _CARD_WORD_FILTERED
            and candidate.match == MatchKind.WORD
            and candidate.value.lower() in card_words
        ):
            dropped["card-word"] += 1
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        kept.append(candidate)
    return kept


# --- matching -----------------------------------------------------------


def _compile_terms(terms: list[Term]) -> list[tuple[Term, str, re.Pattern[str]]]:
    compiled = []
    for candidate in terms:
        escaped = re.escape(candidate.value)
        # Not \b...\b: \b needs a transition between a word and a non-word
        # character, which never exists right at a value's own edge when
        # that edge is already a non-word character glued to another
        # non-word character -- a space before a value that starts with
        # "[", for instance. \b...\b would reject even a cleanly delimited
        # match there (amendment B). "Not preceded/followed by a word
        # character" has no such gap.
        pattern = rf"(?<!\w){escaped}(?!\w)" if candidate.match == MatchKind.WORD else escaped
        compiled.append((candidate, candidate.value.lower(), re.compile(pattern, re.IGNORECASE)))
    return compiled


def _decode_variants(data: bytes) -> list[str]:
    """UTF-8 always. UTF-16 only when a NUL byte is present -- every UTF-16
    encoding of ASCII-range text has one and an ordinary text file never
    does, so this skips two decodings for the common case (amendment D). Two
    UTF-16LE offsets, not one: an embedded UTF-16 string inside a binary blob
    can start at an odd byte, which decoding only from byte 0 would misalign
    for the rest of the string, so ``data[1:]`` is decoded too. The shifted
    decoding also happens to catch ASCII-range UTF-16BE, which for that
    range is UTF-16LE shifted by one byte (each character's zero byte and
    value byte just swap sides). Neither decoding ever raises, even on empty
    or odd-length input, since both use errors="replace"."""
    variants = [data.decode("utf-8", errors="replace")]
    if b"\x00" in data:
        variants.append(data.decode("utf-16-le", errors="replace"))
        variants.append(data[1:].decode("utf-16-le", errors="replace"))
    return variants


def _mask_path(path_text: str, compiled: list[tuple[Term, str, re.Pattern[str]]]) -> str:
    """Every term's compiled pattern applied to a path string, not just the
    one that caused whatever hit is being printed (amendment C): a directory
    or file named after a handle would otherwise print that handle just by
    being a hit's own location, even when the match that triggered the line
    was found somewhere else entirely -- a sibling file's content, say.

    Every pattern's match spans are collected against the *original* string
    first, spans that overlap or touch are merged, and each merged span is
    replaced once -- never one pattern substituted at a time into
    progressively-modified text. Substituting sequentially breaks the moment
    one term is a substring of another: masking the shorter one first (a
    screen name's bare form, gathered before the database's own full
    '#'-suffixed value; a first name before the full name that contains it)
    removes the very text the longer term needed to match, leaking whatever
    the longer match would have covered beyond the shorter one. It breaks
    just as badly when two terms merely overlap without either containing
    the other -- masking longest-first does not help there, since neither
    span is a subset of the other. Collecting every span up front and
    merging avoids both: every pattern always sees the real, original text
    (so a WORD lookaround also sees the real neighbouring characters, never
    an earlier "[redacted]"), and a merged span is redacted as one unit
    regardless of how many terms or partial terms it covers."""
    spans: list[tuple[int, int]] = []
    for _candidate, _value_lower, pattern in compiled:
        for match in pattern.finditer(path_text):
            if match.start() != match.end():
                spans.append((match.start(), match.end()))
    if not spans:
        return path_text

    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    pieces: list[str] = []
    cursor = 0
    for start, end in merged:
        pieces.append(path_text[cursor:start])
        pieces.append("[redacted]")
        cursor = end
    pieces.append(path_text[cursor:])
    return "".join(pieces)


def _accumulate_path_name_hits(
    hits: dict[tuple[str, str], int],
    path_text: str,
    prefix: str,
    compiled: list[tuple[Term, str, re.Pattern[str]]],
) -> None:
    """A path's own name is a scan target, not just its content (amendment
    C): a directory or file named after a handle would otherwise never be
    caught at all, since content scanning never looks at the name a file is
    stored under. Reported under the masked path itself, prefixed ``name:``
    for a live tracked path, ``history:name:`` for a historical one or
    ``push:name:`` for one a push sends, via ``prefix``."""
    lowered = path_text.lower()
    for candidate, value_lower, pattern in compiled:
        if value_lower not in lowered:
            continue
        count = len(pattern.findall(path_text))
        if count:
            masked = _mask_path(path_text, compiled)
            key = (candidate.category, f"{prefix}name:{masked}")
            hits[key] = hits.get(key, 0) + count


def _accumulate_hits(
    hits: dict[tuple[str, str], int],
    path_label: str,
    data: bytes,
    compiled: list[tuple[Term, str, re.Pattern[str]]],
    exempt: Exemption = NO_EXEMPTION,
) -> None:
    """A cheap lowercase ``in`` pre-check before the compiled regex, per term
    per decoding -- with ~900 terms across a full tree this is the
    difference between a scan that finishes and one that doesn't (amendment
    9). Counts from every decoding are summed into one (category, path)
    total. The label is masked before it is ever used as a key (amendment
    C), using every compiled pattern rather than just the one that matched
    here -- a hit found in a file's content still must not print a term that
    happens to also be sitting in that file's own path. Masked at most once
    per call, since the label never changes across candidates or decodings."""
    masked_label: str | None = None
    for text in _decode_variants(data):
        text_lower = text.lower()
        for candidate, value_lower, pattern in compiled:
            if exempt.covers(candidate, value_lower) or value_lower not in text_lower:
                continue
            count = len(pattern.findall(text))
            if count:
                if masked_label is None:
                    masked_label = _mask_path(path_label, compiled)
                key = (candidate.category, masked_label)
                hits[key] = hits.get(key, 0) + count


def _tracked_file_content(
    full_path: Path,
    rel_label: str,
    compiled: list[tuple[Term, str, re.Pattern[str]]],
    counts: dict[str, int],
) -> bytes | None:
    """The bytes this tracked path contributes to the content scan, or
    ``None`` to skip it -- for two cases that are not really "unreadable" at
    all: deleted from disk but still tracked (git allows this; nothing has
    ``git add``ed or ``git rm``ed the change yet) and a directory (a
    submodule's own gitlink, which has no blob content of its own to read
    here). The first is counted in ``counts["missing"]`` for the summary;
    the second is not, since it is not an omission a user needs to know
    about the way a deleted-but-tracked file is (amendment H).

    Classified from a single ``lstat()`` call, not the ``is_symlink()`` /
    ``.exists()`` / ``.is_dir()`` chain this replaced -- that chain had two
    version-dependent failure modes when a *parent directory* (not the file
    itself) was the unreadable thing, permission 000 being the common case.
    On Python 3.12, ``Path.is_symlink()`` only swallows ENOENT/ENOTDIR/
    EBADF/ELOOP, so a PermissionError coming from an inaccessible parent
    escaped uncaught, landing in the top-level crash handler instead of this
    function's own message below. On Python 3.13+, ``Path.exists()`` and
    ``Path.is_symlink()`` swallow every OSError and return False instead, so
    the very same file is silently counted as missing -- exactly what this
    amendment forbids. A single ``lstat()``, wrapped in one try/except from
    the first filesystem call onward, is version-stable and has neither gap:
    "gone" (ENOENT/ENOTDIR) is the only outcome treated as missing, and every
    other OSError is fatal, regardless of which call in the chain raised it.

    A symlink is never followed: git stores its target text as the blob's
    own content, not whatever the target resolves to, so that is what gets
    scanned here -- which also means a symlink to a file outside the repo is
    never read through, whether or not it even resolves (amendment E). Its
    own ``readlink`` is wrapped too, since a race -- the link removed between
    the ``lstat`` above and this call -- must land on the same message
    rather than an uncaught OSError.

    Anything else that fails to read (most commonly a permission bit) is
    fatal: silently skipping it would let a scan finish "clean" without ever
    having read every tracked file, which defeats the point of running this
    tool at all (amendment H). Its message carries this path -- masked, and
    repo-relative, never absolute -- since unlike --repo/--db/--terms-file
    (amendment G), this path is the user's own repository content, not a
    location on this machine."""
    try:
        st = full_path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        # Deleted from disk but still tracked (git allows this; nothing has
        # `git add`ed or `git rm`ed the change yet) -- not "unreadable", just
        # gone.
        counts["missing"] += 1
        return None
    except OSError as exc:
        raise _unreadable_tracked_file_error(rel_label, compiled, exc) from exc

    if stat.S_ISLNK(st.st_mode):
        try:
            target = os.readlink(full_path)
        except OSError as exc:
            raise _unreadable_tracked_file_error(rel_label, compiled, exc) from exc
        return target.encode("utf-8", errors="replace")

    if stat.S_ISDIR(st.st_mode):
        # A submodule's own gitlink -- no blob content of its own to read.
        return None

    try:
        return full_path.read_bytes()
    except OSError as exc:
        raise _unreadable_tracked_file_error(rel_label, compiled, exc) from exc


def _unreadable_tracked_file_error(
    rel_label: str, compiled: list[tuple[Term, str, re.Pattern[str]]], exc: OSError
) -> PrivacyScanError:
    masked = _mask_path(rel_label, compiled)
    return PrivacyScanError(f"could not read tracked file {masked} ({exc.__class__.__name__})")


# --- history and pushes: one walk over a revision range ----------------------
#
# ``revs`` is what ``git rev-list`` and ``git log`` are given: ``["--all"]``
# under --history, ``[<sha>..., "--not", "--remotes=<remote>"]`` under
# --pre-push. ``label`` is the printed prefix, ``history`` or ``push``. A git
# failure here is fatal rather than an empty result -- a non-zero exit, or a
# ``cat-file`` that answers for fewer objects than it was asked for: a range
# that silently read less than it named would let a scan, or a push, pass
# "clean".


@dataclass(frozen=True, slots=True)
class AcceptedEmail:
    """An address set aside wherever it appears in ``<label>:log``:
    ``source`` is ``declared`` (the repository's local ``user.email``) or
    ``global`` (``git config --global``). Never a term, never printed."""

    source: str
    value: str


@dataclass(slots=True)
class RangeScan:
    """What one walk read, for the summary line: blobs, commits and
    annotated tags; which declared parts it set aside in identity fields
    (``name``, ``email``); and how many accepted-email occurrences it set
    aside in the log, by source; and which sources' ``user.email`` was not
    accepted, because it does not look like an address."""

    blobs: int = 0
    commits: int = 0
    tags: int = 0
    declared_parts: list[str] = field(default_factory=list)
    emails: Counter[str] = field(default_factory=Counter)
    refused_emails: list[str] = field(default_factory=list)


# A bare address and nothing else: no space, no angle brackets, no name.
_BARE_ADDRESS = re.compile(r"[\w.%+-]+@[\w.-]+")


def _looks_like_address(value: str) -> bool:
    """A bare address -- address characters, one ``@``, address characters
    -- no shorter than a term may be. A one-letter or handle-shaped
    ``user.email`` accepted as is would set aside every occurrence of that
    text in the log, and one written ``Name <address>`` would set aside the
    name with it, in the very trailer GitHub writes."""
    return len(value) >= _MIN_TERM_LENGTH and _BARE_ADDRESS.fullmatch(value) is not None


def _accepted_emails(
    repo: Path, declared: DeclaredIdentity
) -> tuple[list[AcceptedEmail], list[str]]:
    """The declared address and the global one, longest first so neither
    masks part of the other, one entry per address (case-insensitively),
    credited to ``declared`` when both agree; and the sources whose value is
    set but does not look like an address, so is not accepted (the summary
    says so, never the value). Read whether or not --no-local is given, like
    the declared identity: an accepted address only narrows the log, never
    adds a term. Read only when a range is walked, so a tree scan never
    consults the global configuration for it."""
    found: list[AcceptedEmail] = []
    refused: list[str] = []
    seen: set[str] = set()
    global_email = _git_config_value(repo, "user.email", "--global")
    for source, value in (("declared", declared.email), ("global", global_email)):
        if not value or value.lower() in seen:
            continue
        if not _looks_like_address(value):
            refused.append(source)
            continue
        seen.add(value.lower())
        found.append(AcceptedEmail(source=source, value=value))
    return sorted(found, key=lambda email: len(email.value), reverse=True), refused


# What may sit inside an address: an accepted one is masked only with none of these beside it.
# `\w` rather than ASCII letters, so a non-ASCII letter beside an address is no boundary.
_ADDRESS_CHARS = r"\w.%+@\-"
_ADDRESS_CHARS_BUT_DOT = r"\w%+@\-"


def _mask_accepted_emails(
    text: str, emails: list[AcceptedEmail], counts: Counter[str]
) -> str:
    """Every case-insensitive occurrence of each accepted address, as a
    whole address only -- no address character either side, so one inside
    a longer address-like token is left to match; the one exception is a
    full stop after it that nothing address-like follows, since an address
    never ends in one and a sentence often does -- replaced by a newline (a
    separator, so the text either side never joins into a word a term could
    match), and counted under its source."""
    for email in emails:
        pattern = (
            rf"(?<![{_ADDRESS_CHARS}]){re.escape(email.value)}"
            rf"(?![{_ADDRESS_CHARS_BUT_DOT}])(?!\.[{_ADDRESS_CHARS}])"
        )
        text, replaced = re.subn(pattern, "\n", text, flags=re.IGNORECASE)
        if replaced:
            counts[email.source] += replaced
    return text


def _git_range(repo: Path, args: list[str]) -> bytes:
    result = _git(repo, args)
    if result.returncode != 0:
        raise PrivacyScanError(f"git {args[0]} failed")
    return result.stdout


def _object_types(repo: Path, shas: list[str]) -> dict[str, str]:
    """``cat-file --batch-check``: each object's type. A missing object
    answers ``<sha> missing``, which parses as nothing, so a short answer is
    caught by the count."""
    result = _git(
        repo, ["cat-file", "--batch-check"], input_bytes=("\n".join(shas) + "\n").encode("utf-8")
    )
    types: dict[str, str] = {}
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split(" ")
        if len(parts) >= 3:
            types[parts[0]] = parts[1]
    if result.returncode != 0 or len(types) < len(set(shas)):
        raise PrivacyScanError("git cat-file --batch-check failed")
    return types


def _object_contents(repo: Path, shas: list[str]) -> dict[str, bytes]:
    result = _git(
        repo, ["cat-file", "--batch"], input_bytes=("\n".join(shas) + "\n").encode("utf-8")
    )
    contents = _parse_batch_output(result.stdout)
    if result.returncode != 0 or len(contents) < len(set(shas)):
        raise PrivacyScanError("git cat-file --batch failed")
    return contents


def _log_all_paths(repo: Path, revs: list[str]) -> set[str]:
    """Every path in any commit's diff in ``revs``, with rename
    detection turned off -- a companion to ``rev-list --objects`` for path
    *name* coverage under --history and --pre-push (amendment C), covering
    exactly what that command misses. ``rev-list --objects`` lists each blob
    or tree object once, under only the first path it happens to see it at
    during traversal; a file renamed with unchanged content keeps the same blob, so
    that command can drop its old, possibly leaky name entirely once the new
    name is the one attached to the object. ``--no-renames`` makes a rename
    show up as a delete of the old path plus an add of the new one instead
    of one combined "renamed" entry, so both distinct path strings surface
    here; ``-m`` expands a merge commit's own diff rather than skipping it,
    the same way a file introduced only in a merge would otherwise be
    missed. The output is NUL-separated paths with no separator between
    commits (``--format=`` empties the log message itself), so this splits
    on NUL and drops the empty strings a commit boundary produces."""
    output = _git_range(
        repo, ["log", "-m", "--no-renames", "--name-only", "--format=", "-z", *revs]
    )
    return {path for path in output.decode("utf-8", errors="replace").split("\0") if path}


def _scan_history_blobs(
    repo: Path,
    compiled: list[tuple[Term, str, re.Pattern[str]]],
    hits: dict[tuple[str, str], int],
    declared: DeclaredIdentity,
    revs: list[str],
    label: str,
) -> tuple[int, list[str]]:
    """Every unique blob reachable from ``revs``, reported as
    ``<label>:<path>@<blob7>`` -- including a file that was committed and
    later removed, which ``git ls-files`` alone would never surface. Every
    distinct path recorded anywhere in history, blob or tree, is also
    checked by name (amendment C): a renamed or removed directory is still
    worth checking, the same as a file's own current path. That path set is
    the union of ``rev-list --objects``' own paths with ``_log_all_paths``,
    not ``rev-list --objects`` alone -- see that function's docstring for
    why one alone under-reports a rename. ``rev-list --objects`` names an
    annotated tag object by its tag name, so that name is checked too, and
    the tag objects found are returned for ``_scan_history_log``, beside how
    many blobs were read."""
    objects = _git_range(repo, ["rev-list", "--objects", *revs])

    entries: list[tuple[str, str]] = []
    for line in objects.decode("utf-8", errors="replace").splitlines():
        if not line:
            continue
        sha, _sep, path = line.partition(" ")
        if path:  # commits carry no path; trees, blobs and tags do
            entries.append((sha, path))

    all_paths = {path for _sha, path in entries} | _log_all_paths(repo, revs)
    for path in sorted(all_paths):
        _accumulate_path_name_hits(hits, path, f"{label}:", compiled)

    if not entries:
        return 0, []

    types = _object_types(repo, [sha for sha, _path in entries])
    tags = [sha for sha, _path in entries if types.get(sha) == "tag"]
    blob_paths = {sha: path for sha, path in entries if types.get(sha) == "blob"}
    if not blob_paths:
        return 0, tags

    contents = _object_contents(repo, list(blob_paths))
    for sha, data in contents.items():
        path = blob_paths.get(sha)
        if path is None:
            continue
        # rev-list names each blob once, so a byte-identical copy of AUTHORS
        # elsewhere passes too: harmless, it carries only AUTHORS's own text.
        exempt = _exemption(path, declared)
        _accumulate_hits(hits, f"{label}:{path}@{sha[:7]}", data, compiled, exempt)
    return len(contents), tags


def _parse_batch_output(data: bytes) -> dict[str, bytes]:
    """``git cat-file --batch``'s own framing: a ``<sha> <type> <size>``
    header line, then exactly ``size`` content bytes, then a trailing
    newline, repeated once per requested object. Byte-precise on purpose --
    file content can (and for the MTGO fixture's own format, does) contain
    anything, including bytes that would confuse a line-oriented read. Stops
    at the first header it cannot read, or a body shorter than its header
    says; the caller compares the count against what it asked for."""
    contents: dict[str, bytes] = {}
    pos = 0
    end_of_data = len(data)
    while pos < end_of_data:
        newline = data.find(b"\n", pos)
        if newline == -1:
            break
        header = data[pos:newline].decode("ascii", errors="replace")
        parts = header.split(" ")
        if len(parts) < 3 or not parts[2].isdigit():
            break  # unexpected framing; stop rather than misparse the rest
        sha, size = parts[0], parts[2]
        start = newline + 1
        stop = start + int(size)
        if stop > end_of_data:
            break
        contents[sha] = data[start:stop]
        pos = stop + 1  # the trailing newline after this object's content
    return contents


_TAGGER = re.compile(r"tagger (.*) <(.*)> \d+ [+-]\d{4}")
# A sign-off or co-author trailer: the key at the start of a message line, any
# case, then the name part, then (optionally) ` <address>` and anything after it.
_TRAILER = re.compile(
    r"^(?P<key>signed-off-by|co-authored-by):(?P<name>[^\n]*?)(?P<rest> <[^\n]*)?$",
    re.IGNORECASE | re.MULTILINE,
)


def _mask_declared_name_in_trailers(text: str, name: str | None) -> tuple[str, int]:
    """The declared name set aside in a trailer line whose whole name part
    -- after the key and colon, before `` <``, trimmed -- equals it,
    case-insensitively, the way an author field must equal it whole:
    `git commit -s` writes it there, and a contributor's declared name is
    often their global one, a term. Never as a substring, so a co-author
    whose name merely starts with it is still matched. The address after it
    stays, for the accepted-email rule. Returns the text and how many
    trailers were set aside; the same name anywhere else in a message is
    left to match."""
    if not name:
        return text, 0
    wanted = name.strip().casefold()
    replaced = 0

    def _mask(line: re.Match[str]) -> str:
        nonlocal replaced
        if line.group("name").strip().casefold() != wanted:
            return line.group(0)
        replaced += 1
        return f"{line.group('key')}:{line.group('rest') or ''}"

    return _TRAILER.sub(_mask, text), replaced


def _tag_fields(data: bytes) -> tuple[list[str], str]:
    """An annotated tag object's tagger name and email (none for a tag made
    without one) and its message, signature included: the headers end at
    the first blank line."""
    text = data.decode("utf-8", errors="replace")
    headers, _sep, message = text.partition("\n\n")
    for line in headers.splitlines():
        tagger = _TAGGER.fullmatch(line)
        if tagger:
            return [tagger.group(1), tagger.group(2)], message
    return [], message


def _scan_history_log(
    repo: Path,
    compiled: list[tuple[Term, str, re.Pattern[str]]],
    hits: dict[tuple[str, str], int],
    declared: DeclaredIdentity,
    emails: list[AcceptedEmail],
    revs: list[str],
    tags: list[str],
    label: str,
    scan: RangeScan,
) -> None:
    """Every commit's author/committer name and email, and its full message
    body, reachable from ``revs``, and every annotated tag's tagger and
    message -- one aggregate scan target, reported as ``<label>:log``
    (amendment: "plus git log --all ... reported as history:log", not one
    line per commit).

    Two ``git log`` passes, not one: the identity fields are NUL-separated
    so each can be compared whole against the declared identity, and a
    message body is free text that could hold any separator. A field equal
    to the declared value is left out of the scanned text; the body never
    is. A tagger is two fields more, under the same rule. The declared name
    is also set aside inside a ``Signed-off-by`` or ``Co-Authored-By``
    trailer line, and nowhere else in a message. Then every accepted
    address is set aside wherever it is left -- a field, a body, a trailer,
    a tag message -- while no other name is. Fills
    ``scan`` with the commits and tags read, the declared parts set aside
    and the accepted-email count."""
    identities = _git_range(repo, ["log", "--format=%an%x00%ae%x00%cn%x00%ce", *revs])
    bodies = _git_range(repo, ["log", "--format=%B%x00", *revs])
    tag_objects = _object_contents(repo, tags) if tags else {}
    if not identities and not tag_objects:
        return

    accepted: set[str] = set()
    kept: list[str] = []
    messages = [bodies.decode("utf-8", errors="replace")]
    commit_lines = identities.decode("utf-8", errors="replace").splitlines()
    field_groups = [line.split("\0") for line in commit_lines]
    scan.commits = len(field_groups)
    for data in tag_objects.values():
        tagger, message = _tag_fields(data)
        field_groups.append(tagger)
        messages.append(message)
    scan.tags = len(tag_objects)

    for fields in field_groups:
        for index, value in enumerate(fields):
            part, declared_value = (
                ("name", declared.name) if index % 2 == 0 else ("email", declared.email)
            )
            if declared_value is not None and value == declared_value:
                accepted.add(part)
            else:
                kept.append(value)

    message_text, trailer_names = _mask_declared_name_in_trailers(
        "\n".join(messages), declared.name
    )
    if trailer_names:
        accepted.add("name")
    text = "\n".join(kept) + "\n" + message_text
    text = _mask_accepted_emails(text, emails, scan.emails)
    _accumulate_hits(hits, f"{label}:log", text.encode("utf-8"), compiled)
    scan.declared_parts = [part for part in ("name", "email") if part in accepted]


def _scan_range(
    repo: Path,
    compiled: list[tuple[Term, str, re.Pattern[str]]],
    hits: dict[tuple[str, str], int],
    declared: DeclaredIdentity,
    revs: list[str],
    label: str,
) -> RangeScan:
    """The one walk --history and --pre-push share: the blobs and paths,
    then the log and the tags."""
    scan = RangeScan()
    scan.blobs, tags = _scan_history_blobs(repo, compiled, hits, declared, revs, label)
    emails, scan.refused_emails = _accepted_emails(repo, declared)
    _scan_history_log(repo, compiled, hits, declared, emails, revs, tags, label, scan)
    return scan


# --- --pre-push and --text ---------------------------------------------------


def _pushed_shas(stdin_text: str) -> list[str]:
    """The local object names of git's pre-push lines, ``<local ref> <local
    sha> <remote ref> <remote sha>`` each, leaving out a deletion (an
    all-zero local sha), which sends nothing. Split from the right, so a
    local ref with a space in it still parses. A malformed line is named by
    its number only."""
    shas: list[str] = []
    for lineno, line in enumerate(stdin_text.splitlines(), start=1):
        if not line.strip():
            continue
        # From the right: the local ref is what the user typed, and may hold a space.
        fields = line.rsplit(" ", 3)
        if len(fields) != 4 or not all(_OBJECT_NAME.fullmatch(f) for f in fields[1::2]):
            raise PrivacyScanError(f"--pre-push stdin line {lineno}: expected four fields")
        local_sha = fields[1]
        if set(local_sha) != {"0"} and local_sha not in shas:
            shas.append(local_sha)
    return shas


def _push_revs(shas: list[str], remote: str) -> list[str]:
    """Everything the remote doesn't already hold, as far as this clone
    knows it: a new branch, whose remote sha is zero, is measured against
    every branch of that remote, not against nothing."""
    return [*shas, "--not", f"--remotes={remote}"]


def _read_text_file(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PrivacyScanError(f"--text could not be read ({exc.__class__.__name__})") from exc


# --- orchestration -----------------------------------------------------


def _gather_terms(args: argparse.Namespace, repo: Path) -> tuple[list[Term], frozenset[str]]:
    terms: list[Term] = []
    card_words: frozenset[str] = frozenset()

    if args.terms_file:
        terms += _read_terms_file(Path(args.terms_file))

    if not args.no_local:
        terms += _terms_from_mtgo_handle()
        terms += _terms_from_os_user()
        terms += _terms_from_home()
        terms += _terms_from_git_identity(repo)
        terms += _terms_from_git_account(repo)
        terms += _terms_from_claude_key()
        terms += _terms_from_topdeck_key()
        terms += _terms_from_mtgo_dir()
        terms += _terms_from_arena_log_dir()
        terms += _terms_from_steam_library()
        terms += _terms_from_privacy_terms_file()

    db_explicit = args.db is not None
    db_path = Path(args.db) if db_explicit else (repo / "data" / "sensei-top.db")

    if not args.no_local:
        terms += _terms_from_backup_dir(db_path)

    if db_explicit:
        if not db_path.exists():
            raise PrivacyScanError("--db does not exist")
        db_terms, card_words = _terms_from_db(db_path)
        terms += db_terms
    elif not args.no_local and db_path.exists():
        db_terms, card_words = _terms_from_db(db_path)
        terms += db_terms

    return terms, card_words


def terms_for_demo(db: Path) -> list[Term]:
    """The terms ``scripts/demo_db.py`` rewrites in a copy of ``db``: every
    term this scan derives from that database (``arena-name``, ``arena-id``,
    ``opponent``, ``mtgo-player``), plus this machine's MTGO handle, OS user
    and home directory, filtered exactly as a scan filters them (card words
    never count). ``db`` is opened ``mode=ro`` and must exist. No credential
    is read. The loaders' own warnings are silenced for the call, as ``main``
    silences them, since one can name a config file's absolute path."""
    previous_disable_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            terms = _terms_from_mtgo_handle() + _terms_from_os_user() + _terms_from_home()
            db_terms, card_words = _terms_from_db(db)
    finally:
        logging.disable(previous_disable_level)
    dropped = {"short": 0, "generic": 0, "card-word": 0}
    return _filter_terms(terms + db_terms, card_words, dropped)


def _run(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    _check_git_repo(repo)
    declared = _declared_identity(repo)

    pushed: list[str] = []
    if args.pre_push is not None:
        pushed = _pushed_shas(sys.stdin.read())
        if not declared.name:
            print(
                "error: --pre-push needs a user.name in this repository's own "
                "configuration (git config --local user.name), so nothing is "
                "pushed under the global one",
                file=sys.stderr,
            )
            return 1

    terms, card_words = _gather_terms(args, repo)
    dropped = {"short": 0, "generic": 0, "card-word": 0}
    terms = _filter_terms(terms, card_words, dropped)
    compiled = _compile_terms(terms)

    hits: dict[tuple[str, str], int] = {}
    counts = {"missing": 0}
    scan = RangeScan()
    log_label = _HISTORY_LABEL

    if args.text is not None:
        _accumulate_hits(hits, "text", _read_text_file(Path(args.text)), compiled)
        scanned = "1 text"
    elif args.pre_push is not None:
        log_label = _PUSH_LABEL
        if pushed:
            revs = _push_revs(pushed, args.pre_push)
            scan = _scan_range(repo, compiled, hits, declared, revs, log_label)
        scanned = (
            f"{scan.commits} pushed commits, {scan.blobs} pushed blobs, {scan.tags} pushed tags"
        )
    else:
        tracked = _list_tracked_files(repo)
        prefix = _repo_prefix(repo)
        for rel_path in tracked:
            label = rel_path.as_posix()
            _accumulate_path_name_hits(hits, label, "", compiled)
            data = _tracked_file_content(repo / rel_path, label, compiled, counts)
            if data is not None:
                _accumulate_hits(hits, label, data, compiled, _exemption(prefix + label, declared))
        scanned = f"{len(tracked)} files"
        if args.history:
            scan = _scan_range(repo, compiled, hits, declared, ["--all"], log_label)
            scanned += f", {scan.blobs} history blobs"

    for (category, path), count in sorted(hits.items()):
        print(f"{category}\t{path}\t{count}")

    category_counts = Counter(candidate.category for candidate in terms)
    if category_counts:
        breakdown = ", ".join(f"{cat} {n}" for cat, n in sorted(category_counts.items()))
        terms_desc = f"{len(terms)} terms checked ({breakdown})"
    else:
        terms_desc = f"{len(terms)} terms checked"

    missing_clause = ""
    if counts["missing"] > 0:
        missing_clause = f"; {counts['missing']} missing from the working tree"
    accepted_clause = ""
    if scan.declared_parts:
        accepted_clause = (
            f"; declared identity accepted in {log_label}:log: {', '.join(scan.declared_parts)}"
        )
    if scan.emails:
        by_source = ", ".join(
            f"{source} {scan.emails[source]}"
            for source in ("declared", "global")
            if scan.emails[source]
        )
        accepted_clause += f"; accepted emails set aside in {log_label}:log: {by_source}"
    for source in scan.refused_emails:
        accepted_clause += f"; {source} email not accepted: not an address"

    print(
        f"privacy_scan: {terms_desc}, {scanned} scanned; "
        f"dropped {dropped['short']} short, {dropped['generic']} generic, "
        f"{dropped['card-word']} card-word{missing_clause}{accepted_clause}",
        file=sys.stderr,
    )
    return 1 if hits else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=".", help="git working tree to scan (default: .)")
    parser.add_argument(
        "--db",
        default=None,
        help=(
            "database to derive arena-name/arena-id/opponent terms from, opened "
            "mode=ro (default: <repo>/data/sensei-top.db, skipped silently if absent; "
            "a path given explicitly here is always read, and an explicit path "
            "that does not exist is an error)"
        ),
    )
    parser.add_argument(
        "--terms-file",
        default=None,
        help="path to extra label<TAB>value lines to add as terms, one per line",
    )
    parser.add_argument(
        "--no-local",
        action="store_true",
        help=(
            "skip every automatic local source of terms (this machine's config, "
            "git identity, the default database); --terms-file and an explicit "
            "--db still apply. Still read, only to set log fields aside and "
            "never as terms: the clone's declared identity, and under --history "
            "or --pre-push the global user.email"
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--history",
        action="store_true",
        help=(
            "also scan every blob reachable from any ref, plus commit "
            "authors/committers/messages -- much slower; an author or "
            "committer field equal to the repository's local user.name or "
            "user.email is set aside, as is the local or global user.email "
            "anywhere in the log, and the summary says so"
        ),
    )
    mode.add_argument(
        "--pre-push",
        metavar="REMOTE",
        default=None,
        help=(
            "read git's pre-push lines on stdin and scan only what the push "
            "sends: the commits REMOTE's branches don't hold, their blobs, "
            "paths, identities and messages, as --history does; the working "
            "tree is not scanned, and a repository with no local user.name "
            "is refused"
        ),
    )
    mode.add_argument(
        "--text",
        metavar="FILE",
        default=None,
        help=(
            "scan one file's text instead of the tree (a pull-request body, a "
            "comment); a hit prints as <category> text <count>, never the path"
        ),
    )
    return parser


def _print_crash(exc: BaseException) -> None:
    """Never the message, a source line, or an absolute path -- any of the
    three could hold a term, or this machine's own home directory. The
    exception's class name plus a bare ``file:line in function`` per frame is
    enough to start debugging without either (amendment F)."""
    print(f"error: {exc.__class__.__name__}", file=sys.stderr)
    for frame in traceback.extract_tb(exc.__traceback__):
        print(f"  {Path(frame.filename).name}:{frame.lineno} in {frame.name}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    # The local-source loaders warn (via `logging`) on a malformed or
    # incomplete config file, naming that file's absolute path -- under this
    # machine's own home directory -- and a bare `warnings.warn` prints an
    # absolute source path too. Both are silenced for the run and restored
    # before returning either way, so an in-process caller (a test, or a
    # future importer) is left exactly as it found this process (amendment
    # A). "Restored" means the *previous* logging.disable level, captured
    # before this function overrides it -- never an unconditional reset to
    # NOTSET, which would clobber a caller's own prior logging.disable(...)
    # rather than leave it alone.
    previous_disable_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return _run(args)
    except PrivacyScanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # see _print_crash: never a raw traceback or message (amendment F)
        _print_crash(exc)
        return 2
    finally:
        logging.disable(previous_disable_level)


if __name__ == "__main__":
    sys.exit(main())
