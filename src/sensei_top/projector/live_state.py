"""Request-time replay of the match in progress — the board state exactly as
it stands right now, never waiting on ``project()``'s turn-boundary
snapshots or its full-rebuild cadence (``live.py``).

This is the general form of what ``projector/mulligan.py`` already did for
one narrow question ("is a mulligan pending"): reuse ``GameStateTracker``
(the same one ``project()`` uses) over a window of ``raw_events`` anchored to
the current match's own room-opening event, and read off whatever the
caller needs from the accumulated state — mid-turn, not at the last turn
boundary ``project()`` happened to reach.

Measured against a real database (~173k raw events, ~800 MB): a full
``project()`` rebuild costs **~11.6 s** wall time, of which parsing every
payload is **~3.9 s** with ``orjson`` (was ~7.55 s under the stdlib ``json``
this module used before — see ``live.py``'s module docstring for why the
switch alone doesn't make the rebuild affordable per-request), while
replaying one match (990-4,276 events, bounded by the anchor) costs
**0.03-0.08 s**. That gap is the reason this module exists rather than
reading ``turns``/``matches`` for the live tab: a full rebuild cannot land
inside a 1-second poll, let alone the 5-second median mulligan decision
window ``mulligan.py`` was already built to beat.

``mulligan.py`` is now a thin wrapper around this module (kept as its own
file because ``table/opening_hand.py`` and its tests still import
``MulliganOffer``/``replay_pending_offer`` from there) — see its module
docstring.

Self/opponent seat resolution reuses the hand asymmetry
``docs/arena-log.md`` documents and ``mulligan.py`` already proved: our own
hand always resolves to real ``gameObjects``; the opponent's hand zone never
does, at any point in the game, not only during a mulligan. That lets this
module identify seats without a separate ``authenticateResponse`` lookup —
useful since the mulligan fixture this module's tests share starts at the
room event itself, with no preceding auth message in the window.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import orjson

from sensei_top.projector.game_state import GameStateTracker, ZoneCard

PENDING_MULLIGAN = "ClientMessageType_MulliganResp"


@dataclass(frozen=True, slots=True)
class MulliganCard:
    """One card in the offered hand, in the zone's own order."""

    instance_id: int
    grp_id: int
    card_types: tuple[str, ...]  # Arena's own CardType_* strings


@dataclass(frozen=True, slots=True)
class MulliganOffer:
    """The hand currently offered for a keep/mulligan decision — our own
    seat only, since Arena never sends the opponent's hand contents."""

    seat: int
    cards: tuple[MulliganCard, ...]
    mulligan_count: int  # this seat's own count so far; 0 on the first offer
    active_player: int | None  # turnInfo.activePlayer, when stated


@dataclass(frozen=True, slots=True)
class Intermission:
    """A Bo3 break between two games — see ``docs/arena-log.md``'s trap 11c
    for the log shape this is read from: no event of its own, just the gap
    between the game-over ``gameInfo`` and the next game's first one, with
    ``SubmitDeckConfirmation`` a red herring in between."""

    game_number: int  # the game that just ended
    won: bool | None  # None when winningTeamId or our own teamId is unresolved (rule 4)
    reason: str | None  # ResultReason_* verbatim, e.g. "ResultReason_Concede"


