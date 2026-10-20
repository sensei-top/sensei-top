"""Scryfall card-name import.

No network here: ``fetch_default_cards`` is the only function that opens a
socket and it is left alone, while ``upsert_cards`` is fed the shapes Scryfall
actually returns. Card entries below are trimmed to the fields we read.
"""

import gzip
import io
import json
import sqlite3
import sys
from itertools import pairwise
from pathlib import Path
from xml.etree import ElementTree

import pytest

from sensei_top.cards import (
    _CountingReader,
    arena_card_database_path,
    arena_cards_missing,
    import_arena_cards,
    print_progress,
    refresh_arena_cards,
    upsert_cards,
)
from sensei_top.db import open_database


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "cards.db")
    yield c
    c.close()


def card(**overrides) -> dict:
    base = {
        "arena_id": 68738,
        "name": "Island",
        "mana_cost": "",
        "type_line": "Basic Land — Island",
        "rarity": "common",
        "set": "dmu",
        "colors": [],
    }
    return {**base, **overrides}


def test_only_arena_legal_printings_are_kept(conn):
    """Most of the export is paper-only; a card with no arena_id has no grpId
    to join against and would just bloat the table."""
    assert upsert_cards(conn, [card(), {"name": "Paper Only", "rarity": "rare"}]) == 1
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1


def test_card_fields_are_stored(conn):
    upsert_cards(conn, [card(arena_id=102774, name="Consider", mana_cost="{U}",
                             type_line="Instant", rarity="common", colors=["U"])])
    row = conn.execute("SELECT * FROM cards WHERE grp_id = 102774").fetchone()
    assert (row["name"], row["mana_cost"], row["type_line"]) == ("Consider", "{U}", "Instant")
    assert json.loads(row["colors"]) == ["U"]


def test_double_faced_cards_take_cost_and_colors_from_the_front(conn):
    """A transforming card carries no top-level cost — only the faces do — but
    its top-level name is already the combined 'Front // Back'."""
    upsert_cards(
        conn,
        [
            {
                "arena_id": 90000,
                "name": "Delver of Secrets // Insectile Aberration",
                "rarity": "common",
                "set": "mid",
                "card_faces": [
                    {"name": "Delver of Secrets", "mana_cost": "{U}", "colors": ["U"]},
                    {"name": "Insectile Aberration", "mana_cost": "", "colors": ["U"]},
                ],
            }
        ],
    )
    row = conn.execute("SELECT * FROM cards WHERE grp_id = 90000").fetchone()
    assert row["name"] == "Delver of Secrets // Insectile Aberration"
    assert row["mana_cost"] == "{U}"
    assert json.loads(row["colors"]) == ["U"]


def test_rerunning_refreshes_names_instead_of_duplicating(conn):
    """The command is re-run whenever a set is released."""
    upsert_cards(conn, [card()])
    upsert_cards(conn, [card(name="Island (renamed)")])
    rows = conn.execute("SELECT grp_id, name FROM cards").fetchall()
    assert [(r["grp_id"], r["name"]) for r in rows] == [(68738, "Island (renamed)")]


def test_a_card_without_a_name_is_skipped(conn):
    """name is NOT NULL: an entry missing it is malformed, not merely sparse."""
    assert upsert_cards(conn, [card(name=None)]) == 0


def test_oracle_text_is_stored(conn):
    upsert_cards(conn, [card(arena_id=95062, name="Sunfall", oracle_text="Exile all creatures.")])
    row = conn.execute("SELECT oracle_text FROM cards WHERE grp_id = 95062").fetchone()
    assert row["oracle_text"] == "Exile all creatures."


def test_a_later_import_with_no_oracle_text_does_not_erase_it(conn):
    """The Arena-client path never supplies oracle_text at all (migrations/
    015_card_text.sql) — re-importing from it after a Scryfall run must not
    blank out text that path never claims to know."""
    upsert_cards(conn, [card(oracle_text="Some rules text.")])
    upsert_cards(conn, [card()])  # no oracle_text key: falls back to None
    row = conn.execute("SELECT oracle_text FROM cards WHERE grp_id = 68738").fetchone()
    assert row["oracle_text"] == "Some rules text."


def standard_of(conn, grp_id) -> str | None:
    """A card's Standard legality, read from card_legality; None when unknown."""
    row = conn.execute(
        "SELECT legality FROM card_legality WHERE grp_id = ? AND format = 'Standard'", (grp_id,)
    ).fetchone()
    return row["legality"] if row else None


def test_standard_legality_and_oracle_id_are_stored(conn):
    upsert_cards(
        conn,
        [
            card(
                arena_id=70344,
                name="Oko, Thief of Crowns",
                legalities={"standard": "banned"},
                oracle_id="0e4d3f01-1234-4abc-9def-0123456789ab",
            )
        ],
    )
    row = conn.execute("SELECT oracle_id FROM cards WHERE grp_id = 70344").fetchone()
    assert standard_of(conn, 70344) == "banned"
    assert row["oracle_id"] == "0e4d3f01-1234-4abc-9def-0123456789ab"


def test_a_later_import_with_no_legality_does_not_erase_it(conn):
    """Same COALESCE discipline as oracle_text: the Arena-client path never
    supplies a legality or oracle_id (migrations/017_card_legality.sql)."""
    upsert_cards(conn, [card(legalities={"standard": "banned"}, oracle_id="abc-123")])
    upsert_cards(conn, [card()])  # no legalities/oracle_id keys: fall back to None
    row = conn.execute(
        "SELECT oracle_id FROM cards WHERE grp_id = 68738"
    ).fetchone()
    assert (standard_of(conn, 68738), row["oracle_id"]) == ("banned", "abc-123")


def test_produced_mana_is_stored(conn):
    """Steam Vents taps for either red or blue — the field `cards.colors`
    cannot answer, since a land's own color identity is `[]` (migrations/
    021_produced_mana.sql)."""
    upsert_cards(conn, [card(produced_mana=["U", "R"])])
    row = conn.execute("SELECT produced_mana FROM cards WHERE grp_id = 68738").fetchone()
    assert json.loads(row["produced_mana"]) == ["U", "R"]


def test_a_later_import_with_no_produced_mana_does_not_erase_it(conn):
    """The Arena-client path never supplies produced_mana at all — same
    COALESCE discipline as oracle_text, since it is the default/preferred
    import path (module docstring) and re-running it after Arena patches
    must not blank out what a one-time Scryfall run already supplied."""
    upsert_cards(conn, [card(produced_mana=["U", "R"])])
    upsert_cards(conn, [card()])  # no produced_mana key: falls back to None
    row = conn.execute("SELECT produced_mana FROM cards WHERE grp_id = 68738").fetchone()
    assert json.loads(row["produced_mana"]) == ["U", "R"]


def test_power_toughness_and_keywords_are_stored(conn):
    """Cursed Wombat (MH3): a 2/3 for {B}{G} with no keyword ability of its
    own (its ability is an activated cost, not a keyword) — migrations/
    031_card_body.sql."""
    upsert_cards(
        conn,
        [
            card(
                arena_id=94021,
                name="Cursed Wombat",
                mana_cost="{B}{G}",
                type_line="Creature — Elemental",
                rarity="uncommon",
                power="2",
                toughness="3",
                keywords=[],
            )
        ],
    )
    row = conn.execute(
        "SELECT power, toughness, keywords FROM cards WHERE grp_id = 94021"
    ).fetchone()
    assert (row["power"], row["toughness"]) == ("2", "3")
    assert json.loads(row["keywords"]) == []


def test_a_later_import_with_no_body_does_not_erase_it(conn):
    """Same COALESCE discipline as produced_mana: the Arena-client path never
    supplies power/toughness/keywords at all."""
    upsert_cards(conn, [card(power="2", toughness="3", keywords=["Flying"])])
    upsert_cards(conn, [card()])  # no power/toughness/keywords keys: fall back to None
    row = conn.execute(
        "SELECT power, toughness, keywords FROM cards WHERE grp_id = 68738"
    ).fetchone()
    assert (row["power"], row["toughness"]) == ("2", "3")
    assert json.loads(row["keywords"]) == ["Flying"]


