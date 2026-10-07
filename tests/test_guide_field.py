"""Tests for guide/field.py: the field's shares and this deck's personal
rates, windowed around a format reset.
"""

from __future__ import annotations

import json

import pytest

import sensei_top.guide.field as field_mod
from sensei_top.db import open_database
from sensei_top.guide.deck import DeckIdentity
from sensei_top.guide.field import build_field, faced_archetypes, field_by_key, field_window
from sensei_top.guide.window import FormatReset


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _store_deck(conn, event_id, deck_ord, archetype_key, archetype_name, mainboard, *,
                 event_date, wins=0, losses=0):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', ?, 'Standard', 'B')",
        (event_id, event_date),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins, "
        "losses) VALUES (?, ?, ?, '[]', ?, ?)",
        (event_id, deck_ord, json.dumps(mainboard), wins, losses),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, ?, ?, ?, ?, 'archetype', 'now')",
        (event_id, deck_ord, archetype_key, archetype_name, archetype_name),
    )


def identity_for(deck_ids=()) -> DeckIdentity:
    return DeckIdentity(
        key="deck:x", arena_deck_id=None, name="My Deck", format="Standard",
        deck_ids=deck_ids, matches=0, match_wins=0, match_losses=0, games_won=0,
        games_lost=0, first_played=None, last_played=None, current_cards={},
    )


def test_share_denominator_is_every_classified_deck_not_the_displayed_top_n(conn):
    """An earlier hand-written guide's bug: summing only the top-N rows
    inflated every share by about 6 points. top_n=1 here would break this if
    the denominator were wrong."""
    for i in range(6):
        _store_deck(conn, f"a{i}", 0, "arch_a", "Archetype A", [], event_date="2026-08-15")
    for i in range(4):
        _store_deck(conn, f"b{i}", 0, "arch_b", "Archetype B", [], event_date="2026-08-15")
    conn.commit()

    field = build_field(conn, identity_for(), reset=None, top_n=1)
    assert field.classified_decks == 10
    a = next(s for s in field.shares if s.archetype == "Archetype A")
    assert a.share == pytest.approx(0.6)


def test_a_void_archetypes_personal_rate_is_marked_not_carryable(conn):
    """A pre-reset matchup rate must be rendered as void, not stale, once
    the opponent archetype has changed at the reset."""
    reset = FormatReset(date="2026-08-10", cards=("Badgermole Cub",), detected_from="test")
    for i in range(20):
        _store_deck(conn, f"pre{i}", 0, "changed_arch", "Mono-Green Landfall",
                    [{"count": 4, "name": "Badgermole Cub"}], event_date="2026-08-01")
    for i in range(5):
        _store_deck(conn, f"post{i}", 0, "changed_arch", "Mono-Green Landfall",
                    [{"count": 4, "name": "Forest"}], event_date="2026-08-15")
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'My Deck', 'Standard', '{}', 't', 't')"
    )
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, format) VALUES ('m1', 'e', 'd1', 1, 2, 'u', 'n', 't', "
        "'t', 'win', 2, 0, 'r', 'Standard')"
    )
    conn.execute(
        "INSERT INTO opponent_archetype (match_id, format, archetype_key, archetype_name, "
        "colors, label, method, confidence, cards_seen, conditions_met, conditions_unknown, "
        "evidence_json, classified_at) VALUES "
        "('m1', 'Standard', 'changed_arch', 'Mono-Green Landfall', 'G', 'Mono-Green Landfall', "
        "'archetype', 'high', 5, 3, 0, '[]', 'now')"
    )
    conn.commit()

    field = build_field(conn, identity_for(("d1",)), reset=reset)
    rate = next(r for r in field.personal_rates if r.archetype == "Mono-Green Landfall")
    assert rate.matches == 1
    assert rate.carryable is False


def test_movement_computed_between_pre_and_post_reset_shares(conn):
    reset = FormatReset(date="2026-08-10", cards=(), detected_from="test")
    for i in range(10):
        _store_deck(conn, f"pre{i}", 0, "a", "Archetype A", [], event_date="2026-08-01")
    for i in range(2):
        _store_deck(conn, f"post{i}", 0, "a", "Archetype A", [], event_date="2026-08-15")
    for i in range(8):
        _store_deck(conn, f"post_other{i}", 0, "b", "Archetype B", [], event_date="2026-08-15")
    conn.commit()

    field = build_field(conn, identity_for(), reset=reset)
    a = next(s for s in field.shares if s.archetype == "Archetype A")
    assert a.share_before_reset == pytest.approx(1.0)
    assert a.share == pytest.approx(0.2)
    assert a.movement == pytest.approx(0.2 - 1.0)


def test_no_reset_means_full_corpus_window(conn):
    for i in range(3):
        _store_deck(conn, f"e{i}", 0, "a", "Archetype A", [], event_date="2026-08-01")
    conn.commit()

    field = build_field(conn, identity_for(), reset=None)
    assert field.window_start is None
    assert field.classified_decks == 3


