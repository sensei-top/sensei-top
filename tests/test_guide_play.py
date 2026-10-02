"""Tests for guide/play.py: the deck's own play evidence, generalised from
a one-off script written for a single deck.

Two invariants pinned here on purpose, because both shipped wrong once in
the hand-written version this module replaces:
* the player-turn conversion is (turn_number + 1) // 2
* a game where the tracked card never resolved must land in the
  "never resolved" bucket, not be silently dropped from the count
"""

from __future__ import annotations

import json

import pytest

from sensei_top.db import open_database
from sensei_top.guide.deck import DeckIdentity
from sensei_top.guide.play import (
    GameLengthBucket,
    MulliganBucket,
    WLTally,
    board_curve,
    game_length,
    key_card_timing,
    mulligan_record,
    mulligan_split,
    zone_curve,
)


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


DECK_ID = "deckhash1"


def identity_for(conn, maindeck_grp_ids) -> DeckIdentity:
    return DeckIdentity(
        key=f"deck:{DECK_ID}", arena_deck_id=None, name="Test Deck", format="Standard",
        deck_ids=(DECK_ID,), matches=0, match_wins=0, match_losses=0, games_won=0,
        games_lost=0, first_played=None, last_played=None,
        current_cards={"maindeck": maindeck_grp_ids, "sideboard": []},
    )


def _insert_deck(conn, deck_id=DECK_ID, cards=None):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, 'Test Deck', 'Standard', ?, 't', 't')",
        (deck_id, json.dumps(cards or {"maindeck": [], "sideboard": []})),
    )


def _insert_match(conn, match_id, deck_id=DECK_ID, self_seat=1, opponent_seat=2):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, 'e', ?, ?, ?, 'u', 'n', 't', 't', "
        "'win', 1, 0, 'r')",
        (match_id, deck_id, self_seat, opponent_seat),
    )


def _insert_game(conn, match_id, game_number, result, *, turn_count=10, self_mulligans=0):
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, ?, 1, ?, NULL, ?, ?, 0)",
        (match_id, game_number, result, turn_count, self_mulligans),
    )


def _insert_turn(conn, match_id, game_number, turn_number, *, active_seat=1, self_seat=1,
                  self_life=20, self_hand=7, self_lands=2, opp_permanents=0):
    conn.execute(
        "INSERT INTO turns (match_id, game_number, turn_number, active_seat, self_life, "
        "opp_life, self_hand, opp_hand, self_lands, self_permanents, opp_permanents) "
        "VALUES (?, ?, ?, ?, ?, 20, ?, 7, ?, 0, ?)",
        (match_id, game_number, turn_number, active_seat if active_seat == self_seat else self_seat,
         self_life, self_hand, self_lands, opp_permanents),
    )


# --- board_curve --------------------------------------------------------


def test_board_curve_splits_by_result_and_own_turn_order(conn):
    """Only rows where active_seat == self_seat count as "our" turn — the
    seen counter walks in turn_number order, giving each game a 1-based
    own-turn index independent of the shared turn_number."""
    _insert_deck(conn)
    _insert_match(conn, "m1", self_seat=1)
    _insert_game(conn, "m1", 1, "win")
    # our turns are turn_number 1, 3, 5 (opponent has 2, 4)
    _insert_turn(conn, "m1", 1, 1, active_seat=1, self_hand=7, self_life=20)
    _insert_turn(conn, "m1", 1, 3, active_seat=1, self_hand=5, self_life=19)
    conn.commit()

    curve = board_curve(conn, identity_for(conn, []))
    assert curve["win"]["1"].hand == 7.0
    assert curve["win"]["1"].n == 1
    assert curve["win"]["2"].hand == 5.0


def test_board_curve_ignores_incomplete_games(conn):
    _insert_deck(conn)
    _insert_match(conn, "m1")
    _insert_game(conn, "m1", 1, "incomplete")
    _insert_turn(conn, "m1", 1, 1, active_seat=1)
    conn.commit()
    assert board_curve(conn, identity_for(conn, [])) == {}


