"""The MTGO deck projection (``projector/mtgo/decks.py``).

Rows come from the reader's own ``ingest_deck_dir`` over a temporary folder of
fixture copies, with ``os.utime`` setting their order, never from hand-built
SQL. The one exception is a payload that is not base64, which the reader cannot
write. ``cards`` is seeded from ``tests/fixtures/mtgo_deck_cards.json``:
Arena's own name, ``grp_id`` and type line for every name in the three deck
fixtures that Arena has. Three names are not in it because Arena lacks them:
Lotus Bloom, Disrupting Shoal and Engineered Explosives, all in
``mtgo_deck_double_faced.dek``.

Expectations are read off the ``.dek`` files and that seed by hand (AGENTS.md
non-negotiable #8), as ``{grp_id: copies}`` tables with the card named beside
each number — never by running the projection and copying what it wrote. Each
file is 60 maindeck and 15 sideboard cards; the tables hold the part that
resolves, so the double-faced one comes to 52 and 13.

The deck-store grouping (``tests/fixtures/mtgo_grouping_deck.xml``) names no
card, only ``CatId``s, so its tests fill ``mtgo_card`` themselves
(``_mtgo_cards()``). Thirteen of its ``CatId``s sit beside a name in one of the
``.dek`` fixtures, and those pairs are used as they are; ``139429`` takes
Scryfall's own name from ``tests/fixtures/scryfall_mtgo_printings.jsonl``
instead, which is ``Front // Back``. Eleven more have no name in any fixture
and get a stand-in (``_STAND_INS``), a made-up name and ``grp_id`` added to
``cards`` too, which claims nothing about the real card. ``139621`` and
``144772`` are absent from Scryfall and stay out of ``mtgo_card``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from pathlib import Path

import pytest

from sensei_top.api.models.matches import MtgoFormat
from sensei_top.db import MIGRATIONS_DIR, open_database
from sensei_top.mtgo.formats import FORMAT_CODES, MTGO_FORMATS
from sensei_top.projector.matches import project
from sensei_top.projector.mtgo.decks import project_mtgo_decks
from sensei_top.reader.ingest import ingest_file
from sensei_top.reader.mtgo_decks import ingest_deck_dir

FIXTURES = Path(__file__).parent / "fixtures"
CARDS = FIXTURES / "mtgo_deck_cards.json"
SAMPLE_BYTES = (FIXTURES / "mtgo_deck_sample.dek").read_bytes()
FACED_BYTES = (FIXTURES / "mtgo_deck_double_faced.dek").read_bytes()
ADVENTURE_BYTES = (FIXTURES / "mtgo_deck_adventure.dek").read_bytes()
GROUPING_BYTES = (FIXTURES / "mtgo_grouping_deck.xml").read_bytes()
BINDER_BYTES = (FIXTURES / "mtgo_grouping_binder.xml").read_bytes()
SCRYFALL = FIXTURES / "scryfall_mtgo_printings.jsonl"
MIGRATION_049 = MIGRATIONS_DIR / "049_mtgo_match_pick.sql"
ARENA_LOG = FIXTURES / "match_session.log"
MTGO_LOG_BYTES = (FIXTURES / "mtgo_match_session.log").read_bytes()
MTGO_LOG_NAME = "Match_GameLog_f2244feb-54e1-48ec-b3c5-711b20844adf.dat"

# A fixed day in September 2026; a file's mtime is this plus whole minutes, far
# from any clock change.
_BASE_MTIME = 1_790_000_000

_SAMPLE_MAIN = {
    7193: 1,      # Plains
    103489: 4,    # Smaug the Magnificent
    102474: 2,    # Erode
    97303: 4,     # Momo, Friendly Flier
    97998: 4,     # Multiversal Passage
    96722: 4,     # Nova Hellkite
    95520: 4,     # Clarion Conqueror
    95549: 4,     # Voice of Victory
    95788: 4,     # Maelstrom of the Spirit Dragon
    96556: 2,     # Twinmaw Stormbrood, an omen card Arena names by its front face too
    95638: 4,     # Sarkhan, Dragon Ascendant
    95631: 4,     # Magmatic Hellkite
    95066: 4,     # Sunbillow Verge
    87435: 2,     # Cavern of Souls
    68735: 4,     # Sacred Foundry
    75864: 4,     # Inspiring Vantage
    93905: 4,     # Burst Lightning
    7153: 1,      # Mountain
}
_SAMPLE_SIDE = {
    92235: 2,     # Pyroclasm
    94149: 2,     # Boros Charm
    87145: 1,     # Get Lost
    73807: 3,     # Rest in Peace
    91545: 2,     # Dawn's Truce, written Dawn&apos;s Truce in the file
    92092: 1,     # Split Up
    96608: 4,     # Seam Rip
}
# The sample's sideboard with Pyroclasm swapped for Abrade (73914).
_SAMPLE_SIDE_ABRADE = {g: n for g, n in _SAMPLE_SIDE.items() if g != 92235} | {73914: 2}
# The sample's maindeck with its one Plains swapped for an Island (7065).
_SAMPLE_MAIN_ISLAND = {g: n for g, n in _SAMPLE_MAIN.items() if g != 7193} | {7065: 1}

_FACED_MAIN = {
    82817: 4,     # Goblin Charbelcher
    24113: 3,     # Spell Snare
    91588: 3,     # Into the Flood Maw
    90848: 2,     # Waterlogged Teachings // Inundated Archive
    90846: 4,     # Suppression Ray // Orderly Plaza
    90808: 4,     # Sink into Stupor // Soporific Springs
    90806: 4,     # Hydroelectric Specimen // Hydroelectric Laboratory
    84763: 1,     # Stern Scolding
    71393: 3,     # Force of Negation
    79507: 4,     # Tameshi, Reality Architect
    73267: 4,     # Sea Gate Restoration // Sea Gate, Reborn
    73254: 4,     # Jwari Disruption // Jwari Ruins
    73234: 2,     # Beyeen Veil // Beyeen Coast
    75651: 4,     # Whir of Invention
    77494: 2,     # Counterspell
    37388: 4,     # Preordain
}   # not on Arena, so left out: Lotus Bloom x4, Disrupting Shoal x4
_FACED_SIDE = {
    7153: 1,      # Mountain
    70012: 1,     # Grafdigger's Cage, written Grafdigger&apos;s Cage in the file
    70205: 3,     # Mystical Dispute
    90903: 4,     # Consign to Memory
    92148: 2,     # Unable to Scream
    94869: 2,     # Stock Up
}   # not on Arena, so left out: Engineered Explosives x2
_FACED_UNRESOLVED = ("Lotus Bloom", "Disrupting Shoal", "Engineered Explosives")

_ADVENTURE_MAIN = {
    86758: 4,     # Sleight of Hand
    102698: 2,    # Traumatic Critique
    102670: 4,    # Prismari Charm
    98392: 4,     # Sunderflock
    98475: 1,     # Sear
    24113: 3,     # Spell Snare
    95062: 4,     # Riverpyre Verge
    94994: 1,     # Broadside Barrage
    92126: 3,     # Get Out
    91584: 4,     # Eddymurk Crab
    86835: 4,     # Hearth Elemental // Stoke Genius
    79089: 2,     # Stormcarved Coast
    66091: 4,     # Opt
    73914: 2,     # Abrade
    75876: 4,     # Spirebluff Canal
    68738: 4,     # Steam Vents
    93905: 3,     # Burst Lightning
    7065: 6,      # Island
    90421: 1,     # Three Steps Ahead
}
_ADVENTURE_SIDE = {
    105019: 1,    # Avengers Disassembled
    102639: 3,    # Colorstorm Stallion
    97353: 2,     # Wan Shi Tong, Librarian
    96625: 1,     # Consult the Star Charts
    96001: 1,     # Fire Magic
    94994: 1,     # Broadside Barrage, in the maindeck too
    94869: 1,     # Stock Up
    91691: 2,     # Sunspine Lynx
    90488: 1,     # Return the Favor
    58011: 1,     # Disdainful Stroke
    94018: 1,     # Flashfreeze
}


def _copies(table: dict[int, int]) -> list[int]:
    """One ``grp_id`` per copy, sorted: the shape of ``cards_json``'s lists."""
    return sorted(grp_id for grp_id, copies in table.items() for _ in range(copies))


