"""Tests for guide/list_diff.py: the player's own decklist against the
field's consensus for its classified archetype.
"""

from __future__ import annotations

import json

import pytest

from sensei_top.db import open_database
from sensei_top.guide.deck import DeckIdentity
from sensei_top.guide.list_diff import build_list_diff
from sensei_top.guide.window import FormatReset


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _teach_archetype(conn, key, name, signature_card):
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, "
        "fetched_at) VALUES ('Standard', 'archetype', ?, ?, 0, ?, '2026-01-01T00:00:00Z')",
        (key, name, json.dumps({
            "Name": name,
            "Conditions": [{"Type": "InMainboard", "Cards": [signature_card]}],
        })),
    )


def _insert_card(conn, grp_id, name, *, type_line="Creature", mana_cost="{1}{U}"):
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, mana_cost) VALUES (?, ?, ?, ?)",
        (grp_id, name, type_line, mana_cost),
    )


def _insert_deck_and_match(conn, deck_id, maindeck, sideboard, match_id="m1"):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, 'My Deck', 'TraditionalStandard', ?, 't', 't')",
        (deck_id, json.dumps({"maindeck": maindeck, "sideboard": sideboard})),
    )
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, 'e', ?, 1, 2, 'u', 'n', 't', 't', "
        "'win', 1, 0, 'r')",
        (match_id, deck_id),
    )


def _store_corpus_deck(conn, event_id, deck_ord, archetype_key, mainboard, *, wins=3,
                        event_date="2026-08-15", sideboard=None):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', ?, 'Standard', 'B')",
        (event_id, event_date),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins) "
        "VALUES (?, ?, ?, ?, ?)",
        (event_id, deck_ord, json.dumps(mainboard), json.dumps(sideboard or []), wins),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, ?, ?, ?, ?, 'archetype', 'now')",
        (event_id, deck_ord, archetype_key, archetype_key, archetype_key),
    )


def identity_for(deck_id, maindeck, sideboard) -> DeckIdentity:
    return DeckIdentity(
        key=f"deck:{deck_id}", arena_deck_id=None, name="My Deck", format="TraditionalStandard",
        deck_ids=(deck_id,), matches=1, match_wins=1, match_losses=0, games_won=1,
        games_lost=0, first_played="t", last_played="t",
        current_cards={"maindeck": maindeck, "sideboard": sideboard},
    )


def test_returns_none_when_deck_cannot_be_classified(conn):
    """No archetype definitions loaded at all -> _classify_own_deck returns
    None -> a real gap, not a guess."""
    _insert_card(conn, 1, "Some Card")
    _insert_deck_and_match(conn, "d1", [1, 1, 1, 1], [])
    conn.commit()
    assert build_list_diff(conn, identity_for("d1", [1, 1, 1, 1], [])) is None


def test_returns_none_when_consensus_below_min_decks(conn):
    _teach_archetype(conn, "izzet_spells", "Izzet Spellementals", "Signature Card")
    _insert_card(conn, 1, "Signature Card")
    _insert_deck_and_match(conn, "d1", [1, 1, 1, 1], [])
    for i in range(2):  # fewer than default min_decks=5
        _store_corpus_deck(conn, f"e{i}", 0, "izzet_spells",
                            [{"count": 4, "name": "Signature Card"}])
    conn.commit()
    assert build_list_diff(conn, identity_for("d1", [1, 1, 1, 1], [])) is None


def test_card_verdicts_add_trim_correct(conn):
    _teach_archetype(conn, "izzet_spells", "Izzet Spellementals", "Signature Card")
    _insert_card(conn, 1, "Signature Card")
    _insert_card(conn, 2, "Extra Copies")     # you run 4, consensus wants 2 -> trim
    _insert_card(conn, 3, "Missing Staple")   # you run 0, consensus wants it -> add
    # you run Signature Card correctly at 4 copies (matches consensus)
    maindeck = [1, 1, 1, 1, 2, 2, 2, 2]
    _insert_deck_and_match(conn, "d1", maindeck, [])
    for i in range(5):
        mainboard = [{"count": 4, "name": "Signature Card"}, {"count": 2, "name": "Extra Copies"},
                     {"count": 4, "name": "Missing Staple"}]
        _store_corpus_deck(conn, f"e{i}", 0, "izzet_spells", mainboard)
    conn.commit()

    diff = build_list_diff(conn, identity_for("d1", maindeck, []), min_decks=5)
    assert diff is not None
    by_name = {c.card: c for c in diff.maindeck}
    assert by_name["Signature Card"].verdict == "correct"
    assert by_name["Extra Copies"].verdict == "trim"
    assert by_name["Extra Copies"].recommended == 2
    assert by_name["Missing Staple"].verdict == "add"
    assert by_name["Missing Staple"].yours == 0