def test_board_curve_empty_deck_ids_returns_empty(conn):
    identity = DeckIdentity(
        key="deck:none", arena_deck_id=None, name=None, format=None, deck_ids=(),
        matches=0, match_wins=0, match_losses=0, games_won=0, games_lost=0,
        first_played=None, last_played=None, current_cards={},
    )
    assert board_curve(conn, identity) == {}


# --- key_card_timing -----------------------------------------------------


def _insert_card(conn, grp_id, name, *, oracle_text="Some rules text.", type_line="Creature",
                  mana_cost="{3}{U}{U}"):
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_text, type_line, mana_cost) "
        "VALUES (?, ?, ?, ?, ?)",
        (grp_id, name, oracle_text, type_line, mana_cost),
    )


def _insert_card_event(conn, match_id, game_number, seq, turn_number, seat, grp_id, category):
    conn.execute(
        "INSERT INTO card_events (match_id, game_number, seq, turn_number, seat, grp_id, "
        "category) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (match_id, game_number, seq, turn_number, seat, grp_id, category),
    )


def test_key_card_never_resolving_lands_in_the_never_resolved_bucket(conn):
    """The recorded bug: iterating only games where the card resolved would
    silently drop this game from the count entirely."""
    _insert_card(conn, 100, "Big Creature")
    _insert_deck(conn, cards={"maindeck": [100, 100, 100], "sideboard": []})
    _insert_match(conn, "m1", self_seat=1)
    _insert_game(conn, "m1", 1, "loss")
    # no card_events row for Big Creature in this game at all
    conn.commit()

    timing = key_card_timing(conn, identity_for(conn, [100, 100, 100]))
    assert timing["Big Creature"]["never resolved"] == WLTally(w=0, l=1)


def test_key_card_timing_bucket_boundaries(conn):
    """turn_number 8 -> player turn (8+1)//2 = 4 -> "by T4"; turn_number 9
    -> player turn 5 -> "T5-6". Pins the (turn_number + 1) // 2 conversion."""
    _insert_card(conn, 100, "Big Creature")
    _insert_deck(conn, cards={"maindeck": [100, 100, 100]})
    _insert_match(conn, "m1", self_seat=1)
    _insert_game(conn, "m1", 1, "win")
    _insert_card_event(conn, "m1", 1, 0, 8, 1, 100, "Resolve")
    _insert_match(conn, "m2", self_seat=1)
    _insert_game(conn, "m2", 1, "win")
    _insert_card_event(conn, "m2", 1, 0, 9, 1, 100, "Resolve")
    conn.commit()

    timing = key_card_timing(conn, identity_for(conn, [100, 100, 100]))
    assert timing["Big Creature"]["by T4"] == WLTally(w=1, l=0)
    assert timing["Big Creature"]["T5-6"] == WLTally(w=1, l=0)


def test_key_card_timing_ignores_cards_below_three_copies(conn):
    _insert_card(conn, 100, "One Of")
    _insert_deck(conn, cards={"maindeck": [100]})
    _insert_match(conn, "m1")
    _insert_game(conn, "m1", 1, "win")
    conn.commit()
    assert key_card_timing(conn, identity_for(conn, [100])) == {}


def test_key_card_timing_ranks_finishers_first(conn):
    """A high-mana-value creature (finisher-eligible) is chosen over a
    cheap cantrip when both clear the 3-copy threshold and the cap trims
    the list."""
    _insert_card(conn, 100, "Cheap Cantrip", oracle_text="Draw a card.",
                 type_line="Sorcery", mana_cost="{U}")
    _insert_card(conn, 200, "Big Finisher", oracle_text="Flying.",
                 type_line="Creature", mana_cost="{5}{U}{U}")
    _insert_deck(conn, cards={"maindeck": [100, 100, 100, 200, 200, 200]})
    _insert_match(conn, "m1")
    _insert_game(conn, "m1", 1, "win")
    conn.commit()

    from sensei_top.guide.play import _choose_key_cards
    ranked = _choose_key_cards(conn, identity_for(conn, [100, 100, 100, 200, 200, 200]))
    assert ranked[0] == "Big Finisher"