def _cards_json(
    main: dict[int, int], side: dict[int, int], unresolved: tuple[int, int] = (0, 0)
) -> dict:
    """The whole ``cards_json`` of an MTGO deck: both boards, and the copies
    per board that resolve to no ``grp_id`` (plan 12, D18)."""
    return {
        "maindeck": _copies(main),
        "sideboard": _copies(side),
        "unresolved": {"maindeck": unresolved[0], "sideboard": unresolved[1]},
    }


def _edited(old: bytes, new: bytes) -> bytes:
    """The sample with ``old`` replaced. ``old`` must be on one line only: an
    edit that matched nothing would leave a good deck to test the skip with."""
    assert SAMPLE_BYTES.count(old) == 1, old
    return SAMPLE_BYTES.replace(old, new)


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    c.executemany(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (:grp_id, :name, :type_line)",
        json.loads(CARDS.read_text(encoding="utf-8")),
    )
    yield c
    c.close()


def _write(path: Path, data: bytes, minute: int) -> None:
    path.write_bytes(data)
    stamp = _BASE_MTIME + 60 * minute
    os.utime(path, (stamp, stamp))


def _folder(tmp_path: Path, *files: tuple[str, bytes, int]) -> Path:
    """A deck folder holding each ``(file name, bytes, minutes past the base
    mtime)``. Files are stored in name order, so a name that sorts later gets
    the later ``raw_events`` id."""
    folder = tmp_path / "decks"
    folder.mkdir(exist_ok=True)
    for file_name, data, minute in files:
        _write(folder / file_name, data, minute)
    return folder


def _store(conn, tmp_path: Path, *files: tuple[str, bytes, int]) -> None:
    """``_folder`` through the reader: one ``raw_events`` row per distinct file."""
    ingest_deck_dir(conn, _folder(tmp_path, *files))


def _decks(conn):
    return conn.execute(
        "SELECT deck_id, name, format, cards_json, first_seen, last_seen FROM decks "
        "ORDER BY first_seen, name"
    ).fetchall()


def _cards(deck) -> dict[str, list[int]]:
    return json.loads(deck["cards_json"])


def _logged_at(conn, file_name: str) -> list[str]:
    """Each stored row's ``logged_at`` for ``file_name``, oldest row first: the
    mtimes the reader recorded."""
    return [
        row[0]
        for row in conn.execute(
            "SELECT logged_at FROM raw_events WHERE source = 'mtgo_deck' AND source_file = ? "
            "ORDER BY id",
            (file_name,),
        )
    ]


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_the_sample_is_one_deck_named_by_its_file_stem(conn, tmp_path):
    _store(conn, tmp_path, ("Sample Deck.dek", SAMPLE_BYTES, 0))

    counts = project(conn)

    (deck,) = _decks(conn)
    assert (counts["decks"], counts["warnings"]) == (1, 0)
    assert deck["name"] == "Sample Deck"
    assert deck["format"] is None
    assert re.fullmatch(r"[0-9a-f]{64}", deck["deck_id"])
    cards = _cards(deck)
    assert (len(cards["maindeck"]), len(cards["sideboard"])) == (60, 15)
    assert cards == _cards_json(_SAMPLE_MAIN, _SAMPLE_SIDE)
    assert cards["sideboard"].count(91545) == 2  # Dawn&apos;s Truce, read unescaped
    assert cards["maindeck"].count(96556) == 2  # Twinmaw Stormbrood, by its exact name
    (stamp,) = _logged_at(conn, "Sample Deck.dek")
    assert (deck["first_seen"], deck["last_seen"]) == (stamp, stamp)


def test_modal_double_faced_cards_resolve_by_front_face_and_what_arena_lacks_is_left_out(
    conn, tmp_path, caplog
):
    _store(conn, tmp_path, ("Faced.dek", FACED_BYTES, 0))

    with caplog.at_level(logging.WARNING):
        counts = project(conn)

    (deck,) = _decks(conn)
    cards = _cards(deck)
    assert (len(cards["maindeck"]), len(cards["sideboard"])) == (52, 13)
    # Lotus Bloom x4 and Disrupting Shoal x4; Engineered Explosives x2
    assert cards == _cards_json(_FACED_MAIN, _FACED_SIDE, unresolved=(8, 2))
    assert cards["maindeck"].count(73267) == 4  # Sea Gate Restoration, front face only
    assert cards["sideboard"].count(70012) == 1  # Grafdigger&apos;s Cage, read unescaped
    warnings = _warnings(caplog)
    assert counts["warnings"] == len(warnings) == 3
    for name in _FACED_UNRESOLVED:
        assert len([w for w in warnings if repr(name) in w]) == 1


