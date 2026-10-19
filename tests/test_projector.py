"""M1 projection tests.

Ground truth comes from a real Traditional (Bo3) session, verified against the
unfiltered 17 MB log before the fixture was cut:

  match fd5624a4  self seat 2  LOSS 0-2   on the play in both games
  match fa7a4d16  self seat 1  WIN  2-1   draw, draw, play

The second match is the important one: it shows play/draw alternating *within*
a match, which is why on_play must be recorded per game.
"""

import json
import logging
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector.matches import (
    Projector,
    deck_identity,
    has_match_boundary,
    project,
)
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
MATCH_LOSS = "fd5624a4-d970-40eb-80aa-fba9d2ce17b3"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"


@pytest.fixture
def db(tmp_path):
    conn = open_database(tmp_path / "t.db")
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    yield conn
    conn.close()


def games(db, match_id):
    return {
        r["game_number"]: r
        for r in db.execute("SELECT * FROM games WHERE match_id = ?", (match_id,))
    }


def match(db, match_id):
    return db.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,)).fetchone()


# --- deck identity ----------------------------------------------------------


def test_deck_identity_is_order_independent():
    assert deck_identity([1, 2, 2])[0] == deck_identity([2, 1, 2])[0]


def test_deck_identity_changes_with_one_card():
    assert deck_identity([1, 2, 2])[0] != deck_identity([1, 2, 3])[0]


def test_deck_identity_counts_matter():
    assert deck_identity([1, 1])[0] != deck_identity([1])[0]


# --- projection: matches ----------------------------------------------------


def test_both_matches_projected(db):
    assert db.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 2


def test_self_seat_resolved_from_authenticate_response(db):
    assert match(db, MATCH_LOSS)["self_seat"] == 2
    assert match(db, MATCH_WIN)["self_seat"] == 1


def test_opponent_is_not_us(db):
    for mid in (MATCH_LOSS, MATCH_WIN):
        row = match(db, mid)
        assert row["opponent_seat"] != row["self_seat"]
        assert row["opponent_name"] is not None


def test_match_results(db):
    assert match(db, MATCH_LOSS)["result"] == "loss"
    assert match(db, MATCH_WIN)["result"] == "win"


def test_match_game_tallies(db):
    lost = match(db, MATCH_LOSS)
    assert (lost["games_won"], lost["games_lost"]) == (0, 2)
    won = match(db, MATCH_WIN)
    assert (won["games_won"], won["games_lost"]) == (2, 1)


def test_event_id_captured(db):
    assert match(db, MATCH_WIN)["event_id"] == "Traditional_Ladder"


def test_ladder_matches_are_standard(db):
    """Both inputs say Standard in the fixture: the deck format is
    TraditionalStandard (fixture_peek entries 0-2 and 17) and the event id is
    Traditional_Ladder (entries 5 and 19)."""
    assert match(db, MATCH_WIN)["format"] == "Standard"
    assert match(db, MATCH_LOSS)["format"] == "Standard"


def test_best_of_three_matches_project_best_of_3(db):
    # match_session.log's gameInfo carries MatchWinCondition_Best2of3 throughout.
    assert match(db, MATCH_LOSS)["best_of"] == 3
    assert match(db, MATCH_WIN)["best_of"] == 3


def test_single_elimination_match_projects_best_of_1(tmp_path):
    # bo1_session.log: fixture_peek entries 1 and 4 name the match in
    # gameRoomConfig.matchId; entries 2 and 3 carry gameInfo.matchID and
    # MatchWinCondition_SingleElimination (show --max-depth 7).
    conn = open_database(tmp_path / "bo1.db")
    ingest_file(conn, FIXTURE.with_name("bo1_session.log"), locale_hint="mdy")
    project(conn)
    assert [tuple(r) for r in conn.execute("SELECT match_id, best_of FROM matches")] == [
        ("801ebc43-c204-4cb4-856c-00b22837087b", 1)
    ]
    conn.close()


def test_unknown_win_condition_is_null_and_warns(tmp_path, caplog):
    conn, counts = _reproject_with(
        tmp_path, [("MatchWinCondition_Best2of3", "MatchWinCondition_Mystery")], caplog
    )
    assert [r[0] for r in conn.execute("SELECT best_of FROM matches")] == [None, None]
    assert sum("MatchWinCondition_Mystery" in r.getMessage() for r in caplog.records) == 2
    assert counts["warnings"] == 2
    conn.close()


def test_later_different_win_condition_warns_once_and_changes_nothing(caplog):
    # Synthetic: tests the keep-the-first rule, not Arena's format.
    p = Projector()
    p.feed(
        "event",
        None,
        '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {'
        '"gameRoomConfig": {"matchId": "m1", "reservedPlayers": ['
        '{"userId": "A", "systemSeatId": 1, "teamId": 1}]},'
        '"stateType": "MatchGameRoomStateType_Playing"}}}',
        None,
    )
    before = p.warnings
    for condition in (
        "MatchWinCondition_Best2of3",
        "MatchWinCondition_SingleElimination",
        "MatchWinCondition_SingleElimination",
    ):
        p._handle_gre_message(
            {"gameStateMessage": {"gameInfo": {"matchID": "m1", "matchWinCondition": condition}}},
            None,
        )
    assert p.matches["m1"].best_of == 3
    assert p.warnings - before == 1


def test_best_of_is_stable_across_a_second_project(db):
    first = [tuple(r) for r in db.execute("SELECT match_id, best_of FROM matches ORDER BY 1")]
    project(db)
    second = [tuple(r) for r in db.execute("SELECT match_id, best_of FROM matches ORDER BY 1")]
    assert first == second
    assert {b for _, b in second} == {3}


def _reproject_with(tmp_path, replacements, caplog):
    """Rewrite raw_events payloads, project, return (conn, project()'s counts).
    The fixture's two matches share one event id, Traditional_Ladder."""
    conn = open_database(tmp_path / "t.db")
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    for old, new in replacements:
        conn.execute("UPDATE raw_events SET payload = REPLACE(payload, ?, ?)", (old, new))
    with caplog.at_level(logging.WARNING):
        counts = project(conn)
    return conn, counts


def _formats(conn):
    return [r[0] for r in conn.execute("SELECT format FROM matches")]


def test_deck_format_alone_gives_standard(tmp_path, caplog):
    """Only the event id is rewritten (fixture_peek entries 5 and 19, Traditional_Ladder);
    the deck format TraditionalStandard (entries 0-2 and 17) still says Standard."""
    conn, counts = _reproject_with(
        tmp_path, [("Traditional_Ladder", "Constructed_Mystery")], caplog
    )
    assert _formats(conn) == ["Standard", "Standard"]
    assert counts["warnings"] == 0
    conn.close()