def test_double_faced_cards_take_power_and_toughness_from_the_front():
    """A DFC's top-level card carries no power/toughness at all — only its
    faces do (Delver of Secrets has no top-level 'power'), same front-face
    fallback as mana_cost/type_line."""
    conn = open_database(":memory:")
    upsert_cards(
        conn,
        [
            {
                "arena_id": 90001,
                "name": "Delver of Secrets // Insectile Aberration",
                "rarity": "common",
                "set": "mid",
                "card_faces": [
                    {"name": "Delver of Secrets", "mana_cost": "{U}", "colors": ["U"],
                     "power": "1", "toughness": "1"},
                    {"name": "Insectile Aberration", "mana_cost": "", "colors": ["U"],
                     "power": "3", "toughness": "2"},
                ],
            }
        ],
    )
    row = conn.execute("SELECT power, toughness FROM cards WHERE grp_id = 90001").fetchone()
    assert (row["power"], row["toughness"]) == ("1", "1")
    conn.close()


def test_arena_import_leaves_body_and_keywords_null(conn, tmp_path):
    """The client's own database carries no power/toughness/keywords at all —
    same honest gap as oracle_text/legality/produced_mana."""
    path = arena_database(
        tmp_path / "body.mtga",
        [(1, 10, 11, 0, "", 2, "", "WOE")],
        [(10, 1, "Some Card"), (11, 1, "Creature")],
    )
    import_arena_cards(conn, path)
    row = conn.execute("SELECT power, toughness, keywords FROM cards").fetchone()
    assert (row["power"], row["toughness"], row["keywords"]) == (None, None, None)


def test_arena_import_leaves_legality_and_oracle_id_null(conn, tmp_path):
    """The client's own database carries neither field at all."""
    path = arena_database(
        tmp_path / "legality.mtga",
        [(1, 10, 11, 0, "", 2, "", "WOE")],
        [(10, 1, "Some Card"), (11, 1, "Creature")],
    )
    import_arena_cards(conn, path)
    row = conn.execute("SELECT grp_id, oracle_id FROM cards").fetchone()
    assert (standard_of(conn, row["grp_id"]), row["oracle_id"]) == (None, None)


# --- the installed client's own card database -------------------------------


def arena_database(path, rows, localizations=None):
    """A miniature of Arena's Raw_CardDatabase: the two tables we read, with
    the columns we select. Field names and the Formatted=1 convention are
    taken from the real file shipped with the client."""
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE Cards (GrpId INT PRIMARY KEY, TitleId INT, TypeTextId INT,
                            SubtypeTextId INT, OldSchoolManaText TEXT, Rarity INT,
                            Colors TEXT, ExpansionCode TEXT);
        CREATE TABLE Localizations_enUS (LocId INT, Formatted INT, Loc TEXT,
                                         PRIMARY KEY (LocId, Formatted));
        """
    )
    db.executemany("INSERT INTO Cards VALUES (?,?,?,?,?,?,?,?)", rows)
    db.executemany("INSERT INTO Localizations_enUS VALUES (?,?,?)", localizations or [])
    db.commit()
    db.close()
    return path


def test_arena_database_names_cards_scryfall_cannot(conn, tmp_path):
    """Tokens and the back faces of double-faced cards appear in a game log
    like any other card, but carry no Scryfall arena_id. The client's own
    database is what closes that gap."""
    path = arena_database(
        tmp_path / "cards.mtga",
        [
            (86836, 100, 101, 102, "o1oR", 3, "4", "WOE"),   # DFC back face
            (95822, 200, 201, 202, "", 0, "", "TDM"),        # token
        ],
        [
            (100, 1, "Stoke Genius"), (101, 1, "Sorcery"), (102, 1, "Adventure"),
            (200, 1, "Monk"), (201, 1, "Token Creature"), (202, 1, "Monk"),
        ],
    )
    assert import_arena_cards(conn, path) == 2
    rows = {r["grp_id"]: r for r in conn.execute("SELECT * FROM cards")}
    assert rows[86836]["name"] == "Stoke Genius"
    assert rows[86836]["type_line"] == "Sorcery — Adventure"
    assert rows[95822]["name"] == "Monk"


def test_arena_mana_notation_is_converted(conn, tmp_path):
    """Arena writes o5oR where the rest of the world writes {5}{R}."""
    path = arena_database(
        tmp_path / "m.mtga",
        [(1, 10, 11, 0, "o5oR", 4, "4", "WOE")],
        [(10, 1, "Hearth Elemental"), (11, 1, "Creature")],
    )
    import_arena_cards(conn, path)
    assert conn.execute("SELECT mana_cost FROM cards").fetchone()[0] == "{5}{R}"


def test_arena_rarity_and_colors_are_decoded(conn, tmp_path):
    """Both are integer enums in the client's database. The rarity mapping was
    cross-checked against Scryfall's own rarities over 19,600 shared cards."""
    path = arena_database(
        tmp_path / "r.mtga",
        [(1, 10, 11, 0, "", 5, "2,4", "WOE")],
        [(10, 1, "Some Card"), (11, 1, "Instant")],
    )
    import_arena_cards(conn, path)
    row = conn.execute("SELECT rarity, colors FROM cards").fetchone()
    assert row["rarity"] == "mythic"
    assert json.loads(row["colors"]) == ["U", "R"]


def test_a_card_with_no_english_title_is_skipped(conn, tmp_path):
    """Internal objects exist in the table with no display name; they are not
    cards and must not reach the dashboard."""
    path = arena_database(
        tmp_path / "u.mtga",
        [(6, 999, 0, 0, "", 0, "", ""), (7, 10, 11, 0, "", 2, "", "MIR")],
        [(10, 1, "Crash of Rhinos"), (11, 1, "Creature")],
    )
    assert import_arena_cards(conn, path) == 1


def test_arena_import_is_rerunnable_after_a_client_patch(conn, tmp_path):
    path = arena_database(
        tmp_path / "v1.mtga",
        [(1, 10, 11, 0, "", 2, "", "WOE")],
        [(10, 1, "Old Name"), (11, 1, "Creature")],
    )
    import_arena_cards(conn, path)
    patched = arena_database(
        tmp_path / "v2.mtga",
        [(1, 10, 11, 0, "", 2, "", "WOE")],
        [(10, 1, "New Name"), (11, 1, "Creature")],
    )
    import_arena_cards(conn, patched)
    rows = conn.execute("SELECT grp_id, name FROM cards").fetchall()
    assert [(r["grp_id"], r["name"]) for r in rows] == [(1, "New Name")]


def test_arena_database_is_opened_read_only(conn, tmp_path):
    """The client's file is not ours to touch."""
    path = arena_database(
        tmp_path / "ro.mtga",
        [(1, 10, 11, 0, "", 2, "", "WOE")],
        [(10, 1, "A Card"), (11, 1, "Creature")],
    )
    before = path.read_bytes()
    import_arena_cards(conn, path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "dirname",
    [
        "a#b %c ã",
        pytest.param(
            "a?b",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="no ? in Windows names"),
        ),
    ],
)
def test_arena_database_in_a_directory_with_uri_special_characters(conn, tmp_path, dirname):
    """The client's file is opened through a ``file:`` URI; ``#``, ``%``, ``?``
    and a non-ASCII letter in its path must not change which file that is."""
    folder = tmp_path / dirname
    folder.mkdir()
    path = arena_database(
        folder / "x.mtga",
        [(1, 10, 11, 0, "", 2, "", "WOE")],
        [(10, 1, "Some Card"), (11, 1, "Creature")],
    )

    assert arena_cards_missing(conn, path) == 1
    assert import_arena_cards(conn, path) == 1
    assert arena_cards_missing(conn, path) == 0


def test_card_database_is_found_in_a_non_default_steam_library(monkeypatch, steam_libraries):
    """Same discovery problem as the log: Arena may be installed on any drive."""
    default_steam, other_library = steam_libraries
    monkeypatch.setattr("sensei_top.steam.STEAM_DATA_DIRS", (default_steam,))
    raw = other_library / "steamapps/common/MTGA/MTGA_Data/Downloads/Raw"
    raw.mkdir(parents=True)
    expected = raw / "Raw_CardDatabase_abc123.mtga"
    expected.write_text("")
    assert arena_card_database_path() == expected


