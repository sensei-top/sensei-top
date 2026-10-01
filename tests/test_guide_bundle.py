"""Tests for guide/bundle.py: assembling one deck's whole evidence bundle.
"""

from __future__ import annotations

import json

import pytest

from sensei_top.db import open_database
from sensei_top.guide.bundle import build_deck_guide


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_deck_and_match(conn, deck_id, match_id, maindeck, sideboard, result="win"):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, 'My Deck', 'Standard', ?, 't', 't')",
        (deck_id, json.dumps({"maindeck": maindeck, "sideboard": sideboard})),
    )
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, 'e', ?, 1, 2, 'u', 'n', "
        "'2026-08-15T00:00:00', 't', ?, 1, 0, 'r')",
        (match_id, deck_id, result),
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 8, 0, 0)",
        (match_id, result),
    )


def test_unknown_key_returns_none(conn):
    conn.commit()
    assert build_deck_guide(conn, "deck:nonexistent") is None


def test_guide_assembles_with_no_matches_gap(conn):
    """A deck resolved by identity but with no matches must still produce a
    guide, with the gap stated rather than the whole thing failing."""
    _insert_deck_and_match(conn, "d1", "m1", [1, 1, 1, 1], [])
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    assert guide is not None
    assert guide.provenance.deck.key == "deck:d1"
    assert guide.list_diff is None  # no archetype definitions loaded
    assert any("classified" in g for g in guide.gaps)


def test_no_reset_gap_is_stated(conn):
    """With legality data present and nothing banned, "no reset" is a real
    answer about the corpus and may be stated as one."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_text, standard_legality) "
        "VALUES (1, 'Some Card', 'Text.', 'legal')"
    )
    _insert_deck_and_match(conn, "d1", "m1", [1, 1, 1, 1], [])
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    assert guide.provenance.reset is None
    assert any("No format reset" in g for g in guide.gaps)
    assert not any("legality" in g for g in guide.gaps)


def test_missing_legality_is_reported_as_a_hole_not_as_no_reset(conn):
    """Without legality data no ban is detectable, so the guide must not
    claim the corpus has no reset — it has no way to know, and every field
    number in it may pool across one."""
    conn.execute("INSERT INTO cards (grp_id, name, oracle_text) VALUES (1, 'Some Card', 'Text.')")
    _insert_deck_and_match(conn, "d1", "m1", [1, 1, 1, 1], [])
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    assert guide.provenance.reset is None
    assert not any("No format reset was detected" in g for g in guide.gaps)
    gap = next(g for g in guide.gaps if "legality" in g)
    assert "cards --scryfall" in gap


def test_oracle_coverage_gap_when_text_is_missing(conn):
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (1, 'Some Card')")
    _insert_deck_and_match(conn, "d1", "m1", [1, 1, 1, 1], [])
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    assert guide.provenance.oracle_coverage == (0, 1)
    assert any("Rules text is missing" in g for g in guide.gaps)


def test_leaks_and_leaks_all_decks_are_both_present(conn):
    _insert_deck_and_match(conn, "d1", "m1", [1, 1, 1, 1], [])
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    assert isinstance(guide.leaks, tuple)
    assert isinstance(guide.leaks_all_decks, tuple)