def test_event_id_alone_gives_standard(tmp_path, caplog):
    """Only the deck format is rewritten (fixture_peek entries 0-2 and 17,
    TraditionalStandard); the event id Traditional_Ladder (entries 5 and 19)
    still says Standard."""
    conn, counts = _reproject_with(tmp_path, [("TraditionalStandard", "Mystery")], caplog)
    assert _formats(conn) == ["Standard", "Standard"]
    assert counts["warnings"] == 0
    conn.close()


def test_draft_match_has_no_format_and_no_warning(tmp_path, caplog):
    conn, counts = _reproject_with(
        tmp_path,
        [("Traditional_Ladder", "PremierDraft_ABC_20260101"), ("TraditionalStandard", "Draft")],
        caplog,
    )
    assert _formats(conn) == [None, None]
    assert counts["warnings"] == 0
    conn.close()


def test_unmapped_constructed_event_id_warns_once_per_id(tmp_path, caplog):
    conn, counts = _reproject_with(
        tmp_path,
        [("Traditional_Ladder", "Constructed_Mystery"), ("TraditionalStandard", "Mystery")],
        caplog,
    )
    assert _formats(conn) == [None, None]
    assert counts["warnings"] == 1  # two matches, one event id
    assert caplog.text.count("no format for constructed event id") == 1
    conn.close()


def test_historic_deck_in_a_direct_game_is_null_without_warning(tmp_path, caplog):
    conn, counts = _reproject_with(
        tmp_path,
        [("Traditional_Ladder", "DirectGame"), ("TraditionalStandard", "TraditionalHistoric")],
        caplog,
    )
    assert _formats(conn) == [None, None]
    assert counts["warnings"] == 0
    conn.close()


def test_precon_queue_with_no_deck_format_is_null_without_warning(tmp_path, caplog):
    conn, counts = _reproject_with(
        tmp_path, [("Traditional_Ladder", "DualColorPrecons"), ("TraditionalStandard", "")], caplog
    )
    assert _formats(conn) == [None, None]
    assert counts["warnings"] == 0
    conn.close()


def test_completed_reason_captured(db):
    assert match(db, MATCH_WIN)["completed_reason"] == "MatchCompletedReasonType_Success"


# --- projection: games ------------------------------------------------------


def test_no_double_counted_games(db):
    """Arena emits GameStage_GameOver twice for the last game of a match."""
    assert sorted(games(db, MATCH_LOSS)) == [1, 2]
    assert sorted(games(db, MATCH_WIN)) == [1, 2, 3]
    assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 5


def test_per_game_results_not_cumulative(db):
    """gameInfo.results lists every game so far; game 2 must not inherit game 1."""
    g = games(db, MATCH_WIN)
    assert [g[n]["result"] for n in (1, 2, 3)] == ["win", "loss", "win"]


def test_on_play_alternates_within_a_bo3(db):
    g = games(db, MATCH_WIN)
    assert [g[n]["on_play"] for n in (1, 2, 3)] == [0, 0, 1]


def test_on_play_recorded_for_every_game(db):
    for mid in (MATCH_LOSS, MATCH_WIN):
        for row in games(db, mid).values():
            assert row["on_play"] in (0, 1)


def test_result_reasons_captured(db):
    assert games(db, MATCH_WIN)[3]["result_reason"] == "ResultReason_Timeout"


def test_absent_mulligan_count_means_zero(db):
    """Arena omits mulliganCount when it is zero, for both seats."""
    g = games(db, MATCH_WIN)
    assert g[1]["self_mulligans"] == 1
    assert g[2]["self_mulligans"] == 0
    assert g[1]["opp_mulligans"] == 0


# --- projection: turns (M2) --------------------------------------------------


def turns(db, match_id, game_number):
    return {
        r["turn_number"]: r
        for r in db.execute(
            "SELECT * FROM turns WHERE match_id = ? AND game_number = ?",
            (match_id, game_number),
        )
    }


def test_turns_row_count_is_exact(db):
    """15 turns across the 5 games, plus fa7a4d16 game 2's trailing turn 24.

    The fixture is a *curated subset* of a real session — 34 log entries cut
    from a 4,595-entry log — so most intermediate turns were dropped when it
    was anonymized. What survives is turns 1-3 of each game, plus the last
    state message of fa7a4d16 game 2, which reports turnNumber 24.
    """
    assert db.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 16


def test_turns_have_no_duplicate_keys_and_a_parent_game(db):
    total = db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    distinct = db.execute(
        "SELECT COUNT(DISTINCT match_id || ':' || game_number || ':' || turn_number) FROM turns"
    ).fetchone()[0]
    assert total == distinct

    orphans = db.execute(
        """
        SELECT COUNT(*) FROM turns t
         WHERE NOT EXISTS (
            SELECT 1 FROM games g
             WHERE g.match_id = t.match_id AND g.game_number = t.game_number
         )
        """
    ).fetchone()[0]
    assert orphans == 0


def test_turn_count_matches_max_recorded_turn(db):
    """games.turn_count and MAX(turns.turn_number) must agree for every game.

    fa7a4d16 game 2 is the case that matters: its final state message arrives
    *after* GameStage_GameOver and reports turnNumber 24. Without the trailing
    flush, that turn is accumulated but never written, and this game's turns
    would stop at 3 while turn_count said 24.
    """
    rows = db.execute(
        """
        SELECT g.match_id, g.game_number, g.turn_count, MAX(t.turn_number) AS max_turn
          FROM games g LEFT JOIN turns t USING (match_id, game_number)
         WHERE g.result != 'incomplete'
         GROUP BY g.match_id, g.game_number
        """
    ).fetchall()
    assert [r for r in rows if r["turn_count"] != r["max_turn"]] == []
    assert dict(games(db, MATCH_WIN))[2]["turn_count"] == 24


def test_trailing_turn_after_game_over_is_recorded(db):
    """The post-GameOver message carries the game's real final state (life 4
    and 10, read straight from the fixture), so turn 24 must exist and hold
    it rather than being dropped on the floor."""
    final = turns(db, MATCH_WIN, 2)[24]
    assert (final["self_life"], final["opp_life"]) == (4, 10)


def test_life_totals_at_decisive_final_turn(db):
    """Ground truth read directly from the fixture's GameComplete messages,
    not from running the projector and copying its output:

    - fd5624a4 (LOSS match, self seat 2) game 2 ends at gameStateId 733 with
      both players' lifeTotal == 10.
    - fa7a4d16 (WIN match, self seat 1) game 3 ends at gameStateId 240 with
      seat 1 (self) at 20 and seat 2 (opponent) at 8.
    """
    loss_final = turns(db, MATCH_LOSS, 2)[3]
    assert (loss_final["self_life"], loss_final["opp_life"]) == (10, 10)

    win_final = turns(db, MATCH_WIN, 3)[3]
    assert (win_final["self_life"], win_final["opp_life"]) == (20, 8)