def test_reset_windows_the_consensus_to_post_reset_decks(conn):
    """A pre-reset deck's list must never leak into the guide's consensus
    once a reset is in effect."""
    _teach_archetype(conn, "izzet_spells", "Izzet Spellementals", "Signature Card")
    _insert_card(conn, 1, "Signature Card")
    _insert_card(conn, 9, "Old Tech")
    maindeck = [1, 1, 1, 1]
    _insert_deck_and_match(conn, "d1", maindeck, [])
    for i in range(5):
        _store_corpus_deck(conn, f"pre{i}", 0, "izzet_spells",
                            [{"count": 4, "name": "Signature Card"},
                             {"count": 4, "name": "Old Tech"}],
                            event_date="2026-08-01")
    for i in range(5):
        _store_corpus_deck(conn, f"post{i}", 0, "izzet_spells",
                            [{"count": 4, "name": "Signature Card"}],
                            event_date="2026-08-15")
    conn.commit()

    reset = FormatReset(date="2026-08-10", cards=("Old Tech",), detected_from="test")
    diff = build_list_diff(conn, identity_for("d1", maindeck, []), reset=reset, min_decks=5)
    assert diff is not None
    assert diff.winning_decks == 5
    assert not any(c.card == "Old Tech" for c in diff.maindeck)


def test_flex_card_never_seen_in_the_corpus_is_not_cut(conn):
    """A card the player runs that the corpus has never recorded for this
    archetype must be labelled flex, never cut on absence alone."""
    _teach_archetype(conn, "izzet_spells", "Izzet Spellementals", "Signature Card")
    _insert_card(conn, 1, "Signature Card")
    _insert_card(conn, 2, "Rogue Tech")
    maindeck = [1, 1, 1, 1, 2, 2]
    _insert_deck_and_match(conn, "d1", maindeck, [])
    for i in range(5):
        _store_corpus_deck(conn, f"e{i}", 0, "izzet_spells",
                            [{"count": 4, "name": "Signature Card"}])
    conn.commit()

    diff = build_list_diff(conn, identity_for("d1", maindeck, []), min_decks=5)
    rogue = next(c for c in diff.maindeck if c.card == "Rogue Tech")
    assert rogue.verdict == "flex"


def test_duplicate_warning_fires_for_same_shape_never_co_occurring(conn):
    _teach_archetype(conn, "izzet_spells", "Izzet Spellementals", "Signature Card")
    _insert_card(conn, 1, "Signature Card")
    _insert_card(conn, 10, "Hydro-Man, Fluid Felon", type_line="Legendary Creature",
                 mana_cost="{U}{U}")
    _insert_card(conn, 11, "Belion, the Parched", type_line="Legendary Creature",
                 mana_cost="{U}{U}")
    maindeck = [1, 1, 1, 1]
    _insert_deck_and_match(conn, "d1", maindeck, [])
    for i in range(3):
        _store_corpus_deck(conn, f"h{i}", 0, "izzet_spells",
                            [{"count": 4, "name": "Signature Card"},
                             {"count": 2, "name": "Hydro-Man, Fluid Felon"}])
    for i in range(3):
        _store_corpus_deck(conn, f"b{i}", 0, "izzet_spells",
                            [{"count": 4, "name": "Signature Card"},
                             {"count": 2, "name": "Belion, the Parched"}])
    conn.commit()

    diff = build_list_diff(conn, identity_for("d1", maindeck, []), min_decks=5)
    assert diff is not None
    assert len(diff.duplicate_warnings) == 1
    assert "Hydro-Man" in diff.duplicate_warnings[0]
    assert "Belion" in diff.duplicate_warnings[0]


