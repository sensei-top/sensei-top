"""Tests for table/hand_read.py: the degraded path (no archetype, or an
archetype too thin for a consensus) still surfaces every observed fact, and
the "ok" path turns a consensus decklist minus what's been revealed into a
ranked, capped set of estimates.
"""

from __future__ import annotations

import pytest

from sensei_top.db import open_database
from sensei_top.projector.live_state import LiveState
from sensei_top.review import effects
from sensei_top.review.consensus import ArchetypeConsensus, ConsensusCard
from sensei_top.table.hand_read import RevealedCard, build_hand_read


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_match(conn, match_id, self_seat=1, opponent_seat=2):
    conn.execute(
        "INSERT INTO matches (match_id, self_seat, opponent_seat) VALUES (?, ?, ?)",
        (match_id, self_seat, opponent_seat),
    )


def _insert_turn(conn, match_id, game_number, turn_number, active_seat, opp_hand,
                  opp_library, opp_open_mana):
    conn.execute(
        "INSERT INTO turns (match_id, game_number, turn_number, active_seat, opp_hand, "
        "opp_library, opp_open_mana) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (match_id, game_number, turn_number, active_seat, opp_hand, opp_library, opp_open_mana),
    )


def test_degraded_path_still_reports_observed_facts(conn):
    """No archetype resolved yet ('unclassified') must still surface hand
    size, hidden pool, open mana and held-turns — only the per-card
    estimates go empty, per AGENTS.md rule 4 (never a blank card for a real,
    partial answer)."""
    _insert_match(conn, "m1")
    conn.execute("INSERT INTO games (match_id, game_number) VALUES ('m1', 1)")
    _insert_turn(conn, "m1", 1, 1, active_seat=2, opp_hand=7, opp_library=53, opp_open_mana=0)
    _insert_turn(conn, "m1", 1, 2, active_seat=1, opp_hand=6, opp_library=52, opp_open_mana=1)
    _insert_turn(conn, "m1", 1, 3, active_seat=2, opp_hand=6, opp_library=51, opp_open_mana=2)
    conn.commit()

    read = build_hand_read(
        conn, "m1", 1, opponent_key=None, archetype_label=None, consensus=None, fmt="Standard",
    )
    assert read.status == "unclassified"
    assert read.hand_size == 6
    assert read.hidden_pool == 57
    assert read.open_mana == 2
    assert read.held_turns == 2  # turns 3 and 2 both sat at 6; turn 1 was 7
    assert read.interaction == ()
    assert read.threats == ()


def test_no_consensus_status_when_archetype_corpus_is_too_thin(conn):
    _insert_match(conn, "m1")
    conn.execute("INSERT INTO games (match_id, game_number) VALUES ('m1', 1)")
    _insert_turn(conn, "m1", 1, 1, active_seat=2, opp_hand=7, opp_library=53, opp_open_mana=0)
    conn.commit()

    read = build_hand_read(
        conn, "m1", 1, opponent_key="archetype:dimir-midrange",
        archetype_label="Dimir Midrange", consensus=None, fmt="Standard",
    )
    assert read.status == "no_consensus"
    assert read.archetype_key == "dimir-midrange"
    assert read.hand_size == 7


def test_ok_path_subtracts_seen_copies_and_splits_interaction_from_threats(conn):
    _insert_match(conn, "m1")
    conn.execute("INSERT INTO games (match_id, game_number) VALUES ('m1', 1)")
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) VALUES "
        "(5, 'Cut Down', '{B}', 'Instant', "
        "'Destroy target creature an opponent controls with total power and toughness "
        "5 or less.')"
    )
    _insert_turn(conn, "m1", 1, 1, active_seat=2, opp_hand=6, opp_library=51, opp_open_mana=2)
    # One copy of Cut Down already resolved to the battlefield's graveyard —
    # seen outside the hand zone, so it should be subtracted from the estimate.
    conn.execute(
        "INSERT INTO turn_zones (match_id, game_number, turn_number, seat, zone, idx, "
        "instance_id, grp_id) VALUES ('m1', 1, 1, 2, 'graveyard', 0, 100, 5)"
    )
    conn.commit()

    removal_tags = effects.classify(
        "Destroy target creature an opponent controls with total power and toughness "
        "5 or less.",
        "Instant",
        "{B}",
    )
    consensus = ArchetypeConsensus(
        archetype_key="dimir-midrange",
        deck_count=20,
        cards=(
            ConsensusCard(
                name="Cut Down", grp_id=5, type_line="Instant", decks_with_card=18,
                copies=3.5, share=0.9, tags=removal_tags.tags, mana_cost="{B}",
            ),
            ConsensusCard(
                name="Big Dragon", grp_id=4, type_line="Creature — Dragon",
                decks_with_card=10, copies=2.0, share=0.5, tags=frozenset(),
                mana_cost="{3}{U}{U}",
            ),
        ),
    )

    read = build_hand_read(
        conn, "m1", 1, opponent_key="archetype:dimir-midrange",
        archetype_label="Dimir Midrange", consensus=consensus, fmt="Standard",
    )
    assert read.status == "ok"
    # grp_id=5 comes straight from turn_zones (the graveyard row inserted
    # above), not from the consensus card — proving the picture is keyed off
    # what was actually seen, not off the field's typical decklist.
    assert read.revealed_this_match == (RevealedCard(name="Cut Down", grp_id=5),)

    assert len(read.interaction) == 1
    cut_down = read.interaction[0]
    assert cut_down.name == "Cut Down"
    assert cut_down.grp_id == 5  # carried straight from ConsensusCard.grp_id
    assert cut_down.expected_copies_left == pytest.approx(0.9 * 3.5 - 1)
    assert cut_down.castable_now is True  # mana value 1 <= 2 open mana, an instant

    assert len(read.threats) == 1
    assert read.threats[0].name == "Big Dragon"
    assert read.threats[0].grp_id == 4
    assert read.threats[0].castable_now is False


