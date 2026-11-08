"""``GET /api/sync/payloads``: one cloud-backup payload per match.

Ground truth, read from the fixtures rather than from running the builder:

- ``match_session.log`` (``fixture_peek.py``): the deck is game 1's
  ``connectResp.deckMessage`` (entries 4 and 20, the same 60 and 15 cards,
  also entry 17's ``DeckUpsertDeckV3``, deck "Spellelementals", format
  ``TraditionalStandard``); event ``Traditional_Ladder``. Match fd5624a4:
  the room starts at 14:49:19 (entry 5), we are seat/team 2, team 1 wins both
  games and the match, which completes at 15:06:16 (entry 16); game 1's turn 1
  is seat 2's (entry 6), so we are on the play. Match fa7a4d16: starts
  15:18:39 (entry 19), we are seat/team 1, games won by 1, 2, 1, completed at
  15:44:35 (entry 33); turn 1 is seat 2's (entry 21), so we are on the draw.
  The opponent's PlayLand transfers whose object rides the same message:
  grpId 69399 by seat 1 in fd5624a4 (entry 14); 98589, 68738 and 102716 by
  seat 2 in fa7a4d16 (entries 22, 26, 31). The deck's ``LastPlayed`` carries
  ``-03:00``, the zone the capture was made in.
- ``mtgo_match_session.log`` (``scripts/mtgo_probe.py --force --lines
  400``): Player1 chooses to play first, wins 2-0. Player2000's plays, casts,
  activations and triggers name ten distinct cards: Fabled Passage, Wastewood
  Verge, Mosswood Dreadknight, Overgrown Tomb, Dread Whispers, The Sibsig
  Ceremony, Agents of HYDRA, Gloomlake Verge, Vengeful Bloodwitch, Island. Of
  those, ``mtgo_deck_cards.json`` names only Island.
- ``mtgo_deck_sample.dek``: 60 main and 15 sideboard copies, every name in
  ``mtgo_deck_cards.json``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from sensei_top.api import create_app
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.reader.mtgo_decks import ingest_deck_dir
from sensei_top.sync import MatchPayload, build_payloads, canonical_json

FIXTURES = Path(__file__).parent / "fixtures"
ARENA_FIXTURE = FIXTURES / "match_session.log"
MTGO_BYTES = (FIXTURES / "mtgo_match_session.log").read_bytes()
MTGO_SOURCE_FILE = "Match_GameLog_f2244feb-54e1-48ec-b3c5-711b20844adf.dat"
MATCH_LOSS = "fd5624a4-d970-40eb-80aa-fba9d2ce17b3"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"
MTGO_MATCH = "f2244feb-54e1-48ec-b3c5-711b20844adf"
# The two MTGO rows stored for the one game log: a shorter snapshot first,
# then the whole file. The match's start is the first, its end the last.
MTGO_FIRST_SEEN = "2026-09-14T12:30:00"
MTGO_LAST_SEEN = "2026-09-14T12:42:37"

ARENA_MAIN = {
    68738: 4, 75876: 4, 79089: 2, 86835: 4, 90421: 2, 91584: 4, 92126: 2, 93122: 4,
    95062: 4, 97169: 6, 98392: 4, 102508: 3, 102578: 1, 102670: 4, 102698: 2,
    102774: 4, 102775: 2, 102793: 4,
}
ARENA_SIDE = {
    86734: 1, 91766: 2, 92348: 2, 94018: 1, 96620: 2, 97353: 2, 97848: 2, 102639: 3,
}
ARENA_OPPONENT_LANDS = {MATCH_LOSS: {69399}, MATCH_WIN: {98589, 68738, 102716}}

MTGO_OPPONENT_UNNAMED = [
    "Agents of HYDRA", "Dread Whispers", "Fabled Passage", "Gloomlake Verge",
    "Mosswood Dreadknight", "Overgrown Tomb", "The Sibsig Ceremony",
    "Vengeful Bloodwitch", "Wastewood Verge",
]

# Every player name and user id the fixtures carry (docs/testing.md, "The
# fixtures"), anonymized already; none may reach a payload.
FIXTURE_IDENTIFIERS = [
    "SelfPlayer", "OppPlayerOne", "OppPlayerTwo", "SELFCLIENTID0001",
    "AAAAAAAAAAAAAAA1", "BBBBBBBBBBBBBBB2", "Player1", "Player2000",
]

_POLICY_LIMIT_BYTES = 1536


@pytest.fixture(autouse=True)
def capture_zone():
    """Local time three hours behind UTC, the zone the Arena capture was made
    in (POSIX ``TZ`` inverts the sign). Windows has no ``tzset``; the tests
    that read ``played_at`` skip there."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "<-03>3"
    if hasattr(time, "tzset"):
        time.tzset()
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    if hasattr(time, "tzset"):
        time.tzset()