def test_the_adventure_card_resolves_by_front_face_and_a_card_in_both_boards_counts_in_each(
    conn, tmp_path, caplog
):
    _store(conn, tmp_path, ("Adventure.dek", ADVENTURE_BYTES, 0))

    with caplog.at_level(logging.WARNING):
        counts = project(conn)

    (deck,) = _decks(conn)
    cards = _cards(deck)
    assert (len(cards["maindeck"]), len(cards["sideboard"])) == (60, 15)
    assert cards == _cards_json(_ADVENTURE_MAIN, _ADVENTURE_SIDE)
    assert cards["maindeck"].count(86835) == 4  # Hearth Elemental, front face only
    assert cards["maindeck"].count(94994) == 1  # Broadside Barrage
    assert cards["sideboard"].count(94994) == 1  # ... and once in the sideboard
    assert counts["warnings"] == 0 == len(_warnings(caplog))


def test_a_name_arena_lacks_warns_once_however_many_decks_hold_it(conn, tmp_path, caplog):
    second = FACED_BYTES.replace(b'Name="Preordain"', b'Name="Opt"')  # one maindeck card changed
    assert second != FACED_BYTES
    _store(conn, tmp_path, ("One.dek", FACED_BYTES, 0), ("Two.dek", second, 1))

    with caplog.at_level(logging.WARNING):
        counts = project(conn)

    warnings = _warnings(caplog)
    assert counts["decks"] == 2
    assert counts["warnings"] == len(warnings) == 3  # not 6: one per name, not per deck


def test_a_card_only_an_older_sideboard_holds_raises_no_warning(conn, tmp_path, caplog):
    """The older file's sideboard is not written, so a name only it holds is
    never resolved: no warning about a card that goes nowhere."""
    newer = FACED_BYTES.replace(b'Name="Engineered Explosives"', b'Name="Opt"')
    assert newer != FACED_BYTES
    _store(conn, tmp_path, ("Alpha.dek", FACED_BYTES, 0), ("Beta.dek", newer, 1))

    with caplog.at_level(logging.WARNING):
        counts = project(conn)

    (deck,) = _decks(conn)
    assert _cards(deck)["sideboard"] == _copies(_FACED_SIDE | {66091: 2})  # Opt, from the newer
    warnings = _warnings(caplog)
    assert counts["warnings"] == len(warnings) == 2  # Lotus Bloom and Disrupting Shoal
    assert not any("Engineered Explosives" in w for w in warnings)


def test_the_same_maindeck_in_two_files_is_one_deck_named_by_the_newer_one(conn, tmp_path):
    newer = (
        SAMPLE_BYTES
        .replace(b'CatID="34408"', b'CatID="37610"')  # another printing of Burst Lightning
        .replace(b'Name="Pyroclasm"', b'Name="Abrade"')  # and another sideboard card
    )
    assert newer != SAMPLE_BYTES
    _store(conn, tmp_path, ("Alpha.dek", SAMPLE_BYTES, 0), ("Beta.dek", newer, 7))

    counts = project(conn)

    (deck,) = _decks(conn)
    assert counts["decks"] == 1
    assert deck["name"] == "Beta"
    assert _cards(deck) == _cards_json(_SAMPLE_MAIN, _SAMPLE_SIDE_ABRADE)
    assert deck["first_seen"] == _logged_at(conn, "Alpha.dek")[0]
    assert deck["last_seen"] == _logged_at(conn, "Beta.dek")[0]
    assert deck["first_seen"] < deck["last_seen"]


def test_two_printings_of_one_card_are_one_card(conn, tmp_path):
    split = _edited(
        b'<Cards CatID="34408" Quantity="4" Sideboard="false" Name="Burst Lightning" />',
        b'<Cards CatID="34408" Quantity="3" Sideboard="false" Name="Burst Lightning" />\n'
        b'  <Cards CatID="37610" Quantity="1" Sideboard="false" Name="Burst Lightning" />',
    )
    _store(conn, tmp_path, ("Alpha.dek", SAMPLE_BYTES, 0), ("Beta.dek", split, 1))

    project(conn)

    (deck,) = _decks(conn)
    assert deck["name"] == "Beta"
    assert _cards(deck)["maindeck"] == _copies(_SAMPLE_MAIN)  # Burst Lightning x4, as one entry


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param(_edited(b'Name="Plains"', b'Name="Island"'), id="one-card-swapped"),
        pytest.param(
            _edited(b'Quantity="1" Sideboard="false" Name="Plains"',
                    b'Quantity="2" Sideboard="false" Name="Plains"'),
            id="one-quantity-changed",
        ),
    ],
)
def test_one_changed_maindeck_entry_is_a_new_deck(conn, tmp_path, changed):
    _store(conn, tmp_path, ("Alpha.dek", SAMPLE_BYTES, 0), ("Beta.dek", changed, 1))

    counts = project(conn)

    original, new = _decks(conn)
    assert counts["decks"] == 2
    assert (original["name"], new["name"]) == ("Alpha", "Beta")
    assert original["deck_id"] != new["deck_id"]
    assert _cards(original)["maindeck"] == _copies(_SAMPLE_MAIN)


def test_a_swapped_card_projects_the_swapped_maindeck(conn, tmp_path):
    changed = _edited(b'Name="Plains"', b'Name="Island"')
    _store(conn, tmp_path, ("Alpha.dek", changed, 0))

    project(conn)

    (deck,) = _decks(conn)
    assert _cards(deck)["maindeck"] == _copies(_SAMPLE_MAIN_ISLAND)


def test_the_newest_file_by_mtime_names_the_deck_even_when_stored_first(conn, tmp_path):
    """Alpha is stored first (the lower id) but saved later: the name and the
    sideboard are the newer save's, not the later row's."""
    abrade = _edited(b'Name="Pyroclasm"', b'Name="Abrade"')
    _store(conn, tmp_path, ("Alpha.dek", abrade, 5), ("Beta.dek", SAMPLE_BYTES, 1))

    project(conn)

    (deck,) = _decks(conn)
    assert deck["name"] == "Alpha"
    assert _cards(deck)["sideboard"] == _copies(_SAMPLE_SIDE_ABRADE)
    assert deck["first_seen"] == _logged_at(conn, "Beta.dek")[0]
    assert deck["last_seen"] == _logged_at(conn, "Alpha.dek")[0]


def test_equal_mtimes_fall_back_to_the_row_stored_later(conn, tmp_path):
    abrade = _edited(b'Name="Pyroclasm"', b'Name="Abrade"')
    _store(conn, tmp_path, ("Alpha.dek", SAMPLE_BYTES, 3), ("Beta.dek", abrade, 3))

    project(conn)

    (deck,) = _decks(conn)
    assert deck["name"] == "Beta"
    assert _cards(deck)["sideboard"] == _copies(_SAMPLE_SIDE_ABRADE)
    assert deck["first_seen"] == deck["last_seen"]


