"""Tests for projector/live_state.py's LiveState.intermission — the Bo3
break tracked while replaying, per docs/arena-log.md's trap 11c.

Ground truth comes from tests/fixtures/intermission_session.log (44 raw
events), carved from raw_events, same legitimate-carve precedent as
combat_session.log/mulligan_session.log. Facts below were read directly
from the fixture via fixture_peek.py's ``show`` (entries 34, 35, 40, 41, 42),
never by running replay_live_state and copying its output (AGENTS.md rule
8):

  entry 34 (17:04:25, the last GRE event before game 1 ends) — no
  ``gameInfo`` on either of its gameStateMessages, just ``players[]``
  restating life/turnNumber/teamId (seat 1 -> teamId 1, seat 2 -> teamId 2).

  entry 35 (17:04:34, "GameComplete + IntermissionReq") — the first
  message's ``gameStateMessage.gameInfo`` reads ``matchID
  fd2d98d2-eac6-459a-8b44-cb1a4eb057dd``, ``gameNumber: 1``,
  ``matchState: MatchState_GameComplete``,
  ``matchWinCondition: MatchWinCondition_Best2of3``,
  ``results: [{scope: MatchScope_Game, winningTeamId: 1,
  reason: ResultReason_Concede}]``. Its own ``players[]`` again gives
  our seat (1) teamId 1, so this is a game *we* won (the opponent's
  concede) — winningTeamId 1 == our own team.

  entry 40 (17:05:01, "SubmitDeckConfirmation") — its one GRE message is a
  bare ``{type: GREMessageType_SubmitDeckConfirmation, systemSeatIds,
  msgId, gameStateId}`` with no ``gameStateMessage`` key at all, so nothing
  in it can touch ``intermission`` either way — the break is not over
  (trap 11c).

  entry 41 (17:05:15, game 2's first state) — ``gameInfo`` reads
  ``gameNumber: 2``, ``stage: GameStage_Start``,
  ``matchState: MatchState_GameInProgress`` (not itself a completion
  message, but its gameNumber of 2 is higher than the ended game's 1).

  entry 42 (17:07:09, the match-final event) — two gameStateMessages in
  one event: the first has ``gameInfo.gameNumber: 2``,
  ``matchState: MatchState_GameComplete`` (results now carry two
  MatchScope_Game entries, both winningTeamId 1 — game 2 also went to
  our team); the second has the *same* gameNumber but
  ``matchState: MatchState_MatchComplete``, per trap 1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sensei_top.api.convert import _intermission_out
from sensei_top.api.sql import _cached_break_read
from sensei_top.archetypes.corpus import MIN_CORPUS_DECKS
from sensei_top.brief.store import Brief, write_brief
from sensei_top.db import open_database
from sensei_top.guide.deck import list_identities
from sensei_top.projector.live_state import Intermission, LiveState, replay_live_state
from sensei_top.reader.ingest import ingest_file
from sensei_top.table.intermission import build_break_read

FIXTURE = Path(__file__).parent / "fixtures" / "intermission_session.log"


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    ingest_file(c, FIXTURE, locale_hint="mdy")
    c.commit()
    yield c
    c.close()


def _payloads_through(conn, entry: int) -> list[str]:
    """Payload text for fixture entries 0..``entry`` inclusive.

    ``ingest_file`` inserts one ``raw_events`` row per segmenter entry, in
    file order, into an empty table — so on this fixture (no pre-existing
    rows, no digest collisions) ``raw_events.id`` is exactly the fixture's
    0-based entry index plus one. Verified against test_table_opening_hand.py's
    own comment ("the fixture's 8th raw event" for its entry 7), the same
    convention this file reuses rather than re-deriving.
    """
    cutoff = entry + 1
    rows = conn.execute(
        "SELECT payload FROM raw_events WHERE id <= ? ORDER BY id", (cutoff,)
    ).fetchall()
    return [row["payload"] for row in rows]


def test_mid_game_has_no_intermission(conn):
    state = replay_live_state(_payloads_through(conn, 34))
    assert state.intermission is None


def test_game_over_sets_intermission_with_won_and_reason(conn):
    state = replay_live_state(_payloads_through(conn, 35))
    assert state.self_seat == 1
    assert state.intermission is not None
    assert state.intermission.game_number == 1
    assert state.intermission.won is True  # our team (1) == winningTeamId (1)
    assert state.intermission.reason == "ResultReason_Concede"


def test_game_over_keeps_finished_games_zones_during_the_break(conn):
    """The board state stays as game 1 left it until game 2's first state
    message arrives (docs/arena-log.md trap 11c) — proven, not assumed: the
    opponent's own revealed (non-hand) cards from game 1 must still be in
    zone_cards at this cut point."""
    def revealed(state):
        return sorted(
            (c.zone, c.grp_id)
            for c in state.zone_cards
            if c.seat == state.opponent_seat and c.zone != "hand" and c.grp_id is not None
        )

    at_game_over = revealed(replay_live_state(_payloads_through(conn, 35)))
    assert at_game_over, "expected at least one revealed opponent card at game over"
    # The two mid-break diffs (entries 37, 38) carry no zones, gameObjects or
    # diffDeletedInstanceIds, so the break must leave the board untouched
    # right up to our own deck submission.
    assert revealed(replay_live_state(_payloads_through(conn, 40))) == at_game_over


def test_submit_deck_confirmation_does_not_end_the_break(conn):
    """entry 40 is SubmitDeckConfirmation, a bare message with no gameInfo
    of its own — we are still waiting on the opponent's own submission
    (trap 11c), so the break must still be set, unchanged from game over."""
    state = replay_live_state(_payloads_through(conn, 40))
    assert state.intermission is not None
    assert state.intermission.game_number == 1
    assert state.intermission.won is True
    assert state.intermission.reason == "ResultReason_Concede"


def test_game_2_start_clears_the_intermission(conn):
    """entry 41's gameInfo (gameNumber 2, GameStage_Start) is the break's
    real end, per trap 11c — not SubmitDeckConfirmation."""
    state = replay_live_state(_payloads_through(conn, 41))
    assert state.intermission is None


def test_match_complete_clears_the_intermission(conn):
    """entry 42 carries GameComplete then MatchComplete in one event (trap
    1) — order matters, and it must end cleared even though the first of
    the two messages sets it for game 2."""
    state = replay_live_state(_payloads_through(conn, 42))
    assert state.intermission is None


def _gsm_payload(gsm: dict) -> str:
    return json.dumps({"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": gsm}]}})


def test_bo1_game_complete_never_sets_an_intermission():
    """Only MatchWinCondition_Best2of3 has a break to track — a
    single-elimination (Bo1) GameComplete must be left alone."""
    gsm = {
        "type": "GameStateType_Diff",
        "gameStateId": 1,
        "players": [
            {"systemSeatNumber": 1, "teamId": 1},
            {"systemSeatNumber": 2, "teamId": 2},
        ],
        "gameInfo": {
            "matchID": "bo1-match",
            "gameNumber": 1,
            "stage": "GameStage_GameOver",
            "matchState": "MatchState_GameComplete",
            "matchWinCondition": "MatchWinCondition_SingleElimination",
            "results": [
                {"scope": "MatchScope_Game", "winningTeamId": 1, "reason": "ResultReason_Concede"}
            ],
        },
    }
    state = replay_live_state([_gsm_payload(gsm)])
    assert state.intermission is None


# ---------------------------------------------------------------------------
# build_break_read (S4 steps 2-7): naming the opponent, finding a plan, and
# the past-boarding/caching reads around it. None of this has anything to do
# with Player.log parsing, so there is no fixture fact to derive these
# expectations from (AGENTS.md rule 8 names ``fixture_peek.py`` for exactly
# that reason — it doesn't apply here); instead these build a synthetic
# database directly and check the result against ``archetypes/classify.py``'s
# own documented scoring constants, the same precedent
# tests/test_guide_deck.py and tests/test_brief_store.py already use for
# guide/brief data that isn't log-shaped either. The ``conn`` fixture above
# still applies (it only adds raw_events rows; matches/decks/etc. stay empty
# until a test inserts into them).
# ---------------------------------------------------------------------------


def _insert_deck(conn, deck_id, *, name=None, fmt="Standard", cards=None):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, 't', 't')",
        (deck_id, name, fmt, json.dumps(cards or {"maindeck": [], "sideboard": []})),
    )


def _insert_match(conn, match_id, deck_id, result, started_at, *, event_id="Traditional_Ladder"):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, ?, ?, 1, 2, 'u', 'n', ?, ?, ?, 0, 0, 'r')",
        (match_id, event_id, deck_id, started_at, started_at, result),
    )


def _insert_override(conn, match_id, *, label, archetype_key=None):
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, archetype_key) VALUES (?, ?, ?)",
        (match_id, label, archetype_key),
    )


def _insert_fallback(conn, *, fmt, source, name, common_cards):
    """A ``kind='fallback'``, ``include_color=0`` archetype definition with
    no ``Conditions`` — required_colors() then returns an empty set for it
    (classify.py, read directly), so colour_factor() is always 1.0 and the
    fit/margin math below depends only on how many of ``common_cards`` are
    named in a test's revealed-cards list."""
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, "
        "fetched_at) VALUES (?, 'fallback', ?, ?, 0, ?, 't')",
        (fmt, source, name, json.dumps({"CommonCards": common_cards})),
    )


