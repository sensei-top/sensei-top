"""MTGO raw event ingestion: game-log file -> ``raw_events``.

Stage 1 of the two-stage pipeline (AGENTS.md non-negotiable #1), same
discipline as ``ingest.py``: this module knows about files, offsets and
hashing. It knows nothing about MTGO semantics — no turns, no games, no card
names. ``projector/mtgo/`` is the only place that decodes a payload.

Why this can't reuse ``ingest.py`` as-is
-----------------------------------------
MTGO writes one ``Match_GameLog_<guid>.dat`` **file** per match, not one
growing text stream with a header timestamp on every line:

* **No per-line timestamp exists**, so Arena's digest formula has nothing to
  key on. This reader hashes the **filename plus the whole file's bytes**
  instead (``_file_digest``). The filename carries the match GUID by
  construction, so this stays a reader-level, no-semantics hash: it never
  has to decode the payload to find the GUID that is also the first string
  *inside* the file.
* **There is no line framing to resume from.** The payload is a binary blob
  that only means something decoded whole, so every stored row is the
  **whole file** as it was when read, never the bytes past the previous row.
  A match has one row per store, each a longer prefix of the same eventual
  file; nothing already written is edited or discarded (non-negotiable #2),
  and the projector keeps the **longest** payload per match
  (``projector/mtgo/project.py``). Why not delta rows:
  docs/architecture.md, "Storage".

Scan, read, store
-----------------
Three steps, kept apart so the watcher can put a judgement between them that
this module must not make:

* ``scan_game_logs`` says which files moved since they were last stored and
  returns their identities, not their bytes, writing nothing.
* ``read_game_log`` reads one file whole, with the identity of the bytes it
  read.
* ``store_game_log`` stores the bytes it is handed and records their
  identity, in one transaction of its own.

``ingest_mtgo_dir`` is the three in a row for every changed file: what
``sensei-top ingest-mtgo`` runs, and the watcher's first pass. After that
pass the watcher (``live.py::_poll_mtgo``) stores a changed file only once a
game ends (docs/architecture.md, "Live mode's two cadences"). Whether the
last game is decided is the projector's answer
(``projector/mtgo/parse.py::last_game_decided``); this module only reports
which files moved and stores the one it is handed, and ``live.py`` combines
the two (non-negotiable #1).

Change detection
----------------
``ingest_state`` (``migrations/002_ingest_state.sql``) is keyed by
``source_path``, so every per-match file gets its own bookkeeping row, exactly
as a second Arena log would. Its ``inode`` column, which migration 002 calls
an opaque identity token, holds ``<st_ino>:<st_mtime_ns>`` here, as in
``reader/mtgo_decks.py``; ``byte_offset`` and ``last_size`` both hold the size
("offset" has no resume meaning for a file always read whole). A file is
unchanged only when both the token and the size match.

The identity recorded is that of the bytes stored, never a later ``stat()``:
the size is their own length, and the mtime and inode come from the
``stat()`` taken just before reading them. So a file that grew after the read
shows a different size on the next scan, and a write that lands between the
``stat()`` and the read leaves an older mtime than the content, which the next
scan reports again; the digest then dedupes the re-read or stores the newer
bytes, never loses them. The mtime is in the token for a write that changes
bytes without changing the size, such as a copy that sizes its target before
filling it and sets the source's mtime once done. A file counts as read only
once it is stored, so a watcher stopped mid-game leaves it for the next one
to store.

Payload encoding
----------------
The raw ``.dat`` bytes are not valid TEXT (an opaque .NET binary stream —
non-UTF-8, arbitrary byte values), and ``raw_events.payload`` is a TEXT
column. Storing verbatim (rule 2) therefore means **base64**, not the raw
bytes and not a lossy decode: base64 round-trips exactly, so a future fix to
the decoder in ``projector/mtgo/decode.py`` can be replayed over history
without re-reading any file from disk. Only the projector base64-decodes.

``logged_at`` here is the file's own **mtime** as the read's ``stat()`` saw
it, not a per-event timestamp — MTGO's log offers no other time signal. Every
consumer of ``raw_events.logged_at`` must remember this column means
something different for ``source = 'mtgo'`` rows than it does for Arena's.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sensei_top.reader.ingest import IngestStats, _write_state
from sensei_top.reader.segmenter import EntryKind

log = logging.getLogger(__name__)

_LABEL = "MtgoGameLog"
_SOURCE = "mtgo"
_PATTERN = "Match_GameLog_*.dat"
_NS_PER_SECOND = 1_000_000_000


@dataclass(frozen=True, slots=True)
class GameLogFile:
    """One game-log file's identity as one ``stat()`` saw it, or as one read
    found it (``GameLogRead``). Two are equal only when path, size, mtime and
    inode all are, so the watcher can compare one scan's with the next to tell
    a quiet file from one still being written."""

    path: Path
    size: int
    mtime_ns: int
    inode: int

    @property
    def token(self) -> str:
        """This identity as ``ingest_state.inode`` holds it (module
        docstring, "Change detection")."""
        return f"{self.inode}:{self.mtime_ns}"


@dataclass(frozen=True, slots=True)
class GameLogRead:
    """One file's bytes and the identity they were read at. ``file.size`` is
    ``len(data)``, whatever size a ``stat()`` reported before or after."""

    file: GameLogFile
    data: bytes


def _file_digest(path: Path, data: bytes) -> str:
    """Content digest for one MTGO game-log file.

    Filename + full bytes, not ``ingest.py``'s formula (module docstring).
    The filename is folded in (rather than hashing bytes alone) so
    that two different matches which happened to write byte-identical
    content at some size — plausible early in a game, before any
    match-specific text has been written yet — still digest distinctly.
    """
    material = path.name.encode("utf-8") + b"\x00" + data
    return hashlib.sha256(material).hexdigest()


def _local_iso(mtime_ns: int) -> str:
    """``_mtime_iso``'s shape, from an mtime already taken: the store dates a
    row by the ``stat()`` that went with its read, never a later one."""
    return datetime.fromtimestamp(mtime_ns // _NS_PER_SECOND).isoformat(timespec="seconds")


def _mtime_iso(path: Path) -> str:
    """Local, naive, seconds-resolution ISO-8601 — deliberately the *same
    shape* Arena's header dates take: ``reader/segmenter.py``'s
    ``HeaderStamp.reading()``, put in ISO form by whichever resolver dates
    the header (``fixed_resolver`` there, ``auto_resolver`` in
    ``reader/dates.py``).

    Not a style preference. ``logged_at`` and ``matches.started_at`` are
    compared as TEXT across sources (``v_current_match``'s ``MAX``,
    ``/api/matches``' ``ORDER BY``, ``/api/live``'s newest ``logged_at``).
    Arena's log headers carry no zone, so Arena's column is local wall clock;
    UTC-with-``Z`` here would sort an MTGO match as though it were
    UTC-offset hours newer than an Arena match at the same instant, and put
    ``'Z'`` on the wrong side of the second-boundary comparison besides
    (migration 036).
    """
    return _local_iso(path.stat().st_mtime_ns)


def _stored_identities(
    conn: sqlite3.Connection, files: list[GameLogFile]
) -> dict[str, tuple[str | None, int]]:
    """``(token, size)`` from ``ingest_state`` for each of ``files`` it holds a
    row for, keyed by ``source_path``. One query for the whole scan, however
    many files the folder holds: the path list goes in as one JSON value
    (``json_each``) rather than as SQL built with a placeholder per file.
    Outside any transaction, the query's read snapshot lasts only as long as
    the query itself."""
    rows = conn.execute(
        """
        SELECT source_path, inode, last_size FROM ingest_state
         WHERE source_path IN (SELECT value FROM json_each(?))
        """,
        (json.dumps([str(file.path) for file in files]),),
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def _skip_unstattable(path: Path, exc: OSError) -> None:
    """``ingest_mtgo_dir``'s default ``on_stat_error``: a warning on every
    call that meets the file."""
    log.warning("mtgo: skipping %s (could not stat): %s", path.name, exc)


def scan_game_logs(
    conn: sqlite3.Connection,
    directory: str | Path,
    *,
    on_stat_error: Callable[[Path, OSError], None],
    from_start: bool = False,
) -> list[GameLogFile]:
    """Every ``Match_GameLog_*.dat`` in ``directory`` that moved since it was
    last stored, in name order, as one ``stat()`` saw it; under
    ``from_start``, every one of them. A directory that does not exist is an
    empty result.

    Reads no file, writes nothing and holds no transaction: one ``stat()``
    per file, then one ``ingest_state`` query (``_stored_identities``),
    because the watcher runs it every ``live.py::MTGO_POLL_SECONDS`` over a
    folder that keeps every match ever played. A file still changing keeps
    being reported, scan after scan, until a store records the identity it
    has. A file whose ``stat()`` fails (it vanished between the listing and
    the ``stat()``, or the share refused it) is left out and handed to
    ``on_stat_error`` with its error. Nothing is logged here, because only
    the caller knows how often it scans: ``ingest_mtgo_dir`` warns of it on
    every call, and the watcher once per file. A listing that itself fails
    (a dead mount) raises ``OSError`` for the caller.
    """
    directory = Path(directory)
    if not directory.exists():
        return []

    files: list[GameLogFile] = []
    for path in sorted(directory.glob(_PATTERN)):
        try:
            st = path.stat()
        except OSError as exc:
            on_stat_error(path, exc)
            continue
        files.append(GameLogFile(path, st.st_size, st.st_mtime_ns, st.st_ino))

    if from_start or not files:
        return files
    stored = _stored_identities(conn, files)
    return [file for file in files if stored.get(str(file.path)) != (file.token, file.size)]


def read_game_log(path: Path) -> GameLogRead:
    """Read one game log whole, with the identity of the bytes read: the
    mtime and inode of the ``stat()`` taken just before the read, and the
    bytes' own length as the size (module docstring, "Change detection").
    Raises ``OSError`` when the file vanished since it was scanned; the
    caller decides what that means.
    """
    st = path.stat()
    data = path.read_bytes()
    return GameLogRead(GameLogFile(path, len(data), st.st_mtime_ns, st.st_ino), data)


def store_game_log(conn: sqlite3.Connection, read: GameLogRead) -> bool:
    """Store ``read.data`` as one ``raw_events`` row and record ``read.file``
    in ``ingest_state``, both in one transaction of its own. True when the
    row is new, False when the digest already held these bytes (a file read
    again with nothing added).

    Stores exactly the bytes it is handed, so the caller stores the bytes it
    judged, and records their identity rather than the file's current one: a
    file that grew since the read is reported again by the next scan.
    """
    file = read.file
    digest = _file_digest(file.path, read.data)
    payload = base64.b64encode(read.data).decode("ascii")

    conn.execute("BEGIN")
    try:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO raw_events
                 (digest, source_file, logged_at, kind, label, payload, source)
                 VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                digest, file.path.name, _local_iso(file.mtime_ns), str(EntryKind.EVENT),
                _LABEL, payload, _SOURCE,
            ),
        )
        inserted = conn.total_changes > before
        _write_state(conn, file.path, file.size, file.token, file.size)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return inserted


def ingest_mtgo_dir(
    conn: sqlite3.Connection,
    directory: str | Path,
    *,
    from_start: bool = False,
    on_stat_error: Callable[[Path, OSError], None] = _skip_unstattable,
) -> IngestStats:
    """Store every ``Match_GameLog_*.dat`` in ``directory`` that changed since
    it was last stored: ``scan_game_logs``, then ``read_game_log`` and
    ``store_game_log`` for each file the scan reports, whatever is in it.
    What ``sensei-top ingest-mtgo`` and the watcher's first pass run.

    Unlike ``ingest_file``, there is no ``locale_hint`` (no header timestamps
    to parse). An all-unchanged directory costs the scan alone and opens no
    transaction. Each file is stored in a transaction of its own, so no write
    lock is held while the next file is read from what may be a slow share.

    ``entries_seen`` counts every file the scan reported, including one that
    could not then be read. Tolerates such a file (a virtiofs share torn down
    mid-scan, a match's log rotated away, ...): logs a warning and continues
    with the rest rather than raising (non-negotiable #4) — one unreadable
    file must never block every other file in the directory. A file the scan
    cannot ``stat()`` goes to ``on_stat_error``, which by default warns of it
    on every call, as for one that cannot be read; the watcher's first pass
    passes its own, which warns once per file for as long as it runs.
    """
    stats = IngestStats()
    scan = scan_game_logs(conn, directory, on_stat_error=on_stat_error, from_start=from_start)
    for file in scan:
        stats.entries_seen += 1
        try:
            read = read_game_log(file.path)
        except OSError as exc:
            log.warning("mtgo: skipping %s (could not read): %s", file.path.name, exc)
            continue
        stats.bytes_read += len(read.data)
        if store_game_log(conn, read):
            stats.rows_inserted += 1
        else:
            stats.rows_duplicate += 1
    return stats