def test_an_older_version_of_a_file_stays_a_deck(conn, tmp_path):
    folder = _folder(tmp_path, ("Alpha.dek", SAMPLE_BYTES, 0))
    ingest_deck_dir(conn, folder)
    _write(folder / "Alpha.dek", _edited(b'Name="Plains"', b'Name="Island"'), 9)  # saved over
    ingest_deck_dir(conn, folder)

    counts = project(conn)

    first, second = _decks(conn)
    assert counts["decks"] == 2
    assert (first["name"], second["name"]) == ("Alpha", "Alpha")
    assert _cards(first)["maindeck"] == _copies(_SAMPLE_MAIN)
    assert _cards(second)["maindeck"] == _copies(_SAMPLE_MAIN_ISLAND)
    older, newer = _logged_at(conn, "Alpha.dek")
    assert (first["first_seen"], first["last_seen"]) == (older, older)
    assert (second["first_seen"], second["last_seen"]) == (newer, newer)


def test_the_id_is_the_sha256_of_the_maindeck_by_name_behind_the_prefix(conn, tmp_path):
    """Pins the text, because a deck pick stored later keeps this id across
    rebuilds: ``mtgo-deck:`` and the compact JSON of ``[name, quantity]``
    sorted by name, the sideboard and every ``CatID`` left out."""
    tiny = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b"<Deck>\n"
        b'  <Cards CatID="1" Quantity="4" Sideboard="false" Name="Opt" />\n'
        b'  <Cards CatID="2" Quantity="56" Sideboard="false" Name="Island" />\n'
        b'  <Cards CatID="3" Quantity="15" Sideboard="true" Name="Mountain" />\n'
        b"</Deck>\n"
    )
    _store(conn, tmp_path, ("Tiny.dek", tiny, 0))

    project(conn)

    (deck,) = _decks(conn)
    expected = hashlib.sha256(b'mtgo-deck:[["Island",56],["Opt",4]]').hexdigest()
    assert deck["deck_id"] == expected


def test_a_second_project_gives_the_same_decks_and_ids(conn, tmp_path):
    _store(
        conn,
        tmp_path,
        ("Adventure.dek", ADVENTURE_BYTES, 0),
        ("Faced.dek", FACED_BYTES, 1),
        ("Sample.dek", SAMPLE_BYTES, 2),
        ("Sample island.dek", _edited(b'Name="Plains"', b'Name="Island"'), 3),
    )
    raw_before = conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]

    project(conn)
    first = [tuple(row) for row in _decks(conn)]
    counts = project(conn)
    second = [tuple(row) for row in _decks(conn)]

    assert len(first) == 4
    assert second == first
    assert counts["decks"] == 4
    assert len({row[0] for row in first}) == 4  # four distinct ids
    assert conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == raw_before


@pytest.mark.parametrize(
    ("file_name", "stem"),
    [
        ("Plain.dek", "Plain"),
        ("Two Words.dek", "Two Words"),
        ("dotted.v2.dek", "dotted.v2"),
        ("Upper.DEK", "Upper"),
    ],
)
def test_the_name_is_the_file_name_without_its_suffix(conn, tmp_path, file_name, stem):
    _store(conn, tmp_path, (file_name, SAMPLE_BYTES, 0))

    project(conn)

    (deck,) = _decks(conn)
    assert deck["name"] == stem


def test_mtgo_decks_sit_beside_arena_decks_and_leave_them_alone(conn, tmp_path):
    ingest_file(conn, ARENA_LOG, locale_hint="mdy")
    project(conn)
    arena = [tuple(row) for row in _decks(conn)]
    assert arena  # the Arena fixture plays a deck; with none there is nothing to leave alone

    _store(conn, tmp_path, ("Alpha.dek", SAMPLE_BYTES, 0))
    counts = project(conn)

    after = [tuple(row) for row in _decks(conn)]
    assert counts["decks"] == len(arena) + 1
    assert all(row in after for row in arena)
    (mtgo,) = [row for row in after if row not in arena]
    assert mtgo[1] == "Alpha"
    (guids,) = conn.execute(
        "SELECT COUNT(*) FROM deck_guids WHERE deck_id = ?", (mtgo[0],)
    ).fetchone()
    assert guids == 0


def test_a_deck_file_is_never_linked_to_an_mtgo_match(conn, tmp_path, monkeypatch):
    """Nothing in an MTGO game log says which deck was played, so the deck
    and the match both exist and nothing joins them (rule 4)."""
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    conn.execute(
        """
        INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, '2026-09-14T12:42:37', 'event', 'MtgoGameLog', ?, 'mtgo')
        """,
        (
            hashlib.sha256(MTGO_LOG_BYTES).hexdigest(),
            MTGO_LOG_NAME,
            base64.b64encode(MTGO_LOG_BYTES).decode("ascii"),
        ),
    )
    _store(conn, tmp_path, ("Alpha.dek", SAMPLE_BYTES, 0))

    counts = project(conn)

    assert (counts["matches"], counts["decks"]) == (1, 1)
    rows = conn.execute("SELECT deck_id FROM matches WHERE source = 'mtgo'").fetchall()
    assert [tuple(row) for row in rows] == [(None,)]


def test_the_rebuild_transaction_only_deletes_and_inserts(conn, tmp_path, monkeypatch):
    """The live watcher's ingest thread waits out ``project()``'s write lock
    before it can store the next log line, so every read and parse runs
    before ``BEGIN``: on a real database, the MTGO game logs decoded inside
    the lock held it 15-18 s (docs/architecture.md, "Live mode's two
    cadences"). Both sources and a deck file are stored, so every half
    ``project()`` builds has rows to write."""
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    ingest_file(conn, ARENA_LOG, locale_hint="mdy")
    conn.execute(
        """
        INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, '2026-09-14T12:42:37', 'event', 'MtgoGameLog', ?, 'mtgo')
        """,
        (
            hashlib.sha256(MTGO_LOG_BYTES).hexdigest(),
            MTGO_LOG_NAME,
            base64.b64encode(MTGO_LOG_BYTES).decode("ascii"),
        ),
    )
    _store(conn, tmp_path, ("Alpha.dek", SAMPLE_BYTES, 0))
    statements: list[str] = []
    conn.set_trace_callback(lambda sql: statements.append(sql.split(None, 1)[0].upper()))

    try:
        project(conn)
    finally:
        conn.set_trace_callback(None)

    inside = statements[statements.index("BEGIN") + 1 : statements.index("COMMIT")]
    assert set(inside) == {"DELETE", "INSERT"}
    # Every half had rows to write inside: Arena matches, the MTGO one, and
    # the deck file beside the Arena fixture's decks.
    by_source = dict(
        conn.execute("SELECT source, COUNT(*) FROM matches GROUP BY source").fetchall()
    )
    assert by_source.get("arena", 0) > 0
    assert by_source.get("mtgo") == 1
    names = [row["name"] for row in _decks(conn)]
    assert "Alpha" in names and len(names) > 1