needs_tzset = pytest.mark.skipif(not hasattr(time, "tzset"), reason="no tzset on Windows")


def _arena_names() -> dict[int, str]:
    """A name for every card the Arena deck and the opponent's lands use: the
    real one where ``mtgo_deck_cards.json`` has it, a placeholder otherwise."""
    known = {
        row["grp_id"]: row["name"]
        for row in json.loads((FIXTURES / "mtgo_deck_cards.json").read_text(encoding="utf-8"))
    }
    wanted = set(ARENA_MAIN) | set(ARENA_SIDE) | set().union(*ARENA_OPPONENT_LANDS.values())
    return {g: known.get(g, f"Placeholder {g}") for g in wanted}


def _insert_mtgo_row(conn, *, data: bytes, logged_at: str) -> None:
    payload = base64.b64encode(data).decode("ascii")
    digest = hashlib.sha256(f"{MTGO_SOURCE_FILE}:{logged_at}:{len(data)}".encode()).hexdigest()
    conn.execute(
        """
        INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, ?, 'event', 'MtgoGameLog', ?, 'mtgo')
        """,
        (digest, MTGO_SOURCE_FILE, logged_at, payload),
    )


def _build(tmp_path: Path, *, name_opponent: bool = False, drop: tuple[str, ...] = ()) -> Path:
    """The Arena fixture, the MTGO fixture and two MTGO deck files, projected.

    ``name_opponent`` gives the MTGO opponent's nine unnamed cards a
    placeholder ``cards`` row each; ``drop`` leaves those card names out of
    ``cards`` entirely."""
    db_path = tmp_path / "sync.db"
    conn = open_database(db_path)
    rows = [
        r for r in json.loads((FIXTURES / "mtgo_deck_cards.json").read_text(encoding="utf-8"))
        if r["name"] not in drop
    ]
    arena = {g: n for g, n in _arena_names().items() if g not in {r["grp_id"] for r in rows}}
    rows += [{"grp_id": g, "name": n, "type_line": "Land"} for g, n in arena.items()]
    if name_opponent:
        rows += [
            {"grp_id": 900001 + i, "name": n, "type_line": "Creature"}
            for i, n in enumerate(MTGO_OPPONENT_UNNAMED)
        ]
    conn.executemany(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (:grp_id, :name, :type_line)", rows
    )
    ingest_file(conn, ARENA_FIXTURE, locale_hint="mdy")
    _insert_mtgo_row(conn, data=MTGO_BYTES[: len(MTGO_BYTES) // 2], logged_at=MTGO_FIRST_SEEN)
    _insert_mtgo_row(conn, data=MTGO_BYTES, logged_at=MTGO_LAST_SEEN)
    conn.commit()
    decks = tmp_path / "decks"
    decks.mkdir()
    shutil.copy(FIXTURES / "mtgo_deck_sample.dek", decks / "Sample.dek")
    shutil.copy(FIXTURES / "mtgo_deck_adventure.dek", decks / "Adventure.dek")
    ingest_deck_dir(conn, decks)
    project(conn)
    conn.close()
    return db_path


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    conn = sqlite3.connect(_build(tmp_path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _pick_mtgo_deck(conn, deck_name: str, fmt: str | None = "Modern") -> None:
    (deck_id,) = conn.execute("SELECT deck_id FROM decks WHERE name = ?", (deck_name,)).fetchone()
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format, updated_at) "
        "VALUES (?, ?, ?, '2026-10-01T10:00:00Z')",
        (MTGO_MATCH, deck_id, fmt),
    )
    conn.commit()


def _by_match(conn) -> dict[str, MatchPayload]:
    return {p.match_id: p for p in build_payloads(conn)}


def _board(counts: dict[int, int], names: dict[int, str]) -> list[list]:
    return sorted([names[g], n] for g, n in counts.items())


# --- Arena -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("match_id", "result", "won", "lost", "play", "duration_s"),
    [
        (MATCH_LOSS, "loss", 0, 2, "play", 16 * 60 + 57),   # 14:49:19 -> 15:06:16
        (MATCH_WIN, "win", 2, 1, "draw", 25 * 60 + 56),     # 15:18:39 -> 15:44:35
    ],
)
def test_an_arena_match_payload_carries_the_policy_fields(
    db, match_id, result, won, lost, play, duration_s
):
    found = _by_match(db)[match_id]
    payload = found.payload
    names = _arena_names()

    assert found.source == "arena"
    assert payload["schema_version"] == 1
    assert payload["event"] == "Traditional_Ladder"
    assert payload["format"] == "Standard"
    assert payload["best_of"] == 3
    assert (payload["result"], payload["won"], payload["lost"]) == (result, won, lost)
    assert payload["play"] == play
    assert payload["duration_s"] == duration_s
    assert payload["deck"] == {
        "name": "Spellelementals",
        "main": _board(ARENA_MAIN, names),
        "side": _board(ARENA_SIDE, names),
    }
    assert {names[g] for g in ARENA_OPPONENT_LANDS[match_id]} <= set(payload["opp_cards"])
    assert payload["opp_cards"] == sorted(set(payload["opp_cards"]))
    assert payload["picks"] == {"opp": None, "mtgo": None}


@needs_tzset
def test_played_at_is_the_match_start_in_utc(db):
    """The header's local time, three hours behind UTC in the capture's zone."""
    found = _by_match(db)
    assert found[MATCH_LOSS].played_at == "2026-08-13T17:49:19Z"
    assert found[MATCH_WIN].payload["played_at"] == "2026-08-13T18:18:39Z"


def test_a_deck_card_with_no_name_is_left_out_and_counted(tmp_path):
    """Synthetic: one Arena match, a deck whose grpId 999 has no ``cards``
    row, no card events. Its three copies are counted, never named."""
    conn = open_database(tmp_path / "t.db")
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (1, 'Known')")
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json) VALUES ('d', 'Deck', ?)",
        (json.dumps({"maindeck": [1, 1, 999, 999, 999], "sideboard": [999]}),),
    )
    conn.execute(
        "INSERT INTO matches (match_id, deck_id, started_at, result) "
        "VALUES ('m', 'd', '2026-08-13T14:49:19', 'win')"
    )
    conn.commit()
    (found,) = build_payloads(conn)
    assert found.payload["deck"] == {"name": "Deck", "main": [["Known", 2]], "side": []}
    assert found.payload["unknown_cards"] == 4
    assert found.payload["duration_s"] is None  # no end recorded
    conn.close()


