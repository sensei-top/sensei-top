"""MTGO deck ingestion: deck files in a folder -> ``raw_events``.

Stage 1 of the two-stage pipeline (AGENTS.md non-negotiable #1): this module
knows about files, hashing and the unchanged-file skip, and nothing about
what is inside a deck file — no XML, no card names, no ``CatID``. The
projector is the only place that decodes a payload.

Two kinds of file are read, each by its name alone:

* ``*.dek``, a deck the user exported (``[mtgo] deck_dir``; plan 12, D6),
  stored with the label ``MtgoDeckFile``.
* ``grouping *.xml``, an entry in MTGO's own deck store, which MTGO keeps in
  the folder its game logs are written to (``[mtgo] dir``; plan 12, D14),
  stored with the label ``MtgoDeckGrouping``. A grouping may be a binder or a
  wishlist rather than a deck; telling them apart means reading the XML, so
  that is the projector's job and every grouping is stored.

Both kinds are read from whichever folder ``ingest_deck_dir`` is given, so the
caller passes each configured folder in turn. The label is the one thing the
reader says about a file, and it says it from the name, never the contents.

The pattern is ``reader/mtgo.py``'s, with the differences that matter:

* ``source = 'mtgo_deck'`` for both kinds, so a query that filters on it never
  sees a deck. (A query that filters on neither source nor label —
  ``MAX(id)``, ``MAX(logged_at)`` — does, and must say so if that matters.)
* One file is one row per **distinct content**: the digest is over filename
  plus bytes, so saving a deck again writes a new row, and re-reading an
  unchanged file writes nothing. Nothing already stored is edited or
  discarded (non-negotiable #2); the payload is the file's bytes in base64,
  so a later fix to the decoder replays over history without the file.
* The folder is not walked recursively, and nothing else in it is read: no
  ``.txt`` export, which waits for a real sample of one (plan 12, D13), and
  none of the game logs that share ``[mtgo] dir`` with the deck store.
* ``logged_at`` is the file's mtime, as in ``reader/mtgo.py``.

Unchanged-file skip. ``reader/mtgo.py`` skips a file whose inode and size
match ``ingest_state``. That is enough for a game log, which only grows, and
wrong for a deck: MTGO or the user can rewrite either kind in place with the
same inode and, for a one-card swap of equal-length names, the same size. So
the ``inode`` column, which migration 002 calls an opaque identity token,
holds ``<st_ino>:<st_mtime_ns>`` here, and ``byte_offset`` and ``last_size``
both hold the size, as in ``reader/mtgo.py``. A file is unchanged only when
both the token and the size match.

A file caught half-written (the XML is read while MTGO is still saving it)
is stored as it was; the next poll sees a new mtime or size and stores the
finished one. Whatever reads these rows must therefore tolerate a payload
that does not parse, per rule 4.

One bad file never stops the folder (rule 4). A name that is not valid UTF-8
cannot be bound into SQLite or hashed, and raises ``UnicodeError``; an
unreadable or vanished file raises ``OSError``. Either is logged and that file
is skipped, in both passes, and every other file in the folder is still
stored. The name is logged with ``%r``: printed raw, it would raise again
inside the log handler.
"""

from __future__ import annotations

import base64
import logging
import os
import sqlite3
import stat
from pathlib import Path

from sensei_top.reader.ingest import IngestStats, _read_state, _write_state
from sensei_top.reader.mtgo import _file_digest, _mtime_iso
from sensei_top.reader.segmenter import EntryKind

log = logging.getLogger(__name__)

_DECK_FILE_LABEL = "MtgoDeckFile"
_GROUPING_LABEL = "MtgoDeckGrouping"
_SOURCE = "mtgo_deck"
_GROUPING_PREFIX = "grouping "
_SKIPPABLE = (OSError, UnicodeError)


def _label(name: str) -> str | None:
    """The label a file of this name is stored under, or ``None`` if it is no
    kind of deck. Case is ignored, since MTGO runs on Windows."""
    lowered = name.lower()
    if lowered.endswith(".dek"):
        return _DECK_FILE_LABEL
    if lowered.startswith(_GROUPING_PREFIX) and lowered.endswith(".xml"):
        return _GROUPING_LABEL
    return None