def test_turn_one_starts_at_default_life_total(db):
    for mid, game_numbers in ((MATCH_LOSS, (1, 2)), (MATCH_WIN, (1, 2, 3))):
        for n in game_numbers:
            first = turns(db, mid, n)[1]
            assert first["self_life"] == 20
            assert first["opp_life"] == 20


def test_turn_numbers_start_at_one_and_increase(db):
    """Contiguity is checked against the *full* log, not this fixture.

    The fixture keeps only a sample of each game's state messages, so gaps are
    expected here (fa7a4d16 game 2 runs 1, 2, 3, 24). What must always hold is
    that a game's turns start at 1 and never repeat.
    """
    for mid, game_numbers in ((MATCH_LOSS, (1, 2)), (MATCH_WIN, (1, 2, 3))):
        for n in game_numbers:
            numbers = sorted(turns(db, mid, n))
            assert numbers[0] == 1
            assert numbers == sorted(set(numbers))


def test_turns_projection_is_idempotent(db):
    before = {
        (r["match_id"], r["game_number"], r["turn_number"]): dict(r)
        for r in db.execute("SELECT * FROM turns")
    }
    project(db)
    after = {
        (r["match_id"], r["game_number"], r["turn_number"]): dict(r)
        for r in db.execute("SELECT * FROM turns")
    }
    assert before == after


def test_hand_and_battlefield_card_counts_match_the_scalar_counts(db):
    """turn_zones and turns are two views onto the same tracker state —
    _zone_cards deliberately reuses _zone_counts'/_battlefield_counts' seat
    rules, so the row count for a turn's hand/battlefield must always equal
    the scalar column beside it. Any drift here is a real bug, not a fixture
    quirk."""
    rows = db.execute(
        """
        SELECT t.match_id, t.game_number, t.turn_number, t.self_hand, t.opp_hand,
               t.self_permanents, t.opp_permanents, m.self_seat, m.opponent_seat
          FROM turns t JOIN matches m ON m.match_id = t.match_id
        """
    ).fetchall()
    assert rows, "fixture must produce at least one turn"
    for row in rows:
        key = (row["match_id"], row["game_number"], row["turn_number"])
        for zone, self_col, opp_col in (
            ("hand", "self_hand", "opp_hand"),
            ("battlefield", "self_permanents", "opp_permanents"),
        ):
            pairs = ((row["self_seat"], row[self_col]), (row["opponent_seat"], row[opp_col]))
            for seat, expected in pairs:
                count = db.execute(
                    "SELECT COUNT(*) FROM turn_zones WHERE match_id=? AND game_number=? "
                    "AND turn_number=? AND zone=? AND seat=?",
                    (*key, zone, seat),
                ).fetchone()[0]
                assert count == (expected or 0)


def test_tapped_land_stays_tapped_for_the_turn_it_was_tapped_on(db):
    """Ground truth read directly from the fixture, gameStateMessage by
    gameStateMessage, not from running the projector:

    - match fa7a4d16 game 1: a diff carrying **no turnInfo** (so still turn 1)
      puts instance 374 on the battlefield with `"isTapped": true` — the land
      was played and tapped for mana during turn 1's first main phase.
    - nothing untaps it during turn 2, which is the *other* seat's turn.
    - the diff reading `turnInfo: {turnNumber: 3, step: Step_Upkeep}` carries
      annotation id 103, `AnnotationType_TappedUntappedPermanent,
      affectedIds: [374], tapped: 0`. That same diff re-sends 374's game object
      **without any isTapped key at all** — the direct evidence that Arena never
      reports the false, only the annotation.

    So: tapped on turns 1 and 2, untapped on turn 3. Both failure modes are
    caught here. Applying the annotation before the turn boundary would report
    turn 2 untapped, on the very turn the land was still sideways; ignoring the
    annotation would leave turn 3 tapped forever.
    """
    tapped_on = db.execute(
        "SELECT turn_number, is_tapped FROM turn_zones "
        " WHERE match_id LIKE 'fa7a4d16%' AND game_number = 1 AND zone = 'battlefield' "
        "   AND instance_id = 374 ORDER BY turn_number"
    ).fetchall()
    assert [(r["turn_number"], r["is_tapped"]) for r in tapped_on] == [(1, 1), (2, 1), (3, 0)]


def test_is_tapped_is_null_off_the_battlefield(db):
    """None means "does not apply" — a card in hand has no orientation. A 0
    there would be a claim we never observed."""
    stray = db.execute(
        "SELECT COUNT(*) FROM turn_zones WHERE zone != 'battlefield' AND is_tapped IS NOT NULL"
    ).fetchone()[0]
    assert stray == 0
    known = db.execute(
        "SELECT COUNT(*) FROM turn_zones WHERE zone = 'battlefield' AND is_tapped IS NULL"
    ).fetchone()[0]
    assert known == 0


def test_turn_zones_projection_is_idempotent(db):
    order = "ORDER BY match_id, game_number, turn_number, zone, seat, idx"
    before = [dict(r) for r in db.execute(f"SELECT * FROM turn_zones {order}")]
    project(db)
    after = [dict(r) for r in db.execute(f"SELECT * FROM turn_zones {order}")]
    assert before == after


# --- resource counts ----------------------------------------------------


def test_turns_carry_graveyard_and_open_mana_counts(db):
    """Ground truth read directly from the fixture, same as the tapped-land
    test above:

    - fd5624a4 (LOSS match, self seat 2) game 1 turn 1: a spell has already
      resolved to our graveyard (the same annotation
      test_rekeyed_spell_keeps_its_identity reads), so self_graveyard == 1.
    - fd5624a4 game 2 turn 3: one land in play, untapped, so self_open_mana
      matches self_lands at 1.
    """
    assert turns(db, MATCH_LOSS, 1)[1]["self_graveyard"] == 1

    at_turn_3 = turns(db, MATCH_LOSS, 2)[3]
    assert at_turn_3["self_lands"] == 1
    assert at_turn_3["self_open_mana"] == 1


def test_fresh_tracker_per_game_does_not_inherit_board_state():
    """MatchState.game(n) constructs a new GameState (default_factory tracker)
    the first time n is seen, so a new game must not see the previous game's
    battlefield."""
    p = Projector()
    p.self_user_id = "SELF"
    p.feed(
        "event", None,
        '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {'
        '"gameRoomConfig": {"matchId": "m1", "reservedPlayers": ['
        '{"userId": "SELF", "systemSeatId": 1, "teamId": 1}, '
        '{"userId": "OPP", "systemSeatId": 2, "teamId": 2}]},'
        '"stateType": "MatchGameRoomStateType_Playing"}}}',
        None,
    )
    p.feed(
        "event", None,
        '{"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {'
        '"gameInfo": {"matchID": "m1", "gameNumber": 1}, '
        '"gameObjects": [{"instanceId": 1, "controllerSeatId": 1}], '
        '"zones": [{"zoneId": 1, "type": "ZoneType_Battlefield", '
        '"objectInstanceIds": [1]}]}}]}}',
        None,
    )
    p.feed(
        "event", None,
        '{"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {'
        '"gameInfo": {"matchID": "m1", "gameNumber": 2}}}]}}',
        None,
    )
    state = p.matches["m1"]
    assert 1 in state.game(1).tracker.objects
    assert state.game(2).tracker.objects == {}


