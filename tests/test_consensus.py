"""Tests for review/consensus.py: aggregating the metagame corpus into a
per-archetype card list.

Synthetic meta_deck/meta_deck_archetype/cards rows, matching this project's
established pattern for pieces that do not need a real log capture
(docs/testing.md) — the shapes here mirror ``metagame/source.py``'s own
``{"count": int, "name": str}`` mainboard encoding exactly.
"""

from __future__ import annotations

import json

import pytest

from sensei_top.db import open_database
from sensei_top.review.consensus import build_consensus


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _store_deck(conn, event_id, deck_ord, archetype_key, mainboard, *, event_date=None,
                 wins=0, tier="B", sideboard=None, fmt="Standard"):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, tier, format) VALUES (?, 'p', 's', 'mtgo', 'e', ?, ?, ?)",
        (event_id, event_date, tier, fmt),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins) "
        "VALUES (?, ?, ?, ?, ?)",
        (event_id, deck_ord, json.dumps(mainboard), json.dumps(sideboard or []), wins),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, ?, ?, 'Name', 'Name', 'archetype', 'now')",
        (event_id, deck_ord, archetype_key),
    )


def test_below_min_decks_returns_none(conn):
    _store_deck(conn, "e1", 0, "Boros", [{"count": 4, "name": "Lightning Bolt"}])
    conn.commit()
    assert build_consensus(conn, "Boros", fmt="Standard", min_decks=5) is None


def test_share_and_average_copies(conn):
    """3 of 5 decks run 4 copies of Sunfall; 5 of 5 run a basic land at
    varying counts — share and copies must be computed independently."""
    for i in range(5):
        mainboard = [{"count": 17, "name": "Island"}]
        if i < 3:
            mainboard.append({"count": 4, "name": "Sunfall"})
        _store_deck(conn, f"e{i}", 0, "Control", mainboard)
    conn.commit()

    consensus = build_consensus(conn, "Control", fmt="Standard", min_decks=5)
    assert consensus.deck_count == 5

    island = next(c for c in consensus.cards if c.name == "Island")
    assert island.share == 1.0
    assert island.copies == 17.0

    sunfall = next(c for c in consensus.cards if c.name == "Sunfall")
    assert sunfall.share == pytest.approx(0.6)
    assert sunfall.copies == 4.0
    assert sunfall.decks_with_card == 3


def test_staples_method_filters_by_minimum_share(conn):
    for i in range(4):
        mainboard = [{"count": 4, "name": "Common Card"}]
        if i == 0:
            mainboard.append({"count": 1, "name": "Rare Tech"})
        _store_deck(conn, f"e{i}", 0, "Aggro", mainboard)
    conn.commit()

    consensus = build_consensus(conn, "Aggro", fmt="Standard", min_decks=4)
    staple_names = {c.name for c in consensus.staples(min_share=0.5)}
    assert staple_names == {"Common Card"}
    assert "Rare Tech" not in staple_names


def test_a_card_with_no_matching_cards_row_is_tagged_unknown(conn):
    """The corpus can name a card this project's own `cards` table has never
    heard of (not yet downloaded, or a card printed after the last refresh)
    — rule 4: that is unknown, not zero effect tags."""
    for i in range(5):
        _store_deck(conn, f"e{i}", 0, "Mono-Red", [{"count": 4, "name": "Never Downloaded Card"}])
    conn.commit()

    consensus = build_consensus(conn, "Mono-Red", fmt="Standard", min_decks=5)
    card = consensus.cards[0]
    assert card.name == "Never Downloaded Card"
    assert card.grp_id is None
    assert card.tags == "unknown"


