"""Stage 2, M1: project ``raw_events`` into ``decks``, ``matches`` and ``games``.

All Arena semantics live here. The projector is a pure function of
``raw_events`` and is always run as a **full rebuild**: derived rows are deleted
and recomputed from scratch. At this scale (a heavy session is ~3k events, a
year of play well under a million) a full pass costs under a second, and it
removes an entire class of incremental-state bugs. When a parsing rule is fixed,
re-running applies the fix to every match ever recorded.

Field paths verified against client 2026.62.10 (see brief §6):

* ``authenticateResponse.clientId`` — our own user id.
* ``matchGameRoomStateChangedEvent`` / ``MatchGameRoomStateType_Playing`` —
  match start: ``matchId``, ``eventId``, ``reservedPlayers[]`` (``userId``,
  ``playerName``, ``systemSeatId``, ``teamId``).
* ``…/MatchGameRoomStateType_MatchCompleted`` — ``finalMatchResult.resultList``.
* ``greToClientEvent.greToClientMessages[].connectResp.deckMessage`` — our
  submitted deck for the match (``deckCards`` / ``sideboardCards``, grpIds).
* ``…[].gameStateMessage.gameInfo`` — per-game result at
  ``stage == GameStage_GameOver``.
* ``…[].gameStateMessage.turnInfo`` — sibling of ``gameInfo``; ``turnNumber``
  and ``activePlayer`` drive on-play detection and turn counts.
* requests ``DeckUpsertDeckV3`` (deck edited) and ``EventSetDeckV3`` (deck
  chosen for an event) — both wrap escaped JSON in ``request``, carrying
  ``Summary.Name``, ``Summary.DeckId`` (Arena's own stable deck GUID) and
  ``Summary.Attributes[]`` with ``Format`` and ``Version``.
* ``…[].gameStateMessage.gameObjects[].attackState``/``attackInfo`` and
  ``blockState``/``blockInfo`` — combat declarations, handled in
  ``game_state.py`` (see ``projector/combat.py``).
* ``…[].gameStateMessage.annotations[]`` with ``AnnotationType_DamageDealt``
  or ``AnnotationType_ModifiedLife`` — damage and life attribution, same
  module.

M2 adds ``turns`` (per-game board state by turn number); the accumulation
logic for that lives in ``game_state.py`` — see its module docstring. This
module only decides *when* a tracker is fresh (one per ``GameState``) and
*when* to finalize the trailing turn (at ``GameOver``).

Three traps this code exists to avoid:

1. **Double-counted games.** Arena emits ``GameStage_GameOver`` twice for the
   final game — once with ``MatchState_GameComplete`` and again with
   ``MatchState_MatchComplete``. Only the former is counted.
2. **Cumulative results.** ``gameInfo.results`` is not the result of *this*
   game; it is every result so far this match. The current game's outcome is
   the ``MatchScope_Game`` entry at index ``gameNumber - 1``.
3. **Batched messages.** Most events carry two or more ``GameStateMessage``
   entries in ``greToClientMessages[]``. Every element is iterated; a
   find-first approach drops turn changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import orjson

from sensei_top.formats import _NOT_CONSTRUCTED_STANDARD, arena_format
from sensei_top.mtgo.config import load_handle as mtgo_load_handle
from sensei_top.projector.game_state import GameStateTracker
from sensei_top.projector.live_state import _game_result_entry
from sensei_top.projector.mtgo.decks import project_mtgo_decks
from sensei_top.projector.mtgo.project import project_mtgo

log = logging.getLogger(__name__)

WIN, LOSS, DRAW, INCOMPLETE = "win", "loss", "draw", "incomplete"

# The literal Arena sends for a match starting to play — the one event that
# both `has_match_boundary` (below, for live.py's force-projection) and
# `table/opening_hand.py` (the mulligan read's replay anchor) key off. A
# plain substring match on the raw payload text, not a parsed field: cheap
# enough to run as a SQL LIKE filter without touching the projection.
MATCH_ROOM_PLAYING_MARKER = "MatchGameRoomStateType_Playing"




def deck_identity(maindeck_grp_ids: list[int]) -> tuple[str, str]:
    """Return ``(deck_id, canonical_json)`` for a maindeck card list.

    ``deck_id`` is a SHA-256 over the sorted ``(grpId, count)`` pairs, so
    renaming a deck in Arena keeps its identity while changing a single card
    creates a new one. Sideboard is excluded from identity on purpose: in Bo3
    the same deck is resubmitted with a different sideboard configuration
    between games, and those must not fragment into separate decks.
    """
    counts = Counter(maindeck_grp_ids)
    canonical = json.dumps(sorted(counts.items()), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), canonical




@dataclass
class GameState:
    game_number: int
    on_play: bool | None = None
    result: str | None = None
    result_reason: str | None = None
    turn_count: int = 0
    mulligans: dict[int, int] = field(default_factory=dict)  # seat -> count
    # One tracker per game: GameState is constructed once per game_number
    # (via MatchState.game()'s setdefault), so this default factory is what
    # gives M2 a fresh board-state accumulator at every game boundary.
    tracker: GameStateTracker = field(default_factory=GameStateTracker)


@dataclass
class MatchState:
    match_id: str
    event_id: str | None = None
    self_user_id: str | None = None
    self_seat: int | None = None
    self_team: int | None = None
    opponent_seat: int | None = None
    opponent_user_id: str | None = None
    opponent_name: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    deck_id: str | None = None
    deck_cards: dict[str, list[int]] | None = None
    result: str = INCOMPLETE
    completed_reason: str | None = None
    games: dict[int, GameState] = field(default_factory=dict)
    current_game: int = 1
    # game_number -> {"maindeck": [...], "sideboard": [...]}, from
    # ClientMessageType_SubmitDeckResp — the deck actually held for that
    # game after sideboarding. Never set for game 1 (see
    # Projector._handle_submit_deck); a Bo3 that boarded gets rows for 2
    # and/or 3 here, game 1's own deck staying in `deck_cards` above.
    submitted_decks: dict[int, dict[str, list[int]]] = field(default_factory=dict)

    def game(self, number: int) -> GameState:
        return self.games.setdefault(number, GameState(game_number=number))


def _outcome(winning_team: int | None, self_team: int | None) -> str:
    if winning_team is None:
        return DRAW  # ResultType_Draw carries no winning team
    if self_team is None:
        return INCOMPLETE
    return WIN if winning_team == self_team else LOSS


def _messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    gre = payload.get("greToClientEvent")
    if not isinstance(gre, dict):
        return []
    msgs = gre.get("greToClientMessages")
    return msgs if isinstance(msgs, list) else []




class Projector:
    """Replays raw_events in order, accumulating match/game state."""

    def __init__(self) -> None:
        self.self_user_id: str | None = None
        self.matches: dict[str, MatchState] = {}
        self.deck_names: dict[str, str] = {}       # deck_id -> latest human name
        self.deck_formats: dict[str, str] = {}
        # deck_id -> Arena's own deck GUID -> (version, format, last seen).
        # Recorded but not yet used for identity: deck_id stays the card-list
        # hash, so that normalizing deck versions later is a projection change
        # rather than a re-read of every log ever ingested.
        self.deck_guids: dict[str, dict[str, tuple[str | None, str | None, str | None]]] = {}
        self._active: MatchState | None = None
        # connectResp (carrying our deck) is emitted *before* the match-start
        # event, so the deck has to be parked until a match exists to own it.
        self._pending_deck: tuple[str, dict[str, list[int]]] | None = None
        self.warnings: int = 0
        # (observed_at, class, level, step, season, wins, losses) — one row
        # per RankGetCombinedRankInfo *response*, in the order raw_events was
        # replayed. Not match-scoped: Arena polls this on its own schedule,
        # never once per match.
        self.rank_observations: list[tuple[str | None, str | None, int | None,
                                            int | None, int | None, int | None, int | None]] = []
        # Parked between the SubmitDeckResp that carries it and the game-start
        # message that says which game it was held for — see
        # _handle_submit_deck. Cleared the moment it is claimed.
        self._pending_sideboard_deck: dict[str, list[int]] | None = None

    def feed(self, kind: str, label: str | None, payload_text: str, logged_at: str | None) -> None:
        try:
            payload = orjson.loads(payload_text)
        except ValueError:  # orjson.JSONDecodeError, a ValueError subclass
            self._warn("unparseable payload in raw_events")
            return
        self.feed_parsed(kind, label, payload, logged_at)

    def feed_parsed(
        self, kind: str, label: str | None, payload: Any, logged_at: str | None
    ) -> None:
        """Same as ``feed``, but for a payload ``project()`` already parsed.

        Parsing is ``project()``'s job, once per row; this is the entry point
        that expects the parsed result. ``feed`` above stays the text entry point
        so a direct caller (tests, mainly) can still hand it a JSON string.
        """
        if not isinstance(payload, dict):
            return
        try:
            self._dispatch(kind, label, payload, logged_at)
        except Exception as exc:  # never let one bad event halt ingestion (brief §6)
            self._warn(f"projection error on {label!r}: {exc}")

    def finish(self) -> None:
        """Close out accumulated state. Call once after the last event.

        A game's last turn is normally snapshotted at GameOver, but Arena keeps
        sending state for a game after that (and an abandoned game never gets a
        GameOver), so the trailing turn can be left unrecorded. This fills that
        gap without rewriting turns already captured.
        """
        for state in self.matches.values():
            for game in state.games.values():
                game.tracker.flush_trailing()

    def _warn(self, message: str) -> None:
        self.warnings += 1
        log.warning(message)

    def _dispatch(self, kind, label, payload, logged_at) -> None:
        if "authenticateResponse" in payload:
            auth = payload["authenticateResponse"]
            self.self_user_id = auth.get("clientId") or auth.get("userId")
            return

        if "matchGameRoomStateChangedEvent" in payload:
            self._handle_room_state(payload["matchGameRoomStateChangedEvent"], logged_at)
            return

        if kind == "request" and label in ("DeckUpsertDeckV3", "EventSetDeckV3"):
            self._handle_deck_request(payload, logged_at)
            return

        if kind == "response" and label == "RankGetCombinedRankInfo":
            self._handle_rank_response(payload, logged_at)
            return

        # A client-outbound message, not a greToClientEvent batch: unlike
        # every other GRE traffic this projector reads, this one carries the
        # deck at its own top level (payload.payload.submitDeckResp.deck),
        # never nested inside greToClientMessages[] — verified against a
        # real capture, not assumed; _messages() below would silently find
        # nothing here.
        if kind == "event" and label == "ClientToGremessage":
            inner = payload.get("payload")
            if isinstance(inner, dict) and inner.get("type") == "ClientMessageType_SubmitDeckResp":
                self._handle_submit_deck(inner.get("submitDeckResp", {}).get("deck"))
                return

        for message in _messages(payload):
            self._handle_gre_message(message, logged_at)

    def _handle_room_state(self, event: dict[str, Any], logged_at: str | None) -> None:
        info = event.get("gameRoomInfo", {})
        config = info.get("gameRoomConfig", {})
        match_id = config.get("matchId")
        if not match_id:
            return
        state = self.matches.setdefault(match_id, MatchState(match_id=match_id))
        state_type = info.get("stateType")

        if state_type == "MatchGameRoomStateType_Playing":
            self._active = state
            state.started_at = state.started_at or logged_at
            players = config.get("reservedPlayers") or []
            for player in players:
                state.event_id = state.event_id or player.get("eventId")
                if not self.self_user_id:
                    # self.self_user_id unresolved (a log that lost
                    # authenticateResponse, e.g. a truncated session) — every
                    # reserved player would otherwise fall into the `else`
                    # branch below, making the *last* player in the list the
                    # "opponent", which can be the user's own seat (rule 4:
                    # unknown means null, never a guess). Leave every seat
                    # field unset instead; the warning below still fires
                    # since self_seat stays None.
                    continue
                if player.get("userId") == self.self_user_id:
                    state.self_user_id = player.get("userId")
                    state.self_seat = player.get("systemSeatId")
                    state.self_team = player.get("teamId")
                else:
                    state.opponent_seat = player.get("systemSeatId")
                    state.opponent_user_id = player.get("userId")
                    state.opponent_name = player.get("playerName")
            if state.deck_id is None and self._pending_deck is not None:
                state.deck_id, state.deck_cards = self._pending_deck
            if state.self_seat is None:
                # Happens if the log lost authenticateResponse (truncated session).
                self._warn(f"self seat unresolved for match {match_id}")

        elif state_type == "MatchGameRoomStateType_MatchCompleted":
            state.ended_at = logged_at
            final = info.get("finalMatchResult", {})
            state.completed_reason = final.get("matchCompletedReason")
            game_index = 0
            for entry in final.get("resultList", []) or []:
                scope = entry.get("scope")
                winning_team = entry.get("winningTeamId")
                if scope == "MatchScope_Game":
                    game_index += 1
                    game = state.game(game_index)
                    # finalMatchResult is authoritative; it also covers games whose
                    # GameOver message never arrived.
                    game.result = _outcome(winning_team, state.self_team)
                    game.result_reason = entry.get("reason")
                elif scope == "MatchScope_Match":
                    state.result = _outcome(winning_team, state.self_team)
            if self._active is state:
                self._active = None

    def _handle_deck_request(self, payload: dict[str, Any], logged_at: str | None) -> None:
        """Learn a deck's name, format and Arena GUID from a deck request.

        Two requests carry the same summary: ``DeckUpsertDeckV3`` when a deck is
        edited, ``EventSetDeckV3`` when one is chosen for an event. Both wrap
        escaped JSON inside JSON. The card list keys the metadata, since that is
        what ``deck_id`` is; each field is learned independently, so a summary
        missing a name still contributes its format and GUID.
        """
        raw = payload.get("request")
        if not isinstance(raw, str):
            return
        # A bad payload here is caught by _dispatch's broad except (above),
        # same as every other dispatch path, so this stays unguarded.
        inner = orjson.loads(raw)
        maindeck = (inner.get("Deck") or {}).get("MainDeck") or []
        grp_ids: list[int] = []
        for card in maindeck:
            grp_ids.extend([card["cardId"]] * int(card.get("quantity", 0)))
        if not grp_ids:
            return  # no card list, so nothing to attach the metadata to
        deck_id, _ = deck_identity(grp_ids)

        summary = inner.get("Summary") or {}
        if name := summary.get("Name"):
            self.deck_names[deck_id] = name  # later requests win: "most recent"
        attributes = {
            attribute.get("name"): attribute.get("value")
            for attribute in summary.get("Attributes") or []
        }
        # Arena's own spelling ('TraditionalStandard'), never remapped.
        if fmt := attributes.get("Format"):
            self.deck_formats[deck_id] = fmt
        if arena_deck_id := summary.get("DeckId"):
            self.deck_guids.setdefault(deck_id, {})[arena_deck_id] = (
                attributes.get("Version"),
                attributes.get("Format"),
                logged_at,
            )

    def _handle_rank_response(self, payload: dict[str, Any], logged_at: str | None) -> None:
        """One bare observation from a ``RankGetCombinedRankInfo`` response —
        not match-scoped, so it is simply appended in replay order rather than
        attached to ``self._active``. ``observed_at`` withheld (``None``, never
        guessed — rule 4) rather than defaulting to "now": an unresolved
        header timestamp (see docs/arena-log.md) makes this observation
        unrankable by time, and a fabricated one would corrupt every
        "most recent snapshot before this match" lookup silently.
        """
        if logged_at is None:
            self._warn("RankGetCombinedRankInfo with no resolved timestamp, dropped")
            return

        def _int(key: str) -> int | None:
            value = payload.get(key)
            return value if isinstance(value, int) else None

        rank_class = payload.get("constructedClass")
        self.rank_observations.append((
            logged_at,
            rank_class if isinstance(rank_class, str) else None,
            _int("constructedLevel"),
            _int("constructedStep"),
            _int("constructedSeasonOrdinal"),
            _int("constructedMatchesWon"),
            _int("constructedMatchesLost"),
        ))

    def _handle_gre_message(self, message: dict[str, Any], logged_at: str | None) -> None:
        connect = message.get("connectResp")
        if isinstance(connect, dict) and "deckMessage" in connect:
            self._handle_deck_message(connect["deckMessage"])

        gsm = message.get("gameStateMessage")
        if not isinstance(gsm, dict):
            return

        info = gsm.get("gameInfo")
        state = self._active
        if isinstance(info, dict):
            match_id = info.get("matchID")
            if match_id:
                state = self.matches.setdefault(match_id, MatchState(match_id=match_id))
                self._active = state
            if state is not None and (number := info.get("gameNumber")) is not None:
                state.current_game = number
                state.game(number)
                # The deck held for *this* game, if one was submitted since the
                # last game boundary — verified against a real capture: the
                # message carrying the new gameNumber is the very next event
                # after SubmitDeckResp, so the first gameNumber sighting after
                # a submission is always the game it was held for.
                if self._pending_sideboard_deck is not None:
                    state.submitted_decks[number] = self._pending_sideboard_deck
                    self._pending_sideboard_deck = None
        if state is None:
            return

        game = state.game(state.current_game)
        # Apply this message's own state changes before deciding whether it's
        # a GameOver: the terminal message may itself carry the final life/board
        # change, and that must land in the finalized turn snapshot below.
        game.tracker.apply(gsm)

        if isinstance(info, dict):
            self._handle_game_over(state, info)

        turn = gsm.get("turnInfo")  # sibling of gameInfo, not nested in it
        if isinstance(turn, dict):
            number = turn.get("turnNumber")
            if isinstance(number, int):
                game.turn_count = max(game.turn_count, number)
                active = turn.get("activePlayer")
                if number == 1 and game.on_play is None and active is not None:
                    if state.self_seat is None:
                        self._warn(f"on-play undetermined for match {state.match_id}")
                    else:
                        # Per game, not per match: in Bo3 the previous loser chooses.
                        game.on_play = active == state.self_seat

        for player in gsm.get("players") or []:
            seat = player.get("systemSeatNumber")
            if seat is None:
                continue
            # Arena omits mulliganCount entirely when it is zero, but reports it
            # for both seats when non-zero. So seeing the seat at all is what
            # distinguishes "kept seven" (0) from "never observed" (NULL).
            game.mulligans.setdefault(seat, 0)
            count = player.get("mulliganCount")
            if count is not None:
                game.mulligans[seat] = max(game.mulligans[seat], count)

    def _handle_submit_deck(self, deck: dict[str, Any] | None) -> None:
        """``ClientMessageType_SubmitDeckResp`` — the deck actually held for
        the game that follows, i.e. Bo3 sideboarding as played. It carries no
        ``matchID`` and no ``gameNumber`` of its own (verified against a real
        capture: raw_events ids 581->583 and 1897->1899, both Bo3 matches,
        2026-08-31), so it cannot be attached to a game directly — it is
        parked here and claimed by the next game-boundary message, the same
        "park it, the next real event claims it" shape ``_handle_deck_message``
        already uses for game 1's own deck. Never fires for game 1: Arena's
        ``connectResp.deckMessage`` already covers that one.
        """
        if not isinstance(deck, dict):
            return
        maindeck = [int(g) for g in deck.get("deckCards") or []]
        if not maindeck:
            return
        self._pending_sideboard_deck = {
            "maindeck": sorted(maindeck),
            "sideboard": sorted(int(g) for g in deck.get("sideboardCards") or []),
        }

    def _handle_deck_message(self, deck: dict[str, Any]) -> None:
        """connectResp.deckMessage is only ever sent to us, so it is our deck.

        It arrives on connecting to the game room, which is *before* the
        matchGameRoomStateChangedEvent that creates the match. So park it: the
        match-start handler claims it. If a match happens to be active already
        (reconnect mid-match), attach directly as well.
        """
        maindeck = [int(g) for g in deck.get("deckCards") or []]
        if not maindeck:
            return
        deck_id, _ = deck_identity(maindeck)
        cards = {
            "maindeck": sorted(maindeck),
            "sideboard": sorted(int(g) for g in deck.get("sideboardCards") or []),
        }
        self._pending_deck = (deck_id, cards)
        if self._active is not None:
            self._active.deck_id, self._active.deck_cards = deck_id, cards

    def _handle_game_over(self, state: MatchState, info: dict[str, Any]) -> None:
        if info.get("stage") != "GameStage_GameOver":
            return
        # Trap 1: the same GameOver is re-emitted with MatchState_MatchComplete.
        if info.get("matchState") != "MatchState_GameComplete":
            return
        number = info.get("gameNumber")
        if number is None:
            self._warn(f"GameOver without gameNumber in match {state.match_id}")
            return
        game = state.game(number)
        # Trap 2: results is cumulative across the match. _game_result_entry
        # (projector/live_state.py) already gets this right and is reused
        # rather than re-implemented: None when results is empty, or shorter
        # than gameNumber (a game whose results simply haven't arrived yet),
        # never a guess by falling back to some other game's entry.
        entry = _game_result_entry(info, number)
        if entry is None:
            self._warn(
                f"GameOver results missing an entry for game {number} in match {state.match_id}"
            )
            return
        game.result = _outcome(entry.get("winningTeamId"), state.self_team)
        game.result_reason = entry.get("reason")
        game.tracker.finalize_current()




def has_match_boundary(conn: sqlite3.Connection, *, after_event_id: int) -> bool:
    """True when raw events newer than ``after_event_id`` include a match
    room opening — the one boundary worth a rebuild on sight rather than on
    the next slow-cadence tick (``live.py``). It is what puts a deck on the
    Current match tab, and the mulligan decision that read informs arrives
    about eleven seconds later (measured on real captures) — comfortably
    inside a poll tick, but not inside the up-to-``project_every``-second
    wait for the next scheduled rebuild.
    """
    row = conn.execute(
        "SELECT 1 FROM raw_events WHERE id > ? AND label = 'MatchGameRoomStateChangedEvent' "
        "AND payload LIKE ? LIMIT 1",
        (after_event_id, f"%{MATCH_ROOM_PLAYING_MARKER}%"),
    ).fetchone()
    return row is not None


def _first_request_occurrences(
    conn: sqlite3.Connection,
) -> tuple[dict[str, int], dict[str, str]]:
    """Map each Arena request's own payload ``id`` (a client-generated UUID,
    unique per request and echoed in the response's ``<== Method(<id>)``) to
    the ``raw_events.id`` of its *first* replayed row, plus the earliest
    non-``NULL`` ``logged_at`` among all rows sharing that request id.

    Exists because a poll boundary used to make one real request hash to two
    different digests — a ``logged_at``-``NULL`` row from the poll that saw
    it first, and a fully-timestamped twin from the whole-file read that saw
    it again later (``docs/architecture.md``'s Idempotency section; fixed
    going forward by migration 042, but the old rows are append-only and
    stay). The twin is inserted *after* its own header timestamp would have
    placed it, so replaying ``raw_events`` in ``id`` order — the order every
    other rule in this module depends on — plays it out of order relative to
    the request it duplicates. ``project()``'s main loop uses this map to
    skip every occurrence but the first and, when that first occurrence
    itself has no timestamp, to borrow the twin's.

    ``json_valid(payload)`` guards ``json_extract`` in the same query: a
    malformed payload must not abort this pass, and the main replay loop
    already warns about it on its own pass over every row (not just
    requests).
    """
    first_id: dict[str, int] = {}
    first_logged_at: dict[str, str] = {}
    for row in conn.execute(
        """
        SELECT id, logged_at, json_extract(payload, '$.id') AS request_id
          FROM raw_events
         WHERE source = 'arena' AND kind = 'request' AND json_valid(payload)
         ORDER BY id
        """
    ):
        request_id = row["request_id"]
        if not isinstance(request_id, str):
            continue
        if request_id not in first_id:
            first_id[request_id] = row["id"]
        if request_id not in first_logged_at and row["logged_at"] is not None:
            first_logged_at[request_id] = row["logged_at"]
    return first_id, first_logged_at


def project(conn: sqlite3.Connection) -> dict[str, int]:
    """Rebuild ``decks``/``matches``/``games`` from ``raw_events``.

    Always a full rebuild — see module docstring; there is no incremental
    mode to opt into.

    Requests replayed here are additionally deduplicated by their own payload
    ``id`` (see ``_first_request_occurrences``): a fixed reader bug (migration
    042) still left old databases holding, for some requests, an earlier
    ``logged_at``-``NULL`` row and a later fully-timestamped twin, inserted
    out of order relative to each other. The *first* twin in ``raw_events.id``
    order wins — that is replay order, the order every other rule here
    depends on, and the order the out-of-order twin would otherwise violate
    (e.g. a stale deck name from a twin replayed after the request that
    should have won). This is retroactive with no re-ingest needed: it reads
    straight off rows already in ``raw_events``, the same append-only table
    every other rebuild reads.
    """
    projector = Projector()
    # See _first_request_occurrences' own docstring for why this pre-pass
    # exists: an old request-dedup gap left twin rows in raw_events that
    # migration 042 stops from recurring but cannot retroactively remove.
    first_request_id, first_request_logged_at = _first_request_occurrences(conn)
    duplicate_requests = 0
    for row in conn.execute(
        "SELECT id, kind, label, payload, logged_at FROM raw_events "
        "WHERE source = 'arena' ORDER BY id"
    ):
        try:
            payload = orjson.loads(row["payload"])
        except ValueError:  # orjson.JSONDecodeError, a ValueError subclass
            projector._warn(f"unparseable payload in raw_events (id={row['id']})")
            continue

        logged_at = row["logged_at"]
        if row["kind"] == "request" and isinstance(payload, dict):
            request_id = payload.get("id")
            if isinstance(request_id, str) and request_id in first_request_id:
                if first_request_id[request_id] != row["id"]:
                    # A later twin of a request already replayed under this
                    # id — skip it rather than replay
                    # it a second time out of order (see
                    # _first_request_occurrences).
                    duplicate_requests += 1
                    continue
                if logged_at is None:
                    # Not a guess (rule 4): the same request's own header
                    # timestamp, read from the twin the poll boundary split
                    # off, not a fabricated one.
                    logged_at = first_request_logged_at.get(request_id)

        projector.feed_parsed(row["kind"], row["label"], payload, logged_at)
    projector.finish()

    conn.execute("BEGIN")
    try:
        # Children before parents, for the foreign keys. Absent on purpose:
        # `cards` and `archetypes` are downloaded reference data, and
        # `opponent_deck_override` is the user's own words — none of these is
        # something this projection could rebuild.
        conn.execute("DELETE FROM card_events")
        conn.execute("DELETE FROM turn_zones")
        conn.execute("DELETE FROM combat_attacks")
        conn.execute("DELETE FROM combat_blocks")
        conn.execute("DELETE FROM damage_events")
        conn.execute("DELETE FROM life_events")
        conn.execute("DELETE FROM opponent_archetype")
        conn.execute("DELETE FROM turns")        # FK -> games: must go first
        conn.execute("DELETE FROM game_decks")   # FK -> matches: must go first
        conn.execute("DELETE FROM games")
        conn.execute("DELETE FROM matches")
        conn.execute("DELETE FROM deck_guids")
        conn.execute("DELETE FROM decks")
        conn.execute("DELETE FROM rank_snapshot")

        conn.executemany(
            """
            INSERT INTO rank_snapshot
                 (observed_at, constructed_class, constructed_level, constructed_step,
                  constructed_season, constructed_matches_won, constructed_matches_lost)
                 VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            projector.rank_observations,
        )

        counts = {
            "decks": 0, "matches": 0, "games": 0, "turns": 0, "turn_zones": 0,
            "card_events": 0, "deck_guids": 0, "combat_attacks": 0,
            "combat_blocks": 0, "damage_events": 0, "life_events": 0,
            "game_decks": 0,
            "rank_observations": len(projector.rank_observations),
            "warnings": projector.warnings,
            # Old poll-boundary twins skipped this run — see
            # _first_request_occurrences. Zero on a database ingested
            # entirely under migration 042's fix.
            "duplicate_requests": duplicate_requests,
        }
        seen_decks: set[str] = set()
        unmapped_event_ids: set[str] = set()

        for state in projector.matches.values():
            if state.deck_id and state.deck_id not in seen_decks:
                seen_decks.add(state.deck_id)
                conn.execute(
                    """
                    INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen)
                         VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (deck_id) DO UPDATE SET
                         last_seen = MAX(COALESCE(excluded.last_seen, ''), COALESCE(last_seen, '')),
                         name = COALESCE(excluded.name, name)
                    """,
                    (
                        state.deck_id,
                        projector.deck_names.get(state.deck_id),
                        projector.deck_formats.get(state.deck_id),
                        json.dumps(state.deck_cards or {}),
                        state.started_at,
                        state.ended_at or state.started_at,
                    ),
                )
                counts["decks"] += 1

            games = sorted(state.games.values(), key=lambda g: g.game_number)
            won = sum(1 for g in games if g.result == WIN)
            lost = sum(1 for g in games if g.result == LOSS)
            deck_format = projector.deck_formats.get(state.deck_id) if state.deck_id else None
            match_format = arena_format(deck_format, state.event_id)
            if (
                match_format is None
                and state.event_id
                and not any(w in state.event_id.lower() for w in _NOT_CONSTRUCTED_STANDARD)
                and not any(w in (deck_format or "").lower() for w in _NOT_CONSTRUCTED_STANDARD)
                and state.event_id not in unmapped_event_ids
            ):
                # Limited and Arena-only queues are NULL by design (D8); only an
                # event id that looks constructed and still maps to nothing is
                # news, and once per id rather than once per match.
                unmapped_event_ids.add(state.event_id)
                log.warning("no format for constructed event id %r", state.event_id)
                counts["warnings"] += 1
            conn.execute(
                """
                INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat,
                                     opponent_user_id, opponent_name, started_at, ended_at,
                                     result, games_won, games_lost, completed_reason, format)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.match_id, state.event_id, state.deck_id, state.self_seat,
                    state.opponent_seat, state.opponent_user_id, state.opponent_name,
                    state.started_at, state.ended_at, state.result, won, lost,
                    state.completed_reason, match_format,
                ),
            )
            counts["matches"] += 1

            for game_number, cards in state.submitted_decks.items():
                conn.execute(
                    """
                    INSERT INTO game_decks
                         (match_id, game_number, deck_cards_json, sideboard_cards_json)
                         VALUES (?, ?, ?, ?)
                    """,
                    (
                        state.match_id, game_number,
                        json.dumps(cards["maindeck"]),
                        json.dumps(cards["sideboard"]),
                    ),
                )
                counts["game_decks"] += 1

            for game in games:
                conn.execute(
                    """
                    INSERT INTO games (match_id, game_number, on_play, result, result_reason,
                                       turn_count, self_mulligans, opp_mulligans)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.match_id, game.game_number,
                        None if game.on_play is None else int(game.on_play),
                        game.result or INCOMPLETE, game.result_reason,
                        game.turn_count or None,
                        game.mulligans.get(state.self_seat),
                        game.mulligans.get(state.opponent_seat),
                    ),
                )
                counts["games"] += 1

                # Card events keep Arena's raw seat, so unlike turns they stay
                # meaningful without a resolved self seat: v_card_events maps
                # the seat, and reports NULL when it cannot.
                for event in game.tracker.card_events:
                    conn.execute(
                        """
                        INSERT INTO card_events (match_id, game_number, seq, turn_number,
                                                 seat, grp_id, category, zone_src, zone_dest)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            state.match_id, game.game_number, event.seq, event.turn_number,
                            event.seat, event.grp_id, event.category,
                            event.zone_src, event.zone_dest,
                        ),
                    )
                    counts["card_events"] += 1

                # Combat and damage keep Arena's raw seat too, same reason as
                # card_events: meaningful even without a resolved self seat.
                for atk in game.tracker.attacks:
                    conn.execute(
                        """
                        INSERT INTO combat_attacks (match_id, game_number, turn_number,
                                                    attacker_seat, instance_id, grp_id,
                                                    target_id, blocked)
                             VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                        """,
                        (
                            state.match_id, game.game_number, atk.turn_number,
                            atk.seat, atk.instance_id, atk.grp_id, atk.target_id,
                        ),
                    )
                    counts["combat_attacks"] += 1

                for blk in game.tracker.blocks:
                    conn.execute(
                        """
                        INSERT INTO combat_blocks (match_id, game_number, turn_number,
                                                   blocker_seat, blocker_instance_id,
                                                   blocker_grp_id, attacker_instance_id)
                             VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            state.match_id, game.game_number, blk.turn_number,
                            blk.seat, blk.blocker_instance_id, blk.blocker_grp_id,
                            blk.attacker_instance_id,
                        ),
                    )
                    counts["combat_blocks"] += 1
                    # An attacker with an observed block is no longer
                    # "unknown whether blocked" (rule 4) — see
                    # migrations/014_combat.sql for why the reverse (marking
                    # an attack unblocked on the absence of a block row) is
                    # not done.
                    conn.execute(
                        """
                        UPDATE combat_attacks SET blocked = 1
                         WHERE match_id = ? AND game_number = ? AND turn_number = ?
                               AND instance_id = ?
                        """,
                        (state.match_id, game.game_number, blk.turn_number,
                         blk.attacker_instance_id),
                    )

                for dmg in game.tracker.damage_events:
                    conn.execute(
                        """
                        INSERT INTO damage_events (match_id, game_number, annotation_id,
                                                   turn_number, source_instance_id,
                                                   source_grp_id, source_seat,
                                                   target_instance_id, target_grp_id,
                                                   target_seat, amount, damage_type)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            state.match_id, game.game_number, dmg.annotation_id,
                            dmg.turn_number, dmg.source_instance_id, dmg.source_grp_id,
                            dmg.source_seat, dmg.target_instance_id, dmg.target_grp_id,
                            dmg.target_seat, dmg.amount, dmg.damage_type,
                        ),
                    )
                    counts["damage_events"] += 1

                for life in game.tracker.life_events:
                    conn.execute(
                        """
                        INSERT INTO life_events (match_id, game_number, annotation_id,
                                                 turn_number, seat, delta,
                                                 affector_instance_id, affector_grp_id)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            state.match_id, game.game_number, life.annotation_id,
                            life.turn_number, life.seat, life.delta,
                            life.affector_instance_id, life.affector_grp_id,
                        ),
                    )
                    counts["life_events"] += 1

                # Zone contents keep Arena's raw seat too, for the same reason
                # card_events does: a truncated session without a resolved
                # self seat still gets meaningful per-turn board state, even
                # though the turns row it would otherwise sit beside is absent.
                for turn in game.tracker.turns.values():
                    for zc in turn.cards:
                        conn.execute(
                            """
                            INSERT INTO turn_zones (match_id, game_number, turn_number, seat,
                                                    zone, idx, instance_id, grp_id, card_types,
                                                    drawn_on_turn,
                                                    is_tapped, power, toughness)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                state.match_id, game.game_number, turn.turn_number, zc.seat,
                                zc.zone, zc.idx, zc.instance_id, zc.grp_id, zc.card_types,
                                zc.drawn_on_turn,
                                zc.is_tapped, zc.power, zc.toughness,
                            ),
                        )
                        counts["turn_zones"] += 1

                # self/opp columns would be meaningless without a resolved self
                # seat, so an unresolved match (already warned about above) gets
                # no turns rows rather than nulls masquerading as data.
                if state.self_seat is None:
                    continue
                for turn in sorted(game.tracker.turns.values(), key=lambda t: t.turn_number):
                    conn.execute(
                        """
                        INSERT INTO turns (match_id, game_number, turn_number, active_seat,
                                           self_life, opp_life, self_hand, opp_hand,
                                           self_lands, self_permanents, opp_permanents,
                                           self_library, opp_library,
                                           self_graveyard, opp_graveyard,
                                           self_open_mana, opp_open_mana)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            state.match_id, game.game_number, turn.turn_number, turn.active_seat,
                            turn.life.get(state.self_seat), turn.life.get(state.opponent_seat),
                            turn.hand.get(state.self_seat), turn.hand.get(state.opponent_seat),
                            turn.lands.get(state.self_seat),
                            turn.permanents.get(state.self_seat),
                            turn.permanents.get(state.opponent_seat),
                            turn.library.get(state.self_seat),
                            turn.library.get(state.opponent_seat),
                            turn.graveyard.get(state.self_seat),
                            turn.graveyard.get(state.opponent_seat),
                            turn.open_mana.get(state.self_seat),
                            turn.open_mana.get(state.opponent_seat),
                        ),
                    )
                    counts["turns"] += 1

        # Only for Arena decks that were actually played: until the MTGO decks
        # are written below, `decks` holds played Arena decks alone, and this
        # table points at it.
        for deck_id, guids in projector.deck_guids.items():
            if deck_id not in seen_decks:
                continue
            for arena_deck_id, (version, fmt, last_seen) in guids.items():
                conn.execute(
                    """
                    INSERT INTO deck_guids (deck_id, arena_deck_id, version, format, last_seen)
                         VALUES (?, ?, ?, ?, ?)
                    """,
                    (deck_id, arena_deck_id, version, fmt, last_seen),
                )
                counts["deck_guids"] += 1

        # MTGO: a second source, same tables, same full-rebuild pass, entirely
        # independent of the Arena replay above (which is itself scoped to
        # source='arena' at its own SELECT). Runs inside this same transaction
        # rather than opening its own — see projector/mtgo/project.py's
        # module docstring.
        mtgo_counts = project_mtgo(conn, mtgo_load_handle())
        for key in ("matches", "games", "card_events"):
            counts[key] += mtgo_counts[key]
        counts["warnings"] += mtgo_counts["warnings"]

        # MTGO's exported deck files, into the same `decks` table and the same
        # transaction. Not tied to any match: `matches.deck_id` stays NULL for
        # MTGO — see projector/mtgo/decks.py.
        deck_counts = project_mtgo_decks(conn)
        counts["decks"] += deck_counts["decks"]
        counts["warnings"] += deck_counts["warnings"]

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return counts
