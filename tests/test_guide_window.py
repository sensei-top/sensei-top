"""Tests for guide/window.py: detecting a format reset from the corpus
itself, and which archetypes survived it.

Synthetic meta_event/meta_deck/meta_deck_archetype/cards rows, matching this
project's established pattern for pieces that do not need a real log capture
(docs/testing.md).
"""

from __future__ import annotations

import json

import pytest

from sensei_top.db import open_database
from sensei_top.guide.window import (
    CHANGED_THRESHOLD,
    consensus_window_resolver,
    format_resets,
    legality_known,
    structural_change,
)


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _store_deck(conn, event_id, deck_ord, archetype_key, mainboard, *, event_date, fmt="Standard"):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', ?, ?, 'B')",
        (event_id, event_date, fmt),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json) "
        "VALUES (?, ?, ?, '[]')",
        (event_id, deck_ord, json.dumps(mainboard)),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, ?, ?, ?, ?, 'archetype', 'now')",
        (event_id, deck_ord, archetype_key, archetype_key, archetype_key),
    )


def _ban(conn, name, fmt="Standard"):
    conn.execute(
        "INSERT INTO cards (grp_id, name) VALUES (?, ?)",
        (hash(name) % 1_000_000, name),
    )
    conn.execute(
        "INSERT INTO card_legality (grp_id, format, legality) VALUES (?, ?, 'banned')",
        (hash(name) % 1_000_000, fmt),
    )


# --- legality_known ----------------------------------------------------------


def test_legality_is_unknown_when_no_card_carries_it(conn):
    """The installed-client card import writes names but no legality
    (cards.read_arena_cards), which is exactly this state: cards present,
    legality absent, so no ban is detectable however clear the corpus is."""
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (1, 'Gran-Gran')")
    conn.commit()
    assert legality_known(conn) is False
    assert format_resets(conn) == []


def test_legality_is_known_once_any_card_carries_it(conn):
    conn.execute(
        "INSERT INTO cards (grp_id, name) VALUES (1, 'Gran-Gran')"
    )
    conn.execute(
        "INSERT INTO card_legality (grp_id, format, legality) VALUES (1, 'Standard', 'legal')"
    )
    conn.commit()
    assert legality_known(conn) is True


def test_legality_known_is_per_format(conn):
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (1, 'Gran-Gran')")
    conn.execute(
        "INSERT INTO card_legality (grp_id, format, legality) VALUES (1, 'Standard', 'legal')"
    )
    conn.commit()
    assert legality_known(conn, "Modern") is False
    conn.execute(
        "INSERT INTO card_legality (grp_id, format, legality) VALUES (1, 'Modern', 'legal')"
    )
    conn.commit()
    assert legality_known(conn, "Modern") is True


# --- format_resets -----------------------------------------------------------


def test_a_modern_only_ban_gives_a_modern_reset_and_no_standard_one(conn):
    """Banned only in Modern; the Modern corpus shows it last on 2026-08-09."""
    _ban(conn, "Badgermole Cub", fmt="Modern")
    for i in range(3):
        _store_deck(conn, f"pre{i}", 0, "Mono-Green", [{"count": 4, "name": "Badgermole Cub"}],
                    event_date="2026-08-09", fmt="Modern")
    for i in range(3):
        _store_deck(conn, f"post{i}", 0, "Mono-Green", [{"count": 4, "name": "Forest"}],
                    event_date="2026-08-15", fmt="Modern")
    for i in range(3):
        _store_deck(conn, f"std-pre{i}", 0, "Mono-Green", [{"count": 4, "name": "Badgermole Cub"}],
                    event_date="2026-08-09")
    for i in range(3):
        _store_deck(conn, f"std-post{i}", 0, "Mono-Green", [{"count": 4, "name": "Forest"}],
                    event_date="2026-08-15")
    conn.commit()

    resets = format_resets(conn, "Modern")
    assert len(resets) == 1
    assert resets[0].date == "2026-08-09"
    assert resets[0].cards == ("Badgermole Cub",)
    assert format_resets(conn, "Standard") == []


