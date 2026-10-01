"""MTGO raw event ingestion: game-log file -> ``raw_events``.

Stage 1 of the two-stage pipeline (AGENTS.md non-negotiable #1), same
discipline as ``ingest.py``: this module knows about files, offsets and
hashing. It knows nothing about MTGO semantics — no turns, no games, no card
names. ``projector/mtgo/`` is the only place that decodes a payload.

Why this can't reuse ``ingest.py`` as-is
-----------------------------------------
MTGO writes one ``Match_GameLog_<guid>.dat`` **file** per match, not one
growing text stream with a header timestamp on every line
(``.claude/handoffs/mtgo-source.md``, questions 1-2):

* **No per-line timestamp exists**, so Arena's digest formula — hashing
  ``(logged_at, occurrence, payload)`` (``ingest.py``'s module docstring) —
  has nothing to key on. This reader hashes the **filename plus the whole
  file's bytes** instead. The filename already carries the match GUID by
  construction (``Match_GameLog_<guid>.dat``), so this stays a
  reader-level, no-semantics hash — it never has to decode the payload to
  find the GUID that is also the first string *inside* the file.
* **The file isn't append-only text to seek into.** MTGO flushes the same
  file progressively during a match (recon: 28 size changes across one real
  match) and there is no line-oriented framing to resume from mid-file — the
  payload is a binary blob that only means something decoded whole. So this
  reader has no byte-offset resume path: every ingest that finds a file
  changed re-reads it **in full** and stores the **entire current
  content** as a new row, rather than only the delta.
* One consequence of that: a match still in progress produces **multiple
  raw_events rows over time**, each a longer prefix of the same eventual
  file, one full payload per size seen. That is correct under append-only
  storage (non-negotiable #2) — nothing already written is ever edited or
  discarded — but it means the projector must pick, per match GUID, the
  **longest** payload rather than assuming one row is one match. See
  ``projector/mtgo/project.py``.
* This means storage grows with the *sum* of every prefix a live match ever
  reaches, not just its final size (``docs/architecture.md``'s storage
  arithmetic). The escape hatch, deferred rather than built: store only the
  **delta** past the previously-seen size instead of the whole file. Not done
  here because it rests on an unverified assumption — that MTGO never
  rewrites bytes earlier in the file on a later flush, only appends — and the
  transport this project uses (``robocopy /mon:1``) rewrites the destination
  file wholesale on every sync, which makes that assumption harder to trust
  without first tracing raw flush-to-flush byte diffs on a live match. Revisit
  if payload volume actually becomes a problem; don't build it speculatively.

``ingest_state`` (``migrations/002_ingest_state.sql``) still does the
unchanged-file skip: it is keyed by absolute ``source_path``, so every
per-match file gets its own bookkeeping row for free, exactly as it would for
a second Arena log. ``_read_state``/``_write_state`` are reused directly from
``ingest.py`` rather than reimplemented — same package, same table, same
inode/size truncation-detection idea (a file that shrank or changed inode is
treated as new content, not corruption).

Payload encoding
-----------------
The raw ``.dat`` bytes are not valid TEXT (they are an opaque .NET binary
stream — non-UTF-8, arbitrary byte values), and ``raw_events.payload`` is a
TEXT column. Storing verbatim (rule 2) therefore means **base64**, not the
raw bytes and not a lossy decode: base64 round-trips exactly, so a future fix
to the decoder in ``projector/mtgo/decode.py`` can be replayed over history
without re-reading any file from disk. Only the projector base64-decodes; the
cost of that is contained to the one place that needs the bytes.

``logged_at`` here is the file's own **mtime**, not a per-event timestamp —
MTGO's log offers no other time signal (recon question 2). Every consumer of
``raw_events.logged_at`` must remember this column means something different
for ``source = 'mtgo'`` rows than it does for Arena's.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from sensei_top.reader.ingest import IngestStats, _read_state, _write_state
from sensei_top.reader.segmenter import EntryKind

log = logging.getLogger(__name__)

_LABEL = "MtgoGameLog"
_SOURCE = "mtgo"


def _file_digest(path: Path, data: bytes) -> str:
    """Content digest for one MTGO game-log file.

    Filename + full bytes, not ``ingest.py``'s ``(logged_at, occurrence,
    payload)`` — see the module docstring for why that formula can't
    transfer. The filename is folded in (rather than hashing bytes alone) so
    that two different matches which happened to write byte-identical
    content at some size — plausible early in a game, before any
    match-specific text has been written yet — still digest distinctly.
    """
    material = path.name.encode("utf-8") + b"\x00" + data
    return hashlib.sha256(material).hexdigest()


def _mtime_iso(path: Path) -> str:
    """Local, naive, seconds-resolution ISO-8601 — deliberately the *same
    shape* ``reader/segmenter.py``'s ``parse_header_timestamp`` produces for
    Arena.

    Not a style preference. ``logged_at`` and ``matches.started_at`` are
    compared as TEXT across sources (``v_current_match``'s ``MAX``,
    ``/api/matches``' ``ORDER BY``, ``/api/live``'s ``MAX(logged_at)``).
    Arena's log headers carry no zone, so Arena's column is local wall clock;
    writing MTGO's as UTC-with-``Z`` made an MTGO match sort as though it were
    UTC-offset hours newer than an Arena match at the same instant, and put
    ``'Z'`` on the wrong side of the second-boundary comparison besides.
    """
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _file_changed(conn: sqlite3.Connection, path: Path, *, from_start: bool) -> bool:
    """True when ``path`` needs (re-)ingesting: unseen, grown, or its inode
    changed since the last recorded state (a truncation/replace, treated as
    new content rather than corruption — same idiom as ``ingest.py``).

    Deliberately just a ``stat()`` plus an ``ingest_state`` lookup, with **no
    transaction open** — see ``ingest_mtgo_dir`` for why that separation
    matters. Can raise ``OSError`` (the file vanished between ``glob()`` and
    this call, e.g. a torn-down virtiofs share); the caller decides how to
    handle that, not this function.
    """
    st = path.stat()
    _offset, known_inode, last_size = _read_state(conn, path)
    unchanged = (
        not from_start
        and known_inode is not None
        and str(st.st_ino) == known_inode
        and st.st_size == last_size
    )
    return not unchanged


def _ingest_one_file(conn: sqlite3.Connection, path: Path, stats: IngestStats) -> None:
    """Read, digest and store one file already known to have changed.

    Caller (``ingest_mtgo_dir``) has confirmed the change and opened the
    transaction this runs inside. Can raise ``OSError`` (the file vanished
    between the change check and this read); the caller decides how to
    handle that, not this function.
    """
    stats.entries_seen += 1
    st = path.stat()
    data = path.read_bytes()
    stats.bytes_read += len(data)
    digest = _file_digest(path, data)
    payload = base64.b64encode(data).decode("ascii")
    logged_at = _mtime_iso(path)

    before = conn.total_changes
    conn.execute(
        """
        INSERT OR IGNORE INTO raw_events
             (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (digest, path.name, logged_at, str(EntryKind.EVENT), _LABEL, payload, _SOURCE),
    )
    if conn.total_changes - before:
        stats.rows_inserted += 1
    else:
        stats.rows_duplicate += 1

    # "Offset" has no line-resume meaning here (see module docstring); it is
    # set to the current size so a future read of this same size, same
    # inode is recognised as unchanged without re-reading the file.
    _write_state(conn, path, st.st_size, str(st.st_ino), st.st_size)