def test_lands_never_appear_in_the_estimate(conn):
    """A regression test for the bug this fixed: without a land filter, a
    deck's own basics topped the estimate ahead of every real spell —
    verified against the real corpus, where URProwess's top card by
    share*copies was a basic Island at 6.33 expected copies, ahead of every
    actual spell in the deck."""
    _insert_match(conn, "m1")
    conn.execute("INSERT INTO games (match_id, game_number) VALUES ('m1', 1)")
    _insert_turn(conn, "m1", 1, 1, active_seat=2, opp_hand=6, opp_library=51, opp_open_mana=2)
    conn.commit()

    consensus = ArchetypeConsensus(
        archetype_key="dimir-midrange",
        deck_count=20,
        cards=(
            ConsensusCard(
                name="Island", grp_id=99, type_line="Basic Land — Island",
                decks_with_card=20, copies=6.0, share=1.0, tags=frozenset(), mana_cost=None,
            ),
            ConsensusCard(
                name="Big Dragon", grp_id=4, type_line="Creature — Dragon",
                decks_with_card=10, copies=2.0, share=0.5, tags=frozenset(),
                mana_cost="{3}{U}{U}",
            ),
        ),
    )

    read = build_hand_read(
        conn, "m1", 1, opponent_key="archetype:dimir-midrange",
        archetype_label="Dimir Midrange", consensus=consensus, fmt="Standard",
    )
    names = {c.name for c in read.interaction} | {c.name for c in read.threats}
    assert "Island" not in names
    assert "Big Dragon" in names


def test_a_card_with_land_in_its_name_but_not_a_land_still_appears(conn):
    """A regression test for a fourth private land-detection copy that
    skipped the em-dash split: ``"Land" in card.type_line`` misreads
    ``"Artifact — Lander"`` as a land, exactly the trap
    ``review/effects.py::is_land`` exists to prevent
    (``migrations/011_review_views.sql``'s own comment names this same
    example). A card whose type line only contains "Land" as a substring
    after the em-dash must still reach the opponent's estimate."""
    _insert_match(conn, "m1")
    conn.execute("INSERT INTO games (match_id, game_number) VALUES ('m1', 1)")
    _insert_turn(conn, "m1", 1, 1, active_seat=2, opp_hand=6, opp_library=51, opp_open_mana=2)
    conn.commit()

    consensus = ArchetypeConsensus(
        archetype_key="dimir-midrange",
        deck_count=20,
        cards=(
            ConsensusCard(
                name="Voyager's Lander", grp_id=7, type_line="Artifact — Lander",
                decks_with_card=15, copies=1.0, share=0.75, tags=frozenset(),
                mana_cost="{2}",
            ),
        ),
    )

    read = build_hand_read(
        conn, "m1", 1, opponent_key="archetype:dimir-midrange",
        archetype_label="Dimir Midrange", consensus=consensus, fmt="Standard",
    )
    names = {c.name for c in read.interaction} | {c.name for c in read.threats}
    assert "Voyager's Lander" in names


