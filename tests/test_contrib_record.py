"""``GET /api/contrib/games`` and ``GET /api/contrib/records``: one
contributed-game record per finished game.

Ground truth, read from the fixtures rather than from running the builder:

- ``match_session.log`` (``fixture_peek.py`` and a replay of its entries):
  event ``Traditional_Ladder``, ``MatchWinCondition_Best2of3``, the deck's
  format ``TraditionalStandard``; both matches on 2026-08-13 (entries 5 and
  19), a Thursday of ISO week 33. Match fd5624a4 starts first (14:49:19),
  fa7a4d16 second (15:18:39) with games 1, 2 and 3. In fa7a4d16 we are seat
  and team 1. Game 1: turn 1 is seat 2's (entry 21), so we are on the draw,
  and our ``mulliganCount`` is 1 (entry 22); seat 2 plays the land 98589 on
  turn 1, we draw 86835 on turn 2, seat 2 draws a hidden card on turn 3, and
  both life totals are 20 when turns 2 and 3 begin. The game ends with team
  1 winning (entry 24), the last turn seen being 3. No entry carries a
  ``MulliganResp`` or a ``SubmitDeckResp``, so no game has a kept hand and
  games 2 and 3 have no deck list of their own.
- ``mulligan_session.log``: one room start (``Traditional_Ladder``), game 1,
  our seat 1. The first offer is 102774, 98389, 98392, 102698, 95062, 91584,
  102670; our ``MulliganOption_Mulligan`` follows; the second offer
  (``mulliganCount`` 1) is 102774, 68738, 102774, 86835, 102698, 91584,
  102578; then our ``MulliganOption_AcceptHand``. The capture ends mid-game.
- ``mtgo_match_session.log`` (``scripts/mtgo_probe.py --force --lines
  400``), first seen 2026-09-14, a Monday of ISO week 38. Game 1: Player1
  chooses to play first and begins with seven cards; nine ``Turn`` lines;
  Player1 wins. Per turn line, the plays and casts: 1 Player1 Plains,
  Dragonfire Blade; 2 Player2000 Fabled Passage; 3 Player1 Cavern of Souls,
  Lavaspur Boots, Giantcraft Helm; 4 Player2000 Wastewood Verge, Mosswood
  Dreadknight; 5 Player1 Giott, King of the Dwarves; 6 Player2000 Overgrown
  Tomb, Dread Whispers; 7 Player1 Kíli the Resourceful, Sacred Foundry; 8
  Player2000 Wastewood Verge, The Sibsig Ceremony, Agents of HYDRA; 9
  Player1 Sunbillow Verge, Thorin, Mountain-king. Game 2: Player2000 chooses
  to play first, Player1 begins with seven cards; eight ``Turn`` lines; on
  turn 2 Player1 plays Inspiring Vantage and casts Giantcraft Helm, on turn 7
  Player2000 plays Island and casts Agents of HYDRA; Player1 wins.
- ``mtgo_deck_sample.dek``: the deck picked for the MTGO match, read below.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pytest

from sensei_top.api import create_app
from sensei_top.contrib import build_records, finished_game_keys
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.reader.mtgo_decks import ingest_deck_dir

FIXTURES = Path(__file__).parent / "fixtures"
ARENA_FIXTURE = FIXTURES / "match_session.log"
MULLIGAN_FIXTURE = FIXTURES / "mulligan_session.log"
MTGO_BYTES = (FIXTURES / "mtgo_match_session.log").read_bytes()
MTGO_SOURCE_FILE = "Match_GameLog_f2244feb-54e1-48ec-b3c5-711b20844adf.dat"
MATCH_FIRST = "fd5624a4-d970-40eb-80aa-fba9d2ce17b3"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"
MTGO_MATCH = "f2244feb-54e1-48ec-b3c5-711b20844adf"
MTGO_SEEN = "2026-09-14T12:42:37"
POLICY = "2026-11-03"

# Game 1's deck, from the fixture's connectResp deckMessage (entries 4 and 20).
ARENA_MAIN = {
    68738: 4, 75876: 4, 79089: 2, 86835: 4, 90421: 2, 91584: 4, 92126: 2, 93122: 4,
    95062: 4, 97169: 6, 98392: 4, 102508: 3, 102578: 1, 102670: 4, 102698: 2,
    102774: 4, 102775: 2, 102793: 4,
}
ARENA_SIDE = {
    86734: 1, 91766: 2, 92348: 2, 94018: 1, 96620: 2, 97353: 2, 97848: 2, 102639: 3,
}
OPPONENT_LANDS = {69399, 98589, 102716}
FIRST_OFFER = [102774, 98389, 98392, 102698, 95062, 91584, 102670]
KEPT_OFFER = [102774, 68738, 102774, 86835, 102698, 91584, 102578]

# The transcript's card names the card database is given, so the MTGO plays
# resolve; Kíli the Resourceful is left out on purpose, to stand for a card
# with no name.
MTGO_NAMED = [
    "Dragonfire Blade", "Lavaspur Boots", "Giantcraft Helm", "Giott, King of the Dwarves",
    "Thorin, Mountain-king", "Leyline Axe", "Dwarven Mauler",
    "Fabled Passage", "Wastewood Verge", "Mosswood Dreadknight", "Overgrown Tomb",
    "Dread Whispers", "The Sibsig Ceremony", "Agents of HYDRA", "Gloomlake Verge",
    "Vengeful Bloodwitch",
]

FIXTURE_IDENTIFIERS = [
    "SelfPlayer", "OppPlayerOne", "OppPlayerTwo", "SELFCLIENTID0001",
    "AAAAAAAAAAAAAAA1", "BBBBBBBBBBBBBBB2", "Player1", "Player2000",
]


def _placeholder(grp_id: int) -> str:
    return f"Placeholder {grp_id}"


def _arena_names() -> dict[int, str]:
    """A name for every Arena card the tests read: the real one where
    ``mtgo_deck_cards.json`` has it, a placeholder otherwise."""
    known = {
        row["grp_id"]: row["name"]
        for row in json.loads((FIXTURES / "mtgo_deck_cards.json").read_text(encoding="utf-8"))
    }
    wanted = set(ARENA_MAIN) | set(ARENA_SIDE) | OPPONENT_LANDS | set(FIRST_OFFER) | set(KEPT_OFFER)
    return {g: known.get(g, _placeholder(g)) for g in wanted}


def _cards(conn) -> None:
    rows = json.loads((FIXTURES / "mtgo_deck_cards.json").read_text(encoding="utf-8"))
    taken = {r["grp_id"] for r in rows}
    rows += [
        {"grp_id": g, "name": n, "type_line": "Land"}
        for g, n in _arena_names().items() if g not in taken
    ]
    rows += [
        {"grp_id": 910001 + i, "name": n, "type_line": "Artifact"}
        for i, n in enumerate(MTGO_NAMED)
    ]
    conn.executemany(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (:grp_id, :name, :type_line)", rows
    )


def _insert_mtgo_row(conn) -> None:
    payload = base64.b64encode(MTGO_BYTES).decode("ascii")
    digest = hashlib.sha256(f"{MTGO_SOURCE_FILE}:{MTGO_SEEN}".encode()).hexdigest()
    conn.execute(
        """
        INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, ?, 'event', 'MtgoGameLog', ?, 'mtgo')
        """,
        (digest, MTGO_SOURCE_FILE, MTGO_SEEN, payload),
    )


def _build(tmp_path: Path) -> Path:
    db_path = tmp_path / "contrib.db"
    conn = open_database(db_path)
    _cards(conn)
    ingest_file(conn, ARENA_FIXTURE, locale_hint="mdy")
    _insert_mtgo_row(conn)
    conn.commit()
    decks = tmp_path / "decks"
    decks.mkdir()
    shutil.copy(FIXTURES / "mtgo_deck_sample.dek", decks / "Sample.dek")
    ingest_deck_dir(conn, decks)
    project(conn)
    conn.close()
    return db_path


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    return _build(tmp_path)


@pytest.fixture
def db(db_path):
    conn = _open(db_path)
    yield conn
    conn.close()


def _one(conn, key: str) -> dict:
    ((got, record),) = build_records(conn, [key], policy_version=POLICY)
    assert got == key
    return record


def _board(counts: dict[int, int] | Counter, names: dict[int, str]) -> list[list]:
    return sorted([names[g], n] for g, n in counts.items())


def _dek_boards(path: Path) -> tuple[list[list], list[list]]:
    main: Counter[str] = Counter()
    side: Counter[str] = Counter()
    for card in ET.parse(path).getroot().iter("Cards"):
        board = side if card.get("Sideboard") == "true" else main
        board[card.get("Name")] += int(card.get("Quantity"))
    return sorted([n, c] for n, c in main.items()), sorted([n, c] for n, c in side.items())


def _pick_sample_deck(conn) -> None:
    (deck_id,) = conn.execute("SELECT deck_id FROM decks WHERE name = 'Sample'").fetchone()
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format, updated_at) "
        "VALUES (?, ?, 'Modern', '2026-10-01T10:00:00Z')",
        (MTGO_MATCH, deck_id),
    )
    conn.commit()


def _define(conn, fmt: str, key: str, name: str, card: str) -> None:
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES (?, 'archetype', ?, ?, 0, ?, '2026-01-01T00:00:00Z')",
        (fmt, key, name, json.dumps({"Name": name,
                                     "Conditions": [{"Type": "InMainboard", "Cards": [card]}]})),
    )
    conn.commit()


# --- the game keys -----------------------------------------------------------


def test_every_finished_game_has_a_key_oldest_match_first(db):
    assert finished_game_keys(db) == [
        f"{MATCH_FIRST}:1", f"{MATCH_FIRST}:2",
        f"{MATCH_WIN}:1", f"{MATCH_WIN}:2", f"{MATCH_WIN}:3",
        f"{MTGO_MATCH}:1", f"{MTGO_MATCH}:2",
    ]


def test_a_key_that_names_no_finished_game_is_skipped(db):
    keys = ["no-colon", f"{MATCH_WIN}:x", f"{MATCH_WIN}:9", "unknown-match:1",
            f"{MATCH_WIN}:1", f"{MATCH_WIN}:1"]
    assert [key for key, _ in build_records(db, keys, policy_version=POLICY)] == [
        f"{MATCH_WIN}:1"
    ]


def test_an_unfinished_game_has_no_key_and_no_record(tmp_path):
    db_path = tmp_path / "mulligan.db"
    conn = open_database(db_path)
    ingest_file(conn, MULLIGAN_FIXTURE, locale_hint="mdy")
    project(conn)
    (match_id,) = conn.execute("SELECT match_id FROM matches").fetchone()
    assert finished_game_keys(conn) == []
    assert build_records(conn, [f"{match_id}:1"], policy_version=POLICY) == []
    conn.close()


# --- Arena -------------------------------------------------------------------


def test_an_arena_game_record_holds_the_logs_own_fields(db):
    names = _arena_names()
    record = _one(db, f"{MATCH_WIN}:1")
    assert {k: record[k] for k in (
        "schema_version", "client", "format", "event", "best_of", "week", "game",
        "on_play", "mulligans", "result", "turn_count", "policy_version",
    )} == {
        "schema_version": 1, "client": "arena", "format": "Standard",
        "event": "ranked", "best_of": 3, "week": "2026-W33", "game": 1,
        "on_play": False, "mulligans": 1, "result": "win", "turn_count": 3,
        "policy_version": POLICY,
    }
    assert record["deck"] == {"main": _board(ARENA_MAIN, names), "side": _board(ARENA_SIDE, names)}
    turns = {t["n"]: t for t in record["turns"]}
    assert sorted(turns) == [1, 2, 3]
    assert turns[1]["played"] == {"self": [], "opp": [names[98589]]}
    assert turns[1]["drawn"] == []
    assert turns[2]["drawn"] == [names[86835]]
    assert turns[2]["played"] == {"self": [], "opp": []}
    # The opponent's turn-3 draw is a hidden card: never theirs to show, and
    # never one of ours.
    assert turns[3]["drawn"] == []
    assert turns[3]["played"] == {"self": [], "opp": []}
    assert turns[1]["life"] == turns[2]["life"] == {"self": 20, "opp": 20}
    # No rank snapshot, no archetype definitions, and lands alone name no
    # opponent's deck.
    assert "rank" not in record
    assert "archetypes" not in record


@pytest.mark.parametrize(
    "key",
    [f"{MATCH_FIRST}:1", f"{MATCH_FIRST}:2", f"{MATCH_WIN}:1", f"{MATCH_WIN}:2", f"{MATCH_WIN}:3"],
)
def test_a_game_whose_log_lacks_the_opening_hand_omits_it(db, key):
    record = _one(db, key)
    assert "kept_hand" not in record
    if not key.endswith(":1"):
        assert "deck" not in record


def test_a_later_game_reads_the_deck_it_was_played_with(db):
    # Synthetic: the fixture carries no SubmitDeckResp, so game_decks is
    # empty; this row stands for one, game 1's lists with 102578 boarded out
    # for one 102639, to reach the read.
    main = sorted([g for g, n in ARENA_MAIN.items() for _ in range(n) if g != 102578] + [102639])
    side = sorted([g for g, n in ARENA_SIDE.items() for _ in range(n)] + [102578])
    side.remove(102639)
    db.execute(
        "INSERT INTO game_decks (match_id, game_number, deck_cards_json, sideboard_cards_json) "
        "VALUES (?, 2, ?, ?)",
        (MATCH_WIN, json.dumps(main), json.dumps(side)),
    )
    names = _arena_names()
    assert _one(db, f"{MATCH_WIN}:2")["deck"] == {
        "main": _board(Counter(main), names), "side": _board(Counter(side), names),
    }


def test_a_deck_with_a_card_of_no_name_is_left_out_whole(db):
    db.execute("DELETE FROM cards WHERE grp_id = 102793")
    record = _one(db, f"{MATCH_WIN}:1")
    assert "deck" not in record
    assert record["turns"]


def test_the_rank_is_the_class_in_force_and_never_the_step(db):
    db.executemany(
        "INSERT INTO rank_snapshot (observed_at, constructed_class, constructed_level, "
        "constructed_step) VALUES (?, ?, ?, ?)",
        [("2026-08-12T20:00:00", "Gold", 2, 3), ("2026-08-14T09:00:00", "Platinum", 4, 1)],
    )
    record = _one(db, f"{MATCH_WIN}:1")
    assert record["rank"] == "Gold"
    assert {"level", "step"}.isdisjoint(record)
    # MTGO has no rank, even with an Arena snapshot from before its match.
    assert "rank" not in _one(db, f"{MTGO_MATCH}:1")


def test_the_opponents_archetype_comes_from_a_pick_only_when_the_app_named_it(db):
    _define(db, "Standard", "TestTempo", "Tempo", "Placeholder 1")
    db.execute(
        "INSERT INTO opponent_deck_override (match_id, label, archetype_key) "
        "VALUES (?, 'Tempo', 'TestTempo')",
        (MATCH_WIN,),
    )
    db.execute(
        "INSERT INTO opponent_deck_override (match_id, label) VALUES (?, 'Rogue')", (MATCH_FIRST,)
    )
    db.execute(
        "INSERT INTO opponent_deck_override (match_id, label) VALUES (?, 'typed by hand')",
        (MTGO_MATCH,),
    )
    assert _one(db, f"{MATCH_WIN}:1")["archetypes"] == {
        "opp": {"key": "TestTempo", "label": "Tempo"}
    }
    assert _one(db, f"{MATCH_FIRST}:1")["archetypes"] == {"opp": {"label": "Rogue"}}
    assert "archetypes" not in _one(db, f"{MTGO_MATCH}:1")


def test_a_picks_stored_label_is_never_sent_when_it_names_an_archetype(db):
    _define(db, "Standard", "TestTempo", "Tempo", "Placeholder 1")
    db.execute(
        "INSERT INTO opponent_deck_override (match_id, label, archetype_key) "
        "VALUES (?, 'my own words about it', 'TestTempo')",
        (MATCH_WIN,),
    )
    record = _one(db, f"{MATCH_WIN}:1")
    assert record["archetypes"] == {"opp": {"key": "TestTempo", "label": "Tempo"}}
    assert "my own words" not in json.dumps(record)


def test_an_own_archetype_is_classified_from_the_match_deck_for_every_game(db):
    _define(db, "Standard", "TestOwn", "Own Deck", "Placeholder 102793")
    # Game 2 has no list of its own in the fixture; the match's deck still names it.
    for key in (f"{MATCH_WIN}:1", f"{MATCH_WIN}:2"):
        assert _one(db, key)["archetypes"] == {"self": {"key": "TestOwn", "label": "Own Deck"}}
    db.execute("DELETE FROM archetypes")
    assert "archetypes" not in _one(db, f"{MATCH_WIN}:2")


@pytest.mark.parametrize(
    ("event_id", "expected"),
    [
        ("Ladder", "ranked"), ("Traditional_Ladder", "ranked"),
        ("Play", "play"), ("Traditional_Play", "play"), ("Constructed_BestOf3", "play"),
        ("PremierDraft_FRA_20260929", "limited"), ("Sealed_FRA_20260929", "limited"),
        ("Traditional_Cons_Event_2026", "event"), ("Cons_Event_20261012", "event"),
        ("AIBotMatch", None), ("DirectGame", None), (None, None),
    ],
)
def test_the_event_is_a_fixed_class_never_the_raw_id(db, event_id, expected):
    db.execute("UPDATE matches SET event_id = ? WHERE match_id = ?", (event_id, MATCH_WIN))
    record = _one(db, f"{MATCH_WIN}:1")
    if expected is None:
        assert "event" not in record
    else:
        assert record["event"] == expected
    sent = json.dumps({k: v for k, v in record.items() if k not in ("week", "policy_version")})
    for run in re.findall(r"\d{4,}", event_id or ""):
        assert run not in sent


def test_a_match_with_no_best_of_omits_it(db):
    db.execute("UPDATE matches SET best_of = NULL WHERE match_id = ?", (MATCH_WIN,))
    assert "best_of" not in _one(db, f"{MATCH_WIN}:1")


def test_an_mtgo_card_with_no_grp_id_is_sent_under_the_transcripts_name(db):
    rows = db.execute(
        "SELECT mtgo_name FROM card_events WHERE match_id = ? AND grp_id IS NULL "
        "AND mtgo_name IS NOT NULL AND category IN ('PlayLand', 'CastSpell')",
        (MTGO_MATCH,),
    ).fetchall()
    assert "Kíli the Resourceful" in {r[0] for r in rows}
    record = _one(db, f"{MTGO_MATCH}:1")
    turn7 = next(t for t in record["turns"] if t["n"] == 7)
    assert "Kíli the Resourceful" in turn7["played"]["self"]


def test_the_kept_hand_is_the_offer_we_accepted(tmp_path):
    db_path = tmp_path / "mulligan.db"
    conn = open_database(db_path)
    _cards(conn)
    ingest_file(conn, MULLIGAN_FIXTURE, locale_hint="mdy")
    project(conn)
    # Synthetic: the capture ends mid-game, so the game never finished; it is
    # marked won only so that it has a record.
    conn.execute("UPDATE games SET result = 'win'")
    (match_id,) = conn.execute("SELECT match_id FROM matches").fetchone()
    names = _arena_names()
    record = _one(conn, f"{match_id}:1")
    assert record["kept_hand"] == _board(Counter(KEPT_OFFER), names)
    conn.close()


# --- MTGO --------------------------------------------------------------------


def test_an_mtgo_game_record_holds_the_transcripts_fields(db):
    _pick_sample_deck(db)
    _define(db, "Modern", "TestDragons", "Dragons", "Smaug the Magnificent")
    record = _one(db, f"{MTGO_MATCH}:1")
    assert {k: record[k] for k in (
        "client", "format", "week", "game", "on_play", "mulligans", "result", "turn_count",
    )} == {
        "client": "mtgo", "format": "Modern", "week": "2026-W38", "game": 1, "on_play": True,
        "mulligans": 0, "result": "win", "turn_count": 9,
    }
    assert record["best_of"] == 3
    assert {"event", "rank", "kept_hand"}.isdisjoint(record)
    main, side = _dek_boards(FIXTURES / "mtgo_deck_sample.dek")
    assert record["deck"] == {"main": main, "side": side}
    assert record["archetypes"] == {"self": {"key": "TestDragons", "label": "Dragons"}}

    turns = {t["n"]: t for t in record["turns"]}
    assert sorted(turns) == list(range(1, 10))
    assert all({"drawn", "life"}.isdisjoint(t) for t in turns.values())
    assert turns[1]["played"] == {"self": ["Plains", "Dragonfire Blade"], "opp": []}
    assert turns[2]["played"] == {"self": [], "opp": ["Fabled Passage"]}
    assert turns[3]["played"]["self"] == ["Cavern of Souls", "Lavaspur Boots", "Giantcraft Helm"]
    assert turns[5]["played"]["self"] == ["Giott, King of the Dwarves"]
    # Kíli the Resourceful has no row in the card database, so the transcript's
    # own name stands for it, the cast order kept.
    assert turns[7]["played"] == {"self": ["Kíli the Resourceful", "Sacred Foundry"], "opp": []}
    assert turns[8]["played"]["opp"] == [
        "Wastewood Verge", "The Sibsig Ceremony", "Agents of HYDRA",
    ]
    assert turns[9]["played"]["self"] == ["Sunbillow Verge", "Thorin, Mountain-king"]


def test_a_later_mtgo_game_has_no_deck_list(db):
    _pick_sample_deck(db)
    record = _one(db, f"{MTGO_MATCH}:2")
    assert {k: record[k] for k in ("game", "on_play", "mulligans", "result", "turn_count")} == {
        "game": 2, "on_play": False, "mulligans": 0, "result": "win", "turn_count": 8,
    }
    assert "deck" not in record
    turns = {t["n"]: t for t in record["turns"]}
    assert turns[2]["played"]["self"] == ["Inspiring Vantage", "Giantcraft Helm"]
    assert turns[7]["played"]["opp"] == ["Island", "Agents of HYDRA"]


# --- the routes --------------------------------------------------------------


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield from _strings(key)
            yield from _strings(inner)
    elif isinstance(value, list | tuple):
        for inner in value:
            yield from _strings(inner)


def _held_values(conn) -> set[str]:
    """What the database holds that a record must never carry: ids, handles,
    deck names, and the time of day and full date of each match."""
    needles: set[str] = set()
    for row in conn.execute(
        "SELECT match_id, opponent_user_id, opponent_name, started_at, ended_at FROM matches"
    ):
        needles.update(v for v in (row["match_id"], row["opponent_user_id"], row["opponent_name"])
                       if v)
        for stamp in (row["started_at"], row["ended_at"]):
            if stamp:
                needles.update({stamp[:10], stamp[11:16], stamp[11:19]} - {""})
    needles.update(f"{m}:{g}" for m, g in conn.execute("SELECT match_id, game_number FROM games"))
    needles.update(name for (name,) in conn.execute("SELECT name FROM decks") if name)
    return needles


def _scan(records, needles) -> None:
    strings = list(_strings(records))
    for needle in needles:
        assert all(needle not in text for text in strings), needle


def test_a_record_with_every_optional_field_carries_no_identifier(tmp_path, monkeypatch):
    # Rank, kept hand, both archetypes and a dated event, all present: the
    # mulligan capture holds the offer and the keep, the rest is added.
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    conn = open_database(tmp_path / "full.db")
    _cards(conn)
    ingest_file(conn, MULLIGAN_FIXTURE, locale_hint="mdy")
    _insert_mtgo_row(conn)
    conn.commit()
    decks = tmp_path / "decks"
    decks.mkdir()
    shutil.copy(FIXTURES / "mtgo_deck_sample.dek", decks / "Sample.dek")
    ingest_deck_dir(conn, decks)
    project(conn)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "UPDATE games SET result = 'win' "
        "WHERE match_id IN (SELECT match_id FROM matches WHERE source = 'arena')"
    )
    (arena_id,) = conn.execute("SELECT match_id FROM matches WHERE source = 'arena'").fetchone()
    started = conn.execute(
        "SELECT started_at FROM matches WHERE match_id = ?", (arena_id,)
    ).fetchone()[0]
    conn.execute("UPDATE matches SET event_id = 'PremierDraft_FRA_20260929' WHERE match_id = ?",
                 (arena_id,))
    conn.execute(
        "INSERT INTO rank_snapshot (observed_at, constructed_class, constructed_level, "
        "constructed_step) VALUES ('2000-01-01T00:00:00', 'Gold', 2, 3)"
    )
    fmt = conn.execute(
        "SELECT format FROM v_match_format WHERE match_id = ?", (arena_id,)
    ).fetchone()[0]
    (deck_id,) = conn.execute(
        "SELECT deck_id FROM matches WHERE match_id = ?", (arena_id,)
    ).fetchone()
    main = json.loads(conn.execute("SELECT cards_json FROM decks WHERE deck_id = ?", (deck_id,))
                      .fetchone()[0])["maindeck"]
    own_card = _arena_names()[main[0]]
    _define(conn, fmt, "TestOwn", "Own Deck", own_card)
    _define(conn, fmt, "TestTempo", "Tempo", own_card)
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, archetype_key) "
        "VALUES (?, 'typed by hand', 'TestTempo')",
        (arena_id,),
    )
    _pick_sample_deck(conn)
    keys = [f"{arena_id}:1", f"{MTGO_MATCH}:1"]
    records = build_records(conn, keys, policy_version=POLICY)
    arena = records[0][1]
    assert {"rank", "kept_hand", "event", "best_of"} <= arena.keys()
    assert arena["event"] == "limited"
    assert {"self", "opp"} == arena["archetypes"].keys()
    assert started[:10] not in json.dumps(arena)
    _scan([record for _, record in records], _held_values(conn) | set(FIXTURE_IDENTIFIERS))
    conn.close()


def test_the_routes_serve_every_record_and_no_identifier(tmp_path, db_path, make_client):
    with make_client(create_app(db_path)) as client:
        games = client.get("/api/contrib/games")
        assert games.status_code == 200
        keys = games.json()
        records = client.get(
            "/api/contrib/records", params={"keys": keys, "policy_version": POLICY}
        )
    assert records.status_code == 200
    assert [item["key"] for item in records.json()] == keys
    sent = json.dumps([item["record"] for item in records.json()])
    for needle in [
        *FIXTURE_IDENTIFIERS, MATCH_FIRST, MATCH_WIN, MTGO_MATCH, "Match_GameLog",
        "Spellelementals", "2026-08-13", "2026-09-14",
        str(tmp_path), str(FIXTURES), str(Path.home()),
    ]:
        assert needle not in sent, needle
    # Absent means absent: no field is sent as null.
    assert "null" not in sent
    first = records.json()[2]["record"]["turns"][0]
    assert first["played"] == {"self": [], "opp": [_arena_names()[98589]]}


@pytest.mark.parametrize(
    "params",
    [
        {"keys": [f"{MATCH_WIN}:{n}" for n in range(51)], "policy_version": POLICY},
        {"keys": [f"{MATCH_WIN}:1"], "policy_version": "3 November"},
        {"keys": [f"{MATCH_WIN}:1"]},
        {"policy_version": POLICY},
    ],
    ids=["over-50-keys", "policy-not-a-date", "no-policy", "no-keys"],
)
def test_the_records_route_refuses_a_bad_request(db_path, make_client, params):
    with make_client(create_app(db_path)) as client:
        assert client.get("/api/contrib/records", params=params).status_code == 422
