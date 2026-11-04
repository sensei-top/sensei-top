"""One contributed-game record per finished game, built at request time from
the projected tables and, for the opening hand, a replay of ``raw_events``;
never stored. ``GET /api/contrib/games`` and ``GET /api/contrib/records``
serve them.

Contract:

- Every key a record carries is a field the privacy policy lists for
  contributed games ("What is sent"); a new key is a policy change first.
  The match id, ``opponent_name``, ``opponent_user_id``, the deck's name and
  id, any time finer than the ISO week, and every raw event's text stay out.
  A game's key (``match_id:game_number``) is the caller's handle for its
  record, never part of it, and the random code a record is sent under is
  the caller's to make.
- A field the log never recorded is omitted, never null and never guessed
  (rule 4). An MTGO card with no ``grp_id`` is sent under the transcript's
  own ``mtgo_name``. A card with neither a name in ``cards`` nor a transcript
  name is not guessed: a deck list, a kept hand, or one side's cards on one
  turn that holds such a card is omitted whole, since a list with a hole
  would read as complete.
- Only a game whose result is a win, a loss or a draw has a key; a key for
  any other game, or one that names no game, is skipped.
- ``played`` is the ``PlayLand`` and ``CastSpell`` events of each seat;
  ``drawn`` is Arena's own ``Draw`` events, and MTGO records carry neither
  ``drawn`` nor ``life`` (its log has neither). A turn is listed when
  ``turns`` or ``card_events`` has a row for it, never filled in between.
- An opponent's archetype key is sent with the definition's own name, never
  the stored label. A manual pick is sent only when its key has a
  definition, or when it is ``Rogue``: any other label is the user's own
  text. A colours-and-card description is never sent.
- ``event`` is a fixed class (``ranked``, ``play``, ``limited``, ``event``),
  never Arena's raw id, because those ids carry dates.

Traps:

- ``kept_hand`` is the hand on offer when our own ``AcceptHand`` went out:
  after a mulligan it still holds the cards then put on the bottom, which
  ``mulligans`` counts. Each replay starts at the match's own
  ``MatchGameRoomStateType_Playing`` row, never earlier, for the instance-id
  reuse ``table/live.py::find_anchor`` describes.
- ``week`` is read off ``matches.started_at``'s date, which is the log's
  naive local time, so it is the local calendar's week.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from sensei_top.archetypes.classify import Definition, card_colors_by_name, load_definitions
from sensei_top.projector.live_state import PENDING_MULLIGAN, replay_live_state
from sensei_top.projector.matches import MATCH_ROOM_PLAYING_MARKER
from sensei_top.review.snapshot import classify_own_deck

__all__ = ["SCHEMA_VERSION", "build_records", "finished_game_keys"]

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_FINISHED = ("win", "loss", "draw")
_PLAYED = frozenset({"PlayLand", "CastSpell"})
_ACCEPT = "MulliganOption_AcceptHand"
# The one label ``PUT /api/matches/{match_id}/opponent-deck`` takes with no
# archetype key (``api/routes/matches.py::ROGUE_LABEL``; core never imports
# ``api``).
_ROGUE = "Rogue"
_CHUNK = 500
_RANKED_EVENTS = frozenset({"Ladder", "Traditional_Ladder"})
_PLAY_EVENTS = frozenset({"Play", "Traditional_Play", "Constructed_BestOf3"})
_NO_EVENT = frozenset({"AIBotMatch", "DirectGame"})

_GAME = """
    SELECT m.match_id, m.source, m.event_id, m.best_of, m.started_at,
           m.self_seat, m.opponent_seat,
           g.game_number, g.on_play, g.result, g.turn_count, g.self_mulligans,
           md.deck_id, f.format,
           o.opponent_label, o.opponent_key, o.opponent_source,
           (SELECT r.constructed_class FROM rank_snapshot r
             WHERE m.source = 'arena' AND r.observed_at <= m.started_at
             ORDER BY r.observed_at DESC LIMIT 1) AS rank_class
      FROM games g
      JOIN matches m ON m.match_id = g.match_id
      LEFT JOIN v_match_deck md ON md.match_id = m.match_id
      LEFT JOIN v_match_format f ON f.match_id = m.match_id
      LEFT JOIN v_match_opponent o ON o.match_id = m.match_id
     WHERE g.match_id = ? AND g.game_number = ? AND g.result IN ('win', 'loss', 'draw')