def test_known_in_hand_is_subtracted_from_the_estimate(conn):
    """A card already confirmed sitting in the opponent's hand should not
    also show up as a probabilistic guess a few rows below it."""
    _insert_match(conn, "m1")
    conn.execute("INSERT INTO games (match_id, game_number) VALUES ('m1', 1)")
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line) VALUES "
        "(4, 'Big Dragon', '{3}{U}{U}', 'Creature — Dragon')"
    )
    _insert_turn(conn, "m1", 1, 1, active_seat=2, opp_hand=1, opp_library=51, opp_open_mana=2)
    # The single expected copy, revealed sitting in their hand right now.
    conn.execute(
        "INSERT INTO turn_zones (match_id, game_number, turn_number, seat, zone, idx, "
        "instance_id, grp_id) VALUES ('m1', 1, 1, 2, 'hand', 0, 200, 4)"
    )
    conn.commit()

    consensus = ArchetypeConsensus(
        archetype_key="dimir-midrange",
        deck_count=20,
        cards=(
            ConsensusCard(
                name="Big Dragon", grp_id=4, type_line="Creature — Dragon",
                decks_with_card=10, copies=1.0, share=1.0, tags=frozenset(),
                mana_cost="{3}{U}{U}",
            ),
        ),
    )

    read = build_hand_read(
        conn, "m1", 1, opponent_key="archetype:dimir-midrange",
        archetype_label="Dimir Midrange", consensus=consensus, fmt="Standard",
    )
    assert read.known_in_hand == (RevealedCard(name="Big Dragon", grp_id=4),)
    # Fully accounted for by the one known copy — nothing left to estimate.
    assert read.interaction == ()
    assert read.threats == ()


def test_castable_now_widens_with_other_mana_sources_from_a_live_replay(conn):
    """A mana rock or dork should count toward castable_now the same way an
    untapped land does — open_mana alone (untapped lands) used to
    under-report against ramp; the live replay's other_mana_sources is the
    upper bound this adds, not a certainty (a summoning-sick creature still
    counts, since Arena's isTapped says nothing about legal-to-tap-now)."""
    _insert_match(conn, "m1")
    conn.execute("INSERT INTO games (match_id, game_number) VALUES ('m1', 1)")
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line) VALUES "
        "(5, 'Cut Down', '{B}', 'Instant')"
    )
    conn.commit()

    consensus = ArchetypeConsensus(
        archetype_key="dimir-midrange",
        deck_count=20,
        cards=(
            ConsensusCard(
                name="Cut Down", grp_id=5, type_line="Instant", decks_with_card=18,
                copies=3.5, share=0.9, tags=frozenset({"spot_removal"}), mana_cost="{B}",
            ),
        ),
    )
    # One untapped land plus one untapped mana rock — {B} needs 1 total,
    # which only the rock's own count actually supplies here.
    live = LiveState(
        self_seat=1, opponent_seat=2, turn_number=2, active_seat=2,
        life={}, hand={2: 6}, library={2: 51}, graveyard={}, open_mana={2: 0},
        other_mana_sources={2: 1}, zone_cards=(), offer=None,
    )

    read = build_hand_read(
        conn, "m1", 1, opponent_key="archetype:dimir-midrange",
        archetype_label="Dimir Midrange", consensus=consensus, fmt="Standard", live=live,
    )
    assert read.open_mana == 0
    assert read.other_mana_sources == 1
    assert len(read.interaction) == 1
    assert read.interaction[0].castable_now is True


def test_format_unknown_status_comes_before_unclassified_and_the_consensus(conn):
    """A match with no format reads format_unknown, even with a real consensus
    in hand and whether or not the opponent is classified: there is no field it
    could belong to."""
    _insert_match(conn, "m1")
    conn.execute("INSERT INTO games (match_id, game_number) VALUES ('m1', 1)")
    _insert_turn(conn, "m1", 1, 1, active_seat=2, opp_hand=7, opp_library=53, opp_open_mana=0)
    conn.commit()
    consensus = ArchetypeConsensus(
        archetype_key="dimir-midrange",
        deck_count=20,
        cards=(
            ConsensusCard(
                name="Big Dragon", grp_id=4, type_line="Creature — Dragon",
                decks_with_card=10, copies=2.0, share=0.5, tags=frozenset(),
                mana_cost="{3}{U}{U}",
            ),
        ),
    )

    read = build_hand_read(
        conn, "m1", 1, opponent_key="archetype:dimir-midrange",
        archetype_label="Dimir Midrange", consensus=consensus, fmt=None,
    )
    assert read.status == "format_unknown"
    assert read.archetype_key == "dimir-midrange"
    assert read.hand_size == 7
    assert read.interaction == () and read.threats == ()

    unclassified = build_hand_read(
        conn, "m1", 1, opponent_key=None, archetype_label=None, consensus=None, fmt=None,
    )
    assert unclassified.status == "format_unknown"
    assert unclassified.hand_size == 7