def test_oracle_text_comes_from_a_printing_that_actually_has_it(conn):
    """A card name can span several grp_ids (one per printing/art variant),
    and not every printing in a real Scryfall export carries oracle_text —
    verified against a live download, where most 'Island' rows had none.
    Whichever printing does carry text must win, not an arbitrary row."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, oracle_text) VALUES "
        "(1, 'Sunfall', 'Sorcery', NULL), "
        "(2, 'Sunfall', 'Sorcery', 'Exile all creatures.')"
    )
    for i in range(5):
        _store_deck(conn, f"e{i}", 0, "Control", [{"count": 1, "name": "Sunfall"}])
    conn.commit()

    consensus = build_consensus(conn, "Control", fmt="Standard", min_decks=5)
    card = consensus.cards[0]
    assert card.tags == frozenset({"sweeper"})


def test_since_excludes_decks_before_the_window(conn):
    for i in range(3):
        _store_deck(conn, f"pre{i}", 0, "Boros", [{"count": 4, "name": "Old Card"}],
                    event_date="2026-08-01")
    for i in range(5):
        _store_deck(conn, f"post{i}", 0, "Boros", [{"count": 4, "name": "New Card"}],
                    event_date="2026-08-15")
    conn.commit()

    consensus = build_consensus(conn, "Boros", fmt="Standard", min_decks=5, since="2026-08-11")
    assert consensus.deck_count == 5
    assert {c.name for c in consensus.cards} == {"New Card"}


def test_min_wins_filters_to_winning_decks(conn):
    for i in range(5):
        _store_deck(conn, f"e{i}", 0, "Boros", [{"count": 4, "name": "Card"}], wins=3)
    for i in range(5):
        _store_deck(conn, f"f{i}", 0, "Boros", [{"count": 4, "name": "Card"}], wins=0)
    conn.commit()

    consensus = build_consensus(conn, "Boros", fmt="Standard", min_decks=5, min_wins=3)
    assert consensus.deck_count == 5


def test_tiers_filters_by_evidence_tier(conn):
    for i in range(5):
        _store_deck(conn, f"a{i}", 0, "Boros", [{"count": 4, "name": "Card"}], tier="A")
    for i in range(5):
        _store_deck(conn, f"c{i}", 0, "Boros", [{"count": 4, "name": "Card"}], tier="C")
    conn.commit()

    consensus = build_consensus(conn, "Boros", fmt="Standard", min_decks=5, tiers=("A",))
    assert consensus.deck_count == 5


def test_two_printings_sharing_one_oracle_id_are_merged(conn):
    """The Izzet Spellementals guide's own bug: 'Hydro-Man, Fluid Felon' and
    'Belion, the Parched' are the same card under two Universes Beyond
    printings, and counting them separately halved a 52% inclusion rate
    into 39% + 14%."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, oracle_id) VALUES "
        "(1, 'Hydro-Man, Fluid Felon', 'Legendary Creature', 'oracle-abc'), "
        "(2, 'Belion, the Parched', 'Legendary Creature', 'oracle-abc')"
    )
    for i in range(3):
        _store_deck(conn, f"h{i}", 0, "Izzet", [{"count": 2, "name": "Hydro-Man, Fluid Felon"}])
    for i in range(2):
        _store_deck(conn, f"b{i}", 0, "Izzet", [{"count": 2, "name": "Belion, the Parched"}])
    conn.commit()

    consensus = build_consensus(conn, "Izzet", fmt="Standard", min_decks=5)
    names = {c.name for c in consensus.cards}
    assert "Hydro-Man, Fluid Felon" in names
    assert "Belion, the Parched" not in names
    merged = next(c for c in consensus.cards if c.name == "Hydro-Man, Fluid Felon")
    assert merged.decks_with_card == 5
    assert merged.share == 1.0