# --- zone_curve ------------------------------------------------------------


def _insert_turn_zone(conn, match_id, game_number, turn_number, seat, zone, idx, grp_id):
    conn.execute(
        "INSERT INTO turn_zones (match_id, game_number, turn_number, seat, zone, idx, "
        "instance_id, grp_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (match_id, game_number, turn_number, seat, zone, idx, idx + 1000, grp_id),
    )


def test_zone_curve_diverges_between_win_and_loss(conn):
    _insert_card(conn, 100, "Instant One", type_line="Instant")
    _insert_deck(conn)
    _insert_match(conn, "m1", self_seat=1)
    _insert_game(conn, "m1", 1, "win")
    _insert_turn_zone(conn, "m1", 1, 5, 1, "graveyard", 0, 100)
    _insert_turn_zone(conn, "m1", 1, 5, 1, "graveyard", 1, 100)
    _insert_match(conn, "m2", self_seat=1)
    _insert_game(conn, "m2", 1, "loss")
    _insert_turn_zone(conn, "m2", 1, 5, 1, "graveyard", 0, 100)
    conn.commit()

    curve = zone_curve(conn, identity_for(conn, []))
    assert curve["graveyard/Instant"].win["3"] == 2.0  # player turn (5+1)//2 = 3
    assert curve["graveyard/Instant"].loss["3"] == 1.0


def test_zone_curve_breaks_a_divergence_tie_by_zone_and_bucket_not_by_row_order(conn):
    """Two buckets with the same win/loss divergence: the one shown at
    ``top_n=1`` is the first by (zone, bucket), whichever the query returned
    first. The Sorcery rows go in first, so row order would pick Sorcery."""
    _insert_card(conn, 100, "Instant One", type_line="Instant")
    _insert_card(conn, 101, "Sorcery One", type_line="Sorcery")
    _insert_deck(conn)
    _insert_match(conn, "m1", self_seat=1)
    _insert_game(conn, "m1", 1, "win")
    _insert_match(conn, "m2", self_seat=1)
    _insert_game(conn, "m2", 1, "loss")
    for base, grp_id in ((0, 101), (10, 100)):
        # one copy in the loss, two in the win: a divergence of 1 for each bucket
        _insert_turn_zone(conn, "m1", 1, 5, 1, "graveyard", base, grp_id)
        _insert_turn_zone(conn, "m1", 1, 5, 1, "graveyard", base + 1, grp_id)
        _insert_turn_zone(conn, "m2", 1, 5, 1, "graveyard", base, grp_id)
    conn.commit()

    curve = zone_curve(conn, identity_for(conn, []), top_n=1)
    assert list(curve) == ["graveyard/Instant"]


# --- mulligan_record / game_length -----------------------------------------


def test_mulligan_record_splits_kept_seven_from_mulliganed(conn):
    _insert_deck(conn)
    _insert_match(conn, "m1")
    _insert_game(conn, "m1", 1, "win", self_mulligans=0)
    _insert_match(conn, "m2")
    _insert_game(conn, "m2", 1, "loss", self_mulligans=1)
    conn.commit()

    record = mulligan_record(conn, identity_for(conn, []))
    assert record["kept_seven"] == MulliganBucket(games=1, wins=1, losses=0)
    assert record["mulliganed"] == MulliganBucket(games=1, wins=0, losses=1)