def test_the_resolver_resolves_each_format_once_and_keeps_a_seed(conn):
    """Modern's ban is last seen 2026-08-09, so its window opens the day
    after. Once resolved, a corpus change is not seen again by the same
    resolver; a seeded format answers its seed whatever the corpus says."""
    _ban(conn, "Badgermole Cub", fmt="Modern")
    for i in range(3):
        _store_deck(conn, f"pre{i}", 0, "Mono-Green", [{"count": 4, "name": "Badgermole Cub"}],
                    event_date="2026-08-09", fmt="Modern")
    conn.commit()
    resolve = consensus_window_resolver(conn, {"Standard": "2026-01-01"})

    assert resolve("Modern") == "2026-08-10"
    conn.execute("DELETE FROM meta_deck")
    conn.commit()
    assert resolve("Modern") == "2026-08-10"
    assert resolve("Standard") == "2026-01-01"
    assert resolve("Pioneer") is None


def test_no_banned_card_means_no_reset(conn):
    for i in range(20):
        _store_deck(conn, f"e{i}", 0, "Boros", [{"count": 4, "name": "Lightning Bolt"}],
                    event_date="2026-08-01")
    conn.commit()
    assert format_resets(conn) == []


def test_reset_detected_from_a_banned_card_disappearing(conn):
    """The card appears in enough decks through 2026-08-09, then never
    again after — the reset date is the last date it was seen."""
    _ban(conn, "Badgermole Cub")
    for i in range(3):
        _store_deck(conn, f"pre{i}", 0, "Mono-Green", [{"count": 4, "name": "Badgermole Cub"}],
                    event_date="2026-08-09")
    for i in range(3):
        _store_deck(conn, f"post{i}", 0, "Mono-Green", [{"count": 4, "name": "Forest"}],
                    event_date="2026-08-15")
    conn.commit()

    resets = format_resets(conn)
    assert len(resets) == 1
    assert resets[0].date == "2026-08-09"
    assert resets[0].cards == ("Badgermole Cub",)


def test_a_single_stray_appearance_does_not_move_the_date(conn):
    """One deck playing a banned card after the real cutoff is a data
    quirk, not evidence of a later ban — MIN_DECKS_FOR_LAST_APPEARANCE
    requires the card to appear in more than one deck to count."""
    _ban(conn, "Badgermole Cub")
    for i in range(3):
        _store_deck(conn, f"pre{i}", 0, "Mono-Green", [{"count": 4, "name": "Badgermole Cub"}],
                    event_date="2026-08-09")
    # one stray deck after the real cutoff
    _store_deck(conn, "stray", 0, "Mono-Green", [{"count": 1, "name": "Badgermole Cub"}],
                event_date="2026-08-20")
    conn.commit()

    resets = format_resets(conn)
    assert len(resets) == 1
    assert resets[0].date == "2026-08-09"


def test_multiple_banned_cards_ship_together_cluster_into_one_reset(conn):
    _ban(conn, "Badgermole Cub")
    _ban(conn, "Gran-Gran")
    for i in range(3):
        _store_deck(conn, f"a{i}", 0, "Mono-Green", [{"count": 4, "name": "Badgermole Cub"}],
                    event_date="2026-08-09")
    for i in range(3):
        _store_deck(conn, f"b{i}", 0, "Jeskai", [{"count": 4, "name": "Gran-Gran"}],
                    event_date="2026-08-10")
    conn.commit()

    resets = format_resets(conn)
    assert len(resets) == 1
    assert resets[0].date == "2026-08-10"
    assert set(resets[0].cards) == {"Badgermole Cub", "Gran-Gran"}