def test_no_arena_installation_reports_none(monkeypatch, tmp_path):
    """Which is what makes the Scryfall fallback reachable."""
    monkeypatch.setattr("sensei_top.steam.STEAM_DATA_DIRS", (tmp_path / "nope",))
    assert arena_card_database_path() is None


def test_refresh_arena_cards_imports_only_whats_missing(conn, tmp_path, monkeypatch):
    """The Cube-pack gap the module docstring measures: a grpId the
    installed client's own database defines but `cards` doesn't have a row
    for yet. `arena_cards_missing` counts it, and `refresh_arena_cards`
    imports only that row — leaving the already-known one alone — then
    reports 0 once nothing is missing any more."""
    path = arena_database(
        tmp_path / "missing.mtga",
        [
            (1, 10, 11, 0, "", 2, "", "WOE"),
            (2, 20, 21, 0, "", 2, "", "WOE"),
        ],
        [
            (10, 1, "Already Here"), (11, 1, "Creature"),
            (20, 1, "New Card"), (21, 1, "Creature"),
        ],
    )
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors) "
        "VALUES (1, 'Already Here', 'common', 'WOE', '[]')"
    )
    conn.commit()
    monkeypatch.setattr("sensei_top.cards.arena_card_database_path", lambda: path)

    assert arena_cards_missing(conn, path) == 1
    assert refresh_arena_cards(conn) == 1
    rows = {r["grp_id"]: r["name"] for r in conn.execute("SELECT grp_id, name FROM cards")}
    assert rows == {1: "Already Here", 2: "New Card"}
    assert arena_cards_missing(conn, path) == 0
    assert refresh_arena_cards(conn) == 0


def test_refresh_arena_cards_reports_none_without_an_install(monkeypatch, tmp_path, conn):
    """No installed client, no path — `refresh_arena_cards` reports None
    rather than raising, same fail-soft shape as `arena_card_database_path`
    itself."""
    monkeypatch.setattr("sensei_top.cards.arena_card_database_path", lambda: None)
    assert refresh_arena_cards(conn) is None


# --- localization markup ----------------------------------------------------
# Formatted=1 is the display form and carries Unity rich-text markup; the plain
# Formatted=0 twin is the one that renders and the one an outside card list
# uses. See read_arena_cards' docstring for why stripping tags is not the fix.


def test_plain_localization_wins_over_display_markup(conn, tmp_path):
    path = arena_database(
        tmp_path / "n.mtga",
        [(1, 10, 11, 12, "", 2, "", "DMU")],
        [
            (10, 1, "<nobr>Deep-Cavern</nobr> Bat"), (10, 0, "Deep-Cavern Bat"),
            (11, 1, "Creature"), (12, 1, "Bat"),
        ],
    )
    import_arena_cards(conn, path)
    assert conn.execute("SELECT name FROM cards").fetchone()[0] == "Deep-Cavern Bat"


def test_rebalanced_card_keeps_its_a_prefix(conn, tmp_path):
    """Alchemy's rebalanced cards wear a sprite badge instead of the 'A-' the
    plain name spells out. Stripping the tag would silently rename the card to
    its paper original, which is a different card with different rules text."""
    path = arena_database(
        tmp_path / "a.mtga",
        [(1, 10, 11, 0, "", 4, "", "Y22")],
        [
            (10, 1, '<sprite="SpriteSheet_MiscIcons" name="arena_a">Cori-Steel Cutter'),
            (10, 0, "A-Cori-Steel Cutter"),
            (11, 1, "Artifact"),
        ],
    )
    import_arena_cards(conn, path)
    assert conn.execute("SELECT name FROM cards").fetchone()[0] == "A-Cori-Steel Cutter"


def test_type_line_markup_is_also_resolved(conn, tmp_path):
    """Subtypes carry markup too, so the same COALESCE covers all three joins."""
    path = arena_database(
        tmp_path / "t.mtga",
        [(1, 10, 11, 12, "", 2, "", "BRO")],
        [
            (10, 1, "Some Card"), (11, 1, "Artifact Creature"),
            (12, 1, "<nobr>Assembly-Worker</nobr>"), (12, 0, "Assembly-Worker"),
        ],
    )
    import_arena_cards(conn, path)
    assert conn.execute("SELECT type_line FROM cards").fetchone()[0] == (
        "Artifact Creature — Assembly-Worker"
    )


def test_a_card_with_only_a_display_title_still_imports(conn, tmp_path):
    """The 25,308 cards whose name needs no markup have no plain twin at all."""
    path = arena_database(
        tmp_path / "d.mtga",
        [(1, 10, 11, 0, "", 2, "", "MIR")],
        [(10, 1, "Crash of Rhinos"), (11, 1, "Creature")],
    )
    assert import_arena_cards(conn, path) == 1
    assert conn.execute("SELECT name FROM cards").fetchone()[0] == "Crash of Rhinos"


# --- name backfill -----------------------------------------------------------
# arena_id covers only one representative printing per functional card. An
# alternate-art/showcase/bonus-sheet sibling, or a DFC/Adventure/Omen/Room
# second face, gets its own grpId from Arena but no arena_id from Scryfall, so
# it never reaches `_row`/`_write` directly. Simulate "already in the table
# from a prior installed-client import" by inserting the sibling row by hand,
# the same way `import_arena_cards` would have left it: named, but with
# legality/oracle_id still NULL because that path never supplies them.


def test_alternate_art_sibling_is_filled_by_name(conn):
    """A borderless/showcase sibling shares the primary printing's name but
    not its arena_id. The name backfill fills it from the printing Scryfall
    did attach arena_id to."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors) "
        "VALUES (99001, 'Fated Firepower', 'rare', 'TLA', '[]')"
    )
    conn.commit()
    upsert_cards(
        conn,
        [
            card(
                arena_id=99000,
                name="Fated Firepower",
                rarity="rare",
                set="tla",
                legalities={"standard": "legal"},
                oracle_id="abc-firepower",
            )
        ],
    )
    row = conn.execute(
        "SELECT oracle_id FROM cards WHERE grp_id = 99001"
    ).fetchone()
    assert (standard_of(conn, 99001), row["oracle_id"]) == ("legal", "abc-firepower")


def test_back_face_row_is_filled_via_card_faces(conn):
    """A DFC's back face gets its own grpId from Arena (it can be drawn,
    cast, seen alone in a log entry) but Scryfall's arena_id names only the
    combined front // back card. The backfill indexes each face's own name
    too, so the back face's own row is reachable by exact match."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors) "
        "VALUES (99101, 'Insectile Aberration', 'common', 'MID', '[]')"
    )
    conn.commit()
    upsert_cards(
        conn,
        [
            {
                "arena_id": 99100,
                "name": "Delver of Secrets // Insectile Aberration",
                "rarity": "common",
                "set": "mid",
                "legalities": {"standard": "legal"},
                "oracle_id": "abc-delver",
                "card_faces": [
                    {"name": "Delver of Secrets", "mana_cost": "{U}", "colors": ["U"]},
                    {"name": "Insectile Aberration", "mana_cost": "", "colors": ["U"]},
                ],
            }
        ],
    )
    row = conn.execute(
        "SELECT oracle_id FROM cards WHERE grp_id = 99101"
    ).fetchone()
    assert (standard_of(conn, 99101), row["oracle_id"]) == ("legal", "abc-delver")