def test_unresolved_self_seat_yields_no_turns_rows(tmp_path):
    """self/opp columns would be meaningless without a resolved seat — the
    match already gets a self-seat warning (see test_projector's M1 tests);
    M2 must additionally write zero turns rows for it."""
    conn = open_database(tmp_path / "u.db")
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        (
            "d1", "Player.log", "event", None,
            '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {'
            '"gameRoomConfig": {"matchId": "m1", "reservedPlayers": ['
            '{"userId": "A", "systemSeatId": 1, "teamId": 1}]},'
            '"stateType": "MatchGameRoomStateType_Playing"}}}',
        ),
    )
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        (
            "d2", "Player.log", "event", None,
            '{"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {'
            '"gameInfo": {"matchID": "m1", "gameNumber": 1}, '
            '"turnInfo": {"turnNumber": 1, "activePlayer": 1}, '
            '"players": [{"systemSeatNumber": 1, "lifeTotal": 20}]}}]}}',
        ),
    )
    counts = project(conn)
    assert counts["warnings"] >= 1
    assert conn.execute("SELECT COUNT(*) FROM turns WHERE match_id = 'm1'").fetchone()[0] == 0
    conn.close()


def test_turn_zones_persist_without_a_resolved_self_seat(tmp_path):
    """Unlike turns, turn_zones keeps the raw seat — the same reasoning as
    card_events — so a truncated session that never resolved self_seat still
    gets zone contents to build a board from."""
    conn = open_database(tmp_path / "u2.db")
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        (
            "d1", "Player.log", "event", None,
            '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {'
            '"gameRoomConfig": {"matchId": "m1", "reservedPlayers": ['
            '{"userId": "A", "systemSeatId": 1, "teamId": 1}]},'
            '"stateType": "MatchGameRoomStateType_Playing"}}}',
        ),
    )
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        (
            "d2", "Player.log", "event", None,
            '{"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {'
            '"gameInfo": {"matchID": "m1", "gameNumber": 1}, '
            '"turnInfo": {"turnNumber": 1, "activePlayer": 1}, '
            '"gameObjects": [{"instanceId": 1, "grpId": 100}], '
            '"zones": [{"zoneId": 5, "type": "ZoneType_Hand", "ownerSeatId": 1, '
            '"objectInstanceIds": [1]}], '
            '"players": [{"systemSeatNumber": 1, "lifeTotal": 20}]}}]}}',
        ),
    )
    counts = project(conn)
    assert counts["warnings"] >= 1
    assert conn.execute("SELECT COUNT(*) FROM turns WHERE match_id = 'm1'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM turn_zones WHERE match_id = 'm1'").fetchone()[0] == 1
    conn.close()


# --- projection: decks ------------------------------------------------------


def test_deck_recorded_with_name(db):
    rows = db.execute("SELECT * FROM decks").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Spellelementals"


def test_matches_linked_to_deck(db):
    deck_id = db.execute("SELECT deck_id FROM decks").fetchone()[0]
    assert match(db, MATCH_WIN)["deck_id"] == deck_id


# --- metric views -----------------------------------------------------------


def test_deck_winrate_view(db):
    row = db.execute("SELECT * FROM v_deck_winrate").fetchone()
    assert row["matches_completed"] == 2
    assert row["matches_won"] == 1
    assert (row["games_won"], row["games_lost"]) == (2, 3)


def test_play_draw_view_splits_by_on_play(db):
    rows = {r["on_play"]: r for r in db.execute("SELECT * FROM v_play_draw_winrate")}
    assert rows[1]["games_completed"] == 3  # play: 2 losses + 1 win
    assert rows[1]["games_won"] == 1
    assert rows[0]["games_completed"] == 2  # draw: 1 win + 1 loss
    assert rows[0]["games_won"] == 1


# --- robustness -------------------------------------------------------------


def test_projection_is_idempotent(db):
    before = db.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    project(db)
    assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == before


def test_fixture_projects_without_warnings(tmp_path):
    conn = open_database(tmp_path / "w.db")
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    assert project(conn)["warnings"] == 0
    conn.close()


def test_malformed_payload_does_not_halt_projection():
    p = Projector()
    p.feed("event", None, "{not json", None)
    p.feed("event", None, '{"authenticateResponse": {"clientId": "X"}}', None)
    assert p.self_user_id == "X"
    assert p.warnings == 1


def test_project_warns_once_per_malformed_row(tmp_path):
    """``project()`` parses each raw_events row once. A row that fails to
    parse must warn exactly once, and every other row must still project
    correctly around it."""
    conn = open_database(tmp_path / "w.db")
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload) "
        "VALUES ('bad-digest', 'Player.log', NULL, 'event', 'BadEvent', '{not json')"
    )
    result = project(conn)
    assert result["warnings"] == 1
    # The rest of the fixture still projects normally around the bad row.
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 2
    conn.close()