def _insert_cards(conn, names_by_grp_id: dict[int, str]):
    for grp_id, name in names_by_grp_id.items():
        conn.execute(
            "INSERT INTO cards (grp_id, name, type_line) VALUES (?, ?, ?)",
            (grp_id, name, "Creature — Human"),
        )


def _brief(deck_key, archetype_key, **overrides) -> Brief:
    defaults = dict(
        deck_key=deck_key, archetype_key=archetype_key, archetype_label=None,
        archetype_share=None, personal_matches=None, personal_wins=None, personal_losses=None,
        prose="prose", play_around=(), board_in=(), board_out=(), staples=(), problems=(),
        prompt="prompt", model="claude-sonnet-5", generated_at="2026-09-20T00:00:00.000Z",
        corpus_commit=None, list_hash="hash", source="live",
    )
    defaults.update(overrides)
    return Brief(**defaults)


def _live_at_break(*, game_number=1, won=True, reason="ResultReason_Concede", zone_cards=()):
    return LiveState(
        self_seat=1, opponent_seat=2, turn_number=None, active_seat=None,
        life={}, hand={}, library={}, graveyard={}, open_mana={}, other_mana_sources={},
        zone_cards=zone_cards, offer=None,
        intermission=Intermission(game_number=game_number, won=won, reason=reason),
    )


