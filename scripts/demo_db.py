"""Build the demo database: a copy of a real one with every identifier
rewritten, for the screenshots the site and the README show.

    uv run python scripts/demo_db.py --from PATH --to PATH \\
        [--live MATCH_ID] [--live-cut RAW_EVENT_ID] [--seed N]

Every screenshot in ``site/img/`` and ``docs/images/`` comes from a database
this script wrote, and nothing captured from the real database goes into a
tracked file (``docs/frontend.md``, "The demo database").

**The copy.** ``--to`` must not exist, must not be ``--from``, must not sit
under the repository's ``data/``, and must be gitignored if it is inside the
repository at all; each is refused before anything is touched. The copy is
``sqlite3.Connection.backup()`` from a ``mode=ro`` connection, so a running
server is never disturbed and the copy is consistent. The copy is then
migrated like any database ``open_database()`` opens: it is a scratch file.

**The terms** are ``privacy_scan.py``'s own (``terms_for_demo``): every
identifier the database names, the user's and every opponent's, plus this
machine's MTGO handle, OS user and home directory. They are read after a
first ``project()`` of the copy, since the source's own projection can lag
its raw events and an opponent missing from ``matches`` would have no term.
Matching follows the scan:
case-insensitive, a name only as a whole word (and also right after MTGO's
``@P`` handle marker, which the scan's word rule would not see), an id or a
path anywhere.

**The rewrite** touches every text value of every table, longest term first,
each term always to the same pseudonym: the user's Arena name becomes
``Deshi#00001`` (``Deshi`` without the number), their MTGO handle
``Deshi``, every other player ``<given name>#<5 digits>`` drawn from a fixed
list with ``--seed``; ids, the OS user and the home directory get fixed
stand-ins. ``raw_events.digest`` keeps the original payload's hash, which only
ingestion reads, and nothing is ever ingested into the copy. MTGO rows are
base64 of the client's own bytes, not text: a game log is rewritten string by
string, by the projector's own reading of its framing, each string's length
prefix rewritten with it; a deck file is rewritten as the UTF-8 it is. Then
``project()`` rebuilds the copy, with ``MTGO_HANDLE`` set to the pseudonym so
MTGO matches resolve again, and every table is rewritten once more: a rebuild
writes what the raw events say, and the authored tables survive it.

**``--live MATCH_ID``** cuts ``raw_events`` inside one match so the Live page
shows it in progress. The match must be Arena, unranked
(``table/ranked.py``), completed and best of three (two games or more in
``games``). The cut is the row after which the projector knows the last
game's result, found by replaying the rows through ``Projector`` itself;
every row from it on is deleted, later matches with them. ``--live-cut``
moves the cut earlier, to any row inside the match; the per-game ranges the
script prints are the choices.

**Last, the check**: every text value of every table, and every MTGO payload
decoded, scanned for every term. One hit deletes the copy and exits 2 with
counts by category.

Nothing printed, on any path, carries a term: stdout is row counts, term
counts by category and the cut; a refusal names the flag, never a path; an
exception prints its class and the frames' file names only, as
``privacy_scan.py`` does. Logging and warnings are silenced for the run,
since a projector warning can name a source file's path.

Exit codes: 0 written; 2 the check found a term, nothing kept; 3 refused,
nothing written; 4 failed, nothing kept.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import importlib.util
import logging
import os
import random
import re
import sqlite3
import subprocess
import sys
import traceback
import warnings
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
_PRIVACY_SCAN = Path(__file__).resolve().with_name("privacy_scan.py")

EXIT_FOUND, EXIT_REFUSED, EXIT_FAILED = 2, 3, 4

# Forty neutral given names (D6). None may be a card word or a real
# player's name on purpose; a draw that collides with any term is drawn again.
_GIVEN_NAMES = (
    "Alex", "Ana", "Ari", "Bea", "Caio", "Cris", "Dani", "Davi", "Eli", "Ema",
    "Fran", "Gil", "Ian", "Iris", "Jo", "Jules", "Kai", "Lara", "Leo", "Lia",
    "Luca", "Mae", "Max", "Mia", "Nico", "Noa", "Otto", "Paz", "Rafa", "Remy",
    "Rio", "Sam", "Sasha", "Tai", "Teo", "Uma", "Val", "Vic", "Yan", "Zoe",
)
# Not `Sensei`: the scan matches the user's Arena name as a whole word, so the
# product's own name would make every "Sensei Top" in the tree a finding.
SELF_NAME = "Deshi"
SELF_TAGGED = "Deshi#00001"
# The user's own categories claim a value first, so a handle that is both the
# user's MTGO handle and an `mtgo-player` becomes `Deshi`, not a stranger.
_PRIORITY = ("arena-name", "arena-id", "mtgo-handle", "os-user", "home")
_MTGO_SOURCES = ("mtgo", "mtgo_deck")
_WORD_CHAR = re.compile(r"\w")


class RefusedError(Exception):
    """A refusal, exit 3. The message names a flag or a condition, never a
    path or a term."""


class FoundError(Exception):
    """The final check found a term, exit 2. Carries counts by category."""

    def __init__(self, counts: Counter[str]) -> None:
        super().__init__("terms found")
        self.counts = counts


# --- terms and pseudonyms ------------------------------------------------


def _load_privacy_scan() -> ModuleType:
    spec = importlib.util.spec_from_file_location("privacy_scan", _PRIVACY_SCAN)
    if spec is None or spec.loader is None:
        raise RuntimeError("privacy_scan.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves its string annotations through sys.modules.
    sys.modules.setdefault("privacy_scan", module)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True, slots=True)
class DemoTerm:
    category: str
    value: str
    word: bool


def _lower(text: str) -> str:
    """Lowercase without moving any character: a handful of characters
    lowercase to two, which would shift every match position after them."""
    lowered = text.lower()
    if len(lowered) == len(text):
        return lowered
    return "".join(ch.lower() if len(ch.lower()) == 1 else ch for ch in text)


def _trie_pattern(keys: Iterable[str], *, word: bool) -> re.Pattern[str] | None:
    """One regex for every key, shaped as a trie so a search costs the length
    of a key, not the number of them (a real database holds thousands). The
    longer continuation is always tried before a key's own end, so the
    longest key wins at any start. A word key must end at a non-word
    character; where it starts is checked by the caller."""
    root: dict[str, dict] = {}
    for key in keys:
        node = root
        for ch in key:
            node = node.setdefault(ch, {})
        node[""] = {}
    if not root:
        return None
    end = r"(?!\w)" if word else ""

    def emit(node: dict[str, dict]) -> str:
        branches = [re.escape(ch) + emit(child) for ch, child in sorted(node.items()) if ch]
        if "" in node:
            branches.append(end)
        if len(branches) == 1 and "" not in node:
            return branches[0]
        return "(?:" + "|".join(branches) + ")"

    return re.compile(emit(root))


def _word_start(lowered: str, start: int) -> bool:
    if start == 0 or not _WORD_CHAR.match(lowered[start - 1]):
        return True
    return lowered[start - 2 : start] == "@p"


class Matcher:
    """Finds and replaces terms in text. Keys are the terms' lowercase
    values; a value that is a substring term anywhere needs no word
    boundary anywhere."""

    def __init__(self, terms: Iterable[DemoTerm], mapping: dict[str, str] | None = None):
        self.category: dict[str, str] = {}
        words: set[str] = set()
        substrings: set[str] = set()
        for term in terms:
            key = _lower(term.value)
            self.category.setdefault(key, term.category)
            (words if term.word else substrings).add(key)
        self._word = _trie_pattern(words - substrings, word=True)
        self._substring = _trie_pattern(substrings, word=False)
        self.mapping = mapping or {}
        self.rewritten: set[str] = set()

    def spans(self, text: str) -> list[tuple[int, int, str]]:
        lowered = _lower(text)
        found: list[tuple[int, int]] = []
        if self._substring is not None:
            found += [(m.start(), m.end()) for m in self._substring.finditer(lowered)]
        if self._word is not None:
            pos = 0
            while (m := self._word.search(lowered, pos)) is not None:
                if _word_start(lowered, m.start()):
                    found.append((m.start(), m.end()))
                    pos = m.end()
                else:
                    # Where a word starts depends on the position only, so
                    # no other key starting here can pass either.
                    pos = m.start() + 1
        if not found:
            return []
        found.sort(key=lambda span: (span[0], -span[1]))
        chosen: list[tuple[int, int, str]] = []
        end = -1
        for start, stop in found:
            if start >= end:
                chosen.append((start, stop, lowered[start:stop]))
                end = stop
        return chosen

    def has_hit(self, text: str) -> bool:
        return bool(self.spans(text))

    def rewrite(self, text: str) -> str:
        spans = self.spans(text)
        if not spans:
            return text
        parts: list[str] = []
        last = 0
        for start, stop, key in spans:
            parts.append(text[last:start])
            parts.append(self.mapping[key])
            self.rewritten.add(key)
            last = stop
        parts.append(text[last:])
        return "".join(parts)

    def hit_categories(self, text: str) -> Counter[str]:
        return Counter(self.category[key] for _start, _stop, key in self.spans(text))


def _demo_terms(privacy_terms: Iterable[object]) -> list[DemoTerm]:
    return [
        DemoTerm(category=t.category, value=t.value, word=str(t.match) == "word")  # type: ignore[attr-defined]
        for t in privacy_terms
    ]


def build_mapping(terms: list[DemoTerm], seed: int) -> dict[str, str]:
    """Lowercase term value -> pseudonym (D6). The order is fixed (the
    user's categories first, then by category and value) and the draws come
    from ``random.Random(seed)``, so the same database and seed always give
    the same pseudonyms; no pseudonym is derived from the value itself."""
    rank = {category: i for i, category in enumerate(_PRIORITY)}
    ordered = sorted(
        terms, key=lambda t: (rank.get(t.category, len(rank)), t.category, _lower(t.value), t.value)
    )
    checker = Matcher(terms)
    rng = random.Random(seed)
    used: set[str] = set()
    numbered: Counter[str] = Counter()
    mapping: dict[str, str] = {}

    def draw() -> str:
        for _ in range(10_000):
            candidate = f"{rng.choice(_GIVEN_NAMES)}#{rng.randrange(100_000):05d}"
            if _lower(candidate) not in used and not checker.has_hit(candidate):
                return candidate
        raise RuntimeError("no free pseudonym")

    for term in ordered:
        key = _lower(term.value)
        if key in mapping:
            continue
        category = term.category
        if category == "arena-name":
            pseudonym = SELF_TAGGED if "#" in term.value else SELF_NAME
        elif category == "mtgo-handle":
            pseudonym = SELF_NAME
        elif category == "os-user":
            pseudonym = "deshi"
        elif category == "home":
            pseudonym = "home/deshi"
        elif category == "arena-id":
            numbered[category] += 1
            pseudonym = f"DESHIDEMO{numbered[category]:06d}"
        elif category in ("opponent", "mtgo-player") and term.word:
            pseudonym = draw()
        elif category == "opponent":
            numbered[category] += 1
            pseudonym = f"DEMOOPPONENT{numbered[category]:04d}"
        else:
            numbered[category] += 1
            pseudonym = f"redacted{numbered[category]:05d}"
        used.add(_lower(pseudonym))
        mapping[key] = pseudonym
    return mapping


# --- MTGO payloads --------------------------------------------------------


def _encode_7bit(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def rewrite_game_log(data: bytes, rewrite: Callable[[str], str]) -> bytes:
    """``decode_strings``' own walk over a game log, emitting every byte it
    skips unchanged and every string it accepts rewritten, behind a length
    prefix for the new length. The projector's resync scan reads the result
    the way it read the original."""
    from sensei_top.projector.mtgo.decode import (
        _MIN_LEN,
        _looks_like_text,
        _read_7bit_encoded_int,
    )

    out = bytearray()
    changed = False
    i = 0
    n = len(data)
    while i < n:
        parsed = _read_7bit_encoded_int(data, i)
        if parsed is not None:
            length, after = parsed
            if length >= _MIN_LEN and after + length <= n:
                try:
                    text = data[after : after + length].decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    text = None
                if text is not None and _looks_like_text(text):
                    new = rewrite(text)
                    changed = changed or new != text
                    encoded = new.encode("utf-8")
                    out += _encode_7bit(len(encoded)) + encoded
                    i = after + length
                    continue
        out.append(data[i])
        i += 1
    return bytes(out) if changed else data


def _b64(payload: str) -> bytes | None:
    try:
        return base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        return None


def _rewrite_mtgo_payload(source: str, payload: str, rewrite: Callable[[str], str]) -> str:
    data = _b64(payload)
    if data is None:
        return rewrite(payload)
    if source == "mtgo":
        new = rewrite_game_log(data, rewrite)
    else:
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return payload  # left as it is; the check reads it anyway
        new = rewrite(text).encode("utf-8")
    return payload if new == data else base64.b64encode(new).decode("ascii")


def _decoded_texts(source: str, payload: str) -> Iterator[str]:
    """What the check reads of an MTGO payload: its strings the projector's
    way, and its bytes as ``privacy_scan.py`` reads a file (UTF-8, and
    UTF-16 at both offsets when there is a NUL), framing included."""
    from sensei_top.projector.mtgo.decode import decode_strings

    data = _b64(payload)
    if data is None:
        yield payload
        return
    if source == "mtgo":
        yield from decode_strings(data)
    yield data.decode("utf-8", errors="replace")
    if b"\x00" in data:
        yield data.decode("utf-16-le", errors="replace")
        yield data[1:].decode("utf-16-le", errors="replace")


# --- the database ---------------------------------------------------------


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({_q(table)})")]


def _mtgo_filter(table: str, column: str) -> str:
    if table == "raw_events" and column == "payload":
        return " AND COALESCE(source, '') NOT IN ('mtgo', 'mtgo_deck')"
    return ""


def rewrite_database(conn: sqlite3.Connection, matcher: Matcher) -> None:
    """Every text value of every table, then the MTGO payloads. Foreign keys
    are off for it: a key and its references are rewritten alike, but not in
    the same statement."""
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.create_function("demo_hit", 1, matcher.has_hit, deterministic=True)
    conn.create_function("demo_rewrite", 1, matcher.rewrite, deterministic=True)
    conn.execute("BEGIN")
    try:
        for table in _tables(conn):
            for column in _columns(conn, table):
                c = _q(column)
                conn.execute(
                    f"UPDATE {_q(table)} SET {c} = demo_rewrite({c}) "
                    f"WHERE typeof({c}) = 'text' AND demo_hit({c})" + _mtgo_filter(table, column)
                )
        rows = conn.execute(
            "SELECT id, source, payload FROM raw_events WHERE source IN (?, ?)", _MTGO_SOURCES
        ).fetchall()
        for row_id, source, payload in rows:
            new = _rewrite_mtgo_payload(source, payload, matcher.rewrite)
            if new != payload:
                conn.execute("UPDATE raw_events SET payload = ? WHERE id = ?", (new, row_id))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("PRAGMA foreign_keys=ON")


def check_database(conn: sqlite3.Connection, matcher: Matcher) -> Counter[str]:
    """Counts by category of every term still anywhere in the copy."""
    counts: Counter[str] = Counter()
    for table in _tables(conn):
        for column in _columns(conn, table):
            c = _q(column)
            for (value,) in conn.execute(
                f"SELECT {c} FROM {_q(table)} WHERE typeof({c}) IN ('text', 'blob')"
                + _mtgo_filter(table, column)
            ):
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                counts += matcher.hit_categories(value)
    for source, payload in conn.execute(
        "SELECT source, payload FROM raw_events WHERE source IN (?, ?)", _MTGO_SOURCES
    ):
        for text in _decoded_texts(source, payload):
            counts += matcher.hit_categories(text)
    return counts


@dataclass(frozen=True, slots=True)
class LiveCut:
    match_id: str
    cut: int
    games: list[tuple[int, int, int]]  # (game number, first raw event id, last)


def find_live_cut(conn: sqlite3.Connection, match_id: str, override: int | None) -> LiveCut:
    """Checks ``--live``'s match, then replays ``raw_events`` through the
    projector until it knows the last game's result: that row is the
    default cut, and each game's range is from the row that opened it to the
    row that decided it."""
    import orjson

    from sensei_top.projector.matches import Projector, _first_request_occurrences
    from sensei_top.table.ranked import is_ranked

    row = conn.execute(
        "SELECT source, event_id, result FROM matches WHERE match_id = ?", (match_id,)
    ).fetchone()
    if row is None:
        raise RefusedError("--live: no match with that id")
    source, event_id, result = row
    if source != "arena":
        raise RefusedError("--live: the match is not an Arena match")
    if is_ranked(event_id):
        raise RefusedError("--live: the match was played in a ranked queue (table/ranked.py)")
    if result == "incomplete":
        raise RefusedError("--live: the match is not completed")
    games = conn.execute(
        "SELECT COUNT(*), MAX(game_number) FROM games WHERE match_id = ?", (match_id,)
    ).fetchone()
    if games[0] < 2:
        raise RefusedError("--live: the match is not best of three (fewer than two games)")
    last_game = games[1]

    # project()'s own replay loop, request dedup included, one row at a time.
    projector = Projector()
    first_request_id, first_request_logged_at = _first_request_occurrences(conn)
    match_start: int | None = None
    opened: dict[int, int] = {}
    decided: dict[int, int] = {}
    for row_id, kind, label, payload_text, logged_at in conn.execute(
        "SELECT id, kind, label, payload, logged_at FROM raw_events "
        "WHERE source = 'arena' ORDER BY id"
    ):
        try:
            payload = orjson.loads(payload_text)
        except ValueError:
            continue
        if kind == "request" and isinstance(payload, dict):
            request_id = payload.get("id")
            if isinstance(request_id, str) and request_id in first_request_id:
                if first_request_id[request_id] != row_id:
                    continue
                if logged_at is None:
                    logged_at = first_request_logged_at.get(request_id)
        projector.feed_parsed(kind, label, payload, logged_at)
        state = projector.matches.get(match_id)
        if state is None:
            continue
        if match_start is None:
            match_start = row_id
        for number, game in state.games.items():
            opened.setdefault(number, row_id)
            if game.result is not None:
                decided.setdefault(number, row_id)
        if last_game in decided:
            break
    if match_start is None or last_game not in decided:
        raise RefusedError("--live: replaying the raw events never decided the match's last game")
    cut = decided[last_game]
    if override is not None:
        if not match_start < override <= cut:
            raise RefusedError("--live-cut: the row is not inside the match (see the game ranges)")
        cut = override
    spans = [(n, opened[n], decided.get(n, cut)) for n in sorted(opened)]
    return LiveCut(match_id=match_id, cut=cut, games=spans)


# --- paths ----------------------------------------------------------------


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def check_paths(source: Path, target: Path) -> None:
    if not source.is_file():
        raise RefusedError("--from is not a database file")
    if target.resolve() == source.resolve():
        raise RefusedError("--to is --from")
    for candidate in (target, *(target.with_name(target.name + s) for s in ("-wal", "-shm"))):
        if candidate.exists() or candidate.is_symlink():
            raise RefusedError("--to already exists")
    # The address first, then the disk: data/ and the gitignore judge where
    # --to points, whether or not its directory exists on this clone.
    resolved = target.parent.resolve() / target.name
    if _inside(resolved, REPO_ROOT / "data"):
        raise RefusedError("--to is under the repository's data/")
    if _inside(resolved, REPO_ROOT):
        ignored = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--", str(resolved)],
            capture_output=True,
        )
        if ignored.returncode != 0:
            raise RefusedError("--to is inside the repository and not gitignored")
    if not target.parent.is_dir():
        raise RefusedError("--to's directory does not exist")


def copy_database(source: Path, target: Path) -> None:
    src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _remove(target: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        target.with_name(target.name + suffix).unlink(missing_ok=True)


# --- the run --------------------------------------------------------------


def _project(conn: sqlite3.Connection, self_handle: str | None) -> None:
    """``project()``, with ``MTGO_HANDLE`` naming the user's MTGO pseudonym
    when they have a handle, so their MTGO matches resolve against the
    rewritten logs, and restored afterwards. ``None`` leaves the
    environment alone: the machine's own handle, as before the rewrite."""
    from sensei_top.projector.matches import project

    previous = os.environ.get("MTGO_HANDLE")
    if self_handle is not None:
        os.environ["MTGO_HANDLE"] = self_handle
    try:
        project(conn)
    finally:
        if previous is None:
            os.environ.pop("MTGO_HANDLE", None)
        else:
            os.environ["MTGO_HANDLE"] = previous


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {_q(table)}").fetchone()[0]


def build(args: argparse.Namespace) -> list[str]:
    """Writes the copy and returns the lines to print. Raises ``RefusedError``
    before the copy exists; after it exists, every failure deletes it."""
    source, target = Path(args.source), Path(args.target)
    if args.live_cut is not None and args.live is None:
        raise RefusedError("--live-cut needs --live")
    check_paths(source, target)
    try:
        copy_database(source, target)
        return _build_copy(target, args)
    except BaseException:
        _remove(target)
        raise


def _build_copy(target: Path, args: argparse.Namespace) -> list[str]:
    from sensei_top.db import open_database

    lines: list[str] = []
    conn = open_database(target)
    try:
        # Project first, with this machine's own MTGO handle: the terms come
        # from `matches`, and the source's own projection can lag its raw
        # events (a match in progress, or one inside the watcher's gate). A
        # match missing there would leave its opponent without a term.
        _project(conn, None)
        privacy_scan = _load_privacy_scan()
        terms = _demo_terms(privacy_scan.terms_for_demo(target))
        mapping = build_mapping(terms, args.seed)
        matcher = Matcher(terms, mapping)
        matches_before = _count(conn, "matches")

        live: LiveCut | None = None
        if args.live is not None:
            live = find_live_cut(conn, args.live, args.live_cut)
            conn.execute("DELETE FROM raw_events WHERE id >= ?", (live.cut,))

        self_handle = next(
            (mapping[_lower(t.value)] for t in terms if t.category == "mtgo-handle"), None
        )
        rewrite_database(conn, matcher)
        _project(conn, self_handle)
        rewrite_database(conn, matcher)

        found = check_database(conn, matcher)
        if found:
            raise FoundError(found)

        if live is not None:
            current = conn.execute("SELECT match_id FROM v_current_match").fetchall()
            if [row[0] for row in current] != [live.match_id]:
                raise RefusedError("--live: after the rebuild the match is not the current match")

        lines.append(f"raw_events: {_count(conn, 'raw_events')} rows")
        lines.append(f"matches: {_count(conn, 'matches')} rows")
        by_category = Counter(matcher.category[key] for key in matcher.rewritten)
        summary = ", ".join(f"{cat} {n}" for cat, n in sorted(by_category.items())) or "none"
        lines.append(f"terms rewritten: {summary} (of {len(mapping)} terms)")
        if live is not None:
            for number, first, last in live.games:
                lines.append(f"game {number}: raw events {first}-{last}")
            dropped = matches_before - _count(conn, "matches")
            lines.append(
                f"live: match {live.match_id} cut at raw event {live.cut}; "
                f"{dropped} later match(es) dropped"
            )
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    return lines


def _print_crash(exc: BaseException) -> None:
    """Never the message, a source line or an absolute path: any could hold
    a term (``privacy_scan.py``'s ``_print_crash``, the same rule)."""
    print(f"error: {exc.__class__.__name__}", file=sys.stderr)
    for frame in traceback.extract_tb(exc.__traceback__):
        print(f"  {Path(frame.filename).name}:{frame.lineno} in {frame.name}", file=sys.stderr)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy a database with every identifier rewritten, for screenshots.",
    )
    parser.add_argument("--from", dest="source", required=True, help="the database to copy")
    parser.add_argument("--to", dest="target", required=True, help="the copy; must not exist")
    parser.add_argument(
        "--live", metavar="MATCH_ID",
        help="cut raw_events inside this unranked best-of-three Arena match",
    )
    parser.add_argument(
        "--live-cut", metavar="RAW_EVENT_ID", type=int,
        help="cut at this raw event instead of the last game's result",
    )
    parser.add_argument("--seed", type=int, default=0, help="seed for the pseudonyms (default 0)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    previous_disable_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lines = build(args)
    except RefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except FoundError as exc:
        counts = ", ".join(f"{cat} {n}" for cat, n in sorted(exc.counts.items()))
        print(f"terms still in the copy, so it was deleted: {counts}", file=sys.stderr)
        return EXIT_FOUND
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_FAILED
    except Exception as exc:  # _print_crash: never the message
        _print_crash(exc)
        return EXIT_FAILED
    finally:
        logging.disable(previous_disable_level)
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