def test_one_bad_message_in_a_gre_event_costs_only_itself(tmp_path, caplog):
    """A GreToClientEvent carries several messages. In match_session.log the
    event holding states 388 and 389 (``fixture_peek.py grep``) is the first
    game's end: state 388 is ``GameStage_GameOver`` / ``MatchState_GameComplete``
    with winning team 1 -- a loss for MATCH_LOSS, where the user is team 2
    (``test_match_results`` reads the same match). A malformed copy of state
    389 is put in front of it, in memory only: ``gameObjects`` an int reaches
    the tracker's loop and raises. The game's result must still land, and the
    failure must warn once, naming the message type and state id.

    The match's closing ``MatchGameRoomStateChangedEvent`` also lists the
    game results (``finalMatchResult``), so that row is deleted from the copy:
    state 388 is then the only source of game 1's result."""
    conn = open_database(tmp_path / "t.db")
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    deleted = conn.execute(
        "DELETE FROM raw_events WHERE label = 'MatchGameRoomStateChangedEvent' "
        "AND payload LIKE '%MatchGameRoomStateType_MatchCompleted%' AND payload LIKE ?",
        (f"%{MATCH_LOSS}%",),
    ).rowcount
    assert deleted == 1
    row = None
    for candidate in conn.execute(
        "SELECT id, payload FROM raw_events WHERE label = 'GreToClientEvent'"
    ).fetchall():
        parsed = json.loads(candidate["payload"])
        msgs = parsed["greToClientEvent"]["greToClientMessages"]
        ids = [(m.get("gameStateMessage") or {}).get("gameStateId") for m in msgs]
        if 388 in ids and 389 in ids:
            row = (candidate["id"], parsed)
            break
    assert row is not None
    row_id, payload = row
    msgs = payload["greToClientEvent"]["greToClientMessages"]
    bad = json.loads(json.dumps(next(
        m for m in msgs if (m.get("gameStateMessage") or {}).get("gameStateId") == 389
    )))
    bad["gameStateMessage"]["gameObjects"] = 5
    msgs.insert(0, bad)
    conn.execute(
        "UPDATE raw_events SET payload = ? WHERE id = ?", (json.dumps(payload), row_id)
    )
    with caplog.at_level(logging.WARNING):
        counts = project(conn)
    assert games(conn, MATCH_LOSS)[1]["result"] == "loss"
    assert counts["warnings"] == 1
    hits = [
        r.getMessage() for r in caplog.records
        if "GREMessageType_GameStateMessage" in r.getMessage()
    ]
    assert len(hits) == 1
    assert "389" in hits[0]
    conn.close()


UNDO_FIXTURE = Path(__file__).parent / "fixtures" / "undo_session.log"


def test_a_queued_state_messages_zone_change_applies(tmp_path):
    """undo_session.log carries state 96 only as a ``QueuedGameStateMessage``
    (``fixture_peek.py grep --type GREMessageType_QueuedGameStateMessage``);
    its ZoneTransfer moves instance 269 (grpId 106296) from zone 31, seat 1's
    hand, to zone 27, the stack, as a ``CastSpell``. No plain message repeats
    it, so the row exists only if a queued message is applied."""
    conn = open_database(tmp_path / "u.db")
    ingest_file(conn, UNDO_FIXTURE, locale_hint="mdy")
    project(conn)
    rows = conn.execute(
        "SELECT * FROM card_events WHERE grp_id = 106296 AND category = 'CastSpell'"
    ).fetchall()
    assert len(rows) == 1
    assert (rows[0]["seat"], rows[0]["zone_src"], rows[0]["zone_dest"]) == (
        1, "ZoneType_Hand", "ZoneType_Stack",
    )
    conn.close()


def test_a_trackers_warning_is_counted_by_the_projection(tmp_path):
    """The tracker collects its warnings instead of logging them (the Live
    replay runs it at 1 Hz); ``project()`` forwards each through
    ``Projector._warn`` so it is counted. undo_session.log with state 99's
    message removed in memory: state 101 undoes back to 99, which the game
    never applied, and that is the fixture's only warning
    (test_game_state.py asserts the same case on the tracker alone)."""
    conn = open_database(tmp_path / "w.db")
    ingest_file(conn, UNDO_FIXTURE, locale_hint="mdy")
    assert project(conn)["warnings"] == 0
    removed = 0
    for row in conn.execute(
        "SELECT id, payload FROM raw_events WHERE label = 'GreToClientEvent'"
    ).fetchall():
        parsed = json.loads(row["payload"])
        msgs = parsed["greToClientEvent"]["greToClientMessages"]
        kept = [
            m for m in msgs
            if (m.get("gameStateMessage") or {}).get("gameStateId") != 99
        ]
        if len(kept) != len(msgs):
            removed += len(msgs) - len(kept)
            parsed["greToClientEvent"]["greToClientMessages"] = kept
            conn.execute(
                "UPDATE raw_events SET payload = ? WHERE id = ?",
                (json.dumps(parsed), row["id"]),
            )
    assert removed == 1
    assert project(conn)["warnings"] == 1
    conn.close()


DRAFT_FIXTURE = Path(__file__).parent / "fixtures" / "draft_session.log"


def test_a_draft_session_is_kept_raw_and_projects_to_nothing(tmp_path):
    """Draft was deleted from the product (2026-10-01), not its evidence:
    its log entries still ingest verbatim, so a draft feature that returns
    can backfill from ``raw_events``, and a rebuild must pass over them
    without a warning or a row. draft_session.log is one Quick Draft and
    nothing else: 84 ``BotDraftDraftPick`` entries, 42 requests and 42
    responses, in ``fixture_peek.py index``."""
    conn = open_database(tmp_path / "d.db")
    ingest_file(conn, DRAFT_FIXTURE, locale_hint="mdy")
    picks = conn.execute(
        "SELECT COUNT(*) FROM raw_events WHERE label = 'BotDraftDraftPick'"
    ).fetchone()[0]
    assert picks == 84
    result = project(conn)
    assert result["warnings"] == 0
    assert result["matches"] == 0
    conn.close()


# --- request deduplication (poll-boundary twins, migration 042) ------------
#
# Ground truth for request A's id/Name/MainDeck: tests/fixtures/match_session.log
# entry 1 (fixture_peek.py show tests/fixtures/match_session.log --entry 1) —
# a real, already-anonymized DeckUpsertDeckV3 capture. request B reuses the
# same shape with only Name and id changed by hand, since the fixture has no
# second DeckUpsertDeckV3/EventSetDeckV3 naming the same card list something
# else to draw a real pair from.

_SPELLELEMENTALS_MAIN_DECK = [
    (91584, 4), (86835, 4), (98392, 4), (102775, 2), (93122, 4), (102793, 4),
    (90421, 2), (92126, 2), (102698, 2), (102670, 4), (102774, 4), (102578, 1),
    (102508, 3), (97169, 6), (95062, 4), (75876, 4), (68738, 4), (79089, 2),
]
_REQUEST_A_ID = "237864eb-1e48-49ca-9523-d91540d95da8"


def _deck_request_payload(name: str, request_id: str | None) -> str:
    """DeckUpsertDeckV3, shaped like the real entry cited above: only
    ``Deck.MainDeck`` feeds ``deck_identity`` and only ``Summary.Name``/
    ``Attributes``/``DeckId`` feed ``_handle_deck_request``, so every other
    real field (Sideboard, CardSkins, PreferredCosmetics, ...) is trimmed."""
    inner = json.dumps({
        "Summary": {
            "DeckId": "b3ce5e2d-4761-446f-97ee-2c552b3bef9f",
            "Name": name,
            "Attributes": [
                {"name": "Version", "value": "11"},
                {"name": "Format", "value": "TraditionalStandard"},
            ],
        },
        "Deck": {
            "MainDeck": [
                {"cardId": cid, "quantity": qty} for cid, qty in _SPELLELEMENTALS_MAIN_DECK
            ]
        },
    })
    payload: dict = {"request": inner}
    if request_id is not None:
        payload["id"] = request_id
    return json.dumps(payload)