"""


def finished_game_keys(conn: sqlite3.Connection) -> list[str]:
    """``match_id:game_number`` for every finished game, oldest match first."""
    rows = conn.execute(
        """
        SELECT g.match_id, g.game_number
          FROM games g JOIN matches m ON m.match_id = g.match_id
         WHERE g.result IN ('win', 'loss', 'draw')
         ORDER BY m.started_at, g.match_id, g.game_number
        """
    )
    return [f"{match_id}:{number}" for match_id, number in rows]


def _parse_key(key: str) -> tuple[str, int] | None:
    match_id, sep, number = key.rpartition(":")
    if not sep or not match_id or not number.isdigit():
        return None
    return match_id, int(number)


class _Builder:
    """What one request shares across its records: the room anchors, each
    match's kept hands, and the rule engine's inputs, each read once and
    only when a record needs it."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._anchors: list[tuple[int, str | None]] | None = None
        self._hands: dict[str, dict[int, list[int]]] = {}
        self._definitions: dict[str, dict[str, list[Definition]]] | None = None
        self._colors: dict[str, frozenset[str]] | None = None
        self._own: dict[str, dict[str, str] | None] = {}
        self.unnamed = 0

    def names(self, grp_ids: Iterable[int | None]) -> dict[int, str]:
        wanted = sorted({g for g in grp_ids if g is not None})
        names: dict[int, str] = {}
        for start in range(0, len(wanted), _CHUNK):
            chunk = wanted[start:start + _CHUNK]
            rows = self.conn.execute(
                f"SELECT grp_id, name FROM cards WHERE grp_id IN ({','.join('?' * len(chunk))})",
                chunk,
            )
            names.update((grp_id, name) for grp_id, name in rows if name)
        return names

    def named(
        self, grp_ids: Sequence[int | str | None], names: dict[int, str]
    ) -> list[str] | None:
        """Every card's name in order, or ``None`` when any has none. A ``str``
        is a name already (an MTGO card the card database lacks)."""
        out = [
            g if isinstance(g, str) else None if g is None else names.get(g) for g in grp_ids
        ]
        if None in out:
            self.unnamed += out.count(None)
            return None
        return [n for n in out if n is not None]

    def board(self, grp_ids: Sequence[int | None], names: dict[int, str]) -> list[list[Any]] | None:
        """``[[name, count]]`` by name, or ``None`` when any card has no name."""
        named = self.named(grp_ids, names)
        if named is None:
            return None
        counts = Counter(named)
        return [[name, counts[name]] for name in sorted(counts)]

    # -- the opening hand ---------------------------------------------------

    def _room_anchors(self) -> list[tuple[int, str | None]]:
        """``(raw_events.id, matchId)`` of every room-opening row, in order."""
        if self._anchors is None:
            self._anchors = []
            for row_id, payload in self.conn.execute(
                "SELECT id, payload FROM raw_events WHERE label = 'MatchGameRoomStateChangedEvent' "
                "AND payload LIKE ? ORDER BY id",
                (f"%{MATCH_ROOM_PLAYING_MARKER}%",),
            ):
                self._anchors.append((row_id, _room_match_id(payload)))
        return self._anchors

    def kept_hands(self, match_id: str) -> dict[int, list[int]]:
        """Game number to the grpIds of the hand we kept, for the games of an
        Arena match whose log carries both the offer and our keep."""
        if match_id in self._hands:
            return self._hands[match_id]
        hands: dict[int, list[int]] = {}
        self._hands[match_id] = hands
        anchors = self._room_anchors()
        at = next((i for i, (_, m) in enumerate(anchors) if m == match_id), None)
        if at is None:
            return hands
        start = anchors[at][0]
        end = anchors[at + 1][0] if at + 1 < len(anchors) else None
        keeps = [
            row_id
            for row_id, payload in self.conn.execute(
                "SELECT id, payload FROM raw_events WHERE id > ? AND (? IS NULL OR id < ?) "
                "AND source = 'arena' AND payload LIKE ? ORDER BY id",
                (start, end, end, f"%{_ACCEPT}%"),
            )
            if _is_our_keep(payload)
        ]
        for keep in keeps:
            cursor = self.conn.execute(
                "SELECT payload FROM raw_events WHERE id >= ? AND id < ? AND source = 'arena' "
                "ORDER BY id",
                (start, keep),
            )
            offer = replay_live_state(payload for (payload,) in cursor).offer
            if offer is None or offer.game_number is None or not offer.cards:
                continue
            hands.setdefault(offer.game_number, [card.grp_id for card in offer.cards])
        return hands

    # -- the player's own archetype -------------------------------------------

    def definitions(self) -> dict[str, dict[str, list[Definition]]]:
        if self._definitions is None:
            self._definitions = load_definitions(self.conn)
        return self._definitions

    def self_archetype(self, row: sqlite3.Row) -> dict[str, str] | None:
        """The rule engine's name for the match's own deck (game 1's full
        list, DB11), made once per match and shared by all its games."""
        match_id = row["match_id"]
        if match_id not in self._own:
            if self._colors is None:
                self._colors = card_colors_by_name(self.conn)
            verdict, _ = classify_own_deck(
                self.conn, row["deck_id"], row["event_id"],
                colors_by_name=self._colors, fmt=row["format"],
                use_deck_format=row["source"] == "arena",
            )
            self._own[match_id] = (
                None if verdict is None else {"key": verdict.key, "label": verdict.name}
            )
        return self._own[match_id]

    def opponent(self, row: sqlite3.Row) -> dict[str, str] | None:
        source, label, key = row["opponent_source"], row["opponent_label"], row["opponent_key"]
        if not label or source in (None, "unknown", "colors"):
            return None
        named_key = key.removeprefix("archetype:") if key and key.startswith("archetype:") else None
        if named_key is None:
            return None if source == "manual" and label != _ROGUE else {"label": label}
        # The definition's own name, never the stored label: a manual pick's
        # label is the user's text.
        formats = self.definitions()
        fmt = next((f for f in formats if f.lower() == (row["format"] or "").lower()), None)
        for definition in (d for kind in formats.get(fmt, {}).values() for d in kind):
            if definition.key == named_key:
                return {"key": named_key, "label": definition.name}
        return None if source == "manual" else {"key": named_key, "label": label}