def test_adventure_card_named_by_its_front_face_still_finds_its_cards_row(conn):
    """A real-world corpus decklist names an adventure card by its front
    face alone ("Hearth Elemental"), while Arena's own card database (and
    this project's `cards` table, sourced from it) stores the combined
    name ("Hearth Elemental // Stoke Genius"). An exact-name join misses
    this and silently reports the card as unknown even though its text is
    on file."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, oracle_text, mana_cost) VALUES "
        "(1, 'Hearth Elemental // Stoke Genius', 'Creature — Elemental // Sorcery — Adventure', "
        "'Discard your hand, then draw two cards.', '{5}{R}')"
    )
    for i in range(5):
        _store_deck(conn, f"e{i}", 0, "Izzet", [{"count": 4, "name": "Hearth Elemental"}])
    conn.commit()

    consensus = build_consensus(conn, "Izzet", fmt="Standard", min_decks=5)
    card = next(c for c in consensus.cards if c.name == "Hearth Elemental")
    assert card.grp_id == 1
    assert card.type_line == "Creature — Elemental // Sorcery — Adventure"
    assert card.tags != "unknown"


def test_cards_with_no_oracle_id_are_never_merged(conn):
    """Two unrelated cards that happen to have no oracle_id on file must
    stay separate — merging requires a real shared identity, not absence."""
    for i in range(3):
        _store_deck(conn, f"a{i}", 0, "Boros", [{"count": 1, "name": "Card A"}])
    for i in range(3):
        _store_deck(conn, f"b{i}", 0, "Boros", [{"count": 1, "name": "Card B"}])
    conn.commit()

    consensus = build_consensus(conn, "Boros", fmt="Standard", min_decks=5)
    assert {c.name for c in consensus.cards} == {"Card A", "Card B"}


def test_board_side_reads_sideboard_json_not_mainboard(conn):
    """A maindeck staple must never leak into the sideboard consensus, and
    vice versa — the two boards are different card pools entirely."""
    for i in range(5):
        _store_deck(conn, f"e{i}", 0, "Izzet", [{"count": 4, "name": "Main Staple"}],
                    sideboard=[{"count": 2, "name": "Side Tech"}])
    conn.commit()

    main = build_consensus(conn, "Izzet", fmt="Standard", min_decks=5, board="main")
    side = build_consensus(conn, "Izzet", fmt="Standard", min_decks=5, board="side")
    assert {c.name for c in main.cards} == {"Main Staple"}
    assert {c.name for c in side.cards} == {"Side Tech"}


def test_board_side_below_min_decks_returns_none(conn):
    """A corpus with mainboards but no sideboard data at all must not be
    treated as a populated (all-zero) sideboard consensus."""
    for i in range(5):
        _store_deck(conn, f"e{i}", 0, "Izzet", [{"count": 4, "name": "Main Staple"}])
    conn.commit()

    side = build_consensus(conn, "Izzet", fmt="Standard", min_decks=5, board="side")
    # every deck IS still counted (min_decks gates deck rows, not card
    # presence) -- an all-empty sideboard just yields no cards at all.
    assert side is not None
    assert side.cards == ()


def test_each_format_counts_only_its_own_decks(conn):
    """One archetype key in a Standard event (3 decks, 4 Shock each) and a
    Modern event (2 decks, 1 Shock in one of them): each format sees its own."""
    for i in range(3):
        _store_deck(conn, f"std{i}", 0, "Boros", [{"count": 4, "name": "Shock"}], fmt="Standard")
    _store_deck(conn, "mod0", 0, "Boros", [{"count": 1, "name": "Shock"}], fmt="Modern")
    _store_deck(conn, "mod1", 0, "Boros", [{"count": 2, "name": "Bolt"}], fmt="Modern")
    conn.commit()

    standard = build_consensus(conn, "Boros", fmt="Standard", min_decks=2)
    assert standard.deck_count == 3
    shock = next(c for c in standard.cards if c.name == "Shock")
    assert shock.copies == 4.0
    assert shock.decks_with_card == 3
    assert not any(c.name == "Bolt" for c in standard.cards)

    modern = build_consensus(conn, "Boros", fmt="Modern", min_decks=2)
    assert modern.deck_count == 2
    shock = next(c for c in modern.cards if c.name == "Shock")
    assert shock.copies == 1.0
    assert shock.decks_with_card == 1

    assert build_consensus(conn, "Boros", fmt=None, min_decks=1) is None