def test_om1_marvel_names_resolve_via_printed_name(conn):
    """OM1 is Arena's Marvel-skinned Standard set: its printings carry no
    arena_id at all under Scryfall's `om1` set (only under the separate `spm`
    set), but the om1 object itself already carries correct Standard legality
    under `printed_name` (the Marvel name Arena actually shows), distinct from
    `name` (the real-world card). Indexing printed_name resolves this with no
    om1->spm set alias needed."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors) "
        "VALUES (99201, 'Verilax the Havenskin', 'rare', 'OM1', '[]')"
    )
    conn.commit()
    upsert_cards(
        conn,
        [
            {
                # No arena_id: this om1 printing never enters the primary
                # write, only the name index.
                "name": "Anti-Venom, Horrifying Healer",
                "printed_name": "Verilax the Havenskin",
                "rarity": "rare",
                "set": "om1",
                "legalities": {"standard": "legal"},
                "oracle_id": "abc-antivenom",
            }
        ],
    )
    row = conn.execute(
        "SELECT oracle_id FROM cards WHERE grp_id = 99201"
    ).fetchone()
    assert (standard_of(conn, 99201), row["oracle_id"]) == ("legal", "abc-antivenom")


def test_token_row_stays_null(conn):
    """A token often carries a generic name ("Food", "Clue") that could
    collide with an unrelated real card. Tokens are excluded from the name
    index entirely, so a token row already in the table stays NULL rather
    than picking up a stray legality — and, in the other direction, a real
    card must never inherit a token's own (non-)legality either."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors) "
        "VALUES (99301, 'Food', 'common', 'WOE', '[]')"
    )
    conn.commit()
    upsert_cards(
        conn,
        [
            {
                "name": "Food",
                "layout": "token",
                "rarity": "common",
                "set": "twoe",
                "type_line": "Token Artifact — Food",
                "legalities": {"standard": "legal"},
                "oracle_id": "abc-food-token",
            }
        ],
    )
    row = conn.execute(
        "SELECT oracle_id FROM cards WHERE grp_id = 99301"
    ).fetchone()
    assert (standard_of(conn, 99301), row["oracle_id"]) == (None, None)


def test_arena_token_row_never_takes_a_real_cards_legality(conn):
    """The other direction: Scryfall also lists a non-token object named
    "Treasure" (not Standard-legal), and Arena's own Treasure token row shares
    that name. Filling the token would mark any match that made a Treasure as
    not Standard, so a row whose type_line says Token is never a backfill
    target."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, rarity, set_code, colors) "
        "VALUES (98012, 'Treasure', 'Token Artifact — Treasure', 'common', 'OM1', '[]')"
    )
    conn.commit()
    upsert_cards(
        conn,
        [
            {
                "name": "Treasure",
                "layout": "normal",
                "rarity": "common",
                "set": "ptrs",
                "type_line": "Artifact — Treasure",
                "legalities": {"standard": "not_legal"},
                "oracle_id": "abc-treasure-card",
            }
        ],
    )
    row = conn.execute(
        "SELECT oracle_id FROM cards WHERE grp_id = 98012"
    ).fetchone()
    assert (standard_of(conn, 98012), row["oracle_id"]) == (None, None)


def test_ambiguous_name_stays_null_and_is_counted(conn, capsys):
    """Two distinct printings sharing a name but disagreeing on legality (or
    oracle_id) must never guess which one a NULL sibling means — left NULL,
    and counted in the summary line rather than silently dropped."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors) "
        "VALUES (99401, 'Ambiguous Name', 'rare', 'ECL', '[]')"
    )
    conn.commit()
    upsert_cards(
        conn,
        [
            card(
                arena_id=99400,
                name="Ambiguous Name",
                rarity="rare",
                set="ecl",
                legalities={"standard": "legal"},
                oracle_id="abc-one",
            ),
            card(
                arena_id=99402,
                name="Ambiguous Name",
                rarity="rare",
                set="ecl",
                legalities={"standard": "not_legal"},
                oracle_id="abc-two",
            ),
        ],
    )
    row = conn.execute(
        "SELECT oracle_id FROM cards WHERE grp_id = 99401"
    ).fetchone()
    assert (standard_of(conn, 99401), row["oracle_id"]) == (None, None)
    assert "1 name(s) left ambiguous" in capsys.readouterr().out


def test_disagreeing_keyword_order_still_fills_legality_and_oracle_id(conn, capsys):
    """A mismatch on a field *other than* legality/oracle_id must not blank
    the legality/oracle_id fix this backfill exists for. Two printings of
    "Disagreeing Keywords" agree on oracle_id, Standard legality and
    oracle_text, but list `keywords` in a different order — `["Flying",
    "Trample"]` vs. `["Trample", "Flying"]` — which round-trips through
    `json.dumps` as two distinct strings, a real disagreement on that field
    alone. The name is not ambiguous (legality/oracle_id agree), so the row
    gets legality, oracle_id and oracle_text filled; `keywords` itself — the
    one field that actually disagreed — stays NULL rather than guessed."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors) "
        "VALUES (99701, 'Disagreeing Keywords', 'rare', 'ECL', '[]')"
    )
    conn.commit()
    upsert_cards(
        conn,
        [
            card(
                arena_id=99700,
                name="Disagreeing Keywords",
                rarity="rare",
                set="ecl",
                legalities={"standard": "legal"},
                oracle_id="abc-shared",
                oracle_text="Flying, trample.",
                keywords=["Flying", "Trample"],
            ),
            card(
                arena_id=99702,
                name="Disagreeing Keywords",
                rarity="rare",
                set="ecl",
                legalities={"standard": "legal"},
                oracle_id="abc-shared",
                oracle_text="Flying, trample.",
                keywords=["Trample", "Flying"],
            ),
        ],
    )
    row = conn.execute(
        "SELECT oracle_id, oracle_text, keywords FROM cards WHERE grp_id = 99701"
    ).fetchone()
    assert (standard_of(conn, 99701), row["oracle_id"], row["oracle_text"]) == (
        "legal",
        "abc-shared",
        "Flying, trample.",
    )
    assert row["keywords"] is None
    assert "0 name(s) left ambiguous" in capsys.readouterr().out


def test_name_backfill_keeps_an_existing_value_but_replaces_its_legality(conn):
    """COALESCE-only for every column: a row that already carries a value — even
    a stale or differently-sourced one — keeps it. Legality is the exception the
    backfill owns: it takes today's answer for the name (module docstring)."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors, oracle_id) "
        "VALUES (99501, 'Kept Value', 'rare', 'DSK', '[]', 'kept-oracle-id')"
    )
    conn.execute(
        "INSERT INTO card_legality (grp_id, format, legality) VALUES (99501, 'Standard', 'banned')"
    )
    conn.commit()
    upsert_cards(
        conn,
        [
            card(
                arena_id=99500,
                name="Kept Value",
                rarity="rare",
                set="dsk",
                legalities={"standard": "legal"},
                oracle_id="abc-fresh",
            )
        ],
    )
    row = conn.execute(
        "SELECT oracle_id FROM cards WHERE grp_id = 99501"
    ).fetchone()
    assert (standard_of(conn, 99501), row["oracle_id"]) == ("legal", "kept-oracle-id")


def test_backfill_fills_rules_text(conn):
    """The other half of the Cube-pack gap the module docstring measures: a
    row that already resolved a name and oracle_id (an earlier arena_id
    upsert, or a prior installed-client import) but never got oracle_text,
    because the printing that carried the text lived under a different
    grpId. Backfilling by name alone — with no arena_id of its own, so this
    dict never reaches `_row`/`_write` directly — is enough to fill the
    still-NULL rules text."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors, oracle_id) "
        "VALUES (99601, 'Silent Text Card', 'common', 'CUBE', '[]', 'abc-silent')"
    )
    conn.commit()
    upsert_cards(
        conn,
        [
            {
                "name": "Silent Text Card",
                "rarity": "common",
                "set": "woe",
                "oracle_text": "Draw a card.",
            }
        ],
    )
    row = conn.execute(
        "SELECT oracle_text FROM cards WHERE grp_id = 99601"
    ).fetchone()
    assert row["oracle_text"] == "Draw a card."


def test_backfill_never_overwrites_oracle_text(conn):
    """COALESCE-only for the broadened field set too: a row that already
    carries oracle_text keeps its own, even when a same-named Scryfall
    printing offers different text."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors, oracle_text) "
        "VALUES (99602, 'Kept Text Card', 'common', 'CUBE', '[]', 'Original text.')"
    )
    conn.commit()
    upsert_cards(
        conn,
        [
            {
                "name": "Kept Text Card",
                "rarity": "common",
                "set": "woe",
                "oracle_text": "Different text.",
            }
        ],
    )
    row = conn.execute(
        "SELECT oracle_text FROM cards WHERE grp_id = 99602"
    ).fetchone()
    assert row["oracle_text"] == "Original text."