def _room_match_id(payload: str) -> str | None:
    try:
        event = json.loads(payload).get("matchGameRoomStateChangedEvent") or {}
        info = event.get("gameRoomInfo") or {}
        if info.get("stateType") != MATCH_ROOM_PLAYING_MARKER:
            return None
        match_id = (info.get("gameRoomConfig") or {}).get("matchId")
    except (ValueError, AttributeError):
        return None
    return match_id if isinstance(match_id, str) else None


def _is_our_keep(payload: str) -> bool:
    """Our own submitted ``AcceptHand``, read off the message's content as
    ``projector/live_state.py::_is_our_decision`` reads it."""
    try:
        body = json.loads(payload)
        if body.get("clientToMatchServiceMessageType") != (
            "ClientToMatchServiceMessageType_ClientToGREMessage"
        ):
            return False
        inner = body.get("payload") or {}
        return (
            inner.get("type") == PENDING_MULLIGAN
            and (inner.get("mulliganResp") or {}).get("decision") == _ACCEPT
        )
    except (ValueError, AttributeError):
        return False


def _week(started_at: str | None) -> str | None:
    if not started_at:
        return None
    try:
        year, week, _ = date.fromisoformat(started_at[:10]).isocalendar()
    except ValueError:
        return None
    return f"{year}-W{week:02d}"