def test_adventure_card_run_by_the_player_is_matched_to_its_corpus_staple(conn):
    """The player's own card comes from Arena's combined name ('Hearth
    Elemental // Stoke Genius'); the corpus decklist names only its front
    face ('Hearth Elemental'). Before name-form matching this reported the
    player as missing a staple they already ran 4 copies of."""
    _teach_archetype(conn, "izzet_spells", "Izzet Spellementals", "Signature Card")
    _insert_card(conn, 1, "Signature Card")
    _insert_card(conn, 2, "Hearth Elemental // Stoke Genius",
                 type_line="Creature — Elemental // Sorcery — Adventure", mana_cost="{5}{R}")
    maindeck = [1, 1, 1, 1, 2, 2, 2, 2]
    _insert_deck_and_match(conn, "d1", maindeck, [])
    for i in range(5):
        _store_corpus_deck(conn, f"e{i}", 0, "izzet_spells",
                            [{"count": 4, "name": "Signature Card"},
                             {"count": 4, "name": "Hearth Elemental"}])
    conn.commit()

    diff = build_list_diff(conn, identity_for("d1", maindeck, []), min_decks=5)
    assert diff is not None
    hearth = next(c for c in diff.maindeck if c.card == "Hearth Elemental // Stoke Genius")
    assert hearth.verdict == "correct"
    assert hearth.consensus_share == 1.0
    assert not any(c.card == "Hearth Elemental" and c.yours == 0 for c in diff.maindeck)


def test_duplicate_warning_does_not_fire_when_cards_co_occur(conn):
    """Two genuinely different cards that happen to share a type line and
    mana cost, and DO appear together in real decks, must not be flagged."""
    _teach_archetype(conn, "izzet_spells", "Izzet Spellementals", "Signature Card")
    _insert_card(conn, 1, "Signature Card")
    _insert_card(conn, 20, "Card Alpha", type_line="Creature", mana_cost="{1}{U}")
    _insert_card(conn, 21, "Card Beta", type_line="Creature", mana_cost="{1}{U}")
    maindeck = [1, 1, 1, 1]
    _insert_deck_and_match(conn, "d1", maindeck, [])
    for i in range(5):
        _store_corpus_deck(conn, f"e{i}", 0, "izzet_spells",
                            [{"count": 4, "name": "Signature Card"},
                             {"count": 2, "name": "Card Alpha"},
                             {"count": 2, "name": "Card Beta"}])
    conn.commit()

    diff = build_list_diff(conn, identity_for("d1", maindeck, []), min_decks=5)
    assert diff.duplicate_warnings == ()


def test_sideboard_verdicts_compare_against_sideboard_consensus_not_maindeck(conn):
    """The bug this fixes: comparing the player's sideboard against the
    field's *maindeck* staples recommended boarding in cards the player
    already runs in their maindeck. 'Signature Card' is a 100%-maindeck
    staple and must never appear as a sideboard 'add'."""
    _teach_archetype(conn, "izzet_spells", "Izzet Spellementals", "Signature Card")
    _insert_card(conn, 1, "Signature Card")
    _insert_card(conn, 5, "Sideboard Tech")
    maindeck = [1, 1, 1, 1]
    sideboard = [5, 5]
    _insert_deck_and_match(conn, "d1", maindeck, sideboard)
    for i in range(5):
        _store_corpus_deck(conn, f"e{i}", 0, "izzet_spells",
                            [{"count": 4, "name": "Signature Card"}],
                            sideboard=[{"count": 2, "name": "Sideboard Tech"}])
    conn.commit()

    diff = build_list_diff(conn, identity_for("d1", maindeck, sideboard), min_decks=5)
    assert diff is not None
    assert not any(c.card == "Signature Card" for c in diff.sideboard)
    tech = next(c for c in diff.sideboard if c.card == "Sideboard Tech")
    assert tech.verdict == "correct"
    assert tech.consensus_share == 1.0


def test_sideboard_falls_back_to_empty_consensus_when_no_sideboards_recorded(conn):
    """A corpus with no sideboard data at all must not fail the whole list
    diff — every sideboard card the player runs reads as flex."""
    _teach_archetype(conn, "izzet_spells", "Izzet Spellementals", "Signature Card")
    _insert_card(conn, 1, "Signature Card")
    _insert_card(conn, 5, "My Tech")
    maindeck = [1, 1, 1, 1]
    sideboard = [5, 5]
    _insert_deck_and_match(conn, "d1", maindeck, sideboard)
    for i in range(5):
        _store_corpus_deck(conn, f"e{i}", 0, "izzet_spells",
                            [{"count": 4, "name": "Signature Card"}])
    conn.commit()

    diff = build_list_diff(conn, identity_for("d1", maindeck, sideboard), min_decks=5)
    assert diff is not None
    tech = next(c for c in diff.sideboard if c.card == "My Tech")
    assert tech.verdict == "flex"