def test_scryfall_set_code_is_uppercased(conn):
    """Scryfall always spells its own `set` field lowercase; the table stores
    uppercase in both import paths (migrations/041)."""
    upsert_cards(conn, [card(set="woe")])
    assert conn.execute("SELECT set_code FROM cards").fetchone()[0] == "WOE"


def test_arena_set_code_is_uppercased(conn, tmp_path):
    """The installed client's own ExpansionCode is uppercase in practice, but
    the writer uppercases regardless rather than trusting that."""
    path = arena_database(
        tmp_path / "lower.mtga",
        [(1, 10, 11, 0, "", 2, "", "woe")],
        [(10, 1, "Some Card"), (11, 1, "Creature")],
    )
    import_arena_cards(conn, path)
    assert conn.execute("SELECT set_code FROM cards").fetchone()[0] == "WOE"


# Magic Online's deck store names a card by its `mtgo_id` alone,
# so every printing that has one is kept in `mtgo_card`, Arena-legal or not.
# `scryfall_mtgo_printings.jsonl` holds five real `default_cards` lines,
# verbatim, picked by `mtgo_id`:
#   25691   Lotus Bloom, no arena_id (an MTGO-only printing)
#   126589  Waterlogged Teachings // Inundated Archive, a modal_dfc that
#           mtgo_deck_double_faced.dek names by its front face
#   139429  Twinmaw Stormbrood // Charring Bite, an adventure, and a CatId in
#           mtgo_grouping_deck.xml
#   146999  Steam Vents // Steam Vents, a reversible_card
#   139609  Marang River Regent // Coil and Catch // Marang River Regent, a
#           three-part reversible_card


def mtgo_printings() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "scryfall_mtgo_printings.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def mtgo_names(conn) -> dict[int, str]:
    return {r["mtgo_id"]: r["name"] for r in conn.execute("SELECT mtgo_id, name FROM mtgo_card")}


def test_mtgo_card_keeps_printings_with_and_without_an_arena_id(conn):
    """Lotus Bloom has no arena_id, so it reaches `cards` only as a synthetic
    negative row; the other two printings that do carry one reach both tables
    under their Arena ids. The return value stays the Arena `cards` count."""
    assert upsert_cards(conn, mtgo_printings()) == 2
    names = mtgo_names(conn)
    assert names[25691] == "Lotus Bloom"
    assert names[126589] == "Waterlogged Teachings // Inundated Archive"
    assert names[139429] == "Twinmaw Stormbrood // Charring Bite"
    arena_names = conn.execute("SELECT name FROM cards WHERE grp_id > 0 ORDER BY grp_id")
    assert [r[0] for r in arena_names] == [
        "Waterlogged Teachings // Inundated Archive",
        "Twinmaw Stormbrood // Charring Bite",
    ]


def test_lotus_bloom_gets_its_mtgo_id_negated(conn):
    """scryfall_mtgo_printings.jsonl: Lotus Bloom, mtgo_id 25691, no arena_id."""
    upsert_cards(conn, mtgo_printings())
    bloom = next(c for c in mtgo_printings() if c["name"] == "Lotus Bloom")
    assert bloom["mtgo_id"] == 25691 and bloom.get("arena_id") is None
    row = conn.execute("SELECT * FROM cards WHERE name = 'Lotus Bloom'").fetchone()
    assert row["grp_id"] == -25691
    assert row["oracle_id"] == bloom["oracle_id"]
    assert row["type_line"] == bloom["type_line"]
    assert row["mana_cost"] == (bloom["mana_cost"] or None)


def test_mtgo_card_name_is_the_one_cards_stores(conn):
    """The same top-level "Front // Back" in both tables, which is what the MTGO
    projector's name -> grp_id rule (exact name, then front-face prefix) is
    written against."""
    upsert_cards(conn, mtgo_printings())
    names = mtgo_names(conn)
    for mtgo_id, grp_id in ((126589, 90848), (139429, 95758)):
        assert conn.execute(
            "SELECT name FROM cards WHERE grp_id = ?", (grp_id,)
        ).fetchone()[0] == names[mtgo_id]


def test_mtgo_card_ids_come_from_the_fixture_decks():
    """The lines were picked from the decks the MTGO fixtures describe: 139429
    is a CatId of the grouping, and the .dek spells 126589 by its front face."""
    grouping = Path(__file__).parent / "fixtures" / "mtgo_grouping_deck.xml"
    cat_ids = {
        int(item.get("CatId"))
        for item in ElementTree.fromstring(grouping.read_bytes()).iter("Item")
    }
    assert 139429 in cat_ids
    deck = Path(__file__).parent / "fixtures" / "mtgo_deck_double_faced.dek"
    card_el = next(
        el for el in ElementTree.fromstring(deck.read_bytes()).iter("Cards")
        if el.get("CatID") == "126589"
    )
    assert card_el.get("Name") == "Waterlogged Teachings"


def test_mtgo_card_reversible_printings_store_their_first_face(conn):
    """Scryfall names a reversible_card "X // X" (or "Front // Adventure //
    Front"), which is no card's name; face 0 holds the card's own name."""
    by_id = {c["mtgo_id"]: c for c in mtgo_printings()}
    assert by_id[146999]["name"] == "Steam Vents // Steam Vents"
    assert by_id[139609]["name"] == (
        "Marang River Regent // Coil and Catch // Marang River Regent"
    )
    upsert_cards(conn, mtgo_printings())
    names = mtgo_names(conn)
    assert names[146999] == "Steam Vents"
    assert names[139609] == "Marang River Regent"


def test_mtgo_card_printings_of_one_name_each_keep_their_row(conn):
    upsert_cards(conn, [
        card(arena_id=None, name="Island", mtgo_id=65001),
        card(arena_id=None, name="Island", mtgo_id=65002),
    ])
    assert mtgo_names(conn) == {65001: "Island", 65002: "Island"}


def test_mtgo_card_rerun_replaces_rather_than_duplicates(conn):
    upsert_cards(conn, [card(arena_id=None, name="Old Name", mtgo_id=70001)])
    upsert_cards(conn, [card(arena_id=None, name="New Name", mtgo_id=70001)])
    assert mtgo_names(conn) == {70001: "New Name"}


def test_mtgo_card_rerun_without_mtgo_ids_keeps_the_map(conn):
    """An export that carries no mtgo_id must not empty what is already known."""
    upsert_cards(conn, mtgo_printings())
    upsert_cards(conn, [card()])
    assert mtgo_names(conn)[25691] == "Lotus Bloom"


def test_mtgo_card_skips_unusable_printings_and_keeps_the_valid_one(conn):
    """The valid printing is what makes this test fail if the writer stores
    nothing at all."""
    upsert_cards(conn, [
        card(arena_id=None, name="No Id"),
        card(arena_id=None, name="Null Id", mtgo_id=None),
        card(arena_id=None, name="", mtgo_id=70002),
        card(arena_id=None, name="Reversible Without Faces", layout="reversible_card",
             mtgo_id=70003),
        card(arena_id=None, name="Valid", mtgo_id=70004),
    ])
    assert mtgo_names(conn) == {70004: "Valid"}


# `scryfall_format_printings.jsonl` holds 17 real `default_cards` lines whose
# `legalities` objects differ by format. Every expectation below is read from
# those lines' own `legalities`.
_FORMAT_KEYS = {
    "Standard": "standard", "Pioneer": "pioneer", "Modern": "modern",
    "Pauper": "pauper", "Legacy": "legacy", "Vintage": "vintage",
    "Premodern": "premodern",
}


def format_printings() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "scryfall_format_printings.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def legality_of(conn, grp_id) -> dict[str, str]:
    rows = conn.execute("SELECT format, legality FROM card_legality WHERE grp_id = ?", (grp_id,))
    return {r["format"]: r["legality"] for r in rows}


def test_every_arena_card_gets_seven_legality_rows_from_its_legalities(conn):
    """Every consumer reads one format's row; a card missing any of the seven would read as
    unknown there."""
    printings = format_printings()
    arena = [c for c in printings if c.get("arena_id") is not None]
    assert arena
    upsert_cards(conn, printings)
    for c in arena:
        expected = {fmt: c["legalities"][key] for fmt, key in _FORMAT_KEYS.items()}
        assert len(expected) == 7
        assert legality_of(conn, c["arena_id"]) == expected