def test_widely_separated_bans_are_two_resets(conn):
    _ban(conn, "Old Ban")
    _ban(conn, "New Ban")
    for i in range(3):
        _store_deck(conn, f"a{i}", 0, "X", [{"count": 4, "name": "Old Ban"}],
                    event_date="2026-05-01")
    for i in range(3):
        _store_deck(conn, f"b{i}", 0, "Y", [{"count": 4, "name": "New Ban"}],
                    event_date="2026-08-09")
    conn.commit()

    resets = format_resets(conn)
    assert len(resets) == 2
    assert resets[0].date == "2026-08-09"  # newest first
    assert resets[1].date == "2026-05-01"


# --- structural_change -------------------------------------------------------


def test_archetype_that_lost_a_banned_card_is_marked_changed(conn):
    """98.9%-style saturation: nearly every pre-reset list ran the banned
    card, well above CHANGED_THRESHOLD."""
    _ban(conn, "Badgermole Cub")
    for i in range(20):
        _store_deck(conn, f"pre{i}", 0, "Mono-Green Landfall",
                    [{"count": 4, "name": "Badgermole Cub"}], event_date="2026-08-01")
    for i in range(5):
        _store_deck(conn, f"post{i}", 0, "Mono-Green Landfall",
                    [{"count": 4, "name": "Forest"}], event_date="2026-08-15")
    conn.commit()

    reset = format_resets(conn)[0]
    changes = structural_change(conn, reset)
    change = changes["Mono-Green Landfall"]
    assert change.verdict == "changed"
    assert change.carryable is False
    assert change.fraction_playing_a_banned_card >= CHANGED_THRESHOLD
    assert change.post_reset_decks == 5


def test_archetype_untouched_by_the_ban_is_intact(conn):
    """A reset is established by a different archetype losing a banned
    card; Mardu Discard never played it and survives both windows."""
    _ban(conn, "Badgermole Cub")
    for i in range(3):
        _store_deck(conn, f"decoy{i}", 0, "Mono-Green Landfall",
                    [{"count": 4, "name": "Badgermole Cub"}], event_date="2026-08-09")
    for i in range(20):
        _store_deck(conn, f"pre{i}", 0, "Mardu Discard",
                    [{"count": 4, "name": "Bloodghast"}], event_date="2026-08-01")
    for i in range(5):
        _store_deck(conn, f"post{i}", 0, "Mardu Discard",
                    [{"count": 4, "name": "Bloodghast"}], event_date="2026-08-15")
    conn.commit()

    reset = format_resets(conn)[0]
    changes = structural_change(conn, reset)
    change = changes["Mardu Discard"]
    assert change.verdict == "intact"
    assert change.carryable is True
    assert change.fraction_playing_a_banned_card == 0.0


def test_archetype_with_zero_post_reset_decks_is_gone(conn):
    _ban(conn, "Stormchaser's Talent")
    for i in range(20):
        _store_deck(conn, f"pre{i}", 0, "Izzet Prowess",
                    [{"count": 4, "name": "Stormchaser's Talent"}], event_date="2026-08-01")
    conn.commit()

    reset = format_resets(conn)[0]
    changes = structural_change(conn, reset)
    change = changes["Izzet Prowess"]
    assert change.verdict == "gone"
    assert change.carryable is False
    assert change.post_reset_decks == 0


def test_archetype_below_min_pre_reset_decks_is_excluded(conn):
    """Too small a pre-reset sample to say anything about it at all."""
    _ban(conn, "Badgermole Cub")
    for i in range(5):
        _store_deck(conn, f"pre{i}", 0, "Rare Deck",
                    [{"count": 4, "name": "Badgermole Cub"}], event_date="2026-08-01")
    for i in range(3):
        _store_deck(conn, f"post{i}", 0, "Rare Deck",
                    [{"count": 4, "name": "Forest"}], event_date="2026-08-15")
    conn.commit()

    reset = format_resets(conn)[0]
    changes = structural_change(conn, reset)
    assert "Rare Deck" not in changes