_SMAUG = b'Quantity="4" Sideboard="false" Name="Smaug the Magnificent"'
_QUANTITIES = [
    ("zero", "0"),
    ("negative", "-1"),
    ("fraction", "4.0"),
    ("padded", " 4"),
    ("signed", "+4"),
    ("word", "four"),
    ("empty", ""),
    ("over-the-ceiling", "1001"),
    ("5000-digits", "9" * 5000),
]
_UNREADABLE = [
    pytest.param(b"this is not a deck file", id="not-xml"),
    pytest.param(b"", id="empty-file"),
    pytest.param(
        b'<?xml version="1.0"?><Other><Cards Quantity="1" Sideboard="false" Name="Opt" /></Other>',
        id="root-is-not-Deck",
    ),
    pytest.param(_edited(b' Name="Plains"', b""), id="Cards-without-a-Name"),
    pytest.param(_edited(b'Name="Plains"', b'Name=" "'), id="blank-Name"),
    pytest.param(
        _edited(b'Sideboard="false" Name="Plains"', b'Sideboard="maybe" Name="Plains"'),
        id="Sideboard-maybe",
    ),
    pytest.param(
        _edited(b'Sideboard="false" Name="Plains"', b'Sideboard="1" Name="Plains"'),
        id="Sideboard-1",
    ),
    pytest.param(
        _edited(b' Sideboard="false" Name="Plains"', b' Name="Plains"'), id="Sideboard-missing"
    ),
    pytest.param(
        SAMPLE_BYTES.replace(b'Sideboard="false"', b'Sideboard="true"'), id="no-maindeck-card"
    ),
    pytest.param(
        _edited(b'encoding="utf-8"', b'encoding="no-such-encoding"'), id="unknown-encoding"
    ),
    pytest.param(_edited(b'encoding="utf-8"', b'encoding="shift_jis"'), id="multi-byte-encoding"),
    pytest.param(_edited(b'Name="Plains"', b'Name="Pl\xffains"'), id="invalid-utf8"),
    pytest.param(_edited(_SMAUG, _SMAUG.replace(b'Quantity="4" ', b"")), id="Quantity-missing"),
    *[
        pytest.param(
            _edited(_SMAUG, _SMAUG.replace(b'Quantity="4"', f'Quantity="{value}"'.encode())),
            id=f"Quantity-{label}",
        )
        for label, value in _QUANTITIES
    ],
]
_END = SAMPLE_BYTES.rindex(b"</Deck>")
_CUTS = [0, 1, 100, 700, 1500, _END, _END + len(b"</Deck>") - 1]


def _skipped_beside_a_good_file(conn, tmp_path, caplog, bad: bytes) -> None:
    """``Bad.dek`` is stored first (the lower id), then ``Good.dek``: the bad
    one is warned about by name and left out, and the good one still projects."""
    _store(conn, tmp_path, ("Bad.dek", bad, 0), ("Good.dek", SAMPLE_BYTES, 1))
    # The row stays (rule 2), so it is the projector that skips it.
    assert len(_logged_at(conn, "Bad.dek")) == 1

    with caplog.at_level(logging.WARNING):
        counts = project(conn)

    (deck,) = _decks(conn)
    assert deck["name"] == "Good"
    assert counts["decks"] == 1
    (warning,) = _warnings(caplog)
    assert counts["warnings"] == 1
    assert repr("Bad.dek") in warning


@pytest.mark.parametrize("bad", _UNREADABLE)
def test_an_unreadable_file_is_warned_about_by_name_and_skipped_whole(
    conn, tmp_path, caplog, bad
):
    _skipped_beside_a_good_file(conn, tmp_path, caplog, bad)


@pytest.mark.parametrize("cut", _CUTS)
def test_a_truncated_copy_is_warned_about_and_never_becomes_a_deck(conn, tmp_path, caplog, cut):
    """A prefix of a real file may lose the tail, never gain content: cut after
    the last card but before the closing tag, or one byte short of it, the
    copy is still no deck."""
    _skipped_beside_a_good_file(conn, tmp_path, caplog, SAMPLE_BYTES[:cut])


def test_a_half_written_file_warns_on_every_rebuild_and_its_row_stays(conn, tmp_path, caplog):
    _store(conn, tmp_path, ("Half.dek", SAMPLE_BYTES[:700], 0))

    for _ in range(2):
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            counts = project(conn)
        assert (counts["decks"], counts["warnings"]) == (0, 1)
        assert len(_warnings(caplog)) == 1

    assert len(_logged_at(conn, "Half.dek")) == 1


def test_a_deck_saved_over_a_half_written_one_projects_beside_the_warning(conn, tmp_path, caplog):
    folder = _folder(tmp_path, ("Alpha.dek", SAMPLE_BYTES[:700], 0))
    ingest_deck_dir(conn, folder)
    _write(folder / "Alpha.dek", SAMPLE_BYTES, 1)  # the finished save
    ingest_deck_dir(conn, folder)

    with caplog.at_level(logging.WARNING):
        counts = project(conn)

    (deck,) = _decks(conn)
    assert deck["name"] == "Alpha"
    assert (counts["decks"], counts["warnings"]) == (1, 1)  # the half-written row still warns


def test_a_payload_that_is_not_base64_is_warned_about_and_skipped(conn, tmp_path, caplog):
    """The one row the reader cannot make, so it is the one built by hand."""
    _store(conn, tmp_path, ("Good.dek", SAMPLE_BYTES, 1))
    conn.execute(
        """
        INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source)
             VALUES ('odd', 'Odd.dek', '2026-09-21T12:00:00', 'event', 'MtgoDeckFile',
                     'not base64!', 'mtgo_deck')
        """
    )

    with caplog.at_level(logging.WARNING):
        counts = project(conn)

    (deck,) = _decks(conn)
    assert deck["name"] == "Good"
    (warning,) = _warnings(caplog)
    assert counts["warnings"] == 1
    assert repr("Odd.dek") in warning