def test_a_printing_without_an_arena_id_writes_legality_only_under_a_synthetic_id(conn):
    """card_legality is keyed by grp_id; an MTGO-only card is keyed by its synthetic id, once
    per oracle card, and a second printing of it adds none."""
    printings = format_printings()
    upsert_cards(conn, printings)
    synthetic = len({c["oracle_id"] for c in printings if c.get("arena_id") is None})
    arena = sum(1 for c in printings if c.get("arena_id") is not None)
    total = conn.execute("SELECT COUNT(*) FROM card_legality").fetchone()[0]
    assert total == 7 * (arena + synthetic)


def test_rerunning_replaces_a_formats_answer(conn):
    """Scryfall's list is today's; a ban after the first run must replace the stored answer, not
    be ignored."""
    printings = format_printings()
    target = next(c for c in printings if c.get("arena_id") is not None)
    upsert_cards(conn, printings)
    changed = {**target, "legalities": {**target["legalities"], "modern": "banned"}}
    upsert_cards(conn, [changed])
    assert legality_of(conn, target["arena_id"])["Modern"] == "banned"
    assert len(legality_of(conn, target["arena_id"])) == 7


def test_a_missing_format_key_leaves_that_format_unknown(conn):
    """An absent key is unknown, never a guessed not_legal (rule 4)."""
    target = next(c for c in format_printings() if c.get("arena_id") is not None)
    legalities = {k: v for k, v in target["legalities"].items() if k != "premodern"}
    upsert_cards(conn, [{**target, "legalities": legalities}])
    assert "Premodern" not in legality_of(conn, target["arena_id"])
    assert len(legality_of(conn, target["arena_id"])) == 6


def _insert_arena_only_row(conn, grp_id, name, type_line="Creature — Human"):
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (?, ?, ?)", (grp_id, name, type_line)
    )
    conn.commit()


def test_name_backfill_writes_all_seven_formats(conn):
    """A sibling grpId with no arena_id of its own needs all seven formats, not just Standard."""
    printings = format_printings()
    mother = next(c for c in printings if c["name"] == "Mother of Runes")
    _insert_arena_only_row(conn, 900001, "Mother of Runes")
    upsert_cards(conn, printings)
    assert legality_of(conn, 900001) == {
        fmt: mother["legalities"][key] for fmt, key in _FORMAT_KEYS.items()
    }


def test_name_backfill_fills_each_format_the_printings_agree_on(conn):
    """The ambiguity rule is Standard legality and oracle_id only. Two printings
    that agree on both and differ only in Pauper: the sibling row gets the six
    agreed formats and its text, and no Pauper row (rule 4: no single answer)."""
    scour = [c for c in format_printings() if c["name"] == "Thought Scour"]
    assert len(scour) == 2
    scour[1] = {**scour[1], "legalities": {**scour[1]["legalities"], "pauper": "banned"}}
    assert scour[0]["legalities"]["pauper"] != scour[1]["legalities"]["pauper"]
    assert scour[0]["legalities"]["standard"] == scour[1]["legalities"]["standard"]
    assert scour[0]["oracle_id"] == scour[1]["oracle_id"]
    _insert_arena_only_row(conn, 900002, "Thought Scour", "Instant")
    upsert_cards(conn, scour)
    row = conn.execute("SELECT oracle_text FROM cards WHERE grp_id = 900002").fetchone()
    assert row["oracle_text"] == scour[0]["oracle_text"]
    assert legality_of(conn, 900002) == {
        fmt: scour[0]["legalities"][key] for fmt, key in _FORMAT_KEYS.items() if fmt != "Pauper"
    }


def test_name_backfill_writes_nothing_when_standard_disagrees(conn, capsys):
    """Printings that disagree on Standard are two different cards sharing a name:
    the sibling gets no legality row in any format, and the name is counted."""
    scour = [c for c in format_printings() if c["name"] == "Thought Scour"]
    assert len(scour) == 2
    other = "banned" if scour[0]["legalities"]["standard"] != "banned" else "legal"
    scour[1] = {**scour[1], "legalities": {**scour[1]["legalities"], "standard": other}}
    assert scour[0]["legalities"]["standard"] != scour[1]["legalities"]["standard"]
    _insert_arena_only_row(conn, 900005, "Thought Scour", "Instant")
    upsert_cards(conn, scour)
    assert legality_of(conn, 900005) == {}
    assert "1 name(s) left ambiguous" in capsys.readouterr().out


def test_a_printing_without_a_standard_value_does_not_blank_the_names_legality(conn, capsys):
    """An absent value is not a disagreement: a printing that omits Standard must
    neither mark the name ambiguous nor stop the sibling taking the other
    printing's Standard legality."""
    scour = [c for c in format_printings() if c["name"] == "Thought Scour"]
    assert len(scour) == 2
    first_standard = scour[0]["legalities"]["standard"]
    scour[1] = {
        **scour[1],
        "legalities": {k: v for k, v in scour[1]["legalities"].items() if k != "standard"},
    }
    _insert_arena_only_row(conn, 900006, "Thought Scour", "Instant")
    upsert_cards(conn, scour)
    assert legality_of(conn, 900006)["Standard"] == first_standard
    assert "0 name(s) left ambiguous" in capsys.readouterr().out


def test_two_arena_printings_of_one_name_each_get_their_own_seven_rows(conn):
    """The direct write, not the name backfill, must give each grp_id its own
    printing's answers: the backfill skips a name whose printings disagree."""
    base = next(c for c in format_printings() if c.get("arena_id") is not None)
    first = {**base, "arena_id": 7001}
    second = {
        **base, "arena_id": 7002,
        "legalities": {**base["legalities"], "pauper": "banned", "modern": "restricted"},
    }
    upsert_cards(conn, [first, second])
    for printing in (first, second):
        expected = {fmt: printing["legalities"][key] for fmt, key in _FORMAT_KEYS.items()}
        assert legality_of(conn, printing["arena_id"]) == expected
    assert legality_of(conn, 7001) != legality_of(conn, 7002)


def test_a_legality_value_outside_the_four_is_dropped_and_counted(conn, capsys):
    """Scryfall could add a value; the CHECK would otherwise abort the whole
    import. That format stays unknown (rule 4) and the run reports the count."""
    target = next(c for c in format_printings() if c.get("arena_id") is not None)
    legalities = {**target["legalities"], "modern": "not_a_value"}
    upsert_cards(conn, [{**target, "legalities": legalities}])
    got = legality_of(conn, target["arena_id"])
    assert "Modern" not in got
    assert len(got) == 6
    assert "1 legality value(s) outside the four known ones dropped" in capsys.readouterr().out


def test_name_backfill_never_marks_a_token_row(conn):
    """A token shares a name with real cards; marking it not_legal would rule a match out of a
    format."""
    printings = format_printings()
    _insert_arena_only_row(conn, 900003, "Mother of Runes", "Token Creature — Human")
    upsert_cards(conn, printings)
    assert legality_of(conn, 900003) == {}


def test_name_backfill_replaces_a_stale_legality_row(conn):
    """Legality is not fill-only: a row an earlier run wrote is replaced by the
    name's answer today, in every format."""
    printings = format_printings()
    mother = next(c for c in printings if c["name"] == "Mother of Runes")
    assert mother["legalities"]["modern"] != "banned"
    _insert_arena_only_row(conn, 900004, "Mother of Runes")
    conn.execute(
        "INSERT INTO card_legality (grp_id, format, legality) VALUES (900004, 'Modern', 'banned')"
    )
    conn.commit()
    upsert_cards(conn, printings)
    assert legality_of(conn, 900004) == {
        fmt: mother["legalities"][key] for fmt, key in _FORMAT_KEYS.items()
    }


