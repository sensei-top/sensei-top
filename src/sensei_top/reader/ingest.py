"""Raw event ingestion: log file -> ``raw_events``.

Stage 1 of the two-stage pipeline (brief §4). This module knows about files,
offsets and hashing. It knows nothing about Arena semantics — every payload is
stored verbatim so a future parser fix can be replayed over history.

Digest strategy (deviation from brief §5, justified)
----------------------------------------------------
The brief specifies ``digest = sha256(payload)``. Measured against a real
session log, that silently drops 18 of 2,933 entries: client-state responses
(``QuestGetQuests``, ``PeriodicRewardsGetStatus``) that are byte-identical when
polled repeatedly, and — more importantly — ``EventEnterPairing``'s
``{"CurrentModule":"CreateMatch","Payload":"Success"}``, which occurs once per
match and would collapse to a single row across a whole session.

So the digest needs a tiebreaker that separates genuine repeats without
breaking idempotent replay. ``source_file`` is deliberately *excluded*: when
Arena rotates ``Player.log`` to ``Player-prev.log``, the same content reappears
under a new name, and including the filename would duplicate every event of the
previous session.

The tiebreaker was originally ``line_number``, and that was wrong. A line
number is *file-relative*, and the two files do not agree on it: rotation is a
snapshot, so ``Player-prev.log`` carries a different amount of preamble than
the ``Player.log`` it was cut from, and every shared line lands at a different
offset in each. Measured on a real pair of logs, that split 3,842 shared
entries into two rows apiece — defeating, in the one case it was written to
protect, the cross-file dedup the excluded ``source_file`` was meant to give.
The damage was invisible in every derived table keyed by natural key
(``matches``, ``games``, ``turns`` all overwrite) and showed up only in
``card_events``, which appends.

So the digest is over ``(logged_at, occurrence, payload)``, where *occurrence*
counts how many times this exact ``(logged_at, payload)`` pair has already been
seen **in this read**. Content alone decides identity, so the same line read
from either file digests the same and dedup works across rotation; a genuine
repeat inside one file still gets its own ordinal and stays distinct.

The tradeoff, stated plainly: the counter is per-read, so a byte-identical
payload carrying the *same second* on both sides of an incremental poll
boundary would be taken for a re-read and dropped. Every full read — a first
sight, a rotation, a truncation, ``--from-start`` — counts from zero and is
exact, which is where cross-file dedup actually matters. The residual risk is
confined to same-second identical client-state polls: two such pairs exist in
15,118 real entries, and neither is a game event. The counter also
self-heals: a same-second identical pair that one incremental read collapsed
is restored the next time the file is read whole, as ``Player-prev.log`` on
recovery, because that full read counts from zero again.

Changing this formula changes every digest, so a database ingested under the
old one must have ``raw_events`` rebuilt from the logs rather than topped up —
otherwise the next ingest re-inserts every entry under its new digest.

Carry state and the held-back pending entry
--------------------------------------------
A fresh ``Segmenter`` per call used to lose two things at every poll
boundary: the most recent header timestamp (``_last_ts``, which a following
request has no timestamp of its own and inherits) and the header's context
label (``_last_context``, consumed by the next bare ``{`` line). A request
landing as the first entry of a poll got ``logged_at = NULL``; the same
request seen later by a whole-file read (``Player-prev.log`` recovery) got
its real timestamp and therefore a different digest — inserted twice.
``ingest_state`` now carries both (``carry_ts``/``carry_context``, migration
042), and the header's stamp as written beside them (``carry_header``,
migration 062, which ``raw_events.header`` stores per entry, outside the
digest): a resumed read restores all three into the new ``Segmenter``
(``restore_carry``) before feeding its first line, while a *fresh* read
(``from_start``, an inode change, or a truncation) starts from an empty carry
instead, since the old file's timestamps no longer apply to whatever replaced
it.

Separately, a poll that stops mid-entry (most often a multi-line response) is
held back rather than split or discarded: the committed byte offset never
advances past the first line of a still-open entry, and the carry state
committed alongside it is the snapshot taken *just before* that line was fed
— the one that still holds the header context a bare ``{`` line would
otherwise already have consumed. The next read re-reads the entry whole, from
its first line (the ``<==`` line for a response), with the same timestamp and
label it would have carried if the file had never been polled mid-entry. An
entry that runs past ``MAX_PENDING_BYTES`` without ever closing is corrupt in
some new way, not merely "still arriving": holding it back forever would make
every subsequent poll re-read an ever-growing tail, so ``ingest_file`` gives
up on it instead — logs a warning and advances past it, the way a truncated
read has always discarded a pending payload.

Truncation
----------
Arena wipes ``Player.log`` on launch. The reader treats "file is smaller than
last time" or "inode changed" as a reset: offset returns to 0 and the file is
re-read from the top, and the carry state resets to empty the same way —
never the old file's timestamp or context. Dedupe absorbs any overlap.

Day/month order
---------------
``locale_hint`` ``"mdy"``/``"dmy"`` is the segmenter's own fixed order.
``"auto"`` (``AUTO``, the CLI's default) is this module's to turn into a
resolver, never the segmenter's: a ``Segmenter`` takes a hint it does not
know as no order at all, silently. ``reader/dates.py`` settles each header on
its own, from its fields, this file's mtime (the ``stat`` taken before the
read) and the orders the database has learned, which it writes inside the
read's transaction.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sensei_top import steam
from sensei_top.reader.dates import AUTO, auto_resolver
from sensei_top.reader.segmenter import LogEntry, Segmenter

log = logging.getLogger(__name__)

# A pending entry that never closes would otherwise make every future poll
# re-read an ever-growing tail (see "Carry state and the held-back pending
# entry" above). The largest real payload measured on a real database is
# 1,055,060 bytes, itself a response — this cap is roughly 30x that, so it
# only ever fires on an entry that is corrupt in some new way, not one that's
# merely still arriving.
MAX_PENDING_BYTES = 32 * 1024 * 1024

# Read the file in fixed-size chunks rather than all at once: a first read of
# a real Player.log can be 100+ MB. Kept as a module attribute (not a default
# argument) so a test can monkeypatch it small without writing a huge file.
_CHUNK_BYTES = 1024 * 1024


def compute_digest(entry: LogEntry, occurrence: int = 0) -> str:
    """Stable content digest for an entry. See module docstring.

    ``occurrence`` separates genuine repeats of an identical payload carrying
    an identical timestamp. It is a count, not a position, so the same content
    digests the same whichever file it is read from.
    """
    material = f"{entry.logged_at or ''}\x00{occurrence}\x00{entry.payload}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class IngestStats:
    entries_seen: int = 0
    rows_inserted: int = 0
    rows_duplicate: int = 0
    bytes_read: int = 0
    truncation_detected: bool = False

    def __str__(self) -> str:
        return (
            f"{self.entries_seen} entries, {self.rows_inserted} new, "
            f"{self.rows_duplicate} duplicate, {self.bytes_read} bytes"
            + (" (truncation detected)" if self.truncation_detected else "")
        )


def _read_state(conn: sqlite3.Connection, path: Path) -> tuple[int, str | None, int]:
    row = conn.execute(
        "SELECT byte_offset, inode, last_size FROM ingest_state WHERE source_path = ?",
        (str(path),),
    ).fetchone()
    if row is None:
        return 0, None, 0
    return row["byte_offset"], row["inode"], row["last_size"]


def _read_carry(
    conn: sqlite3.Connection, path: Path
) -> tuple[str | None, str | None, str | None]:
    """Read the segmenter carry state persisted for ``path`` (migrations 042
    and 062): ``(carry_ts, carry_context, carry_header)``.

    Kept separate from ``_read_state`` rather than folded into it:
    ``reader/mtgo_decks.py`` imports and unpacks ``_read_state`` as a
    3-tuple, and it has no segmenter or carry state of its own to receive
    these columns.
    """
    row = conn.execute(
        "SELECT carry_ts, carry_context, carry_header FROM ingest_state WHERE source_path = ?",
        (str(path),),
    ).fetchone()
    if row is None:
        return None, None, None
    return row["carry_ts"], row["carry_context"], row["carry_header"]


def _write_state(
    conn: sqlite3.Connection,
    path: Path,
    offset: int,
    inode: str | None,
    size: int,
    *,
    carry_ts: str | None = None,
    carry_context: str | None = None,
    carry_header: str | None = None,
):
    """Persist resume state for ``path``.

    The carry values are keyword-only, defaulting to ``None``, so
    ``reader/mtgo.py``'s existing positional call (which has no carry state
    to give) keeps writing NULL for all three, correctly, without having to
    know these columns exist.
    """
    conn.execute(
        """
        INSERT INTO ingest_state
               (source_path, inode, byte_offset, last_size,
                carry_ts, carry_context, carry_header)
             VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source_path) DO UPDATE SET
             inode = excluded.inode,
             byte_offset = excluded.byte_offset,
             last_size = excluded.last_size,
             carry_ts = excluded.carry_ts,
             carry_context = excluded.carry_context,
             carry_header = excluded.carry_header,
             updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (str(path), inode, offset, size, carry_ts, carry_context, carry_header),
    )