def test_mulligan_split_is_the_definition_mulligan_record_now_calls(conn):
    """``mulligan_split`` takes a caller-built ``where``/``params`` pair
    instead of a deck identity, and returns ``(wins, games)`` rather than a
    ``MulliganBucket`` -- ``mulligan_record``'s own scoping (``m.match_id IN
    (SELECT match_id FROM v_match_deck WHERE deck_id IN (...))``) reproduced by hand
    here to pin that the two agree."""
    _insert_deck(conn)
    _insert_match(conn, "m1")
    _insert_game(conn, "m1", 1, "win", self_mulligans=0)
    _insert_match(conn, "m2")
    _insert_game(conn, "m2", 1, "loss", self_mulligans=1)
    conn.commit()

    split = mulligan_split(
        conn, "m.match_id IN (SELECT match_id FROM v_match_deck WHERE deck_id IN (?))", (DECK_ID,)
    )
    assert split["kept_seven"] == (1, 1)  # 1 win of 1 game
    assert split["mulliganed"] == (0, 1)  # 0 wins of 1 game


def test_game_length_medians_by_result(conn):
    _insert_deck(conn)
    _insert_match(conn, "m1")
    _insert_game(conn, "m1", 1, "win", turn_count=8)
    _insert_match(conn, "m2")
    _insert_game(conn, "m2", 1, "loss", turn_count=16)
    conn.commit()

    lengths = game_length(conn, identity_for(conn, []))
    assert lengths["win"] == GameLengthBucket(games=1, median_turns=8.0)
    assert lengths["loss"] == GameLengthBucket(games=1, median_turns=16.0)


def _insert_mtgo_match(conn, match_id, *, pick_deck_id=None):
    """An MTGO match as the projector writes it: no deck_id, no seats, no
    turns. ``pick_deck_id`` is the user's pick (``mtgo_match_pick``), the only
    place its deck can come from."""
    conn.execute(
        "INSERT INTO matches (match_id, started_at, ended_at, result, games_won, games_lost, "
        "source) VALUES (?, 't', 't', 'win', 1, 0, 'mtgo')",
        (match_id,),
    )
    if pick_deck_id is not None:
        conn.execute(
            "INSERT INTO mtgo_match_pick (match_id, deck_id, format) VALUES (?, ?, 'Modern')",
            (match_id, pick_deck_id),
        )


def test_a_picked_mtgo_match_counts_in_the_deck_play_record_and_an_unpicked_one_does_not(conn):
    _insert_deck(conn)
    _insert_match(conn, "arena1")
    _insert_game(conn, "arena1", 1, "win", turn_count=8, self_mulligans=0)
    _insert_mtgo_match(conn, "mtgo-picked", pick_deck_id=DECK_ID)
    _insert_game(conn, "mtgo-picked", 1, "loss", turn_count=14, self_mulligans=2)
    _insert_mtgo_match(conn, "mtgo-unpicked")
    _insert_game(conn, "mtgo-unpicked", 1, "loss", turn_count=30, self_mulligans=3)
    conn.commit()

    record = mulligan_record(conn, identity_for(conn, []))
    assert record["kept_seven"] == MulliganBucket(games=1, wins=1, losses=0)
    # the picked match's game is the only mulliganed one: the unpicked one is out
    assert record["mulliganed"] == MulliganBucket(games=1, wins=0, losses=1)

    lengths = game_length(conn, identity_for(conn, []))
    assert lengths["win"] == GameLengthBucket(games=1, median_turns=8.0)
    assert lengths["loss"] == GameLengthBucket(games=1, median_turns=14.0)


def test_a_pick_on_an_arena_match_never_moves_its_deck(conn):
    """v_match_deck applies a pick to an MTGO match only, so a stray row for an
    Arena match id leaves it under the deck the Arena log named."""
    _insert_deck(conn)
    _insert_deck(conn, "otherdeck")
    _insert_match(conn, "arena1")
    _insert_game(conn, "arena1", 1, "win", turn_count=8)
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) VALUES ('arena1', 'otherdeck', "
        "'Modern')"
    )
    conn.commit()

    assert game_length(conn, identity_for(conn, []))["win"].games == 1
    other = DeckIdentity(
        key="deck:otherdeck", arena_deck_id=None, name="Other", format="Standard",
        deck_ids=("otherdeck",), matches=0, match_wins=0, match_losses=0, games_won=0,
        games_lost=0, first_played=None, last_played=None, current_cards={},
    )
    assert game_length(conn, other) == {}