def test_a_quantity_at_the_ceiling_is_still_a_deck(conn, tmp_path):
    big = _edited(
        b'Quantity="1" Sideboard="false" Name="Plains"',
        b'Quantity="1000" Sideboard="false" Name="Plains"',
    )
    _store(conn, tmp_path, ("Big.dek", big, 0))

    counts = project(conn)

    (deck,) = _decks(conn)
    assert (counts["decks"], counts["warnings"]) == (1, 0)
    assert _cards(deck)["maindeck"].count(7193) == 1000  # Plains


def _scryfall_name(mtgo_id: int) -> str:
    """Scryfall's top-level name for one printing in the Scryfall fixture."""
    for line in SCRYFALL.read_text(encoding="utf-8").splitlines():
        if line.strip() and (card := json.loads(line)).get("mtgo_id") == mtgo_id:
            return card["name"]
    raise AssertionError(f"mtgo_id {mtgo_id} is not in {SCRYFALL.name}")


# CatId -> name, as the .dek fixtures pair them (CatID beside Name).
_DEK_NAMES = {
    61855: "Inspiring Vantage",          # sample
    139189: "Sarkhan, Dragon Ascendant",  # sample
    142909: "Nova Hellkite",             # sample
    139489: "Maelstrom of the Spirit Dragon",  # sample
    144536: "Momo, Friendly Flier",      # sample
    144288: "Multiversal Passage",       # sample
    149529: "Erode",                     # sample
    154156: "Smaug the Magnificent",     # sample
    47477: "Boros Charm",                # sample
    142681: "Seam Rip",                  # sample
    129263: "Dawn's Truce",              # sample, written Dawn&apos;s Truce
    37610: "Burst Lightning",            # adventure
    34408: "Burst Lightning",            # sample: another printing, not in the grouping
}
# CatIds no fixture names: a made-up name and grp_id each, in mtgo_card and cards.
_STAND_INS = {
    308: ("Stand-in 308", 900_001),
    306: ("Stand-in 306", 900_002),
    133410: ("Stand-in 133410", 900_003),
    136863: ("Stand-in 136863", 900_004),
    139011: ("Stand-in 139011", 900_005),
    138953: ("Stand-in 138953", 900_006),
    63513: ("Stand-in 63513", 900_007),
    23590: ("Stand-in 23590", 900_008),
    37544: ("Stand-in 37544", 900_009),
    117674: ("Stand-in 117674", 900_010),
    46469: ("Stand-in 46469", 900_011),
}
_UNMAPPED = (139621, 144772)  # absent from Scryfall


def _mtgo_cards() -> dict[int, str]:
    return (
        dict(_DEK_NAMES)
        | {cat_id: name for cat_id, (name, _) in _STAND_INS.items()}
        | {
            139429: _scryfall_name(139429),  # Twinmaw Stormbrood // Charring Bite
            25691: _scryfall_name(25691),    # Lotus Bloom, which Arena lacks
        }
    )


@pytest.fixture
def store(conn):
    """``conn`` with ``mtgo_card`` and the stand-ins' ``cards`` rows."""
    conn.executemany(
        "INSERT INTO mtgo_card (mtgo_id, name) VALUES (?, ?)", _mtgo_cards().items()
    )
    conn.executemany(
        "INSERT INTO cards (grp_id, name) VALUES (?, ?)",
        [(grp_id, name) for name, grp_id in _STAND_INS.values()],
    )
    return conn


# The fixture grouping, item by item: 60 maindeck, 15 sideboard.
_GROUPING_MAIN = {
    900_001: 1,   # CatId 308, stand-in
    900_002: 1,   # CatId 306, stand-in
    900_003: 2,   # CatId 133410, stand-in
    75864: 4,     # CatId 61855, Inspiring Vantage
    900_004: 4,   # CatId 136863, stand-in
    95638: 4,     # CatId 139189, Sarkhan, Dragon Ascendant
    900_005: 4,   # CatId 139011, stand-in
    96722: 4,     # CatId 142909, Nova Hellkite
    96556: 2,     # CatId 139429, Twinmaw Stormbrood, by its front face
    95788: 4,     # CatId 139489, Maelstrom of the Spirit Dragon
    97303: 4,     # CatId 144536, Momo, Friendly Flier
    900_006: 4,   # CatId 138953, stand-in
    97998: 4,     # CatId 144288, Multiversal Passage
    93905: 2,     # CatId 37610, Burst Lightning
    102474: 2,    # CatId 149529, Erode
    103489: 4,    # CatId 154156, Smaug the Magnificent
    900_007: 2,   # CatId 63513, stand-in
    900_008: 4,   # CatId 23590, stand-in
}   # left out: CatId 139621 x4, unmapped
_GROUPING_SIDE = {
    900_009: 2,   # CatId 37544, stand-in
    94149: 2,     # CatId 47477, Boros Charm
    900_010: 1,   # CatId 117674, stand-in
    96608: 4,     # CatId 142681, Seam Rip
    900_011: 3,   # CatId 46469, stand-in
    91545: 1,     # CatId 129263, Dawn's Truce
}   # left out: CatId 144772 x2, unmapped


def _grouping(old: bytes, new: bytes, data: bytes = GROUPING_BYTES) -> bytes:
    """``data`` with ``old``, which must occur exactly once, replaced."""
    assert data.count(old) == 1, old
    return data.replace(old, new)


def _without_item(cat_id: int, data: bytes = GROUPING_BYTES) -> bytes:
    """``data`` with the one ``Item`` whose ``CatId`` is ``cat_id`` cut out."""
    pattern = rb'  <Item\r\n    CatId="' + str(cat_id).encode() + rb'"\r\n.*?/>\r\n'
    found = re.findall(pattern, data, flags=re.DOTALL)
    assert len(found) == 1, cat_id
    return data.replace(found[0], b"")


def _dek(cards: list[tuple[int, int, bool, str]]) -> bytes:
    """A ``.dek`` export of ``(CatID, Quantity, sideboard, Name)`` lines, in
    the sample's own layout."""
    lines = [
        b'<?xml version="1.0" encoding="utf-8"?>',
        b'<Deck xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        b"  <NetDeckID>0</NetDeckID>",
        b"  <PreconstructedDeckID>0</PreconstructedDeckID>",
    ]
    for cat_id, quantity, sideboard, name in cards:
        escaped = name.replace("'", "&apos;")
        lines.append(
            f'  <Cards CatID="{cat_id}" Quantity="{quantity}" '
            f'Sideboard="{"true" if sideboard else "false"}" Name="{escaped}" />'.encode()
        )
    lines.append(b"</Deck>")
    return b"\r\n".join(lines) + b"\r\n"


