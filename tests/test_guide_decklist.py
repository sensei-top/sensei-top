"""Tests for guide/decklist.py: reading a pasted 75 (Arena export, MTGO
export, plain text) and resolving its names against the card database.

Expectations come from the texts themselves and S3's rules: the set code
and collector number are stripped, a blank line or ``SB:`` starts the
sideboard, a companion is a sideboard card, and a name that does not
resolve exactly (or by its front face) stays unresolved.
"""

from __future__ import annotations

import pytest

from sensei_top.db import open_database
from sensei_top.guide.decklist import parse_decklist, resolve_names

ARENA_EXPORT = """About
Name Synthetic Test Deck

Companion
1 Lurking Companion (ABC) 7

Deck
4 Shock (M21) 159
4 Fable of the Mirror-Breaker (NEO) 141
4 Fire // Ice (MH2) 290
48 Mountain (ZNR) 381

Sideboard
3 Abrade (DMU) 131
2 Unknown Testcard (XYZ) 1
"""

MTGO_EXPORT = """4 Shock
4 Fable of the Mirror-Breaker
52 Mountain

3 Abrade
1 Fire // Ice
"""

PLAIN_WITH_SB = """4x Shock
4x Fable of the Mirror-Breaker
53x Mountain
SB: 3 Abrade
SB: 1 Fire // Ice
this is not a card line
"""


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    rows = [
        (10, "Shock", "Shock deals 2 damage to any target."),
        (11, "Shock", None),  # a second printing without rules text
        (5, "Shock", None),   # lower grp_id, but no rules text either
        (20, "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "Saga text."),
        (30, "Fire // Ice", "Split card text."),
        (40, "Mountain", None),
        (41, "Mountain", None),
        (50, "Abrade", "Choose one."),
        (60, "Lurking Companion", "Companion text."),
    ]
    c.executemany("INSERT INTO cards (grp_id, name, oracle_text) VALUES (?, ?, ?)", rows)
    c.commit()
    yield c
    c.close()


def test_arena_export_strips_printings_and_files_the_companion_in_the_sideboard():
    parsed = parse_decklist(ARENA_EXPORT)
    assert dict(parsed.main) == {
        "Shock": 4, "Fable of the Mirror-Breaker": 4, "Fire // Ice": 4, "Mountain": 48,
    }
    assert dict(parsed.side) == {"Lurking Companion": 1, "Abrade": 3, "Unknown Testcard": 2}
    assert parsed.warnings == ()


def test_mtgo_export_takes_the_blank_line_as_the_sideboard():
    parsed = parse_decklist(MTGO_EXPORT)
    assert dict(parsed.main) == {"Shock": 4, "Fable of the Mirror-Breaker": 4, "Mountain": 52}
    assert dict(parsed.side) == {"Abrade": 3, "Fire // Ice": 1}
    assert parsed.warnings == ()


def test_plain_text_with_sb_lines_and_a_61_card_main():
    parsed = parse_decklist(PLAIN_WITH_SB)
    assert sum(parsed.main.values()) == 61
    assert dict(parsed.side) == {"Abrade": 3, "Fire // Ice": 1}
    # 61 is legal (only fewer than 60 warns); the unreadable line is quoted
    assert parsed.warnings == (
        'Could not read this line, so it was left out: "this is not a card line"',
    )


def test_warnings_for_short_main_long_side_and_a_fifth_copy():
    text = "5 Shock\n20 Mountain\n\n16 Abrade\n"
    parsed = parse_decklist(text)
    assert parsed.warnings == (
        "The maindeck has 25 cards, fewer than 60.",
        "The sideboard has 16 cards, more than 15.",
        "16 copies of Abrade across the maindeck and sideboard, more than 4.",
        "5 copies of Shock across the maindeck and sideboard, more than 4.",
    )


def test_resolution_by_name_front_face_and_split_name(conn):
    resolved = resolve_names(conn, parse_decklist(ARENA_EXPORT))
    # Shock: the printing that carries rules text, not the lowest grp_id (5);
    # Fable by its front face; Fire // Ice by its whole name; Mountain, with
    # no rules text on any printing, the lowest grp_id
    assert sorted(resolved.main_grp_ids) == sorted([10] * 4 + [20] * 4 + [30] * 4 + [40] * 48)
    assert sorted(resolved.side_grp_ids) == sorted([60] + [50] * 3)
    assert resolved.unresolved == ("Unknown Testcard",)


def test_resolution_is_case_insensitive_and_never_fuzzy(conn):
    parsed = parse_decklist("4 shock\n4 Shok\n4 fable of the mirror-breaker\n")
    resolved = resolve_names(conn, parsed)
    assert sorted(resolved.main_grp_ids) == [10] * 4 + [20] * 4
    assert resolved.unresolved == ("Shok",)