def _insert_entries(
    conn: sqlite3.Connection,
    entries: list[LogEntry],
    source_file: str,
    stats: IngestStats,
    occurrences: dict[tuple[str | None, str], int],
) -> None:
    """Insert a batch, ignoring digest collisions (idempotent replay).

    ``occurrences`` is owned by the caller and spans the whole read, not this
    batch: the ordinal has to keep counting across the 500-entry flushes or a
    repeat would reset to zero at an arbitrary boundary.
    """
    if not entries:
        return
    rows = []
    for e in entries:
        key = (e.logged_at, e.payload)
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1
        rows.append(
            (
                compute_digest(e, occurrence),
                source_file,
                e.logged_at,
                str(e.kind),
                e.label,
                e.payload,
                e.header,
            )
        )
    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO raw_events
               (digest, source_file, logged_at, kind, label, payload, header)
             VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    inserted = conn.total_changes - before
    stats.entries_seen += len(rows)
    stats.rows_inserted += inserted
    stats.rows_duplicate += len(rows) - inserted


def _iter_raw_lines(fh) -> Iterator[bytes]:
    """Yield complete raw lines (terminator included) from a binary file handle.

    Reproduces text mode's ``newline=""`` splitting byte-for-byte: a line ends
    at ``\\n``, at ``\\r\\n``, or at a ``\\r`` not followed by ``\\n``; a ``\\r``
    that is the last byte available at EOF counts as a terminator too. A
    trailing run of bytes with no terminator is a partial line — the writer is
    mid-write — and is never yielded; the caller's offset simply doesn't
    advance past it, so the next read starts from the same place once more
    bytes exist.

    Reads in ``_CHUNK_BYTES`` chunks rather than loading the whole file (a
    first read of a real ``Player.log`` can be 100+ MB). A ``\\r`` landing on
    a chunk boundary is ambiguous — the next byte, not yet read, decides
    whether it is a lone terminator or half of ``\\r\\n`` — so it is held in
    the buffer until either the next chunk resolves it or EOF does.
    """
    buf = b""
    while True:
        chunk = fh.read(_CHUNK_BYTES)
        eof = not chunk
        buf += chunk
        pos = 0
        n = len(buf)
        while pos < n:
            nl = buf.find(b"\n", pos)
            cr = buf.find(b"\r", pos)
            if nl == -1 and cr == -1:
                break  # no terminator in the buffer yet
            if cr == -1 or (nl != -1 and nl < cr):
                yield buf[pos : nl + 1]
                pos = nl + 1
                continue
            if cr + 1 < n:
                if buf[cr + 1 : cr + 2] == b"\n":
                    yield buf[pos : cr + 2]
                    pos = cr + 2
                else:
                    yield buf[pos : cr + 1]
                    pos = cr + 1
                continue
            # cr is the last byte currently buffered: ambiguous unless this
            # really is the end of the file.
            if eof:
                yield buf[pos : cr + 1]
                pos = cr + 1
            break
        buf = buf[pos:]
        if eof:
            return  # remaining buf (if any) is a partial line: not yielded