# The fixture grouping, stored first.
_FIRST = ("grouping 0001.xml", GROUPING_BYTES, 0)


def _grouping_warnings(caplog) -> list[str]:
    return [w for w in _warnings(caplog) if "CatId" in w]


def test_a_store_deck_is_named_and_formatted_by_its_grouping(store, tmp_path, caplog):
    _store(store, tmp_path, ("grouping 0001.xml", GROUPING_BYTES, 0))

    with caplog.at_level(logging.WARNING):
        counts = project(store)

    (deck,) = _decks(store)
    assert counts["decks"] == 1
    assert deck["name"] == "Fixture Deck"
    assert deck["format"] == "Standard"  # FormatCode CSTANDARD
    assert _cards(deck) == _cards_json(_GROUPING_MAIN, _GROUPING_SIDE, unresolved=(4, 2))
    assert len(_cards(deck)["maindeck"]) + 4 == 60
    assert len(_cards(deck)["sideboard"]) + 2 == 15
    (stamp,) = _logged_at(store, "grouping 0001.xml")
    assert (deck["first_seen"], deck["last_seen"]) == (stamp, stamp)
    warnings = _warnings(caplog)
    assert counts["warnings"] == len(warnings) == 2
    for cat_id in _UNMAPPED:
        assert len([w for w in warnings if f"CatId {cat_id} " in w]) == 1


def test_a_grouping_and_its_dek_export_are_one_deck(store, tmp_path):
    """The ``.dek`` spells Twinmaw Stormbrood by its front face, as the sample
    export does, while ``mtgo_card`` holds Scryfall's ``Front // Back``; the
    two unmapped ``CatId``s are cut from the grouping, since an export would
    name them."""
    grouping = _without_item(144772, _without_item(139621))
    names = _mtgo_cards()
    items = re.findall(
        rb'CatId="(\d+)"\r\n    Quantity="(\d+)"\r\n    IsSideboard="(true|false)"', grouping
    )
    assert len(items) == 24
    dek = _dek([
        (
            int(cat_id), int(quantity), board == b"true",
            names[int(cat_id)].split(" // ")[0],
        )
        for cat_id, quantity, board in items
    ])
    assert b'Name="Twinmaw Stormbrood"' in dek
    _store(store, tmp_path, ("grouping 0001.xml", grouping, 0), ("Exported.dek", dek, 5))

    counts = project(store)

    (deck,) = _decks(store)
    assert counts["decks"] == 1
    assert deck["name"] == "Exported"  # the newer file's
    assert deck["format"] == "Standard"  # the .dek carries none, so the grouping's stays
    assert deck["first_seen"] == _logged_at(store, "grouping 0001.xml")[0]
    assert deck["last_seen"] == _logged_at(store, "Exported.dek")[0]
    assert _cards(deck) == _cards_json(_GROUPING_MAIN, _GROUPING_SIDE)


def test_another_printing_in_a_grouping_is_the_same_deck(store, tmp_path):
    other = _grouping(b'CatId="37610"', b'CatId="34408"')  # Burst Lightning, sample printing
    _store(store, tmp_path, _FIRST, ("grouping 0002.xml", other, 1))

    counts = project(store)

    (deck,) = _decks(store)
    assert counts["decks"] == 1
    assert _cards(deck)["maindeck"].count(93905) == 2  # Burst Lightning


def test_two_printings_of_one_card_in_a_grouping_are_one_card(store, tmp_path):
    split = _grouping(
        b'  <Item\r\n    CatId="37610"\r\n    Quantity="2"\r\n',
        b'  <Item\r\n    CatId="37610"\r\n    Quantity="1"\r\n    IsSideboard="false"\r\n'
        b'    Annotation="0" />\r\n'
        b'  <Item\r\n    CatId="34408"\r\n    Quantity="1"\r\n',
    )
    _store(store, tmp_path, _FIRST, ("grouping 0002.xml", split, 1))

    counts = project(store)

    (deck,) = _decks(store)
    assert counts["decks"] == 1
    assert _cards(deck)["maindeck"] == _copies(_GROUPING_MAIN)


def test_a_mapped_name_arena_lacks_is_left_out_counted_and_warned(store, tmp_path, caplog):
    lotus = _grouping(b'CatId="63513"', b'CatId="25691"')  # a stand-in x2 becomes Lotus Bloom x2
    _store(store, tmp_path, ("grouping 0001.xml", lotus, 0))

    with caplog.at_level(logging.WARNING):
        counts = project(store)

    (deck,) = _decks(store)
    main = {g: n for g, n in _GROUPING_MAIN.items() if g != 900_007}
    assert _cards(deck) == _cards_json(main, _GROUPING_SIDE, unresolved=(6, 2))
    warnings = _warnings(caplog)
    assert counts["warnings"] == len(warnings) == 3  # two CatIds and one name
    assert len([w for w in warnings if repr("Lotus Bloom") in w]) == 1


def test_an_unmapped_catid_warns_once_however_many_decks_hold_it(store, tmp_path, caplog):
    other = _grouping(b'CatId="308"', b'CatId="37610"')  # a different maindeck
    _store(store, tmp_path, _FIRST, ("grouping 0002.xml", other, 1))

    with caplog.at_level(logging.WARNING):
        counts = project(store)

    assert counts["decks"] == 2
    assert counts["warnings"] == len(_grouping_warnings(caplog)) == 2


@pytest.mark.parametrize("code", sorted(FORMAT_CODES))
def test_each_format_code_is_one_of_the_seven(store, tmp_path, code):
    data = _grouping(b'FormatCode="CSTANDARD"', f'FormatCode="{code}"'.encode())
    _store(store, tmp_path, ("grouping 0001.xml", data, 0))

    project(store)

    (deck,) = _decks(store)
    assert deck["format"] == FORMAT_CODES[code]
    assert deck["format"] in MTGO_FORMATS


_NOT_A_DECK = [
    pytest.param(BINDER_BYTES, id="the-binder-fixture"),
    pytest.param(
        _grouping(b'GroupingType="Deck"', b'GroupingType="Wishlist"'), id="Wishlist"
    ),
    *[
        pytest.param(
            _grouping(b'FormatCode="CSTANDARD"', f'FormatCode="{code}"'.encode()),
            id=f"FormatCode-{code or 'empty'}",
        )
        for code in ("CCMDR", "CFREEFORM", "CHULAHOOP", "", "cstandard")
    ],
    pytest.param(_grouping(b'  GroupingType="Deck"\r\n', b""), id="GroupingType-missing"),
    pytest.param(_grouping(b'  FormatCode="CSTANDARD"\r\n', b""), id="FormatCode-missing"),
    pytest.param(
        _grouping(b'Quantity="10"', b'Quantity="lots"', BINDER_BYTES),
        id="binder-items-never-judged",
    ),
]


