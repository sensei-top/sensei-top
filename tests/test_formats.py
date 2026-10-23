"""The format list, the inclusion order, and the two mappings."""

import re

import pytest

from sensei_top.db import open_database
from sensei_top.formats import (
    BROADER,
    FORMATS,
    SCRYFALL_KEYS,
    arena_format,
    deck_format_name,
    is_within,
)
from sensei_top.mtgo.formats import FORMAT_CODES, MTGO_FORMATS


def test_the_seven_formats_in_mtgos_spelling():
    """The seven formats in MTGO's spelling: MTGO_FORMATS is the same tuple, and every
    FORMAT_CODES value is one of them. The API's Literals
    (api/models/metagame.py::FormatName, api/models/matches.py::MtgoFormat) are
    Literal[FORMATS] and Literal[MTGO_FORMATS], so they hold by construction. The
    migration 049 and 053 CHECKs are pinned by test_the_format_checks_list_exactly_formats."""
    assert FORMATS == (
        "Standard", "Pioneer", "Modern", "Pauper", "Legacy", "Vintage", "Premodern",
    )
    assert MTGO_FORMATS == FORMATS
    assert set(FORMAT_CODES.values()) == set(FORMATS)


@pytest.mark.parametrize("table", ["card_legality", "mtgo_match_pick"])
def test_the_format_checks_list_exactly_formats(tmp_path, table):
    """The CHECK on ``format`` is a copy of FORMATS that SQL cannot import: a format
    added to FORMATS alone passes the API and then fails the INSERT. Read from the
    migrated schema, not the migration files, since a later migration may rebuild the
    table."""
    conn = open_database(tmp_path / "formats.db")
    try:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,),
        ).fetchone()
    finally:
        conn.close()
    assert sql is not None, f"table {table} is missing from the migrated schema"
    match = re.search(
        r"\bformat\s+[^,]*?CHECK\s*\(\s*format\s+IN\s*\(([^)]*)\)", sql[0], re.IGNORECASE,
    )
    assert match is not None, f"no format CHECK found in {table}"
    listed = re.findall(r"'([^']*)'", match.group(1))
    assert sorted(listed) == sorted(FORMATS)


def test_scryfall_keys_are_the_lowercase_names():
    """cards.py reads Scryfall's legalities through this map; a wrong key silently drops a
    format."""
    assert dict(SCRYFALL_KEYS) == {
        "Standard": "standard", "Pioneer": "pioneer", "Modern": "modern",
        "Pauper": "pauper", "Legacy": "legacy", "Vintage": "vintage",
        "Premodern": "premodern",
    }


def test_the_main_chain_nests():
    """Inference picks the narrowest fitting format; a wrong superset set would pick the wrong
    one."""
    assert BROADER["Standard"] == {"Pioneer", "Modern", "Legacy", "Vintage"}
    assert BROADER["Pioneer"] == {"Modern", "Legacy", "Vintage"}
    assert BROADER["Modern"] == {"Legacy", "Vintage"}
    assert BROADER["Legacy"] == {"Vintage"}
    assert BROADER["Vintage"] == frozenset()


def test_premodern_is_inside_legacy_and_pauper_inside_vintage_only():
    """Pauper stays only confirmed, never inferred, because it nests nowhere but under
    Vintage."""
    assert BROADER["Premodern"] == {"Legacy", "Vintage"}
    assert BROADER["Pauper"] == {"Vintage"}


@pytest.mark.parametrize("a, b", [
    ("Pauper", "Standard"), ("Pauper", "Modern"), ("Pauper", "Legacy"),
    ("Premodern", "Modern"), ("Premodern", "Pioneer"), ("Premodern", "Standard"),
    ("Premodern", "Pauper"),
])
def test_incomparable_pairs_include_neither_way(a, b):
    """Incomparable formats must give no tiebreak, so inference reports ambiguous."""
    assert not is_within(a, b)
    assert not is_within(b, a)


def test_is_within_is_strict():
    """A format is not inside itself, or the narrowest-fit search would never end on one."""
    assert is_within("Standard", "Vintage")
    assert not is_within("Modern", "Modern")
    assert not is_within("Vintage", "Standard")


@pytest.mark.parametrize("deck_format, event_id, expected", [
    ("Standard", None, "Standard"),
    ("TraditionalStandard", None, "Standard"),
    ("StandardBrawl", None, None),
    ("Historic", None, None),
    (None, "Traditional_Ladder_2026", "Standard"),
    (None, "Play_Brawl_Direct", None),
    (None, "Draft_FDN_20260101", None),
    (None, None, None),
])
def test_arena_format(deck_format, event_id, expected):
    """Moved from classify.format_key: StandardBrawl and Arena-only queues must never read as
    Standard."""
    assert arena_format(deck_format, event_id) == expected


@pytest.mark.parametrize("stored, expected", [
    ("TraditionalStandard", "Standard"),
    ("Standard", "Standard"),
    ("Modern", "Modern"),
    ("Premodern", "Premodern"),
    ("Draft", None),
    ("Brawl", None),
    ("", None),
    (None, None),
])
def test_deck_format_name(stored, expected):
    """Arena's spelling maps, Draft and unknown names give none rather than a guess."""
    assert deck_format_name(stored) == expected