def test_manual_override_gives_an_exact_plan_and_beats_any_live_read(conn):
    """Step 2's precedence: ``opponent_deck_override`` always wins, checked
    before ``classify_seen`` is ever called (``table/intermission.py``'s
    ``_resolve_opponent`` returns on the override row before it even looks
    at ``fmt``/``names``) — the manual-precedence case S4 names as an
    alternative to seeding archetype definitions. With a brief already
    stored for the picked archetype, the plan is 'exact'."""
    deck_id = "deck-exact"
    _insert_deck(
        conn, deck_id, name="Test Deck", cards={"maindeck": [101, 102], "sideboard": [201]}
    )
    _insert_match(conn, "m-exact", deck_id, "incomplete", "2026-09-20T00:00:00")
    _insert_override(conn, "m-exact", label="Rogue Aggro", archetype_key="rogue-aggro")
    conn.commit()

    identity = next(i for i in list_identities(conn) if deck_id in i.deck_ids)
    write_brief(conn, _brief(identity.key, "rogue-aggro", archetype_label="Rogue Aggro"))
    conn.commit()

    result = build_break_read(conn, "m-exact", deck_id, _live_at_break(), caches={}, names=[])

    assert result is not None
    assert result.opponent is not None
    assert result.opponent.source == "manual"
    assert result.opponent.archetype_key == "rogue-aggro"
    assert result.opponent.confidence == "high"
    assert result.plan_basis == "exact"
    assert result.plan is not None and result.plan.archetype_key == "rogue-aggro"
    assert result.plan_archetype_label == "Rogue Aggro"
    assert result.alternatives == ()
    assert result.prompt is None  # already have an exact plan; nothing to draft
    assert result.deck_key == identity.key