def _deck_lists(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> tuple[list[int], list[int]] | None:
    """The game's own main deck and sideboard as grpIds: game 1's from the
    match's deck, a later game's from ``game_decks``. ``None`` when the log
    never said, or when a copy never resolved to a card."""
    if row["game_number"] == 1:
        if row["deck_id"] is None:
            return None
        deck = conn.execute(
            "SELECT cards_json FROM decks WHERE deck_id = ?", (row["deck_id"],)
        ).fetchone()
        try:
            cards = json.loads(deck[0]) if deck and deck[0] else None
        except json.JSONDecodeError:
            return None
        if not isinstance(cards, dict):
            return None
        unresolved = cards.get("unresolved") or {}
        if any(int(unresolved.get(board) or 0) for board in ("maindeck", "sideboard")):
            return None
        return (
            [int(g) for g in cards.get("maindeck") or []],
            [int(g) for g in cards.get("sideboard") or []],
        )
    held = conn.execute(
        "SELECT deck_cards_json, sideboard_cards_json FROM game_decks "
        "WHERE match_id = ? AND game_number = ?",
        (row["match_id"], row["game_number"]),
    ).fetchone()
    if held is None:
        return None
    try:
        return [int(g) for g in json.loads(held[0])], [int(g) for g in json.loads(held[1])]
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _card(event: sqlite3.Row) -> int | str | None:
    """The card's grpId, else the transcript's own name (``mtgo_name`` is set
    only where no card stands for it)."""
    return event["grp_id"] if event["grp_id"] is not None else event["mtgo_name"]


def _event_class(event_id: str | None) -> str | None:
    """A fixed class, never the raw id: Arena's ids carry dates."""
    if not event_id or event_id in _NO_EVENT:
        return None
    if event_id in _RANKED_EVENTS:
        return "ranked"
    if event_id in _PLAY_EVENTS:
        return "play"
    if "Draft" in event_id or "Sealed" in event_id:
        return "limited"
    return "event"


def _turns(
    builder: _Builder, row: sqlite3.Row, events: list[sqlite3.Row], names: dict[int, str]
) -> list[dict[str, Any]]:
    arena = row["source"] == "arena"
    life: dict[int, tuple[int | None, int | None]] = {}
    if arena:
        for n, self_life, opp_life in builder.conn.execute(
            "SELECT turn_number, self_life, opp_life FROM turns "
            "WHERE match_id = ? AND game_number = ?",
            (row["match_id"], row["game_number"]),
        ):
            life[n] = (self_life, opp_life)
    by_turn: dict[int, list[sqlite3.Row]] = {}
    for event in events:
        by_turn.setdefault(event["turn_number"], []).append(event)

    seats = (("self", row["self_seat"]), ("opp", row["opponent_seat"]))
    turns = []
    for n in sorted(set(life) | set(by_turn)):
        turn: dict[str, Any] = {"n": n}
        happened = by_turn.get(n, [])
        if arena:
            drawn = builder.named(
                [_card(e) for e in happened
                 if e["category"] == "Draw" and e["seat"] == row["self_seat"]],
                names,
            )
            if drawn is not None:
                turn["drawn"] = drawn
        played: dict[str, list[str]] = {}
        for side, seat in seats:
            if seat is None:
                continue
            cards = builder.named(
                [_card(e) for e in happened if e["category"] in _PLAYED and e["seat"] == seat],
                names,
            )
            if cards is not None:
                played[side] = cards
        if played:
            turn["played"] = played
        self_life, opp_life = life.get(n, (None, None))
        totals = {k: v for k, v in (("self", self_life), ("opp", opp_life)) if v is not None}
        if totals:
            turn["life"] = totals
        turns.append(turn)
    return turns


def _record(builder: _Builder, row: sqlite3.Row, policy_version: str) -> dict[str, Any]:
    conn = builder.conn
    arena = row["source"] == "arena"
    events = conn.execute(
        "SELECT turn_number, seat, grp_id, category, mtgo_name FROM card_events "
        "WHERE match_id = ? AND game_number = ? AND turn_number IS NOT NULL ORDER BY seq",
        (row["match_id"], row["game_number"]),
    ).fetchall()
    lists = _deck_lists(conn, row)
    hand = builder.kept_hands(row["match_id"]).get(row["game_number"]) if arena else None
    names = builder.names(
        [e["grp_id"] for e in events]
        + (lists[0] + lists[1] if lists else [])
        + (hand or [])
    )

    record: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "client": row["source"]}
    optional = {
        "format": row["format"],
        "event": _event_class(row["event_id"]),
        "best_of": row["best_of"],
        "week": _week(row["started_at"]),
        "rank": row["rank_class"] if arena else None,
    }
    record.update((k, v) for k, v in optional.items() if v is not None)
    record["game"] = row["game_number"]
    if row["on_play"] is not None:
        record["on_play"] = bool(row["on_play"])
    if row["self_mulligans"] is not None:
        record["mulligans"] = row["self_mulligans"]
    if hand and (kept := builder.board(hand, names)) is not None:
        record["kept_hand"] = kept
    deck = None
    if lists is not None:
        main, side = builder.board(lists[0], names), builder.board(lists[1], names)
        if main is not None and side is not None and main:
            deck = {"main": main, "side": side}
            record["deck"] = deck
    record["turns"] = _turns(builder, row, events, names)
    record["result"] = row["result"]
    if row["turn_count"] is not None:
        record["turn_count"] = row["turn_count"]
    archetypes: dict[str, dict[str, str]] = {}
    if (mine := builder.self_archetype(row)) is not None:
        archetypes["self"] = mine
    if (theirs := builder.opponent(row)) is not None:
        archetypes["opp"] = theirs
    if archetypes:
        record["archetypes"] = archetypes
    record["policy_version"] = policy_version
    return record


def build_records(
    conn: sqlite3.Connection, keys: Iterable[str], *, policy_version: str
) -> list[tuple[str, dict[str, Any]]]:
    """``(key, record)`` for each key that names a finished game, in the
    order asked, each key once. ``conn`` must use ``sqlite3.Row``."""
    builder = _Builder(conn)
    out: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        parsed = _parse_key(key)
        if parsed is None:
            continue
        row = conn.execute(_GAME, parsed).fetchone()
        if row is None:
            continue
        out.append((key, _record(builder, row, policy_version)))
    if builder.unnamed:
        log.warning(
            "contributed games: %d cards with no name in the card database; "
            "the lists holding them were left out",
            builder.unnamed,
        )
    return out