def _seed_deck_match(conn) -> None:
    """authenticateResponse + connectResp.deckMessage + a Playing room state
    for the same maindeck — the minimum ``project()`` needs before a deck_id
    is attached to a real ``MatchState`` and ``decks`` gets a row at all
    (matches.py's own comment above that INSERT: "decks holds played decks
    alone")."""
    flat = [cid for cid, qty in _SPELLELEMENTALS_MAIN_DECK for _ in range(qty)]
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        ("seed-auth", "Player.log", "event", None,
         '{"authenticateResponse": {"clientId": "SELF"}}'),
    )
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        ("seed-connect", "Player.log", "event", None,
         json.dumps({"greToClientEvent": {"greToClientMessages": [
             {"connectResp": {"deckMessage": {"deckCards": flat, "sideboardCards": []}}}
         ]}})),
    )
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        ("seed-room", "Player.log", "event", None,
         json.dumps({"matchGameRoomStateChangedEvent": {"gameRoomInfo": {
             "gameRoomConfig": {"matchId": "m1", "reservedPlayers": [
                 {"userId": "SELF", "systemSeatId": 1, "teamId": 1},
                 {"userId": "OPP", "systemSeatId": 2, "teamId": 2},
             ]},
             "stateType": "MatchGameRoomStateType_Playing",
         }}})),
    )


def test_stale_deck_name_from_an_out_of_order_twin_is_not_replayed(tmp_path):
    """The poll-boundary bug (docs/architecture.md's Idempotency section,
    migration 042) stores a real request twice: once with logged_at=NULL from
    the poll that first saw it, once — the twin — with a real timestamp from
    a later whole-file re-read, at a higher raw_events.id. Replaying
    raw_events in id order therefore plays the twin *after* any request that
    legitimately came after the original in Arena's own timeline — here, a
    rename (request B) — reverting the deck back to its old name unless the
    twin is recognized and skipped."""
    conn = open_database(tmp_path / "stale.db")
    _seed_deck_match(conn)
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        ("req-a", "Player.log", "request", "DeckUpsertDeckV3",
         _deck_request_payload("Spellelementals", _REQUEST_A_ID)),
    )
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        ("req-b", "Player.log", "request", "DeckUpsertDeckV3",
         _deck_request_payload("Renamed Deck", "gen-b-0001")),
    )
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("req-a-twin", "Player.log", "2026-08-13T15:10:00", "request", "DeckUpsertDeckV3",
         _deck_request_payload("Spellelementals", _REQUEST_A_ID)),
    )
    counts = project(conn)
    row = conn.execute("SELECT name FROM decks").fetchone()
    assert row["name"] == "Renamed Deck"
    assert counts["duplicate_requests"] == 1
    conn.close()


def test_duplicate_request_borrows_the_twins_timestamp(tmp_path):
    """The first occurrence of a request id is the one replayed (previous
    test); when it has logged_at=NULL, it borrows the twin's own timestamp
    rather than staying NULL — the same request's real header time, not a
    guess. deck_guids.last_seen is a real column that carries this through."""
    conn = open_database(tmp_path / "borrow.db")
    _seed_deck_match(conn)
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        ("req-a", "Player.log", "request", "DeckUpsertDeckV3",
         _deck_request_payload("Spellelementals", _REQUEST_A_ID)),
    )
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("req-a-twin", "Player.log", "2026-08-13T15:10:00", "request", "DeckUpsertDeckV3",
         _deck_request_payload("Spellelementals", _REQUEST_A_ID)),
    )
    project(conn)
    row = conn.execute("SELECT last_seen FROM deck_guids").fetchone()
    assert row["last_seen"] == "2026-08-13T15:10:00"
    conn.close()


def test_request_with_no_string_id_is_never_deduplicated(tmp_path):
    """Only a request whose payload carries its own top-level string ``id``
    is eligible for the poll-boundary dedup — a request missing that field
    entirely (Arena's real shape too, see
    test_deck_summary_without_a_name_still_yields_format_and_guid) must be
    replayed unconditionally rather than treated as a duplicate of nothing."""
    conn = open_database(tmp_path / "noid.db")
    _seed_deck_match(conn)
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        ("req-first", "Player.log", "request", "DeckUpsertDeckV3",
         _deck_request_payload("First Name", None)),
    )
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) VALUES (?, ?, ?, ?, ?)",
        ("req-second", "Player.log", "request", "DeckUpsertDeckV3",
         _deck_request_payload("Second Name", None)),
    )
    counts = project(conn)
    row = conn.execute("SELECT name FROM decks").fetchone()
    assert row["name"] == "Second Name"  # both replayed; later request wins
    assert counts["duplicate_requests"] == 0
    conn.close()


def test_duplicate_requests_key_present_even_when_zero(db):
    """The count key exists on every project() call, not only when a twin was
    actually found — a caller must be able to read it unconditionally."""
    counts = project(db)
    assert counts["duplicate_requests"] == 0


def test_unparseable_payload_warning_names_the_raw_events_id(tmp_path, caplog):
    """project()'s own warning names the offending row so a real corrupt
    payload can be found again. Projector.feed's own wording (the text entry
    point a direct caller uses, with no row id available at all — see
    test_malformed_payload_does_not_halt_projection) is different and stays
    that way; only project()'s own call site is asked to carry the id."""
    conn = open_database(tmp_path / "bad.db")
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES ('bad-digest', 'Player.log', 'event', 'BadEvent', '{not json')"
    )
    bad_id = conn.execute(
        "SELECT id FROM raw_events WHERE digest = 'bad-digest'"
    ).fetchone()[0]
    with caplog.at_level(logging.WARNING):
        project(conn)
    assert any(f"id={bad_id})" in r.message for r in caplog.records)
    conn.close()


def test_unknown_fields_are_tolerated():
    p = Projector()
    p.feed("event", None, '{"someBrandNewEvent2027": {"nested": true}}', None)
    assert p.warnings == 0


def test_missing_self_identity_yields_incomplete_not_loss():
    """An abandoned or credential-less session must not be scored as a loss."""
    p = Projector()
    p.feed(
        "event",
        None,
        '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {'
        '"gameRoomConfig": {"matchId": "m1", "reservedPlayers": ['
        '{"userId": "A", "systemSeatId": 1, "teamId": 1}]},'
        '"stateType": "MatchGameRoomStateType_Playing"}}}',
        None,
    )
    assert p.matches["m1"].result == "incomplete"