def test_no_plan_when_nothing_is_named_or_stored(conn):
    """No override and an unresolvable format (rule 4's 'never a guess'):
    no opponent, no plan, no basis, no alternatives, no boarding — the
    honest empty read rather than anything invented."""
    deck_id = "deck-none"
    _insert_deck(conn, deck_id, fmt=None, cards={"maindeck": [101], "sideboard": []})
    _insert_match(
        conn, "m-none", deck_id, "incomplete", "2026-09-20T00:00:00", event_id="Arena_Direct_Game"
    )
    conn.commit()

    result = build_break_read(conn, "m-none", deck_id, _live_at_break(), caches={}, names=[])

    assert result is not None
    assert result.opponent is None
    assert result.plan is None
    assert result.plan_basis is None
    assert result.plan_archetype_label is None
    assert result.alternatives == ()
    assert result.past_boarding == ()
    assert result.prompt is None


def test_closest_alternative_plan_when_the_named_archetype_has_no_brief(conn):
    """Step 5: the chosen archetype (a live rule-engine read, no override)
    has no stored brief of its own, but a *different* archetype the
    classifier also ranked does — offered as the closest alternative, never
    substituted silently for the actual read.

    Two ``fallback`` definitions, hand-computed against classify.py's own
    constants (read directly, not run-and-observed — AGENTS.md rule 8):
    revealing all 4 of fallback-a's common cards vs. 2 of fallback-b's 4
    gives fit_a = 0.5 * min(4/4, 1) * 1.0 = 0.5 and fit_b = 0.5 * min(2/4, 1)
    * 1.0 = 0.25 (``_FALLBACK_FIT_CAP=0.5``, ``_FALLBACK_FIT_RAMP=4``,
    colour factor forced to 1.0 by each definition's empty ``Conditions``).
    margin_a = fit_a / fit_b = 2.0 clears both ``MIN_FALLBACK_FIT`` (0.25)
    and ``MIN_MARGIN`` (1.5), so ``choose()`` commits to fallback-a; its
    fit/margin also clear ``_MEDIUM_FIT``/``_MEDIUM_MARGIN`` (0.30/2.0), so
    its confidence is 'medium'. fallback-b's own fit (0.25) misses
    ``_MEDIUM_FIT``, so it ranks at confidence 'low' — still offered by
    ``rank_candidates`` (only 'none'-confidence rows are dropped), and it is
    the one with a stored brief.
    """
    deck_id = "deck-closest"
    _insert_deck(conn, deck_id, fmt="Standard", cards={"maindeck": [101], "sideboard": []})
    _insert_match(conn, "m-closest", deck_id, "incomplete", "2026-09-20T00:00:00")
    _insert_fallback(
        conn, fmt="Standard", source="fallback-a", name="Fallback A",
        common_cards=["Card A1", "Card A2", "Card A3", "Card A4"],
    )
    _insert_fallback(
        conn, fmt="Standard", source="fallback-b", name="Fallback B",
        common_cards=["Card B1", "Card B2", "Card B3", "Card B4"],
    )
    conn.commit()

    identity = next(i for i in list_identities(conn) if deck_id in i.deck_ids)
    write_brief(conn, _brief(identity.key, "fallback-b", archetype_label="Fallback B"))
    conn.commit()

    names = ["Card A1", "Card A2", "Card A3", "Card A4", "Card B1", "Card B2"]
    result = build_break_read(
        conn, "m-closest", deck_id, _live_at_break(), caches={}, names=names
    )

    assert result is not None
    assert result.opponent is not None
    assert result.opponent.archetype_key == "fallback-a"
    assert result.opponent.confidence == "medium"
    assert result.plan_basis == "closest"
    assert result.plan is not None and result.plan.archetype_key == "fallback-b"
    assert result.plan_archetype_label == "Fallback B"  # a different archetype than opponent.label
    assert [a.archetype_key for a in result.alternatives] == ["fallback-b"]
    assert result.alternatives[0].confidence == "low"