def _deck_files(directory: Path) -> list[Path]:
    """Every entry directly inside ``directory`` named like either kind of
    deck file, in name order. Not recursive. Whether an entry is a regular
    file is left to ``_deck_changed``, so a failing ``stat()`` is skipped per
    file rather than ending the listing."""
    return sorted(path for path in directory.iterdir() if _label(path.name) is not None)


def _identity(st: os.stat_result) -> str:
    return f"{st.st_ino}:{st.st_mtime_ns}"


def _deck_changed(conn: sqlite3.Connection, path: Path, *, from_start: bool) -> bool:
    """True when ``path`` is a regular file that is unseen, or whose identity
    token or size differs from what ``ingest_state`` recorded. A ``stat()``
    and a lookup with no transaction open, so an all-unchanged poll takes no
    write lock. Can raise ``OSError`` if the file vanished and
    ``UnicodeError`` for a name SQLite cannot bind; the caller skips the file
    in both cases."""
    st = path.stat()
    if not stat.S_ISREG(st.st_mode):
        return False
    _offset, known_token, last_size = _read_state(conn, path)
    unchanged = (
        not from_start
        and known_token == _identity(st)
        and st.st_size == last_size
    )
    return not unchanged


def _ingest_one_deck(conn: sqlite3.Connection, path: Path, stats: IngestStats) -> None:
    """Read, digest and store one file already known to have changed, inside
    the transaction the caller opened. Can raise ``OSError`` (the file
    vanished since the change check) or ``UnicodeError`` (a name that cannot
    be stored). ``stat()`` runs before the read, so a write landing in between
    leaves a recorded mtime older than the content and the next poll re-reads
    it: the digest then dedupes or stores the newer bytes, never loses
    them."""
    stats.entries_seen += 1
    st = path.stat()
    data = path.read_bytes()
    stats.bytes_read += len(data)
    digest = _file_digest(path, data)
    payload = base64.b64encode(data).decode("ascii")

    before = conn.total_changes
    conn.execute(
        """
        INSERT OR IGNORE INTO raw_events
             (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            digest, path.name, _mtime_iso(path), str(EntryKind.EVENT), _label(path.name),
            payload, _SOURCE,
        ),
    )
    if conn.total_changes - before:
        stats.rows_inserted += 1
    else:
        stats.rows_duplicate += 1

    _write_state(conn, path, st.st_size, _identity(st), st.st_size)


def ingest_deck_dir(
    conn: sqlite3.Connection, directory: str | Path, *, from_start: bool = False
) -> IngestStats:
    """Ingest every ``*.dek`` and ``grouping *.xml`` directly inside
    ``directory`` into ``raw_events``. A directory that does not exist is an
    empty result, not an error. Called once per configured folder: the deck
    folder for exports, the game-log folder for MTGO's deck store.

    Two passes, as in ``ingest_mtgo_dir``: decide which files changed with no
    transaction open, then ``BEGIN`` only if at least one did — this runs from
    the live watcher on a slow clock, almost always with nothing to do. In
    both passes a file that raises ``OSError`` or ``UnicodeError`` is logged
    and skipped (see the module docstring); a listing that itself fails (a
    dead mount) raises ``OSError`` for the caller to handle.
    """
    stats = IngestStats()
    directory = Path(directory)
    if not directory.exists():
        return stats

    changed: list[Path] = []
    for path in _deck_files(directory):
        try:
            if _deck_changed(conn, path, from_start=from_start):
                changed.append(path)
        except _SKIPPABLE as exc:
            log.warning("mtgo decks: skipping %r (could not check it): %s", path.name, exc)

    if not changed:
        return stats

    conn.execute("BEGIN")
    try:
        for path in changed:
            try:
                _ingest_one_deck(conn, path, stats)
            except _SKIPPABLE as exc:
                log.warning("mtgo decks: skipping %r (could not store it): %s", path.name, exc)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return stats
