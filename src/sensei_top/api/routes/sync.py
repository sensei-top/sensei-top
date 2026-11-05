"""The cloud backup's two routes (docs/architecture.md, "Cloud sync").
``GET /api/sync/payloads`` is read-only and calls nothing outside the
machine: the desktop shell's main process uploads what it returns.
``PUT /api/sync/pulled`` is the one sync route on rule 6's allowlist: it
writes ``cloud_match`` and, for a match this install read from its own log,
the user's two picks.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import TypeAdapter, ValidationError

from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.models.sync import (
    SyncDeck,
    SyncMtgoPick,
    SyncOpponentPick,
    SyncPayload,
    SyncPicks,
    SyncPulledIn,
    SyncPulledMatch,
    SyncPulledWritten,
)
from sensei_top.sync import build_payloads, canonical_json

router = APIRouter()
log = logging.getLogger(__name__)

_PICKS = TypeAdapter(SyncPicks)
_DECK = TypeAdapter(SyncDeck)

# The resolved maindeck of every MTGO deck file, as ``[name, copies]`` by
# name: the board a payload's ``deck.main`` carries. ``_mtgo_decks`` in
# ``routes/matches.py`` says why a deck no match carries is an MTGO deck.
_MTGO_DECK_MAINS = """
    SELECT d.deck_id, c.name, COUNT(*) AS copies
      FROM decks d
      JOIN json_each(d.cards_json, '$.maindeck') j
      JOIN cards c ON c.grp_id = j.value
     WHERE json_valid(d.cards_json)
       AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.deck_id = d.deck_id)
     GROUP BY d.deck_id, c.name