@dataclass(frozen=True, slots=True)
class LiveState:
    """Everything a live, request-time read needs from one pass over the
    current match's ``raw_events`` — the shared replay behind
    ``table/live.py``, ``table/opening_hand.py`` and ``table/hand_read.py``.

    ``hand``/``library``/``graveyard``/``open_mana`` are keyed by seat, the
    same convention ``TurnRow`` uses; a caller maps seat -> self/opponent
    with ``self_seat``/``opponent_seat`` exactly as ``matches.py`` does for
    the projected tables. ``open_mana`` keeps today's meaning — untapped
    lands only — matching ``turns.opp_open_mana``.
    """

    self_seat: int | None
    opponent_seat: int | None
    turn_number: int | None  # None before the first turn (mulligan phase)
    active_seat: int | None
    life: dict[int, int]
    hand: dict[int, int]
    library: dict[int, int]
    graveyard: dict[int, int]
    open_mana: dict[int, int]
    # Untapped non-land mana sources (rocks, dorks, Treasures) — a sibling
    # count to open_mana, never merged into it (see GameStateTracker's own
    # docstring on this). Empty unless replay_live_state was given
    # mana_source_grp_ids; table/live.py is what supplies it.
    other_mana_sources: dict[int, int]
    zone_cards: tuple[ZoneCard, ...]
    offer: MulliganOffer | None
    # None outside a Bo3 break. Given a default so the handful of synthetic
    # LiveState(...) call sites elsewhere (tests, mostly) that predate this
    # field keep constructing without it.
    intermission: Intermission | None = None
    # deck_maindeck is the latest SubmitDeckResp's maindeck of this match once
    # the replay has seen one (the deck held for the game after a sideboarding
    # break), else the newest connectResp.deckMessage — this window itself, or
    # (when this window carried none) a small pre-anchor lookback
    # table/live.py supplies via replay_live_state's pre_anchor_payloads. None
    # when neither found one (rule 4: unknown means None, never a guess pulled
    # from a stale decks/matches row elsewhere). deck_id hashes the connectResp
    # list only, game 1's, never the boarded one: it is the same hash
    # projector.matches.deck_identity assigns that list, so it lands on
    # project()'s own deck_id, which is what the match's identity is keyed on.
    deck_maindeck: tuple[int, ...] | None = None
    deck_id: str | None = None
    # True when deck_maindeck came from a SubmitDeckResp of this match: the
    # live reads (library panel, keep guide) then count that list, not the
    # decks row deck_id points at, which is game 1's.
    deck_boarded: bool = False
    # The queue this match was played in, from the room-start event's
    # reservedPlayers[].eventId, read the way projector/matches.py reads it
    # for matches.event_id. None when the window carried no room-start event
    # with one; table/ranked.py counts that as ranked (rule 4).
    event_id: str | None = None


def _is_our_decision(payload: dict[str, Any]) -> bool:
    """A ``ClientToGREMessage`` carrying our own submitted mulligan
    decision — content-based, never on ``raw_events.label``: a capture
    missing header lines leaves every label ``None``
    (``reader/segmenter.py``), and ``_dispatch`` in ``projector/matches.py``
    already routes the same way rather than trusting the label."""
    return (
        payload.get("clientToMatchServiceMessageType")
        == "ClientToMatchServiceMessageType_ClientToGREMessage"
        and (payload.get("payload") or {}).get("type") == PENDING_MULLIGAN
    )


def _room_event_id(payload: dict[str, Any]) -> str | None:
    """The ``eventId`` of a ``MatchGameRoomStateType_Playing`` room event —
    the first reserved player that names one, as ``projector/matches.py``'s
    ``_handle_room_state`` does. ``None`` for every other payload."""
    event = payload.get("matchGameRoomStateChangedEvent")
    if not isinstance(event, dict):
        return None
    info = event.get("gameRoomInfo") or {}
    if info.get("stateType") != "MatchGameRoomStateType_Playing":
        return None
    for player in (info.get("gameRoomConfig") or {}).get("reservedPlayers") or []:
        if isinstance(player, dict) and player.get("eventId"):
            return player["eventId"]
    return None


def _messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    gre = payload.get("greToClientEvent")
    if not isinstance(gre, dict):
        return []
    msgs = gre.get("greToClientMessages")
    return msgs if isinstance(msgs, list) else []


def _find_self_seat(tracker: GameStateTracker) -> int | None:
    """Which seat is ours: the one whose hand zone resolves entirely to
    real objects. The opponent's hand zone ships ids with no matching
    ``gameObjects``, so it can never satisfy this — the same fact that
    makes the opponent's hand genuinely hidden everywhere else in this
    project. Unlike ``mulligan.py``'s original ``_find_our_seat``, this is
    not restricted to seats currently pending a mulligan decision: our own
    hand resolves this way for the entire game, not only during mulligans."""
    for zone in tracker.zones.values():
        if zone.get("type") != "ZoneType_Hand":
            continue
        seat = zone.get("ownerSeatId")
        if seat is None:
            continue
        ids = zone.get("objectInstanceIds") or []
        if ids and all((tracker.objects.get(i) or {}).get("grpId") is not None for i in ids):
            return seat
    return None