def test_an_opponent_token_is_left_out(tmp_path):
    """Synthetic: the opponent (seat 2) shows a card and a token it makes;
    only the card is listed, and the token is not counted as unknown."""
    conn = open_database(tmp_path / "t.db")
    conn.executemany(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (?, ?, ?)",
        [(1, "Twin", "Creature — Elf"), (2, "Twin Spawn", "Token Creature — Elf")],
    )
    conn.execute(
        "INSERT INTO matches (match_id, self_seat, opponent_seat, started_at) "
        "VALUES ('m', 1, 2, '2026-08-13T14:49:19')"
    )
    conn.execute("INSERT INTO games (match_id, game_number) VALUES ('m', 1)")
    conn.executemany(
        "INSERT INTO card_events (match_id, game_number, seq, seat, grp_id, category) "
        "VALUES ('m', 1, ?, 2, ?, 'cast')",
        [(1, 2), (2, 1)],
    )
    conn.commit()
    (found,) = build_payloads(conn)
    assert found.payload["opp_cards"] == ["Twin"]
    assert found.payload["unknown_cards"] == 0
    conn.close()


# --- MTGO --------------------------------------------------------------------


def test_an_mtgo_match_without_a_deck_pick_is_not_sent(db):
    assert MTGO_MATCH not in _by_match(db)
    assert set(_by_match(db)) == {MATCH_LOSS, MATCH_WIN}


def test_an_mtgo_format_pick_alone_does_not_send_the_match(db):
    db.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) VALUES (?, NULL, 'Modern')",
        (MTGO_MATCH,),
    )
    db.commit()
    assert MTGO_MATCH not in _by_match(db)


def test_an_mtgo_match_with_a_deck_pick_is_sent(db):
    _pick_mtgo_deck(db, "Sample")
    payload = _by_match(db)[MTGO_MATCH].payload

    assert _by_match(db)[MTGO_MATCH].source == "mtgo"
    assert payload["event"] is None
    assert payload["format"] == "Modern"
    assert (payload["result"], payload["won"], payload["lost"]) == ("win", 2, 0)
    assert payload["play"] == "play"
    # started_at is the first sighting of the log, not the match's start.
    assert payload["duration_s"] is None
    assert payload["deck"]["name"] == "Sample"
    assert sum(n for _, n in payload["deck"]["main"]) == 60
    assert sum(n for _, n in payload["deck"]["side"]) == 15
    assert ["Smaug the Magnificent", 4] in payload["deck"]["main"]
    assert ["Seam Rip", 4] in payload["deck"]["side"]
    assert payload["opp_cards"] == ["Island"]
    assert payload["unknown_cards"] == len(MTGO_OPPONENT_UNNAMED)
    # Island is a land, so nothing names the opponent's deck.
    assert payload["opp"] is None
    assert payload["picks"] == {
        "opp": None,
        "mtgo": {"format": "Modern", "updated_at": "2026-10-01T10:00:00Z"},
    }