def ingest_mtgo_dir(
    conn: sqlite3.Connection, directory: str | Path, *, from_start: bool = False
) -> IngestStats:
    """Ingest every ``Match_GameLog_*.dat`` in ``directory`` into
    ``raw_events``.

    Unlike ``ingest_file``, there is no ``locale_hint`` (no header timestamps
    to parse). Two passes by design: first decide which files changed with
    **no transaction open** (``_file_changed``, one ``stat()`` + state lookup
    per file), then open ``BEGIN`` only if at least one did. ``db.py`` uses
    ``isolation_level=None`` with a DEFERRED ``BEGIN``, so an all-unchanged
    pass under the old, single-pass structure never took a write lock or
    wrote to the WAL — but it *did* hold a read snapshot open across the
    whole directory scan on every poll (blocking WAL checkpoint) and paid a
    ``stat()`` per file inside that snapshot. This is the idle case: called
    from the live watcher every few seconds while no MTGO match is running.

    Tolerates one file vanishing between ``glob()`` and its ``stat()``/read
    (virtiofs share torn down mid-scan, a match's log rotated away, ...):
    logs a warning and continues with the rest rather than raising
    (non-negotiable #4) — one unreadable file must never block every other
    file in the directory.
    """
    stats = IngestStats()
    directory = Path(directory)
    if not directory.exists():
        return stats

    changed: list[Path] = []
    for path in sorted(directory.glob("Match_GameLog_*.dat")):
        try:
            if _file_changed(conn, path, from_start=from_start):
                changed.append(path)
        except OSError as exc:
            log.warning("mtgo: skipping %s (could not stat): %s", path.name, exc)

    if not changed:
        return stats

    conn.execute("BEGIN")
    try:
        for path in changed:
            try:
                _ingest_one_file(conn, path, stats)
            except OSError as exc:
                log.warning("mtgo: skipping %s (could not read): %s", path.name, exc)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return stats