# --- field_window / field_by_key --------------------------------------------


def test_field_window_both_shapes():
    assert field_window("Standard", None) == ("e.format = ?", ["Standard"])
    assert field_window("Standard", "2026-08-01") == (
        "e.format = ? AND e.event_date >= ?", ["Standard", "2026-08-01"],
    )


def test_field_by_key_groups_variants_two_keys_can_share_a_name(conn):
    """One key with two name variants (3 "Rakdos Midrange" + 1 "Rakdos
    Sacrifice"), a second key sharing one of those names ("Rakdos
    Sacrifice" x2 under a different key), and one deck entirely before the
    window -- which must not count toward either key's variants or the
    true total."""
    _store_deck(conn, "a0", 0, "rakdos-midrange", "Rakdos Midrange", [], event_date="2026-08-15")
    _store_deck(conn, "a1", 0, "rakdos-midrange", "Rakdos Midrange", [], event_date="2026-08-15")
    _store_deck(conn, "a2", 0, "rakdos-midrange", "Rakdos Midrange", [], event_date="2026-08-15")
    _store_deck(conn, "a3", 0, "rakdos-midrange", "Rakdos Sacrifice", [], event_date="2026-08-15")
    _store_deck(conn, "b0", 0, "mono-red-sac", "Rakdos Sacrifice", [], event_date="2026-08-15")
    _store_deck(conn, "b1", 0, "mono-red-sac", "Rakdos Sacrifice", [], event_date="2026-08-15")
    _store_deck(conn, "old0", 0, "rakdos-midrange", "Rakdos Midrange", [], event_date="2026-07-01")
    conn.commit()

    by_key, total = field_by_key(conn, "Standard", "2026-08-10")
    assert total == 6  # the pre-window deck (old0) does not count
    assert by_key["rakdos-midrange"] == (("Rakdos Midrange", 3), ("Rakdos Sacrifice", 1))
    assert by_key["mono-red-sac"] == (("Rakdos Sacrifice", 2),)


def test_shares_for_window_keeps_the_top_n_largest_over_the_true_total(conn):
    """top_n=2 keeps only the two largest of three archetypes, while the
    total stays the whole window's -- the denominator every share divides by
    is never the truncated top-n sum."""
    for i in range(10):
        _store_deck(conn, f"a{i}", 0, "arch_a", "Archetype A", [], event_date="2026-08-15")
    for i in range(8):
        _store_deck(conn, f"b{i}", 0, "arch_b", "Archetype B", [], event_date="2026-08-15")
    for i in range(6):
        _store_deck(conn, f"c{i}", 0, "arch_c", "Archetype C", [], event_date="2026-08-15")
    conn.commit()

    presence, total = field_mod._shares_for_window(conn, "Standard", None, top_n=2)
    assert [name for name, _ in presence] == ["Archetype A", "Archetype B"]
    assert total == 24  # 10 + 8 + 6, the true total, not the truncated top-2 sum


def _mtgo_match_vs(conn, match_id, archetype_key, archetype_name, *, pick_deck_id=None):
    """An MTGO match (no deck_id) whose opponent the classifier has named,
    optionally picked by the user to a deck."""
    conn.execute(
        "INSERT INTO matches (match_id, started_at, ended_at, result, games_won, games_lost, "
        "source) VALUES (?, '2026-09-20T00:00:00', '2026-09-20T00:30:00', 'win', 2, 0, 'mtgo')",
        (match_id,),
    )
    conn.execute(
        "INSERT INTO opponent_archetype (match_id, format, archetype_key, archetype_name, "
        "colors, label, method, confidence, cards_seen, conditions_met, conditions_unknown, "
        "evidence_json, classified_at) VALUES "
        "(?, 'Modern', ?, ?, 'G', ?, 'archetype', 'high', 5, 3, 0, '[]', 'now')",
        (match_id, archetype_key, archetype_name, archetype_name),
    )
    if pick_deck_id is not None:
        conn.execute(
            "INSERT INTO mtgo_match_pick (match_id, deck_id, format) VALUES (?, ?, 'Modern')",
            (match_id, pick_deck_id),
        )


def test_a_picked_mtgo_match_counts_in_the_decks_matchups_and_an_unpicked_one_does_not(conn):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'My Deck', 'Modern', '{}', 't', 't')"
    )
    _mtgo_match_vs(conn, "mt-picked", "arch_x", "Archetype X", pick_deck_id="d1")
    _mtgo_match_vs(conn, "mt-unpicked", "arch_x", "Archetype X")
    conn.commit()

    assert faced_archetypes(conn, ("d1",)) == {"arch_x": ("Archetype X", 1)}
    assert faced_archetypes(conn, ("d1",), since="2026-09-21T00:00:00") == {}

    field = build_field(conn, identity_for(("d1",)), reset=None)
    (rate,) = [r for r in field.personal_rates if r.archetype == "Archetype X"]
    assert (rate.matches, rate.wins, rate.losses) == (1, 1, 0)
