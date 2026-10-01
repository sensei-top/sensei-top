"""Scryfall card-name import.

No network here: ``fetch_default_cards`` is the only function that opens a
socket and it is left alone, while ``upsert_cards`` is fed the shapes Scryfall
actually returns. Card entries below are trimmed to the fields we read.
"""

import json
import sqlite3

import pytest

from sensei_top.cards import (
    arena_card_database_path,
    arena_cards_missing,
    import_arena_cards,
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
    row = conn.execute(
        "SELECT standard_legality, oracle_id FROM cards WHERE grp_id = 70344"
    ).fetchone()
    assert row["standard_legality"] == "banned"
    assert row["oracle_id"] == "0e4d3f01-1234-4abc-9def-0123456789ab"


def test_a_later_import_with_no_legality_does_not_erase_it(conn):
    """Same COALESCE discipline as oracle_text: the Arena-client path never
    supplies standard_legality or oracle_id (migrations/017_card_legality.sql)."""
    upsert_cards(conn, [card(legalities={"standard": "banned"}, oracle_id="abc-123")])
    upsert_cards(conn, [card()])  # no legalities/oracle_id keys: fall back to None
    row = conn.execute(
        "SELECT standard_legality, oracle_id FROM cards WHERE grp_id = 68738"
    ).fetchone()
    assert (row["standard_legality"], row["oracle_id"]) == ("banned", "abc-123")


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
    row = conn.execute("SELECT standard_legality, oracle_id FROM cards").fetchone()
    assert (row["standard_legality"], row["oracle_id"]) == (None, None)


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


# --- name backfill (Phase 3c) ------------------------------------------------
# arena_id covers only one representative printing per functional card. An
# alternate-art/showcase/bonus-sheet sibling, or a DFC/Adventure/Omen/Room
# second face, gets its own grpId from Arena but no arena_id from Scryfall, so
# it never reaches `_row`/`_write` directly. Simulate "already in the table
# from a prior installed-client import" by inserting the sibling row by hand,
# the same way `import_arena_cards` would have left it: named, but with
# standard_legality/oracle_id still NULL because that path never supplies them.


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
        "SELECT standard_legality, oracle_id FROM cards WHERE grp_id = 99001"
    ).fetchone()
    assert (row["standard_legality"], row["oracle_id"]) == ("legal", "abc-firepower")


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
        "SELECT standard_legality, oracle_id FROM cards WHERE grp_id = 99101"
    ).fetchone()
    assert (row["standard_legality"], row["oracle_id"]) == ("legal", "abc-delver")


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
        "SELECT standard_legality, oracle_id FROM cards WHERE grp_id = 99201"
    ).fetchone()
    assert (row["standard_legality"], row["oracle_id"]) == ("legal", "abc-antivenom")


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
        "SELECT standard_legality, oracle_id FROM cards WHERE grp_id = 99301"
    ).fetchone()
    assert (row["standard_legality"], row["oracle_id"]) == (None, None)


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
        "SELECT standard_legality, oracle_id FROM cards WHERE grp_id = 98012"
    ).fetchone()
    assert (row["standard_legality"], row["oracle_id"]) == (None, None)


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
        "SELECT standard_legality, oracle_id FROM cards WHERE grp_id = 99401"
    ).fetchone()
    assert (row["standard_legality"], row["oracle_id"]) == (None, None)
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
        "SELECT standard_legality, oracle_id, oracle_text, keywords "
        "FROM cards WHERE grp_id = 99701"
    ).fetchone()
    assert (row["standard_legality"], row["oracle_id"], row["oracle_text"]) == (
        "legal",
        "abc-shared",
        "Flying, trample.",
    )
    assert row["keywords"] is None
    assert "0 name(s) left ambiguous" in capsys.readouterr().out


def test_name_backfill_never_overwrites_an_existing_value(conn):
    """COALESCE-only: a row that already carries a value — even a stale or
    differently-sourced one — is never touched by the name backfill."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors, "
        "standard_legality, oracle_id) "
        "VALUES (99501, 'Kept Value', 'rare', 'DSK', '[]', 'banned', 'kept-oracle-id')"
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
        "SELECT standard_legality, oracle_id FROM cards WHERE grp_id = 99501"
    ).fetchone()
    assert (row["standard_legality"], row["oracle_id"]) == ("banned", "kept-oracle-id")


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