def test_a_later_refresh_moves_every_face_to_the_new_legality(conn, capsys):
    """Reality Fracture's shape (module docstring): a printing with no arena_id,
    fetched before its release as not_legal in Standard, then legal. The client's
    rows for the combined name and for each face take the new answer."""
    waif = _waif()
    assert waif["legalities"]["standard"] == "not_legal"
    names = ["Reckless Waif // Merciless Predator", "Reckless Waif", "Merciless Predator"]
    for grp_id, name in enumerate(names, start=900020):
        _insert_arena_only_row(conn, grp_id, name)
    upsert_cards(conn, [waif])
    assert {standard_of(conn, g) for g in range(900020, 900023)} == {"not_legal"}
    capsys.readouterr()

    released = {**waif, "legalities": {**waif["legalities"], "standard": "legal"}}
    upsert_cards(conn, [released])
    assert {standard_of(conn, g) for g in range(900020, 900023)} == {"legal"}
    assert "3 changed or removed" in capsys.readouterr().out


def test_a_format_the_printings_now_disagree_on_loses_its_row(conn):
    """Unknown is no row (rule 4), not the answer an earlier run agreed on."""
    scour = [c for c in format_printings() if c["name"] == "Thought Scour"]
    assert scour[0]["legalities"]["pauper"] == scour[1]["legalities"]["pauper"]
    _insert_arena_only_row(conn, 900030, "Thought Scour", "Instant")
    upsert_cards(conn, scour)
    assert "Pauper" in legality_of(conn, 900030)

    other = "banned" if scour[1]["legalities"]["pauper"] != "banned" else "legal"
    scour[1] = {**scour[1], "legalities": {**scour[1]["legalities"], "pauper": other}}
    upsert_cards(conn, scour)
    assert "Pauper" not in legality_of(conn, 900030)
    assert len(legality_of(conn, 900030)) == 6


def test_the_name_backfill_never_replaces_a_direct_rows_legality(conn):
    """A grpId written from its own arena_id printing keeps that printing's
    answers even when the name's consensus has none for a format."""
    crusader = next(c for c in format_printings() if c["name"] == "Crusader of Odric")
    other = "banned" if crusader["legalities"]["pauper"] != "banned" else "legal"
    paper = {
        **crusader, "arena_id": None, "id": "paper-printing",
        "legalities": {**crusader["legalities"], "pauper": other},
    }
    _insert_arena_only_row(conn, 900040, "Crusader of Odric")
    upsert_cards(conn, [crusader, paper])
    assert legality_of(conn, crusader["arena_id"]) == {
        fmt: crusader["legalities"][key] for fmt, key in _FORMAT_KEYS.items()
    }
    assert "Pauper" not in legality_of(conn, 900040)


def _mtgo_only(printings):
    return [c for c in printings if c.get("arena_id") is None and c.get("mtgo_id") is not None]


def test_an_mtgo_only_card_gets_a_row_under_its_lowest_mtgo_id(conn):
    """Thought Scour has two printings, 43399 and 101614, and no Arena id: one row, -43399."""
    printings = format_printings()
    scour = [c for c in printings if c["name"] == "Thought Scour"]
    lowest = min(c["mtgo_id"] for c in scour)
    assert lowest == 43399 and len(scour) == 2
    upsert_cards(conn, printings)
    rows = conn.execute("SELECT * FROM cards WHERE name = 'Thought Scour'").fetchall()
    assert [r["grp_id"] for r in rows] == [-lowest]
    first = next(c for c in scour if c["mtgo_id"] == lowest)
    assert rows[0]["oracle_id"] == first["oracle_id"]
    assert rows[0]["oracle_text"] == first["oracle_text"]
    assert rows[0]["set_code"] == first["set"].upper()


def test_a_synthetic_row_carries_all_seven_legality_rows(conn):
    printings = format_printings()
    mother = next(c for c in printings if c["name"] == "Mother of Runes")
    upsert_cards(conn, printings)
    assert legality_of(conn, -mother["mtgo_id"]) == {
        fmt: mother["legalities"][key] for fmt, key in _FORMAT_KEYS.items()
    }


def test_a_card_with_an_arena_row_gets_no_synthetic_row(conn):
    printings = format_printings()
    arena = next(c for c in printings if c.get("arena_id") is not None)
    upsert_cards(conn, printings)
    same_name = conn.execute("SELECT grp_id FROM cards WHERE name = ?", (arena["name"],))
    assert [r[0] for r in same_name] == [arena["arena_id"]]


def test_one_synthetic_row_per_mtgo_only_oracle_card(conn):
    printings = format_printings()
    upsert_cards(conn, printings)
    expected = {c["oracle_id"] for c in _mtgo_only(printings)}
    negatives = conn.execute("SELECT COUNT(*) FROM cards WHERE grp_id < 0").fetchone()[0]
    assert negatives == len(expected)


def test_synthetic_rows_are_rewritten_idempotently(conn):
    printings = format_printings()
    upsert_cards(conn, printings)
    def state():
        rows = conn.execute("SELECT grp_id, name FROM cards WHERE grp_id < 0 ORDER BY 1")
        count = conn.execute("SELECT COUNT(*) FROM card_legality WHERE grp_id < 0")
        return [tuple(r) for r in rows], count.fetchone()[0]

    before = state()
    upsert_cards(conn, printings)
    assert state() == before


def test_a_card_that_reached_arena_loses_its_synthetic_row(conn):
    printings = format_printings()
    upsert_cards(conn, printings)
    assert conn.execute("SELECT 1 FROM cards WHERE grp_id = -38197").fetchone() is not None
    opal = next(c for c in printings if c["name"] == "Mox Opal")
    upsert_cards(conn, [{**opal, "arena_id": 99999}])
    assert conn.execute("SELECT 1 FROM cards WHERE grp_id = -38197").fetchone() is None
    assert legality_of(conn, -38197) == {}


def test_the_lowest_mtgo_id_wins_whatever_order_the_printings_arrive_in(conn):
    scour = [c for c in format_printings() if c["name"] == "Thought Scour"]
    upsert_cards(conn, sorted(scour, key=lambda c: -c["mtgo_id"]))
    rows = conn.execute("SELECT grp_id, set_code FROM cards WHERE name = 'Thought Scour'")
    assert [tuple(r) for r in rows] == [(-43399, "DKA")]


def test_a_reversible_printing_of_an_arena_card_gets_no_synthetic_row(conn):
    """Marang River Regent (mtgo_id 139609) is a reversible_card whose oracle_id is on its
    faces; an Arena row for "Marang River Regent // Coil and Catch" already covers it."""
    regent = next(c for c in mtgo_printings() if c["mtgo_id"] == 139609)
    assert regent["layout"] == "reversible_card" and not regent.get("oracle_id")
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_id) VALUES (91001, ?, ?)",
        ("Marang River Regent // Coil and Catch", regent["card_faces"][0]["oracle_id"]),
    )
    conn.commit()
    upsert_cards(conn, [regent])
    assert conn.execute("SELECT COUNT(*) FROM cards WHERE grp_id < 0").fetchone()[0] == 0


def test_a_reversible_synthetic_row_takes_its_oracle_id_from_the_faces(conn):
    regent = next(c for c in mtgo_printings() if c["mtgo_id"] == 139609)
    upsert_cards(conn, [regent])
    row = conn.execute("SELECT grp_id, oracle_id FROM cards WHERE grp_id < 0").fetchone()
    assert (row["grp_id"], row["oracle_id"]) == (-139609, regent["card_faces"][0]["oracle_id"])


def _waif():
    waif = next(c for c in format_printings() if c["name"].startswith("Reckless Waif"))
    assert waif["mtgo_id"] == 42380 and waif.get("arena_id") is None
    return waif


def test_a_token_named_like_a_back_face_does_not_suppress_the_card(conn):
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (91002, 'Merciless Predator', "
        "'Token Creature — Werewolf')"
    )
    conn.commit()
    upsert_cards(conn, [_waif()])
    row = conn.execute("SELECT name FROM cards WHERE grp_id = -42380").fetchone()
    assert row["name"] == "Reckless Waif // Merciless Predator"


def test_a_client_row_for_the_front_face_is_matched_by_the_backfill_first(conn):
    """No oracle_id on the client-style row: the name backfill gives it one, and the synthetic
    pass then sees the card as already in `cards`."""
    _insert_arena_only_row(conn, 91003, "Reckless Waif")
    upsert_cards(conn, [_waif()])
    assert conn.execute("SELECT COUNT(*) FROM cards WHERE grp_id < 0").fetchone()[0] == 0