def _build_offer(
    tracker: GameStateTracker, seat: int, mulligan_count: int, active_player: int | None
) -> MulliganOffer | None:
    for zone in tracker.zones.values():
        if zone.get("type") != "ZoneType_Hand" or zone.get("ownerSeatId") != seat:
            continue
        cards: list[MulliganCard] = []
        for instance_id in zone.get("objectInstanceIds") or []:
            obj = tracker.objects.get(instance_id) or {}
            grp_id = obj.get("grpId")
            if grp_id is None:
                # Our own hand should always resolve by the time this is
                # called (this seat was chosen because it did); if it
                # doesn't, something upstream went stale — degrade to
                # nothing rather than publish a hand with a hole in it
                # (rule 4: unknown means null, never a guess).
                return None
            cards.append(
                MulliganCard(
                    instance_id=instance_id,
                    grp_id=grp_id,
                    card_types=tuple(obj.get("cardTypes") or ()),
                )
            )
        return MulliganOffer(
            seat=seat,
            cards=tuple(cards),
            mulligan_count=mulligan_count,
            active_player=active_player,
        )
    return None


def _game_result_entry(info: dict[str, Any], game_number: int) -> dict[str, Any] | None:
    """The ``MatchScope_Game`` entry for the game that just ended.

    ``results[]`` is cumulative across the match (trap 2 /
    ``docs/arena-log.md``), so it is never "the first" or "the last" —
    index ``game_number - 1`` among game-scope entries, same as
    ``projector/matches.py``'s ``_handle_game_over``. ``None`` when the
    array doesn't yet carry that many entries, never a guess.
    """
    results = [r for r in info.get("results") or [] if r.get("scope") == "MatchScope_Game"]
    if len(results) < game_number:
        return None
    return results[game_number - 1]


def _deck_maindeck_from_message(message: dict[str, Any]) -> tuple[int, ...] | None:
    """The maindeck carried by one ``greToClientMessages[]`` entry's own
    ``connectResp.deckMessage.deckCards`` — ``None`` when this message isn't
    a connectResp with a deck, or ``deckCards`` is absent or empty (rule 4:
    unknown means ``None``, never a guess). Mirrors
    ``projector/matches.py``'s ``_handle_deck_message`` exactly, since it
    parses the identical message shape — that function still owns writing
    ``decks``/``matches`` from it; this one only reads it into ``LiveState``.
    """
    connect = message.get("connectResp")
    if not isinstance(connect, dict):
        return None
    deck = connect.get("deckMessage")
    if not isinstance(deck, dict):
        return None
    maindeck = [int(g) for g in deck.get("deckCards") or []]
    if not maindeck:
        return None
    return tuple(maindeck)


def _submitted_deck_from_payload(payload: dict[str, Any]) -> tuple[int, ...] | None:
    """The maindeck of a ``ClientMessageType_SubmitDeckResp`` — the deck held
    for the game that follows a sideboarding break. Content-based, like
    ``_is_our_decision``: the message sits at the payload's own top level
    (``payload.submitDeckResp.deck``), never inside ``greToClientMessages[]``.
    ``None`` for any other payload or an absent or empty ``deckCards``
    (rule 4)."""
    inner = payload.get("payload")
    if not isinstance(inner, dict) or inner.get("type") != "ClientMessageType_SubmitDeckResp":
        return None
    resp = inner.get("submitDeckResp")
    deck = resp.get("deck") if isinstance(resp, dict) else None
    if not isinstance(deck, dict):
        return None
    cards = deck.get("deckCards")
    if not isinstance(cards, list):
        return None
    try:
        maindeck = tuple(int(g) for g in cards)
    except (TypeError, ValueError):
        return None
    return maindeck or None


