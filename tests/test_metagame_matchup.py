"""Tests for metagame/matchup.py: walking the ranked tiers down to one
quoted matchup number, never blending two tiers into one record. The tier
ranking itself is docs/metagame.md, "The evidence tiers".
"""

from __future__ import annotations

import pytest

from sensei_top.db import open_database
from sensei_top.metagame.matchup import RankedMatchup, ranked_field_matchup

OWN = "own-archetype"
OPP = "opp-archetype"


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


_next_id = iter(range(1_000_000))


def _round(conn, *, tier, event_date="2026-08-01", own_wins=1, opp_wins=0, fmt="Standard"):
    """One event with one meta_round_match row between OWN and OPP, at the
    given tier -- one win/loss round, so ``n`` grows by exactly one call.
    ``source`` is derived from ``tier`` (MTGO for B/C, MTGmelee for A/D --
    the spellings ``source.py`` stores) so the row is one the classifier
    could actually have produced."""
    event_id = f"e{next(_next_id)}"
    source = "MTGO" if tier in ("B", "C") else "MTGmelee"
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
        "format, tier) VALUES (?, 'p', 's', ?, 'e', ?, ?, ?)",
        (event_id, source, event_date, fmt, tier),
    )
    for deck_ord, key in ((0, OWN), (1, OPP)):
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json) "
            "VALUES (?, ?, '[]', '[]')",
            (event_id, deck_ord),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) "
            "VALUES (?, ?, ?, ?, ?, 'archetype', 'now')",
            (event_id, deck_ord, key, key, key),
        )
    conn.execute(
        "INSERT INTO meta_round_match (event_id, round_name, deck_ord_a, deck_ord_b, "
        "wins_a, wins_b, draws) VALUES (?, 'Round 1', 0, 1, ?, ?, 0)",
        (event_id, own_wins, opp_wins),
    )


def test_tier_a_with_enough_matches_beats_tier_b(conn):
    for _ in range(5):
        _round(conn, tier="A")
    for _ in range(8):
        _round(conn, tier="B")
    conn.commit()

    result = ranked_field_matchup(conn, OWN, OPP, None, fmt="Standard")
    assert result == RankedMatchup(tier="A", n=5, matches_won=5, matches_lost=0)


def test_thin_tier_a_falls_to_tier_b(conn):
    for _ in range(3):
        _round(conn, tier="A")
    for _ in range(8):
        _round(conn, tier="B", own_wins=0, opp_wins=1)
    conn.commit()

    result = ranked_field_matchup(conn, OWN, OPP, None, fmt="Standard")
    assert result == RankedMatchup(tier="B", n=8, matches_won=0, matches_lost=8)


def test_nothing_reaching_the_floor_takes_the_highest_ranked_tier_with_rows(conn):
    for _ in range(2):
        _round(conn, tier="B", own_wins=1, opp_wins=1)  # a draw each round
    for _ in range(4):
        _round(conn, tier="D")
    conn.commit()

    result = ranked_field_matchup(conn, OWN, OPP, None, fmt="Standard")
    # Neither tier reaches min_n=5; B outranks D, so B is quoted even though
    # D has more rounds.
    assert result is not None
    assert result.tier == "B"
    assert result.n == 2


def test_no_rows_anywhere_is_none(conn):
    conn.commit()
    assert ranked_field_matchup(conn, OWN, OPP, None, fmt="Standard") is None


def test_since_excludes_older_rows(conn):
    for _ in range(5):
        _round(conn, tier="A", event_date="2026-07-01")
    conn.commit()

    assert ranked_field_matchup(conn, OWN, OPP, None, fmt="Standard") is not None
    assert ranked_field_matchup(conn, OWN, OPP, "2026-08-01", fmt="Standard") is None


def test_tier_c_rows_are_never_read(conn):
    """Tier C never populates meta_round_match in real data (a league dump
    has no losses to record), but even a stray row must not be read: 'C' is
    not in MATCHUP_TIERS, so it can never win the walk."""
    _round(conn, tier="C")
    for _ in range(4):
        _round(conn, tier="D")
    conn.commit()

    result = ranked_field_matchup(conn, OWN, OPP, None, fmt="Standard")
    assert result is not None
    assert result.tier == "D"
    assert result.n == 4


def test_each_format_sees_only_its_own_rounds(conn):
    """Plan 13, D14: the same pair of archetype keys can have rounds in two
    formats' corpora. Five Standard wins and six Modern losses, all Tier A:
    each format's record is its own five or six, never the eleven blended."""
    for _ in range(5):
        _round(conn, tier="A", fmt="Standard")
    for _ in range(6):
        _round(conn, tier="A", own_wins=0, opp_wins=1, fmt="Modern")
    conn.commit()

    assert ranked_field_matchup(conn, OWN, OPP, None, fmt="Standard") == RankedMatchup(
        tier="A", n=5, matches_won=5, matches_lost=0
    )
    assert ranked_field_matchup(conn, OWN, OPP, None, fmt="Modern") == RankedMatchup(
        tier="A", n=6, matches_won=0, matches_lost=6
    )
    assert ranked_field_matchup(conn, OWN, OPP, None, fmt="Pioneer") is None


def test_no_format_has_no_field_record(conn):
    """A match or deck with no format gets no field record, never one
    pooled across every format's rounds."""
    for _ in range(5):
        _round(conn, tier="A")
    conn.commit()

    assert ranked_field_matchup(conn, OWN, OPP, None, fmt=None) is None
