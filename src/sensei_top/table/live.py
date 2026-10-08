"""The live board-state read: opponent counts, revealed cards and our own
remaining library, from a fresh replay of the current match rather than
the projected ``turns``/``matches`` tables — see
``projector/live_state.py``'s module docstring for the numbers that justify
this (a real database's full ``project()`` rebuild costs ~11.6 s wall time
against a 5-second ``project_every``, so ``turns`` runs stale by roughly a
rebuild's duration mid-combat; one match's own replay costs 0.03-0.08 s).

This is the ``table/`` sibling of ``table/opening_hand.py``'s existing,
narrow exception to "``table/`` only reads projected data"
(AGENTS.md non-negotiable #1), now shared by more than one question:
``opening_hand.py`` and ``hand_read.py`` both take an optional pre-built
``LiveState`` from here instead of doing their own separate replay, so one
request does one pass over ``raw_events``, not three. Nothing here writes
anything, so every route built on it stays in the API's read-only majority
(non-negotiable #6).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass

from sensei_top.projector.live_state import LiveState, replay_live_state
from sensei_top.projector.matches import MATCH_ROOM_PLAYING_MARKER
from sensei_top.review import effects


def find_anchor(conn: sqlite3.Connection) -> int | None:
    """The current match's own room-opening event id: the single most
    recent ``MatchGameRoomStateType_Playing`` row in ``raw_events``, with no
    window bound.

    Anchoring to the single newest such row is always correct
    (``docs/arena-log.md``): Arena reuses instance ids and ``gameStateId``
    counters game to game, so a replay must never start earlier than the
    current match's own start — and there is exactly one of these events
    per *match* (verified against a real database: every
    ``MatchGameRoomStateType_Playing`` row carried a distinct ``matchId``,
    including across a Bo3's three games, which share one room). A bounded
    version of this query (a fixed lookback window) went silently blind on
    5% of real matches once a Bo3's total event count outgrew the window —
    exactly the grindy games where a game-2 or game-3 mulligan read matters
    most. ``None`` means no match has ever been captured, not "too long ago
    to bother".
    """
    row = conn.execute(
        "SELECT id FROM raw_events WHERE label = 'MatchGameRoomStateChangedEvent' "
        "AND payload LIKE ? ORDER BY id DESC LIMIT 1",
        (f"%{MATCH_ROOM_PLAYING_MARKER}%",),
    ).fetchone()
    return row["id"] if row else None


def _mana_source_grp_ids(conn: sqlite3.Connection) -> frozenset[int]:
    """Every grpId Scryfall names as producing mana — lands included, though
    ``replay_live_state`` already excludes lands from what this set feeds
    (``GameStateTracker._battlefield_counts``'s ``other_mana_sources_only``
    mode). Reference data, like the ``cards`` table itself; costs one query,
    cached nowhere, since it only runs once per ``build_live_state`` call."""
    rows = conn.execute(
        "SELECT grp_id FROM cards WHERE produced_mana IS NOT NULL AND produced_mana != '[]'"
    ).fetchall()
    return frozenset(r["grp_id"] for r in rows)


# The room-opening anchor and the match's own connectResp (carrying the
# submitted deck) are adjacent, never simultaneous. Measured read-only
# against a real ~1.8 GB database (288 MatchGameRoomStateType_Playing rows,
# every one of them): the nearest connectResp landed at anchor-1 (73
# matches) or anchor+1 (215 matches) every single time — never further,
# never missing. _DECK_MESSAGE_LOOKBACK is a 10x margin over that observed
# minimum, comfortably inside the plan's own ±20-row stop threshold for this
# measurement.
_DECK_MESSAGE_LOOKBACK = 10


def replay_from_anchor(
    conn: sqlite3.Connection, anchor: int, *, mana_source_grp_ids: frozenset[int] | None = None
) -> LiveState:
    """``mana_source_grp_ids`` defaults to a fresh ``_mana_source_grp_ids``
    scan — today's behaviour, kept for CLI/test callers with no cache to
    reuse. The 1 Hz API route passes its own request-scoped, app.state-cached
    set instead (``api/sql.py``'s ``_cached_mana_source_grp_ids``), since this
    is reference data that only changes when ``cards`` is refreshed."""
    if mana_source_grp_ids is None:
        mana_source_grp_ids = _mana_source_grp_ids(conn)
    # A cursor iterated directly rather than .fetchall()'d: a mid-Bo3 window
    # measured 990-4,276 rows of raw payload text (8-25 MB) that .fetchall()
    # was materializing into a Python list up front, before replay_live_state
    # ever looked at the first row. replay_live_state only wants an
    # Iterable[str], one payload at a time, so nothing here needs the whole
    # list to exist at once.
    #
    # source = 'arena' here, not on find_anchor: find_anchor's own
    # label='MatchGameRoomStateChangedEvent' predicate already excludes MTGO
    # rows (MTGO never writes that label), and adding a source filter there
    # measured a regression on the real database — SQLite abandons the
    # selective label index for idx_raw_events_source, a scan of every Arena
    # row. This query has no such index to lose: find_anchor deliberately
    # has no window bound, so id >= ? with no source filter would replay
    # every MTGO row written since the last Arena match too — at ~160 KB per
    # MTGO match this is real waste on the 1 Hz API poll, not a rounding
    # error.
    cursor = conn.execute(
        "SELECT payload FROM raw_events WHERE id >= ? AND source = 'arena' ORDER BY id",
        (anchor,),
    )
    # A small, bounded lookback just before the anchor, for
    # replay_live_state's deck_maindeck fallback (connectResp usually
    # precedes the room-opening event by one row — see
    # _DECK_MESSAGE_LOOKBACK above). Unlike the unbounded forward query, a
    # source filter here costs nothing to lose an index over: `id` is the
    # rowid, so a two-sided bounded range is a handful of rows either way,
    # never a scan. .fetchall()'d outright, since the window is at most
    # _DECK_MESSAGE_LOOKBACK rows — nothing like the 990-4,276-row forward
    # window that .fetchall() would be wrong to materialize.
    pre_anchor_rows = conn.execute(
        "SELECT payload FROM raw_events WHERE id >= ? AND id < ? AND source = 'arena' "
        "ORDER BY id",
        (anchor - _DECK_MESSAGE_LOOKBACK, anchor),
    ).fetchall()
    return replay_live_state(
        (row["payload"] for row in cursor),
        mana_source_grp_ids=mana_source_grp_ids,
        pre_anchor_payloads=(row["payload"] for row in pre_anchor_rows),
    )


def build_live_state(
    conn: sqlite3.Connection, *, mana_source_grp_ids: frozenset[int] | None = None
) -> LiveState | None:
    """The current match's board state, replayed fresh right now.
    ``None`` when no match has ever been captured — callers degrade the
    same way ``v_current_match`` returning nothing already does. See
    ``replay_from_anchor`` above for ``mana_source_grp_ids``."""
    anchor = find_anchor(conn)
    if anchor is None:
        return None
    return replay_from_anchor(conn, anchor, mana_source_grp_ids=mana_source_grp_ids)


@dataclass(frozen=True, slots=True)
class LibraryCard:
    """One maindeck card and how many copies are still unaccounted for in
    the library — "accounted for" meaning seen this game in hand,
    battlefield, graveyard or exile, deduplicated by ``instance_id`` so a
    card that moved zones (drawn, then cast) is one copy, not two."""

    grp_id: int
    name: str | None
    mana_cost: str | None
    mana_value: int | None
    type_line: str | None
    is_land: bool
    quantity: int  # copies in the maindeck
    left: int  # copies not yet seen outside the library this game
    is_interaction: bool | None  # None: no downloaded oracle text to classify


def build_library_remaining(
    conn: sqlite3.Connection, deck_id: str | None, state: LiveState | None
) -> tuple[LibraryCard, ...]:
    """This deck's maindeck (``decks.cards_json``) minus every copy of our
    own cards this game has shown outside the library — the read behind
    the tab's primary panel once a game is under way.

    Arena never sends our own library's *contents*, only its count (which
    ``state.library`` already carries honestly); "what's left" stays a
    subtraction against what has been seen elsewhere, the same math
    ``web/src/components/NextDrawsCard.tsx`` used to run client-side off a
    stale ``turns`` row — moved here so it rides the fresh replay instead.
    Empty when there is no deck, no live state, or self_seat is unresolved
    — never a guess at what's left (rule 4).
    """
    if deck_id is None or state is None or state.self_seat is None:
        return ()
    deck_row = conn.execute(
        "SELECT cards_json FROM decks WHERE deck_id = ?", (deck_id,)
    ).fetchone()
    if deck_row is None:
        return ()
    try:
        maindeck = json.loads(deck_row["cards_json"]).get("maindeck") or []
    except (json.JSONDecodeError, AttributeError):
        return ()
    counts = Counter(int(g) for g in maindeck)
    if not counts:
        return ()

    # Distinct instance_ids of our own cards seen anywhere but the library
    # this game — a card drawn then cast still counts once, not twice.
    seen: dict[int, set[int]] = {}
    for card in state.zone_cards:
        if card.seat != state.self_seat or card.zone == "library" or card.grp_id is None:
            continue
        seen.setdefault(card.grp_id, set()).add(card.instance_id)

    rows = conn.execute(
        f"SELECT grp_id, name, mana_cost, type_line, oracle_text FROM cards "
        f"WHERE grp_id IN ({','.join('?' * len(counts))})",
        tuple(counts),
    ).fetchall()
    by_id = {r["grp_id"]: r for r in rows}

    cards: list[LibraryCard] = []
    for grp_id, quantity in counts.items():
        left = max(0, quantity - len(seen.get(grp_id, ())))
        if left <= 0:
            continue
        row = by_id.get(grp_id)
        name = row["name"] if row else None
        mana_cost = row["mana_cost"] if row else None
        type_line = row["type_line"] if row else None
        is_land = effects.is_land(type_line)
        # Same three tags table/keep.py's own interaction_count counts —
        # lands never carry them, so short-circuit rather than asking
        # classify() to notice on its own.
        if is_land:
            is_interaction: bool | None = False
        else:
            tags = effects.classify(row["oracle_text"] if row else None, type_line, mana_cost)
            is_interaction = (
                None
                if isinstance(tags, str)
                else bool(
                    "spot_removal" in tags or "sweeper" in tags or "counterspell" in tags
                )
            )
        cards.append(
            LibraryCard(
                grp_id=grp_id,
                name=name,
                mana_cost=mana_cost,
                mana_value=None if is_land else effects.mana_value(mana_cost),
                type_line=type_line,
                is_land=is_land,
                quantity=quantity,
                left=left,
                is_interaction=is_interaction,
            )
        )
    cards.sort(
        key=lambda c: (
            c.is_land,
            c.mana_value if c.mana_value is not None else 99,
            c.name or "",
        )
    )
    return tuple(cards)