def _deck_maindeck_from_payloads(payloads: Iterable[str]) -> tuple[int, ...] | None:
    """Scans a small, already-materialized payload list (``table/live.py``'s
    pre-anchor lookback window) for the newest ``connectResp.deckMessage`` —
    "last one found wins", the same rule the main replay loop below uses,
    since a payload list is handed in rather than a single known message.
    A SubmitDeckResp is not read here: before the room-opening anchor it is
    always an earlier match's."""
    found: tuple[int, ...] | None = None
    for payload_text in payloads:
        try:
            payload = orjson.loads(payload_text)
        except ValueError:  # orjson.JSONDecodeError, a ValueError subclass
            continue
        if not isinstance(payload, dict):
            continue
        for message in _messages(payload):
            maindeck = _deck_maindeck_from_message(message)
            if maindeck is not None:
                found = maindeck
    return found


def _build_intermission(
    info: dict[str, Any],
    game_number: int,
    self_seat: int | None,
    team_by_seat: dict[int, int],
) -> Intermission:
    entry = _game_result_entry(info, game_number)
    reason = entry.get("reason") if entry else None

    won: bool | None = None
    if entry is not None and self_seat is not None:
        self_team = team_by_seat.get(self_seat)
        winning_team = entry.get("winningTeamId")
        # Never assume team id equals seat id — compare against the team id
        # players[] actually reported for our own seat.
        if self_team is not None and winning_team is not None:
            won = winning_team == self_team

    return Intermission(game_number=game_number, won=won, reason=reason)


