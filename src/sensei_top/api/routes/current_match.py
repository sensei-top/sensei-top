"""The current-match reads: the match in progress, the live matchup brief,
and the opening-hand/keep/opponent-hand/library reads that replaced board
math, play-around and the scoreboard (``sensei_top.table``,
``docs/current-match.md``).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request

from sensei_top.api.convert import (
    _hand_read_out,
    _intermission_out,
    _keep_guide_out,
    _matchup_brief_out,
    _opening_hand_out,
)
from sensei_top.api.deps import Conn
from sensei_top.api.models.common import MatchupBriefResponse
from sensei_top.api.models.current_match import (
    CurrentGame,
    CurrentMatch,
    CurrentMatchRead,
    HandReadOut,
    LibraryCardOut,
)
from sensei_top.api.sql import (
    _attach_zones,
    _cached_break_read,
    _cached_consensus,
    _cached_mana_source_grp_ids,
    _cached_match_opponent,
    _rows,
    match_format,
)
from sensei_top.brief import narrative as brief_narrative
from sensei_top.brief.store import is_stale, list_hash, read_brief
from sensei_top.guide.deck import identity_format, list_identities
from sensei_top.table.hand_read import build_hand_read
from sensei_top.table.keep import build_keep_guide
from sensei_top.table.live import build_library_remaining, build_live_state
from sensei_top.table.opening_hand import build_opening_hand_read
from sensei_top.table.ranked import is_ranked

router = APIRouter()


def _brief_response(
    conn: Conn, request: Request, match_id: str, deck_id: str
) -> MatchupBriefResponse:
    """The body of ``GET /api/current-match/brief``, extracted so the route
    below stays a thin dispatch. Not shared with ``current_match_read``'s own
    ``intermission`` field: that field is built from a name set that pools
    the live replay's own revealed zones with ``card_events`` (S4's
    ``table/intermission.py``), which can know more about the opponent mid-
    break than this route's ``_cached_match_opponent`` (a projection-only
    read) does — sharing this function there would silently cap the break
    read's opponent knowledge at whatever ``project()`` last saw.
    """
    identity = next((i for i in list_identities(conn) if deck_id in i.deck_ids), None)
    if identity is None:
        return MatchupBriefResponse(status="no_match")
    no_format = identity_format(conn, identity) is None
    opp_row = _cached_match_opponent(request, conn, match_id)
    opponent_key = opp_row["opponent_key"] if opp_row else None
    if not opponent_key or not opponent_key.startswith("archetype:"):
        # Before ``unclassified``: the classifier never names an opponent in
        # a match with no format, so "unclassified" would promise a read that
        # never comes.
        return MatchupBriefResponse(
            status="format_unknown" if no_format else "unclassified"
        )
    archetype_key = opponent_key.removeprefix("archetype:")
    archetype_label = opp_row["opponent_label"]

    if no_format:
        # A brief stored while the deck had a format is still the user's:
        # returned first, with no prompt (none can be built without a
        # format). Only when nothing is stored is the format the answer.
        stored = read_brief(conn, identity.key, archetype_key)
        if stored is None:
            return MatchupBriefResponse(status="format_unknown")
        return MatchupBriefResponse(
            status="ok", brief=_matchup_brief_out(stored),
            deck_key=identity.key, archetype_key=archetype_key,
            stale=is_stale(
                conn, stored, current_list_hash=list_hash(identity.current_cards)
            ),
        )

    built = brief_narrative.full_prompt(conn, identity, archetype_key, archetype_label)
    if built is None:
        # No field consensus for this archetype: there is nothing to
        # anchor a brief to, and saying so is more honest than offering
        # a prompt that would be written from nothing.
        return MatchupBriefResponse(status="no_consensus")
    prompt = built[0]

    brief = read_brief(conn, identity.key, archetype_key)
    if brief is None:
        return MatchupBriefResponse(
            status="prompt", prompt=prompt,
            deck_key=identity.key, archetype_key=archetype_key,
        )

    return MatchupBriefResponse(
        status="ok", brief=_matchup_brief_out(brief), prompt=prompt,
        deck_key=identity.key, archetype_key=archetype_key,
        stale=is_stale(
            conn, brief, current_list_hash=list_hash(identity.current_cards)
        ),
    )


@router.get("/api/current-match", response_model=CurrentMatch | None, tags=["matches"])
def current_match(request: Request, conn: Conn) -> CurrentMatch | None:
    """The match in progress, or null when nothing is being played.

    Null rather than a 404: "no game right now" is an ordinary answer, not
    a missing resource, and the dashboard shows it as an empty state.

    Composing the five reads here is not aggregation — each is a thin
    select, and nothing is counted or averaged in Python. The opponent
    fields come from ``_cached_match_opponent`` rather than a joined
    ``v_match_opponent`` here: that view's own CTE can't push a
    ``match_id`` filter down, so joining it costs the same as scanning
    every match's opponent-card history regardless of the join predicate.
    """
    match = conn.execute(
        """
        SELECT m.match_id, m.event_id, m.deck_id, d.name AS deck_name, m.opponent_name,
               m.started_at, m.games_won, m.games_lost, m.source
          FROM v_current_match m
          LEFT JOIN decks d ON d.deck_id = m.deck_id
        """
    ).fetchone()
    if match is None:
        return None

    match_id = match["match_id"]
    opponent = _cached_match_opponent(request, conn, match_id)
    match_fields = dict(match)
    match_fields["opponent_label"] = opponent["opponent_label"] if opponent else None
    match_fields["opponent_source"] = opponent["opponent_source"] if opponent else None
    match_fields["opponent_confidence"] = opponent["opponent_confidence"] if opponent else None
    match_fields["opponent_cards_seen"] = opponent["opponent_cards_seen"] if opponent else 0
    match_fields["opponent_colors"] = opponent["opponent_colors"] if opponent else None
    signature_json = opponent["opponent_signature_cards"] if opponent else None
    match_fields["opponent_signature_cards"] = (
        json.loads(signature_json) if signature_json else []
    )

    game = conn.execute(
        """
        SELECT game_number, on_play, self_mulligans, opp_mulligans, turn_count
          FROM games WHERE match_id = ? ORDER BY game_number DESC LIMIT 1
        """,
        (match_id,),
    ).fetchone()
    if game is None:
        # The room opened but no game state arrived yet — real for a second
        # or two at match start, and the dashboard renders it as such.
        return CurrentMatch(**match_fields, game=None, turns=[], cards=[])

    key = (match_id, game["game_number"])
    turns = _rows(
        conn,
        """
        SELECT turn_number, active_seat, self_life, opp_life, self_hand, opp_hand,
               self_lands, self_permanents, opp_permanents, self_library, opp_library,
               self_graveyard, opp_graveyard, self_open_mana, opp_open_mana
          FROM turns WHERE match_id = ? AND game_number = ? ORDER BY turn_number
        """,
        key,
    )
    cards = _rows(
        conn,
        """
        SELECT seq, turn_number, category, zone_src, zone_dest, grp_id, card_name, is_self
          FROM v_card_events WHERE match_id = ? AND game_number = ? ORDER BY seq
        """,
        key,
    )
    _attach_zones(conn, match_id, game["game_number"], turns)
    return CurrentMatch(
        **match_fields,
        game=CurrentGame(**dict(game)),
        turns=turns,
        cards=cards,
    )


@router.get("/api/current-match/brief", response_model=MatchupBriefResponse, tags=["matches"])
def current_match_brief(request: Request, conn: Conn) -> MatchupBriefResponse:
    """The stored matchup brief for the match in progress, and the prompt
    to write one from — except an ``ok`` with no format, which has none (a
    prompt needs a format to name its corpus). See ``brief/__init__.py`` and
    ``docs/brief.md``.

    Deliberately has no generate route of its own, unlike the match
    report and the deck guide (``docs/llm.md``): a brief is written by
    ``sensei-top brief --import``, or — far more often — filled as a
    side effect of generating or importing a full deck guide
    (``POST /api/guide/{key}/narrative``, ``brief/from_guide.py``).
    """
    match_row = conn.execute("SELECT match_id, deck_id FROM v_current_match").fetchone()
    if match_row is None or match_row["deck_id"] is None:
        return MatchupBriefResponse(status="no_match")
    return _brief_response(conn, request, match_row["match_id"], match_row["deck_id"])


@router.get("/api/current-match/read", response_model=CurrentMatchRead, tags=["matches"])
def current_match_read(request: Request, conn: Conn) -> CurrentMatchRead:
    """The opening-hand read, keep guide, opponent-hand read and our own
    remaining library for the match in progress — the reads that
    replaced board math, play-around and the scoreboard (see
    ``sensei_top.table``).

    One route for all of it: they share the same current match, and the
    tab refetches on every heartbeat, so several round trips per beat
    for one screen would be waste. It also means one live replay of
    ``raw_events`` (``table/live.py``), not three: ``live_state`` below
    is built once and its ``offer``/board-state pieces are handed to
    ``build_opening_hand_read``/``build_hand_read`` instead of letting
    each replay independently — the difference between one pass over
    the current match's events per request and up to three.

    ``opening_hand`` is built from that same replay and returned even
    when ``v_current_match`` finds nothing: it does not wait on
    ``project()`` at all, because the mulligan decision it informs has a
    measured 5-second median in real play and a full rebuild cannot
    land in that window (``projector/live_state.py``'s module docstring
    has the numbers). `deck_id` enriches it with this deck's land band and
    mulligan record — and comes from ``live_state.deck_id`` itself (the
    replay's own ``connectResp.deckMessage``) rather than ``v_current_match``
    whenever the replay resolved one, so the very first mulligan of a match
    can carry a land band before ``project()`` has ever written a ``matches``
    row for it.

    ``v_current_match`` is Arena-only now
    (``migrations/040_arena_only_current_match.sql``), so ``source`` is
    always ``'arena'`` whenever a match row exists — ``build_live_state``
    runs unconditionally rather than branching on it. MTGO is still stored
    and projected (History/Matchups keep working), just never surfaced
    here: its transcript never writes the
    ``MatchGameRoomStateChangedEvent``/``GreToClientEvent`` stream
    ``table/live.py``'s replay depends on, so a ``LiveState`` for an MTGO
    match would have replayed stale Arena rows (or found none at all) —
    worse than not building one, which is exactly the bug that migration
    closed by keeping MTGO off this view in the first place.
    """
    match_row = conn.execute(
        "SELECT match_id, deck_id, source, event_id FROM v_current_match"
    ).fetchone()
    # Defaulting to 'arena' with no match row preserves today's behaviour:
    # the opening-hand read below deliberately runs before any projected
    # match exists, and nothing about that changes for the no-match case.
    # (v_current_match is Arena-only, so a match row's own source is always
    # 'arena' too — this default only covers the no-match-yet case.)
    source = match_row["source"] if match_row is not None else "arena"

    live_state = build_live_state(
        conn, mana_source_grp_ids=_cached_mana_source_grp_ids(request, conn)
    )

    # The deck comes from the live replay when it has one.
    # connectResp.deckMessage resolves inside the same raw_events window
    # everything else in live_state comes from, so it can carry a deck_id
    # before project() has ever written a matches row for this match — the
    # exact gap that left the very first mulligan of a match without a land
    # band. Only falls back to v_current_match's own projected deck_id when
    # the replay found no connectResp at all (older data, or a lookback gap
    # wider than table/live.py's own margin) — never the reverse, so a
    # stale decks.deck_id can't override a fresher one the replay resolved.
    live_deck_id = live_state.deck_id if live_state is not None else None
    deck_id = (
        live_deck_id
        if live_deck_id is not None
        else (match_row["deck_id"] if match_row is not None else None)
    )
    maindeck = live_state.deck_maindeck if live_state is not None else None

    # The queue the same way: the replay's own room-start event first, so
    # the rule holds at the first mulligan, before project() has written a
    # matches row; the projected event_id only when the replay found none.
    # Neither means unknown, and unknown is ranked (table/ranked.py).
    event_id = live_state.event_id if live_state is not None else None
    if event_id is None and match_row is not None:
        event_id = match_row["event_id"]
    ranked = is_ranked(event_id)

    opening_hand = build_opening_hand_read(
        conn,
        deck_id=deck_id,
        offer=live_state.offer if live_state is not None else None,
        maindeck=maindeck,
        boarded=live_state.deck_boarded if live_state is not None else False,
    )
    opening_hand_out = _opening_hand_out(opening_hand) if opening_hand is not None else None

    if match_row is None:
        return CurrentMatchRead(
            status="no_match", opening_hand=opening_hand_out, source=source,
            ranked=ranked, advice=not ranked,
        )

    match_id = match_row["match_id"]

    # build_opening_hand_read above already built this KeepGuide from the
    # same deck_id (and maindeck) when it had one to build from (opening_hand
    # not None and deck_id not None) — reuse it rather than re-running
    # list_identities (~40 queries) and the mulligan aggregate a second time
    # on every 1 Hz poll. Only fall back to a fresh build when opening_hand
    # didn't build one at all (no mulligan offer pending, or no deck_id yet).
    if opening_hand is not None and deck_id is not None:
        keep = opening_hand.keep_guide
    else:
        keep = build_keep_guide(
            conn,
            deck_id,
            maindeck=maindeck,
            boarded=live_state.deck_boarded if live_state is not None else False,
        )
    keep_out = _keep_guide_out(keep)

    game_row = conn.execute(
        "SELECT game_number FROM games WHERE match_id = ? ORDER BY game_number DESC LIMIT 1",
        (match_id,),
    ).fetchone()

    hand_out: HandReadOut | None = None
    if game_row is not None:
        opp_row = _cached_match_opponent(request, conn, match_id)
        opponent_key = opp_row["opponent_key"] if opp_row else None
        archetype_label = opp_row["opponent_label"] if opp_row else None
        fmt = match_format(conn, match_id)
        consensus = _cached_consensus(request, conn, opponent_key, fmt)
        hand = build_hand_read(
            conn,
            match_id,
            game_row["game_number"],
            opponent_key=opponent_key,
            archetype_label=archetype_label,
            consensus=consensus,
            fmt=fmt,
            live=live_state,
        )
        hand_out = _hand_read_out(hand)

    library_out = [
        LibraryCardOut(
            grp_id=c.grp_id,
            name=c.name,
            mana_cost=c.mana_cost,
            mana_value=c.mana_value,
            type_line=c.type_line,
            is_land=c.is_land,
            quantity=c.quantity,
            left=c.left,
            is_interaction=c.is_interaction,
        )
        for c in build_library_remaining(conn, deck_id, live_state)
    ]
    library_count = (
        live_state.library.get(live_state.self_seat)
        if live_state is not None and live_state.self_seat is not None
        else None
    )

    # S5: only built when live_state.intermission is set — costs nothing
    # during a game, since _cached_break_read returns None immediately for
    # any other live_state (see api/sql.py's own docstring).
    break_read = _cached_break_read(request, conn, match_id, deck_id, live_state)
    intermission_out = _intermission_out(break_read) if break_read is not None else None

    return CurrentMatchRead(
        status="ok",
        opening_hand=opening_hand_out,
        keep=keep_out,
        hand=hand_out,
        library=library_out,
        library_count=library_count,
        source=source,
        intermission=intermission_out,
        # Between games the sideboard plan shows in every queue: a written
        # plan read between games is accepted practice, live prompting
        # during one is not (table/ranked.py).
        ranked=ranked,
        advice=not ranked or intermission_out is not None,
    )