def test_past_boarding_diffs_against_that_matchs_own_game_1_maindeck(conn):
    """Step 5b: what this deck identity actually boarded, the last time it
    faced this archetype. ``opponent_deck_override.archetype_key`` alone
    drives ``v_match_opponent.opponent_key`` (migration 035's COALESCE puts
    ``'archetype:' || o.archetype_key`` first), so the past match needs no
    classifier run to be found.

    The diff is against that *past* match's own game-1 maindeck
    (``decks.cards_json``), not the current 75 — the current 75 only flags
    ``in_current_75``, it never decides which cards are shown (rule 4: a
    card since cut from the deck is still part of what actually happened).
    Card 301 was boarded in but has since left the 75 entirely, and must
    still appear, flagged, not dropped."""
    deck_id = "deck-boarding"
    _insert_deck(
        conn, deck_id, fmt="Standard",
        cards={"maindeck": [101, 102, 103, 104, 105], "sideboard": [201, 202, 203]},
    )
    _insert_cards(conn, {
        101: "Card One", 102: "Card Two", 103: "Card Three", 104: "Card Four",
        105: "Card Five", 201: "Side One", 202: "Side Two", 203: "Side Three",
        301: "Outside Card",
    })
    _insert_match(conn, "m-cur", deck_id, "incomplete", "2026-09-20T00:00:00")
    _insert_override(conn, "m-cur", label="Rogue Aggro", archetype_key="rogue-aggro")
    _insert_match(conn, "m-past", deck_id, "win", "2026-09-10T00:00:00")
    _insert_override(conn, "m-past", label="Rogue Aggro", archetype_key="rogue-aggro")
    conn.execute(
        "INSERT INTO games (match_id, game_number, result, result_reason) "
        "VALUES ('m-past', 2, 'win', 'ResultReason_Concede')"
    )
    conn.execute(
        "INSERT INTO game_decks (match_id, game_number, deck_cards_json, sideboard_cards_json) "
        "VALUES ('m-past', 2, ?, ?)",
        (json.dumps([101, 102, 103, 104, 301]), json.dumps([105, 201, 202, 203])),
    )
    conn.commit()

    result = build_break_read(conn, "m-cur", deck_id, _live_at_break(), caches={}, names=[])

    assert result is not None
    assert len(result.past_boarding) == 1
    past = result.past_boarding[0]
    assert past.match_id == "m-past"
    assert len(past.games) == 1
    game = past.games[0]
    assert game.game_number == 2
    assert game.result == "win"
    assert [c.grp_id for c in game.board_out] == [105]
    assert game.board_out[0].card == "Card Five"
    assert game.board_out[0].in_current_75 is True
    assert [c.grp_id for c in game.board_in] == [301]
    assert game.board_in[0].card == "Outside Card"
    assert game.board_in[0].in_current_75 is False  # cut since, but still shown


class _FakeAppState:
    """Just enough of ``FastAPI``'s ``app.state`` for ``_cached_break_read``
    to stash its two lazily-created cache dicts on (``getattr``/plain
    attribute assignment) — a full ``make_client(create_app(...))``
    (``conftest.py``) would work too, but pays for a whole app and an HTTP
    round trip to exercise a cache check that only needs
    ``request.app.state`` to exist."""


class _FakeApp:
    def __init__(self):
        self.state = _FakeAppState()


class _FakeRequest:
    def __init__(self):
        self.app = _FakeApp()


def test_cached_break_read_builds_once_for_unchanged_inputs(conn):
    """api/sql.py's ``_cached_break_read`` (S4 step 7): a second poll with
    nothing new (no card_events, no reprojection, no corpus fetch) must
    reuse the cached ``BreakRead`` rather than reclassifying the opponent —
    checked by identity, not equality, since two independently-built
    ``BreakRead``s with the same values would compare equal regardless."""
    deck_id = "deck-cache"
    _insert_deck(conn, deck_id, fmt="Standard", cards={"maindeck": [101], "sideboard": []})
    _insert_match(conn, "m-cache", deck_id, "incomplete", "2026-09-20T00:00:00")
    conn.commit()

    live = _live_at_break()
    request = _FakeRequest()

    first = _cached_break_read(request, conn, "m-cache", deck_id, live)
    second = _cached_break_read(request, conn, "m-cache", deck_id, live)

    assert first is not None
    assert first is second