def test_room_state_unknown_self_assigns_no_seats():
    """A real Playing payload — tests/fixtures/match_session.log entry 5
    (fixture_peek.py show tests/fixtures/match_session.log --entry 5, match
    fd5624a4, already anonymized) — fed without a preceding
    authenticateResponse, so self.self_user_id stays None. Before this fix,
    every reservedPlayers entry fell into the "not self" branch, making the
    *last* player in the list the "opponent" — which can just as easily be
    the user's own seat. Rule 4: unknown means null, never a guess. event_id
    is kept regardless, since it isn't seat-specific."""
    p = Projector()
    p.feed(
        "event",
        "MatchGameRoomStateChangedEvent",
        json.dumps({
            "transactionId": "10e65755-aacd-4787-8839-b3cbd2668d5d",
            "requestId": 2,
            "timestamp": "1786643359690",
            "matchGameRoomStateChangedEvent": {
                "gameRoomInfo": {
                    "gameRoomConfig": {
                        "reservedPlayers": [
                            {
                                "userId": "AAAAAAAAAAAAAAA1",
                                "playerName": "OppPlayerOne",
                                "systemSeatId": 1,
                                "teamId": 1,
                                "courseId": "Avatar_Basic_Teferi",
                                "sessionId": "00000000-0000-0000-0000-000000000000",
                                "platformId": "Windows",
                                "eventId": "Traditional_Ladder",
                            },
                            {
                                "userId": "SELFCLIENTID0001",
                                "playerName": "SelfPlayer",
                                "systemSeatId": 2,
                                "teamId": 2,
                                "courseId": "Avatar_Basic_Iroh_TLA",
                                "sessionId": "00000000-0000-0000-0000-000000000000",
                                "platformId": "SteamWindows",
                                "eventId": "Traditional_Ladder",
                            },
                        ],
                        "matchId": "fd5624a4-d970-40eb-80aa-fba9d2ce17b3",
                    },
                    "stateType": "MatchGameRoomStateType_Playing",
                    "players": [
                        {"userId": "AAAAAAAAAAAAAAA1", "playerName": "OppPlayerOne",
                         "systemSeatId": 1, "teamId": 1},
                        {"userId": "SELFCLIENTID0001", "playerName": "SelfPlayer",
                         "systemSeatId": 2, "teamId": 2},
                    ],
                },
            },
        }),
        None,
    )
    state = p.matches["fd5624a4-d970-40eb-80aa-fba9d2ce17b3"]
    assert state.self_seat is None
    assert state.self_team is None
    assert state.self_user_id is None
    assert state.opponent_seat is None
    assert state.opponent_user_id is None
    assert state.opponent_name is None
    assert state.event_id == "Traditional_Ladder"
    assert p.warnings == 1


def test_game_over_with_short_results_warns_and_leaves_result_unset():
    """results carries only game 1's entry, but this GameOver says
    gameNumber 2 — a result that has not arrived yet, never guessed via some
    other game's entry (live_state.py's _game_result_entry, reused here
    rather than reimplemented)."""
    p = Projector()
    p.feed("event", None, '{"authenticateResponse": {"clientId": "SELF"}}', None)
    p.feed(
        "event", None,
        '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {'
        '"gameRoomConfig": {"matchId": "m1", "reservedPlayers": ['
        '{"userId": "SELF", "systemSeatId": 1, "teamId": 1}, '
        '{"userId": "OPP", "systemSeatId": 2, "teamId": 2}]},'
        '"stateType": "MatchGameRoomStateType_Playing"}}}',
        None,
    )
    p.feed(
        "event", None,
        json.dumps({
            "greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
                "gameInfo": {
                    "matchID": "m1",
                    "gameNumber": 2,
                    "stage": "GameStage_GameOver",
                    "matchState": "MatchState_GameComplete",
                    "results": [
                        {"scope": "MatchScope_Game", "winningTeamId": 1,
                         "reason": "ResultReason_Concede"},
                    ],
                },
            }}]},
        }),
        None,
    )
    game = p.matches["m1"].game(2)
    assert game.result is None
    assert p.warnings == 1


def test_game_over_with_empty_results_warns_and_leaves_result_unset():
    """results is present but entirely empty — same rule as the short-results
    case above, one edge apart (0 entries rather than 1 short of gameNumber)."""
    p = Projector()
    p.feed("event", None, '{"authenticateResponse": {"clientId": "SELF"}}', None)
    p.feed(
        "event", None,
        '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {'
        '"gameRoomConfig": {"matchId": "m1", "reservedPlayers": ['
        '{"userId": "SELF", "systemSeatId": 1, "teamId": 1}, '
        '{"userId": "OPP", "systemSeatId": 2, "teamId": 2}]},'
        '"stateType": "MatchGameRoomStateType_Playing"}}}',
        None,
    )
    p.feed(
        "event", None,
        json.dumps({
            "greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
                "gameInfo": {
                    "matchID": "m1",
                    "gameNumber": 1,
                    "stage": "GameStage_GameOver",
                    "matchState": "MatchState_GameComplete",
                    "results": [],
                },
            }}]},
        }),
        None,
    )
    game = p.matches["m1"].game(1)
    assert game.result is None
    assert p.warnings == 1


# --- card events ------------------------------------------------------------
# Expected values read straight out of the fixture's ZoneTransfer annotations,
# not from running the projector. Seats are Arena's own: self is seat 2 in
# MATCH_LOSS and seat 1 in MATCH_WIN, so the same seat number means "us" in one
# match and "them" in the other.


def card_events(db, match_id, game_number):
    return db.execute(
        "SELECT * FROM card_events WHERE match_id = ? AND game_number = ? ORDER BY seq",
        (match_id, game_number),
    ).fetchall()


def test_draws_record_the_card_we_drew(db):
    """MATCH_WIN game 1, annotation 66: seat 1 (us) draws grpId 86835."""
    draws = [r for r in card_events(db, MATCH_WIN, 1) if r["category"] == "Draw"]
    ours = [r for r in draws if r["seat"] == 1]
    assert [r["grp_id"] for r in ours] == [86835]
    assert (ours[0]["zone_src"], ours[0]["zone_dest"]) == ("ZoneType_Library", "ZoneType_Hand")


def test_opponent_draws_are_recorded_without_a_card(db):
    """Annotation 107 in MATCH_WIN game 1: seat 2 draws, and Arena sends no
    game object for it. The event is real; the card is not knowable."""
    theirs = [
        r for r in card_events(db, MATCH_WIN, 1)
        if r["category"] == "Draw" and r["seat"] == 2
    ]
    assert len(theirs) == 1
    assert theirs[0]["grp_id"] is None


def test_lands_and_spells_are_recorded_for_both_seats(db):
    """MATCH_WIN game 3, annotations 51 and 70: we play grpId 68738, the
    opponent plays 102716."""
    plays = {
        (r["seat"], r["category"]): r["grp_id"]
        for r in card_events(db, MATCH_WIN, 3)
        if r["category"] == "PlayLand"
    }
    assert plays == {(1, "PlayLand"): 68738, (2, "PlayLand"): 102716}