# `scryfall_name_collision.jsonl` holds two real `default_cards` lines that both
# answer to "Careful Study": Odyssey's sorcery (no arena_id, mtgo_id 16929) and
# the "prepare" face of an Arena card (arena_id 102527). The installed client
# carries row 102527 under the combined name with its oracle_id, and a face row
# 104069 named "Careful Study" with no oracle_id and no legality.
def name_collision() -> tuple[dict, dict]:
    path = Path(__file__).parent / "fixtures" / "scryfall_name_collision.jsonl"
    odyssey, sos = (json.loads(line) for line in path.read_text().splitlines() if line.strip())
    assert odyssey["name"] == "Careful Study" and odyssey.get("arena_id") is None
    assert sos["arena_id"] == 102527
    assert "Careful Study" in {face["name"] for face in sos["card_faces"]}
    assert odyssey["oracle_id"] != sos["oracle_id"]
    return odyssey, sos


def _seed_careful_study_client_rows(conn, sos: dict) -> None:
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_id) VALUES (102527, ?, ?)",
        (sos["name"], sos["oracle_id"]),
    )
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (104069, 'Careful Study')")
    conn.commit()


def test_an_mtgo_only_card_sharing_a_name_with_an_arena_face_gets_its_synthetic_row(conn):
    """The face row's name is not proof the sorcery is on Arena: the two oracle ids
    disagree on that name, so the sorcery gets -(its mtgo_id) and its own legality."""
    odyssey, sos = name_collision()
    _seed_careful_study_client_rows(conn, sos)
    upsert_cards(conn, [odyssey, sos])
    row = conn.execute(
        "SELECT grp_id, name, oracle_id FROM cards WHERE grp_id < 0"
    ).fetchone()
    assert tuple(row) == (-odyssey["mtgo_id"], "Careful Study", odyssey["oracle_id"])
    assert row["grp_id"] == -16929
    assert legality_of(conn, -16929) == {
        fmt: odyssey["legalities"][key] for fmt, key in _FORMAT_KEYS.items()
    }
    assert legality_of(conn, -16929)["Premodern"] == "legal"


def test_the_arena_face_row_of_a_shared_name_is_left_untouched(conn):
    """The name backfill skips "Careful Study" (its oracle ids disagree), so the
    client's face row keeps no oracle_id and no legality."""
    odyssey, sos = name_collision()
    _seed_careful_study_client_rows(conn, sos)
    upsert_cards(conn, [odyssey, sos])
    row = conn.execute(
        "SELECT name, oracle_id, oracle_text FROM cards WHERE grp_id = 104069"
    ).fetchone()
    assert tuple(row) == ("Careful Study", None, None)
    assert legality_of(conn, 104069) == {}


def test_the_arena_card_of_a_shared_name_gets_no_synthetic_row(conn):
    """The Arena card's own oracle id is in `cards`, so its MTGO printing adds nothing:
    the only negative row is the sorcery's."""
    odyssey, sos = name_collision()
    _seed_careful_study_client_rows(conn, sos)
    upsert_cards(conn, [odyssey, sos])
    negatives = conn.execute("SELECT grp_id FROM cards WHERE grp_id < 0").fetchall()
    assert [r[0] for r in negatives] == [-odyssey["mtgo_id"]]


# Download progress: the counting reader over a local gzip of a Scryfall fixture.

FIXTURES = Path(__file__).parent / "fixtures"


def _gzip_of_fixture(name: str = "scryfall_format_printings.jsonl") -> tuple[bytes, list[dict]]:
    text = (FIXTURES / name).read_bytes()
    cards = [json.loads(line) for line in text.splitlines() if line.strip()]
    return gzip.compress(text), cards


def _drain(reader, chunk: int) -> None:
    while reader.read(chunk):
        pass


def test_the_counting_reader_counts_the_wire_and_the_cards_still_decode(capsys):
    blob, cards = _gzip_of_fixture()
    reader = _CountingReader(io.BytesIO(blob), len(blob), as_json=True)
    with gzip.GzipFile(fileobj=reader) as stream:
        decoded = [json.loads(line) for line in stream if line.strip()]
    assert decoded == cards
    assert reader.done == len(blob)
    events = [json.loads(line)["progress"] for line in capsys.readouterr().out.splitlines()]
    assert events[-1] == {"stage": "download", "done": len(blob), "total": len(blob)}
    assert all(e["stage"] == "download" for e in events)
    assert sum(e["done"] == len(blob) for e in events) == 1


def test_progress_is_throttled_to_a_second_or_five_percent(capsys):
    blob, _ = _gzip_of_fixture()
    now = [0.0]
    reader = _CountingReader(io.BytesIO(blob), len(blob), as_json=True, clock=lambda: now[0])
    chunk = max(1, len(blob) // 200)  # 0.5 % a read
    _drain(reader, chunk)
    events = [json.loads(line)["progress"] for line in capsys.readouterr().out.splitlines()]
    # frozen clock: the first read, then no gap of 5 % or more (one chunk of slack)
    assert len(events) <= 1 + 20 + 1
    assert events[0]["done"] == chunk
    assert events[-1]["done"] == len(blob)
    gaps = [b["done"] - a["done"] for a, b in pairwise(events)]
    assert all(gap < len(blob) * 0.05 + chunk for gap in gaps)


def test_a_second_passing_reports_even_without_five_percent(capsys):
    blob, _ = _gzip_of_fixture()
    now = [0.0]
    reader = _CountingReader(io.BytesIO(blob), len(blob), as_json=True, clock=lambda: now[0])
    reader.read(1)
    reader.read(1)
    now[0] = 1.0
    reader.read(1)
    events = [json.loads(line)["progress"] for line in capsys.readouterr().out.splitlines()]
    assert [e["done"] for e in events] == [1, 3]


def test_no_total_means_a_null_total_and_only_the_clock_throttles(capsys):
    blob, _ = _gzip_of_fixture()
    reader = _CountingReader(io.BytesIO(blob), None, as_json=True, clock=lambda: 0.0)
    _drain(reader, 10)
    events = [json.loads(line)["progress"] for line in capsys.readouterr().out.splitlines()]
    assert events[0] == {"stage": "download", "done": 10, "total": None}
    assert len(events) == 2  # the first read and the end


def test_json_progress_lines_have_the_documented_shape(capsys):
    print_progress("download", done=34_000_000, total=79_000_000, as_json=True)
    print_progress("download", done=5, total=None, as_json=True)
    print_progress("save", as_json=True)
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line) for line in lines] == [
        {"progress": {"stage": "download", "done": 34_000_000, "total": 79_000_000}},
        {"progress": {"stage": "download", "done": 5, "total": None}},
        {"progress": {"stage": "save"}},
    ]


def test_plain_progress_lines_say_megabytes_and_the_save(capsys):
    print_progress("download", done=34_000_000, total=79_000_000, as_json=False)
    print_progress("download", done=34_400_000, total=None, as_json=False)
    print_progress("save", as_json=False)
    assert capsys.readouterr().out.splitlines() == [
        "Downloading card data from Scryfall: 34 of 79 MB",
        "Downloading card data from Scryfall: 34 MB so far",
        "Saving cards to the database…",
    ]


def test_upsert_prints_the_save_stage_once_before_the_closing_lines(conn, capsys):
    upsert_cards(conn, [card()], progress_json=True)
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[0]) == {"progress": {"stage": "save"}}
    assert sum('"progress"' in line for line in lines) == 1
    assert lines[1].startswith("Name backfill:")


def test_cards_progress_flag_reaches_the_fetch_and_the_save_event(tmp_path, monkeypatch, capsys):
    from sensei_top.cli import build_parser, cmd_cards

    seen = {}

    def fake_fetch(*, as_json=False, **_):
        seen["as_json"] = as_json
        yield from _gzip_of_fixture()[1]

    monkeypatch.setattr("sensei_top.cards.fetch_default_cards", fake_fetch)
    db = str(tmp_path / "c.db")
    args = build_parser().parse_args(["--db", db, "cards", "--scryfall", "--progress"])
    cmd_cards(args)
    assert seen["as_json"] is True
    first = capsys.readouterr().out.splitlines()[0]
    assert json.loads(first) == {"progress": {"stage": "save"}}