@pytest.mark.parametrize("data", _NOT_A_DECK)
def test_a_grouping_that_is_not_a_deck_in_the_seven_formats_is_counted_not_warned(
    store, tmp_path, caplog, data
):
    _store(store, tmp_path, _FIRST, ("grouping 0002.xml", data, 1))

    with caplog.at_level(logging.INFO):
        counts = project_mtgo_decks(store)  # decks is empty: project() never ran

    assert (counts["decks"], counts["groupings_skipped"]) == (1, 1)
    assert counts["warnings"] == len(_grouping_warnings(caplog)) == 2  # the deck's own two
    assert not any("grouping 0002.xml" in w for w in _warnings(caplog))
    (info,) = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert "1 deck-store grouping" in info


def test_several_skipped_groupings_are_one_count_and_one_line(store, tmp_path, caplog):
    wishlist = _grouping(b'GroupingType="Deck"', b'GroupingType="Wishlist"')
    commander = _grouping(b'FormatCode="CSTANDARD"', b'FormatCode="CCMDR"')
    _store(
        store, tmp_path,
        ("grouping 0001.xml", BINDER_BYTES, 0),
        ("grouping 0002.xml", wishlist, 1),
        ("grouping 0003.xml", commander, 2),
    )

    with caplog.at_level(logging.INFO):
        counts = project_mtgo_decks(store)

    assert counts == {"decks": 0, "warnings": 0, "groupings_skipped": 3}
    (info,) = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert "3 deck-store grouping" in info


def test_no_skipped_grouping_logs_nothing(store, tmp_path, caplog):
    _store(store, tmp_path, ("grouping 0001.xml", GROUPING_BYTES, 0))

    with caplog.at_level(logging.INFO):
        counts = project_mtgo_decks(store)

    assert counts["groupings_skipped"] == 0
    assert not [r for r in caplog.records if r.levelno == logging.INFO]


def test_a_blank_grouping_name_is_no_name(store, tmp_path):
    _store(store, tmp_path, ("grouping 0001.xml", _grouping(b'Name="Fixture Deck"', b'Name=""'), 0))

    project(store)

    (deck,) = _decks(store)
    assert deck["name"] is None


def test_a_grouping_id_pins_the_unmapped_catid_text(store, tmp_path):
    """A ``CatId`` ``mtgo_card`` lacks enters the identity as ``[CatId N]``:
    pinned, because a pick keeps this id across rebuilds."""
    tiny = (
        b'<?xml version="1.0" encoding="utf-8"?>\r\n'
        b'<CardGrouping Name="Tiny" GroupingType="Deck" FormatCode="CMODERN">\r\n'
        b'  <Item CatId="37610" Quantity="4" IsSideboard="false" />\r\n'
        b'  <Item CatId="7" Quantity="56" IsSideboard="false" />\r\n'
        b'  <Item CatId="34408" Quantity="15" IsSideboard="true" />\r\n'
        b"</CardGrouping>\r\n"
    )
    _store(store, tmp_path, ("grouping tiny.xml", tiny, 0))

    project(store)

    (deck,) = _decks(store)
    expected = hashlib.sha256(b'mtgo-deck:[["Burst Lightning",4],["[CatId 7]",56]]').hexdigest()
    assert deck["deck_id"] == expected
    assert deck["format"] == "Modern"
    assert _cards(deck) == _cards_json({93905: 4}, {93905: 15}, unresolved=(56, 0))


_UNREADABLE_GROUPINGS = [
    pytest.param(b"not a grouping", id="not-xml"),
    pytest.param(b"", id="empty-file"),
    pytest.param(SAMPLE_BYTES, id="a-dek-named-like-a-grouping"),
    pytest.param(_grouping(b'    CatId="308"\r\n', b""), id="CatId-missing"),
    pytest.param(_grouping(b'CatId="308"', b'CatId="three"'), id="CatId-word"),
    pytest.param(_grouping(b'CatId="308"', b'CatId="0"'), id="CatId-zero"),
    pytest.param(_grouping(b'CatId="308"', b'CatId="-308"'), id="CatId-negative"),
    pytest.param(
        _grouping(b'CatId="308"\r\n    Quantity="1"', b'CatId="308"\r\n    Quantity="0"'),
        id="Quantity-zero",
    ),
    pytest.param(
        _grouping(b'CatId="308"\r\n    Quantity="1"', b'CatId="308"\r\n    Quantity="1001"'),
        id="Quantity-over-the-ceiling",
    ),
    pytest.param(
        _grouping(
            b'CatId="308"\r\n    Quantity="1"\r\n    IsSideboard="false"',
            b'CatId="308"\r\n    Quantity="1"\r\n    IsSideboard="no"',
        ),
        id="IsSideboard-no",
    ),
    pytest.param(
        GROUPING_BYTES.replace(b'IsSideboard="false"', b'IsSideboard="true"'),
        id="no-maindeck-card",
    ),
    pytest.param(GROUPING_BYTES[: GROUPING_BYTES.rindex(b"</CardGrouping>")], id="truncated"),
]


@pytest.mark.parametrize("bad", _UNREADABLE_GROUPINGS)
def test_an_unreadable_grouping_is_warned_about_by_name_and_skipped_whole(
    store, tmp_path, caplog, bad
):
    _store(store, tmp_path, ("grouping bad.xml", bad, 0), ("Good.dek", SAMPLE_BYTES, 1))

    with caplog.at_level(logging.WARNING):
        counts = project(store)

    (deck,) = _decks(store)
    assert deck["name"] == "Good"
    (warning,) = _warnings(caplog)
    assert counts["warnings"] == 1
    assert repr("grouping bad.xml") in warning


def test_the_seven_formats_have_one_home(store):
    """``mtgo/formats.py`` is the list; migration 049's CHECK and the API's
    ``MtgoFormat`` must say the same seven, and every code maps into it."""
    check = re.search(r"format IN\s*\(([^)]*)\)", MIGRATION_049.read_text(encoding="utf-8"))
    assert check is not None
    assert tuple(re.findall(r"'([^']*)'", check.group(1))) == MTGO_FORMATS
    assert MtgoFormat.__args__ == MTGO_FORMATS
    assert set(FORMAT_CODES.values()) == set(MTGO_FORMATS)
    assert len(FORMAT_CODES) == len(MTGO_FORMATS)