def test_rekeyed_spell_keeps_its_identity(db):
    """MATCH_LOSS game 1, annotations 68 then 69: the cast card is re-keyed
    257 -> 314 immediately before the transfer that names 314. Reading them
    out of order would leave the spell anonymous."""
    cast = [r for r in card_events(db, MATCH_LOSS, 1) if r["category"] == "CastSpell"]
    assert [(r["seat"], r["grp_id"]) for r in cast] == [(2, 102774)]
    assert (cast[0]["zone_src"], cast[0]["zone_dest"]) == ("ZoneType_Hand", "ZoneType_Stack")


def test_mulligan_put_backs_precede_the_first_turn(db):
    """MATCH_WIN game 1 annotation 42 moves a card hand -> library before any
    turnInfo has arrived, so it has no turn to belong to."""
    first = card_events(db, MATCH_WIN, 1)[0]
    assert (first["category"], first["zone_dest"]) == ("Put", "ZoneType_Library")
    assert first["turn_number"] is None


def test_card_event_sequence_is_dense_per_game(db):
    """seq is the order observed within a game, so a gap would mean a dropped
    transfer rather than a hidden one."""
    for match_id, game_number in ((MATCH_LOSS, 1), (MATCH_WIN, 1), (MATCH_WIN, 3)):
        rows = card_events(db, match_id, game_number)
        assert [r["seq"] for r in rows] == list(range(len(rows)))


def test_card_events_projection_is_idempotent(db):
    before = [dict(r) for r in db.execute("SELECT * FROM card_events ORDER BY match_id, seq")]
    project(db)
    after = [dict(r) for r in db.execute("SELECT * FROM card_events ORDER BY match_id, seq")]
    assert before == after


# --- library counts ---------------------------------------------------------


def test_turns_count_both_libraries_from_the_zone(db):
    """MATCH_WIN (self seat 1) game 1: the fixture's library zones hold 54 for
    seat 1 and 60 for seat 2 when turn 1 ends, then 52 and 60 at turn 2."""
    rows = {
        r["turn_number"]: (r["self_library"], r["opp_library"])
        for r in db.execute(
            "SELECT * FROM turns WHERE match_id = ? AND game_number = 1", (MATCH_WIN,)
        )
    }
    assert rows[1] == (54, 60)
    assert rows[2] == (52, 60)


# --- deck metadata ----------------------------------------------------------


def test_deck_format_is_recorded(db):
    """Arena's own spelling, from the deck request's Attributes."""
    row = db.execute("SELECT name, format FROM decks").fetchone()
    assert (row["name"], row["format"]) == ("Spellelementals", "TraditionalStandard")


def test_arena_deck_guid_is_recorded_alongside_the_content_hash(db):
    """The GUID is stable across deck edits, which the content hash is not.
    Stored now so normalizing deck versions later needs no re-read."""
    rows = db.execute("SELECT * FROM deck_guids").fetchall()
    assert len(rows) == 1
    assert rows[0]["arena_deck_id"] == "b3ce5e2d-4761-446f-97ee-2c552b3bef9f"
    assert (rows[0]["version"], rows[0]["format"]) == ("11", "TraditionalStandard")
    assert rows[0]["deck_id"] == db.execute("SELECT deck_id FROM decks").fetchone()["deck_id"]


def test_deck_guids_projection_is_idempotent(db):
    before = [dict(r) for r in db.execute("SELECT * FROM deck_guids")]
    project(db)
    assert [dict(r) for r in db.execute("SELECT * FROM deck_guids")] == before


def test_event_set_deck_request_carries_the_same_summary_as_an_upsert():
    """EventSetDeckV3 is sent when a deck is chosen for an event, and wraps the
    same escaped-JSON Summary as DeckUpsertDeckV3. Shape taken from the real
    log, where the fixture's curated subset happens to contain only upserts."""
    p = Projector()
    inner = json.dumps(
        {
            "EventName": "Traditional_Ladder",
            "Summary": {
                "DeckId": "b3ce5e2d-4761-446f-97ee-2c552b3bef9f",
                "Name": "Spellelementals",
                "Attributes": [
                    {"name": "Version", "value": "11"},
                    {"name": "Format", "value": "TraditionalStandard"},
                ],
            },
            "Deck": {"MainDeck": [{"cardId": 1, "quantity": 4}]},
        }
    )
    p.feed("request", "EventSetDeckV3", json.dumps({"id": "x", "request": inner}), None)
    deck_id, _ = deck_identity([1, 1, 1, 1])
    assert p.deck_names[deck_id] == "Spellelementals"
    assert p.deck_formats[deck_id] == "TraditionalStandard"
    assert p.deck_guids[deck_id] == {
        "b3ce5e2d-4761-446f-97ee-2c552b3bef9f": ("11", "TraditionalStandard", None)
    }


def test_deck_summary_without_a_name_still_yields_format_and_guid():
    """Each field is learned independently: a summary missing one must not
    discard the others."""
    p = Projector()
    inner = json.dumps(
        {
            "Summary": {
                "DeckId": "guid-1",
                "Attributes": [{"name": "Format", "value": "Standard"}],
            },
            "Deck": {"MainDeck": [{"cardId": 7, "quantity": 1}]},
        }
    )
    p.feed("request", "DeckUpsertDeckV3", json.dumps({"request": inner}), None)
    deck_id, _ = deck_identity([7])
    assert deck_id not in p.deck_names
    assert p.deck_formats[deck_id] == "Standard"
    assert "guid-1" in p.deck_guids[deck_id]


# --- has_match_boundary ------------------------------------------------------
#
# match_session.log opens two match rooms (MatchGameRoomStateType_Playing):
# raw id 6 (match fd5624a4) and raw id 20 (match fa7a4d16) — confirmed via
# fixture_peek.py show --entry 5 / --entry 19, both reading
# "stateType": "MatchGameRoomStateType_Playing". Raw ids 17 and 34 are the
# same two matches' MatchCompleted events and must not count as a boundary.


def test_has_match_boundary_true_across_a_room_opening(db):
    assert has_match_boundary(db, after_event_id=0) is True
    assert has_match_boundary(db, after_event_id=6) is True  # the second room, id 20


def test_has_match_boundary_false_once_past_every_room_opening(db):
    assert has_match_boundary(db, after_event_id=20) is False


def test_has_match_boundary_ignores_match_completed(db):
    """id 17 is fd5624a4's MatchCompleted, not a room opening — nothing
    between it and fa7a4d16's own room at id 20 should read as a boundary
    a caller hasn't already seen."""
    assert has_match_boundary(db, after_event_id=17) is True  # id 20 still ahead
    assert has_match_boundary(db, after_event_id=34) is False  # nothing after the last completion