def _segmenter(
    conn: sqlite3.Connection, locale_hint: str | None, *, source_file: str, mtime: float
) -> Segmenter:
    """A ``Segmenter`` for one read: ``AUTO`` becomes ``reader/dates.py``'s
    resolver, any other hint goes to the segmenter as is (module docstring,
    "Day/month order").

    Called before the read's ``BEGIN``, so the resolver's one read of the
    learned orders is not inside the transaction: a deferred transaction that
    reads before it writes holds a WAL snapshot, and if another connection
    commits meanwhile, its first write fails with ``SQLITE_BUSY`` at once
    rather than waiting. Every statement inside the transaction is a write.
    """
    if locale_hint == AUTO:
        resolver = auto_resolver(
            conn, source_file=source_file, last_write=datetime.fromtimestamp(mtime)
        )
        return Segmenter(resolve_date=resolver)
    return Segmenter(locale_hint=locale_hint)


def ingest_file(
    conn: sqlite3.Connection,
    path: str | Path,
    *,
    locale_hint: str | None = None,
    from_start: bool = False,
) -> IngestStats:
    """Ingest new content from ``path`` into ``raw_events``.

    Resumes from the stored byte offset and carry state (see module
    docstring) unless ``from_start`` is set or a truncation/rotation is
    detected, in which case both reset to empty. A poll that ends mid-entry
    holds that entry back rather than splitting or discarding it: the
    committed offset never advances past its first line, so the next call
    re-reads it whole, with the timestamp/context it would have carried if
    the file had never been polled mid-entry.

    ``locale_hint`` is ``"mdy"`` or ``"dmy"`` for one fixed order, ``"auto"``
    to settle each header on its own (``reader/dates.py``), or None for no
    order: only year-first headers are dated then.
    """
    path = Path(path)
    stats = IngestStats()
    if not path.exists():
        return stats

    st = path.stat()
    offset, known_inode, last_size = _read_state(conn, path)
    carry_ts, carry_context, carry_header = _read_carry(conn, path)
    fresh = from_start

    if from_start:
        offset = 0
    elif known_inode is not None and str(st.st_ino) != known_inode:
        offset, stats.truncation_detected, fresh = 0, True, True   # file replaced (rotation)
    elif st.st_size < last_size or st.st_size < offset:
        offset, stats.truncation_detected, fresh = 0, True, True   # Arena wiped it on launch
    elif str(st.st_ino) == known_inode and st.st_size == last_size:
        # Same file, same size, already caught up: every second's poll during
        # a quiet match (or between matches) hit this exact state and still
        # opened a write transaction — a BEGIN, an empty read, a COMMIT to
        # the WAL — for zero new bytes. Nothing changed, so nothing to write:
        # ingest_state already holds this offset/inode/size. Checked against
        # last_size, not offset: a held-back pending entry leaves offset <
        # size on purpose (see below), and comparing against offset would
        # re-read that same unfinished entry every second regardless.
        return stats

    if fresh:
        # A fresh read's carry is empty regardless of what the old file held —
        # never a guess from a file that was just rotated or truncated away.
        carry_ts, carry_context, carry_header = None, None, None

    source_file = path.name
    segmenter = _segmenter(conn, locale_hint, source_file=source_file, mtime=st.st_mtime)
    segmenter.restore_carry(carry_ts, carry_context, carry_header)
    batch: list[LogEntry] = []
    # Spans the whole read: see _insert_entries.
    occurrences: dict[tuple[str | None, str], int] = {}

    start_offset = offset
    # The offset/carry actually safe to persist: advances only when the
    # segmenter is not mid-entry, so it never lands past an entry's first
    # line (see "Carry state and the held-back pending entry" above). While
    # nothing is pending, carry_state() can't change until the next
    # feed_line, so this pair also *is* the checkpoint a held-back entry
    # needs: the line that opens it starts exactly where the previous entry
    # left off, with the same carry it left behind.
    commit_offset = offset
    commit_carry = (carry_ts, carry_context, carry_header)
    # Byte offset of the still-open entry's first line, for the
    # MAX_PENDING_BYTES distance check below; None while nothing is pending.
    pending_started_at: int | None = None

    conn.execute("BEGIN")
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            for raw_line in _iter_raw_lines(fh):
                line_start = offset
                was_pending = segmenter.pending
                # errors="replace" on the fully-buffered raw line, not on
                # pieces read separately, so the substitution can't drift
                # with how the chunk boundaries happened to fall.
                decoded = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                batch.extend(segmenter.feed_line(decoded))
                offset = line_start + len(raw_line)

                if not was_pending and segmenter.pending:
                    pending_started_at = line_start

                if segmenter.pending:
                    if (
                        pending_started_at is not None
                        and offset - pending_started_at > MAX_PENDING_BYTES
                    ):
                        # Corrupt in some new way, not merely "still arriving":
                        # give up on it rather than holding it back forever,
                        # which would make every future poll re-read an
                        # ever-growing tail.
                        log.warning(
                            "%s: entry starting at offset %d exceeded %d "
                            "pending bytes without closing; dropping it and "
                            "resuming from offset %d",
                            source_file, pending_started_at, MAX_PENDING_BYTES, offset,
                        )
                        segmenter.flush()
                        commit_offset, commit_carry = offset, segmenter.carry_state()
                        pending_started_at = None
                else:
                    commit_offset, commit_carry = offset, segmenter.carry_state()
                    pending_started_at = None

                if len(batch) >= 500:
                    _insert_entries(conn, batch, source_file, stats, occurrences)
                    batch.clear()
        _insert_entries(conn, batch, source_file, stats, occurrences)
        # Committed offset, not however far the read actually looked ahead:
        # a held-back entry's bytes were read but not committed, so they are
        # read again (and counted again) next time.
        stats.bytes_read = commit_offset - start_offset
        _write_state(
            conn, path, commit_offset, str(st.st_ino), st.st_size,
            carry_ts=commit_carry[0], carry_context=commit_carry[1],
            carry_header=commit_carry[2],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return stats


def previous_log_path(path: str | Path) -> Path:
    """``Player.log`` -> ``Player-prev.log`` in the same directory."""
    path = Path(path)
    return path.with_name(f"{path.stem}-prev{path.suffix}")


def ingest_with_recovery(
    conn: sqlite3.Connection, path: str | Path, *, locale_hint: str | None = None
) -> dict[str, IngestStats]:
    """Ingest ``Player-prev.log`` (if present) then ``Player.log``.

    Run this on startup: Arena wipes the live log every launch, so the previous
    session survives only in the -prev file, and only until the *next* launch.
    """
    results: dict[str, IngestStats] = {}
    prev = previous_log_path(path)
    if prev.exists():
        results[prev.name] = ingest_file(conn, prev, locale_hint=locale_hint)
    results[Path(path).name] = ingest_file(conn, path, locale_hint=locale_hint)
    return results


def watch(
    conn: sqlite3.Connection,
    path: str | Path,
    *,
    locale_hint: str | None = None,
    interval: float = 2.0,
    max_polls: int | None = None,
) -> Iterator[IngestStats]:
    """Poll ``path`` forever, yielding stats after each pass that found data.

    A plain polling loop, deliberately: inotify/watchdog misbehaves on the
    virtiofs and network mounts this log may live on, and 2 s of latency is
    irrelevant for a dashboard. ``max_polls`` exists so tests can bound it.
    """
    polls = 0
    while max_polls is None or polls < max_polls:
        stats = ingest_file(conn, path, locale_hint=locale_hint)
        if stats.entries_seen:
            yield stats
        polls += 1
        if max_polls is None or polls < max_polls:
            time.sleep(interval)


_STEAM_COMPATDATA_RELATIVE = (
    f"steamapps/compatdata/{steam.MTGA_APP_ID}/pfx/drive_c/users/steamuser/"
    "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
)

# Under the user's profile on Windows, whichever installer put Arena there
# (Wizards', Steam or Epic): the log's folder does not follow the install.
_WINDOWS_LOG_RELATIVE = "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"


def default_log_path() -> Path | None:
    """Best-effort default for the current platform. None if nothing plausible."""
    candidates: list[Path] = []
    if env := os.environ.get("MTGA_LOG"):
        candidates.append(Path(env))
    # Linux/Proton is checked first: this project's home environment runs Arena
    # through Steam Play, where the log sits inside the compatdata prefix —
    # under whichever library folder the game happens to be installed in.
    candidates.extend(root / _STEAM_COMPATDATA_RELATIVE for root in steam.library_roots())
    if sys.platform == "win32" and (profile := os.environ.get("USERPROFILE")):
        candidates.append(Path(profile) / _WINDOWS_LOG_RELATIVE)
    candidates.append(
        Path.home() / "Library/Logs/Wizards Of The Coast/MTGA/Player.log"
    )  # macOS
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