"""


@router.get("/api/sync/payloads", response_model=list[SyncPayload], tags=["sync"])
def sync_payloads(conn: Conn) -> list[dict[str, Any]]:
    """Every backed-up match with its digest, oldest first, all of them on
    every call: the caller pushes the ones whose digest differs from the one
    it last pushed, which catches a rebuild or a pick that a timestamp would
    miss."""
    return [asdict(payload) for payload in build_payloads(conn)]


@router.put("/api/sync/pulled", response_model=SyncPulledWritten, tags=["sync"])
def sync_pulled(body: SyncPulledIn, conn: WritableConn) -> dict[str, int]:
    """Store a batch of rows pulled from the user's cloud backup, in order,
    in one transaction.

    - A row with ``deleted_at`` deletes that match's ``cloud_match`` row, if
      any. A match read from this install's own log is never deleted.
    - A row for a match in ``matches`` is never stored: the local match wins.
      Each of its pulled picks replaces the local one only when strictly
      newer by ``updated_at`` (equal keeps the local one), and keeps the
      pulled ``updated_at``. A missing pulled pick never clears a local one.
    - An MTGO pick names its deck by board, not id: it applies only when
      exactly one local MTGO deck file has that resolved maindeck, and only
      to an MTGO match.
    - A pick that cannot be read or applied is skipped with a warning; the
      rest of the batch is written.
    - Any other row is upserted into ``cloud_match``.
    """
    counts = {"stored": 0, "removed": 0, "local": 0, "picks": 0}
    deck_mains: dict[str, list[tuple[str, int]]] | None = None
    conn.execute("BEGIN")
    try:
        for row in body.items:
            if row.deleted_at is not None:
                cursor = conn.execute(
                    "DELETE FROM cloud_match WHERE match_id = ?", (row.match_id,)
                )
                counts["removed"] += cursor.rowcount
                continue
            local = conn.execute(
                "SELECT source FROM matches WHERE match_id = ?", (row.match_id,)
            ).fetchone()
            if local is None:
                _store(conn, row)
                counts["stored"] += 1
                continue
            counts["local"] += 1
            picks = _pulled_picks(row)
            if picks is None:
                continue
            if picks.opp is not None and _apply_opponent_pick(conn, row.match_id, picks.opp):
                counts["picks"] += 1
            if picks.mtgo is not None and local["source"] == "mtgo":
                if deck_mains is None:
                    deck_mains = _mtgo_deck_mains(conn)
                if _apply_mtgo_pick(conn, row, picks.mtgo, deck_mains):
                    counts["picks"] += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return counts


def _stamp(moment: datetime) -> str:
    """The project's stored timestamp shape, UTC to the second."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _moment(text: str | None) -> datetime | None:
    """``text`` as an aware datetime; ``None`` when missing, unreadable or
    naive, since a naive time cannot be ordered against a UTC one."""
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _store(conn: sqlite3.Connection, row: SyncPulledMatch) -> None:
    conn.execute(
        """
        INSERT INTO cloud_match (match_id, source, played_at, payload, schema_version, updated_at)
             VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (match_id) DO UPDATE SET
             source = excluded.source,
             played_at = excluded.played_at,
             payload = excluded.payload,
             schema_version = excluded.schema_version,
             updated_at = excluded.updated_at,
             received_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        (
            row.match_id,
            row.source,
            None if row.played_at is None else _stamp(row.played_at),
            canonical_json(row.payload),
            row.schema_version,
            _stamp(row.updated_at),
        ),
    )


def _pulled_picks(row: SyncPulledMatch) -> SyncPicks | None:
    try:
        return _PICKS.validate_python(row.payload.get("picks"))
    except ValidationError:
        log.warning("sync pull: match %s: unreadable picks, none applied", row.match_id)
        return None


def _newer(match_id: str, pulled: str, local: str | None) -> datetime | None:
    """The pulled pick's time when it should replace the local pick, else
    ``None``."""
    moment = _moment(pulled)
    if moment is None:
        log.warning("sync pull: match %s: pick has no readable time, skipped", match_id)
        return None
    if local is None:
        return moment
    local_moment = _moment(local)
    if local_moment is None or moment <= local_moment:
        return None
    return moment


def _apply_opponent_pick(conn: sqlite3.Connection, match_id: str, pick: SyncOpponentPick) -> bool:
    local = conn.execute(
        "SELECT updated_at FROM opponent_deck_override WHERE match_id = ?", (match_id,)
    ).fetchone()
    moment = _newer(match_id, pick.updated_at, None if local is None else local["updated_at"])
    if moment is None:
        return False
    # The label rules of PUT .../opponent-deck, which wrote it on the other
    # install; whether its archetype_key is in this install's archetypes is
    # not checked, since that download may lag the other one.
    label = " ".join(pick.label.split())
    if not label or any(character < " " for character in label):
        log.warning("sync pull: match %s: opponent pick has no usable label, skipped", match_id)
        return False
    conn.execute(
        """
        INSERT INTO opponent_deck_override (match_id, label, archetype_key, updated_at)
             VALUES (?, ?, ?, ?)
        ON CONFLICT (match_id) DO UPDATE SET
             label = excluded.label,
             archetype_key = excluded.archetype_key,
             updated_at = excluded.updated_at
        """,
        (match_id, label, pick.archetype_key, _stamp(moment)),
    )
    return True


def _mtgo_deck_mains(conn: sqlite3.Connection) -> dict[str, list[tuple[str, int]]]:
    mains: dict[str, list[tuple[str, int]]] = {}
    for deck_id, name, copies in conn.execute(_MTGO_DECK_MAINS):
        mains.setdefault(deck_id, []).append((name, copies))
    return {deck_id: sorted(board) for deck_id, board in mains.items()}


def _apply_mtgo_pick(
    conn: sqlite3.Connection,
    row: SyncPulledMatch,
    pick: SyncMtgoPick,
    deck_mains: dict[str, list[tuple[str, int]]],
) -> bool:
    """Trap: the pick's deck is matched on the board the payload carries, not
    re-hashed into ``projector/mtgo/decks.py::mtgo_deck_identity``. A ``.dek``
    names a two-faced card by its front face and the payload by the card
    database's full name, so a re-hash misses every deck holding one."""
    match_id = row.match_id
    local = conn.execute(
        "SELECT updated_at FROM mtgo_match_pick WHERE match_id = ?", (match_id,)
    ).fetchone()
    moment = _newer(match_id, pick.updated_at, None if local is None else local["updated_at"])
    if moment is None:
        return False
    try:
        deck = _DECK.validate_python(row.payload.get("deck"))
    except ValidationError:
        log.warning("sync pull: match %s: MTGO pick has no readable deck, skipped", match_id)
        return False
    main = sorted((name, copies) for name, copies in deck.main)
    found = [deck_id for deck_id, board in deck_mains.items() if main and board == main]
    if len(found) != 1:
        log.warning(
            "sync pull: match %s: MTGO pick names %d local decks, not 1, skipped",
            match_id, len(found),
        )
        return False
    conn.execute(
        """
        INSERT INTO mtgo_match_pick (match_id, deck_id, format, updated_at)
             VALUES (?, ?, ?, ?)
        ON CONFLICT (match_id) DO UPDATE SET
             deck_id = excluded.deck_id,
             format = excluded.format,
             updated_at = excluded.updated_at
        """,
        (match_id, found[0], pick.format, _stamp(moment)),
    )
    return True