def replay_live_state(
    payloads: Iterable[str],
    *,
    mana_source_grp_ids: frozenset[int] = frozenset(),
    pre_anchor_payloads: Iterable[str] = (),
) -> LiveState:
    """Replay raw ``payload`` text in ascending id order into the board
    state as it stands after the last payload — mid-turn, not waiting for
    a boundary.

    ``payloads`` must start at or before the current match's own room-start
    event (``matchGameRoomStateChangedEvent`` /
    ``MatchGameRoomStateType_Playing``) — see ``docs/arena-log.md``'s
    anchoring trap (Arena reuses small instance ids and ``gameStateId``
    counters game to game, even match to match). This function trusts its
    caller to have anchored the window; ``table/live.py`` is what enforces
    it for every reader built on this module.

    ``mana_source_grp_ids`` is optional and only widens
    ``LiveState.other_mana_sources`` beyond an empty dict — see
    ``GameStateTracker``'s own docstring for what it counts and why it is a
    sibling to ``open_mana`` rather than folded into it.

    ``pre_anchor_payloads`` resolves ``LiveState.deck_maindeck``/``deck_id``
    for the common case where ``connectResp.deckMessage`` lands just
    *before* the room-opening anchor rather than inside ``payloads`` itself
    (measured against a real database: the nearest connectResp to every
    room-opening row landed one row before or one row after it, never
    further — see ``table/live.py``'s ``_DECK_MESSAGE_LOOKBACK``). Only
    consulted when ``payloads`` itself carried no connectResp; a connectResp
    inside the main window wins over it. A SubmitDeckResp inside the main
    window sets ``deck_maindeck`` (the latest one wins, and a later connectResp
    does not take it back) but never ``deck_id``, which stays the connectResp
    list's.
    """
    tracker = GameStateTracker(mana_source_grp_ids=mana_source_grp_ids)
    pending: dict[int, int] = {}
    self_seat: int | None = None
    active_player: int | None = None
    seen_seats: set[int] = set()
    team_by_seat: dict[int, int] = {}
    intermission: Intermission | None = None
    deck_maindeck: tuple[int, ...] | None = None
    connect_deck: tuple[int, ...] | None = None  # newest connectResp list
    submitted_deck: tuple[int, ...] | None = None  # newest SubmitDeckResp list
    event_id: str | None = None

    for payload_text in payloads:
        try:
            payload = orjson.loads(payload_text)
        except ValueError:  # orjson.JSONDecodeError, a ValueError subclass
            continue
        if not isinstance(payload, dict):
            continue

        if event_id is None:
            event_id = _room_event_id(payload)

        submitted = _submitted_deck_from_payload(payload)
        if submitted is not None:
            submitted_deck = submitted
            continue

        if _is_our_decision(payload):
            if self_seat is not None:
                pending.pop(self_seat, None)
            continue

        for message in _messages(payload):
            # Checked on every message, not only ones with a gameStateMessage:
            # connectResp is a sibling message type in the same
            # greToClientMessages list, never nested inside one. "Last one
            # found wins" (mid-match reconnect resending its own deck). Kept
            # apart from submitted_deck: deck_id hashes this one only.
            maindeck = _deck_maindeck_from_message(message)
            if maindeck is not None:
                connect_deck = maindeck

            gsm = message.get("gameStateMessage")
            if not isinstance(gsm, dict):
                continue
            tracker.apply(gsm)
            for player in gsm.get("players") or []:
                seat = player.get("systemSeatNumber")
                if seat is None:
                    continue
                seen_seats.add(seat)
                if (team := player.get("teamId")) is not None:
                    team_by_seat[seat] = team
                if player.get("pendingMessageType") == PENDING_MULLIGAN:
                    pending[seat] = player.get("mulliganCount") or 0
                else:
                    pending.pop(seat, None)
            turn = gsm.get("turnInfo")
            if isinstance(turn, dict) and turn.get("activePlayer") is not None:
                active_player = turn.get("activePlayer")
            if self_seat is None:
                self_seat = _find_self_seat(tracker)

            # Intermission tracking (docs/arena-log.md trap 11c). Processed
            # in message order, same as everything else here: the
            # match-final event carries a GameComplete gameInfo and then a
            # MatchComplete one (trap 1), and only ending on the latter
            # leaves this cleared.
            info = gsm.get("gameInfo")
            if isinstance(info, dict):
                match_state = info.get("matchState")
                game_number = info.get("gameNumber")
                if match_state == "MatchState_MatchComplete":
                    intermission = None
                elif (
                    match_state == "MatchState_GameComplete"
                    and info.get("matchWinCondition") == "MatchWinCondition_Best2of3"
                    and game_number is not None
                ):
                    intermission = _build_intermission(info, game_number, self_seat, team_by_seat)
                elif (
                    intermission is not None
                    and game_number is not None
                    and game_number > intermission.game_number
                ):
                    # The next game (or a later one) has started without its
                    # own GameComplete/MatchComplete ever landing in this
                    # window — clear rather than leave a stale break behind.
                    intermission = None

    opponent_seat = next((s for s in seen_seats if s != self_seat), None) if self_seat else None
    if opponent_seat is None and self_seat is not None:
        # players[] never named a second seat this replay (e.g. the window
        # ends before the opponent's own life/mulligan state was ever
        # restated) — fall back to any zone owned by a different seat, which
        # a hand or battlefield zone always carries.
        for zone in tracker.zones.values():
            owner = zone.get("ownerSeatId")
            if owner is not None and owner != self_seat:
                opponent_seat = owner
                break

    offer = (
        _build_offer(tracker, self_seat, pending[self_seat], active_player)
        if self_seat is not None and self_seat in pending
        else None
    )

    if connect_deck is None:
        connect_deck = _deck_maindeck_from_payloads(pre_anchor_payloads)
    deck_maindeck = submitted_deck if submitted_deck is not None else connect_deck

    deck_id: str | None = None
    if connect_deck is not None:
        # Local import: projector/matches.py imports this module's own
        # _game_result_entry at module level, so a module-level import back
        # here would be a true circular import — fails regardless of which
        # module loads first. deck_identity itself is a pure function (a
        # sha256 hash over sorted (grpId, count) pairs), so a call-time
        # import costs nothing worth avoiding.
        from sensei_top.projector.matches import deck_identity

        deck_id, _ = deck_identity(list(connect_deck))

    snapshot = tracker.snapshot_now()
    return LiveState(
        self_seat=self_seat,
        opponent_seat=opponent_seat,
        turn_number=tracker.current_turn,
        active_seat=tracker.current_active_seat,
        life=snapshot.life,
        hand=snapshot.hand,
        library=snapshot.library,
        graveyard=snapshot.graveyard,
        open_mana=snapshot.open_mana,
        other_mana_sources=snapshot.other_mana_sources,
        zone_cards=tuple(snapshot.cards),
        offer=offer,
        intermission=intermission,
        deck_maindeck=deck_maindeck,
        deck_id=deck_id,
        deck_boarded=submitted_deck is not None,
        event_id=event_id,
    )