@needs_tzset
def test_an_mtgo_match_is_played_when_first_seen(db):
    _pick_mtgo_deck(db, "Sample")
    assert _by_match(db)[MTGO_MATCH].played_at == "2026-09-14T15:30:00Z"


def test_an_mtgo_deck_copy_that_never_resolved_is_counted(tmp_path, monkeypatch):
    """Burst Lightning (4 main copies of the sample deck) left out of
    ``cards``: the deck file still lists it, the projector cannot, and the
    payload counts the four copies beside the opponent's nine."""
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    conn = sqlite3.connect(_build(tmp_path, drop=("Burst Lightning",)))
    _pick_mtgo_deck(conn, "Sample")
    payload = _by_match(conn)[MTGO_MATCH].payload
    assert sum(n for _, n in payload["deck"]["main"]) == 56
    assert all(name != "Burst Lightning" for name, _ in payload["deck"]["main"])
    assert payload["unknown_cards"] == 4 + len(MTGO_OPPONENT_UNNAMED)
    conn.close()


# --- picks and the digest ----------------------------------------------------


def test_the_opponent_deck_pick_rides_the_payload_and_moves_only_its_digest(db):
    before = {m: p.digest for m, p in _by_match(db).items()}
    db.execute(
        "INSERT INTO opponent_deck_override (match_id, label, archetype_key, updated_at) "
        "VALUES (?, 'Golgari Midrange', 'golgari_midrange', '2026-10-02T09:00:00Z')",
        (MATCH_WIN,),
    )
    db.commit()
    after = _by_match(db)

    assert after[MATCH_WIN].payload["picks"]["opp"] == {
        "label": "Golgari Midrange",
        "archetype_key": "golgari_midrange",
        "updated_at": "2026-10-02T09:00:00Z",
    }
    assert after[MATCH_WIN].payload["opp"] == {
        "label": "Golgari Midrange", "key": "archetype:golgari_midrange",
    }
    assert after[MATCH_WIN].digest != before[MATCH_WIN]
    assert after[MATCH_LOSS].digest == before[MATCH_LOSS]


def test_the_digest_is_sha256_of_the_canonical_payload(db):
    for found in build_payloads(db):
        text = json.dumps(found.payload, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False)
        assert canonical_json(found.payload) == text
        assert found.digest == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_largest_fixture_deck_payload_is_under_the_limit(tmp_path, monkeypatch):
    """The adventure deck is the largest deck file among the fixtures, and
    with every one of the opponent's ten cards named the payload carries
    the most it can from them."""
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    conn = sqlite3.connect(_build(tmp_path, name_opponent=True))
    _pick_mtgo_deck(conn, "Adventure")
    found = _by_match(conn)
    assert len(found[MTGO_MATCH].payload["opp_cards"]) == 10
    for payload in found.values():
        assert len(canonical_json(payload.payload).encode("utf-8")) < _POLICY_LIMIT_BYTES
    conn.close()


# --- the route ---------------------------------------------------------------


def test_the_route_serves_every_payload_and_no_identifier(tmp_path, monkeypatch, make_client):
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    db_path = _build(tmp_path)
    conn = sqlite3.connect(db_path)
    _pick_mtgo_deck(conn, "Sample")
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label) VALUES (?, 'Rogue')", (MATCH_LOSS,)
    )
    conn.commit()
    conn.close()

    with make_client(create_app(db_path)) as client:
        response = client.get("/api/sync/payloads")
    assert response.status_code == 200
    body = response.json()
    assert [item["match_id"] for item in body] == [MATCH_LOSS, MATCH_WIN, MTGO_MATCH]
    for item in body:
        assert item["digest"] == hashlib.sha256(
            canonical_json(item["payload"]).encode("utf-8")
        ).hexdigest()

    text = response.text
    for identifier in FIXTURE_IDENTIFIERS:
        assert identifier not in text, identifier
    assert str(tmp_path) not in text
    assert str(FIXTURES) not in text
    assert str(Path.home()) not in text
    assert "Match_GameLog" not in text