def test_cached_break_read_sees_a_pick_and_a_brief_made_during_the_break(conn):
    """The two things a user actually does *during* a break — pick the
    opponent's deck by hand, then import the brief written from this card's
    own prompt — move no projection token, so the cache key has to carry
    both itself. Without them the card would show the old answer until the
    watcher happened to reproject."""
    deck_id = "deck-edit"
    _insert_deck(conn, deck_id, fmt="Standard", cards={"maindeck": [101], "sideboard": []})
    _insert_match(conn, "m-edit", deck_id, "incomplete", "2026-09-20T00:00:00")
    conn.commit()
    live = _live_at_break()
    request = _FakeRequest()

    before = _cached_break_read(request, conn, "m-edit", deck_id, live)
    assert before is not None and before.opponent is None

    _insert_override(conn, "m-edit", label="Rogue Aggro", archetype_key="rogue-aggro")
    conn.commit()
    picked = _cached_break_read(request, conn, "m-edit", deck_id, live)
    assert picked.opponent is not None and picked.opponent.source == "manual"
    assert picked.plan is None

    identity = next(i for i in list_identities(conn) if deck_id in i.deck_ids)
    write_brief(conn, _brief(identity.key, "rogue-aggro", archetype_label="Rogue Aggro"))
    conn.commit()
    imported = _cached_break_read(request, conn, "m-edit", deck_id, live)
    assert imported.plan_basis == "exact"
    assert imported.plan is not None and imported.plan.archetype_key == "rogue-aggro"


def test_unknown_format_reads_no_opponent_and_says_fmt_is_null(conn):
    """A match whose format resolves to nothing (an event id that maps to no format, no
    deck format, no matches.format) is never classified, however many cards
    were seen: no opponent, and ``fmt`` is None so the card can say why."""
    deck_id = "deck-nofmt"
    _insert_deck(conn, deck_id, fmt=None, cards={"maindeck": [101], "sideboard": []})
    _insert_match(
        conn, "m-nofmt", deck_id, "incomplete", "2026-09-20T00:00:00", event_id="Arena_Direct_Game"
    )
    _insert_fallback(
        conn, fmt="Standard", source="fallback-a", name="Fallback A",
        common_cards=["Card A1", "Card A2", "Card A3", "Card A4"],
    )
    conn.commit()

    names = ["Card A1", "Card A2", "Card A3", "Card A4"]
    result = build_break_read(conn, "m-nofmt", deck_id, _live_at_break(), caches={}, names=names)

    assert result is not None
    assert result.fmt is None
    assert result.opponent is None


def _store_corpus_deck(conn, fmt, event_id, deck_ord, archetype_key, card_names):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', '2026-09-01', ?, 'B')",
        (event_id, fmt),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json) "
        "VALUES (?, ?, ?, '[]')",
        (event_id, deck_ord, json.dumps([{"name": n, "count": 4} for n in card_names])),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, ?, ?, ?, ?, 'archetype', 'now')",
        (event_id, deck_ord, archetype_key, archetype_key, archetype_key),
    )


def test_non_standard_match_is_read_with_that_formats_prior(conn):
    """The corpus holds ``MIN_CORPUS_DECKS`` Pioneer decks under one key and
    as many Standard decks under another, all containing the four cards the
    opponent showed, and no rule definition matches them. A match whose
    ``matches.format`` is Pioneer must therefore come out as the Pioneer key,
    which only Pioneer's prior can say; Standard's prior would name the
    Standard one. ``_intermission_out`` carries the format through."""
    deck_id = "deck-pioneer"
    _insert_deck(conn, deck_id, fmt=None, cards={"maindeck": [101], "sideboard": []})
    _insert_match(conn, "m-pioneer", deck_id, "incomplete", "2026-09-20T00:00:00")
    conn.execute("UPDATE matches SET format = 'Pioneer' WHERE match_id = 'm-pioneer'")
    names = ["Card P1", "Card P2", "Card P3", "Card P4"]
    for ord_ in range(MIN_CORPUS_DECKS):
        _store_corpus_deck(conn, "Pioneer", "ev-pio", ord_, "pioneer-key", names)
        _store_corpus_deck(conn, "Standard", "ev-std", ord_, "standard-key", names)
    conn.commit()

    result = build_break_read(
        conn, "m-pioneer", deck_id, _live_at_break(), caches={}, names=names
    )

    assert result is not None
    assert result.fmt == "Pioneer"
    assert result.opponent is not None
    assert result.opponent.archetype_key == "pioneer-key"
    assert _intermission_out(result).fmt == "Pioneer"
