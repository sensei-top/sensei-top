"""``PUT /api/sync/pulled``: rows pulled from the user's cloud backup.

Ground truth, read from the fixtures rather than from running the route:

- ``match_session.log`` (``fixture_peek.py``) holds two Arena matches,
  fd5624a4 and fa7a4d16; ``mtgo_match_session.log`` one MTGO match, named by
  its file. All three are local matches once projected.
- ``mtgo_deck_double_faced.dek`` names eight two-faced cards by their front
  face (Beyeen Veil, Jwari Disruption, Sea Gate Restoration, ...), where
  ``mtgo_deck_cards.json`` has each one's full ``Front // Back`` name, which
  is the name a payload carries.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from sensei_top.api import create_app
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.reader.mtgo_decks import ingest_deck_dir
from sensei_top.sync import build_payloads, canonical_json

FIXTURES = Path(__file__).parent / "fixtures"
ARENA_FIXTURE = FIXTURES / "match_session.log"
MTGO_SOURCE_FILE = "Match_GameLog_f2244feb-54e1-48ec-b3c5-711b20844adf.dat"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"
MTGO_MATCH = "f2244feb-54e1-48ec-b3c5-711b20844adf"
CLOUD_ONLY = "c10ud000-0000-4000-8000-000000000001"
DECK_FILES = {"Sample": "sample", "Faced": "double_faced", "Adventure": "adventure"}


def _build(path: Path) -> Path:
    """The Arena fixture, the MTGO fixture and three MTGO deck files,
    projected, with no pick."""
    conn = open_database(path)
    conn.executemany(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (:grp_id, :name, :type_line)",
        json.loads((FIXTURES / "mtgo_deck_cards.json").read_text(encoding="utf-8")),
    )
    ingest_file(conn, ARENA_FIXTURE, locale_hint="mdy")
    data = (FIXTURES / "mtgo_match_session.log").read_bytes()
    logged_at = "2026-09-14T12:42:37"
    conn.execute(
        """
        INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, ?, 'event', 'MtgoGameLog', ?, 'mtgo')
        """,
        (
            hashlib.sha256(f"{MTGO_SOURCE_FILE}:{logged_at}:{len(data)}".encode()).hexdigest(),
            MTGO_SOURCE_FILE,
            logged_at,
            base64.b64encode(data).decode("ascii"),
        ),
    )
    conn.commit()
    decks = path.parent / f"{path.stem}-decks"
    decks.mkdir()
    for name, source in DECK_FILES.items():
        shutil.copy(FIXTURES / f"mtgo_deck_{source}.dek", decks / f"{name}.dek")
    ingest_deck_dir(conn, decks)
    project(conn)
    conn.close()
    return path


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    return _build(tmp_path / "pull.db")


@pytest.fixture
def client(db_path, make_client):
    with make_client(create_app(db_path)) as c:
        yield c


def _query(db_path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return [tuple(row) for row in conn.execute(sql, params)]
    finally:
        conn.close()


def _deck_id(db_path: Path, name: str) -> str:
    ((deck_id,),) = _query(db_path, "SELECT deck_id FROM decks WHERE name = ?", (name,))
    return deck_id


def _payload(**changes) -> dict:
    """A payload in phase-one shape for a match this install never saw."""
    payload = {
        "schema_version": 1,
        "played_at": "2026-10-20T21:00:00Z",
        "event": "Traditional_Ladder",
        "format": "Standard",
        "best_of": 3,
        "deck": {"name": "Some Deck", "main": [["Island", 60]], "side": []},
        "result": "win",
        "won": 2,
        "lost": 1,
        "play": "play",
        "opp": None,
        "opp_cards": [],
        "duration_s": 1200,
        "unknown_cards": 0,
        "picks": {"opp": None, "mtgo": None},
    }
    payload.update(changes)
    return payload


def _row(match_id: str, payload: dict, **fields) -> dict:
    row = {
        "match_id": match_id,
        "source": "arena",
        "played_at": "2026-10-20T21:00:00+00:00",
        "payload": payload,
        "schema_version": 1,
        "updated_at": "2026-11-01T09:30:15.123456+00:00",
        "deleted_at": None,
    }
    row.update(fields)
    return row


def _pull(client, *rows: dict) -> dict:
    response = client.put("/api/sync/pulled", json={"items": list(rows)})
    assert response.status_code == 200, response.text
    return response.json()


# --- cloud_match -------------------------------------------------------------


def test_a_match_pulled_twice_is_one_row_holding_the_second(client, db_path):
    first = _pull(client, _row(CLOUD_ONLY, _payload()))
    second_payload = _payload(result="loss", won=1, lost=2)
    second = _pull(
        client,
        _row(CLOUD_ONLY, second_payload, updated_at="2026-11-02T08:00:00-03:00"),
    )
    assert first == second == {"stored": 1, "removed": 0, "local": 0, "picks": 0}
    assert _query(
        db_path,
        "SELECT match_id, source, played_at, payload, schema_version, updated_at "
        "FROM cloud_match",
    ) == [
        (
            CLOUD_ONLY, "arena", "2026-10-20T21:00:00Z", canonical_json(second_payload), 1,
            "2026-11-02T11:00:00Z",
        )
    ]


def test_a_soft_deleted_row_removes_the_restored_copy(client, db_path):
    _pull(client, _row(CLOUD_ONLY, _payload()))
    written = _pull(
        client, _row(CLOUD_ONLY, _payload(), deleted_at="2026-11-02T10:00:00+00:00")
    )
    assert written == {"stored": 0, "removed": 1, "local": 0, "picks": 0}
    assert _query(db_path, "SELECT COUNT(*) FROM cloud_match") == [(0,)]


def test_a_soft_deleted_row_never_touches_a_local_match(client, db_path):
    written = _pull(
        client, _row(MATCH_WIN, _payload(), deleted_at="2026-11-02T10:00:00+00:00")
    )
    assert written == {"stored": 0, "removed": 0, "local": 0, "picks": 0}
    assert _query(db_path, "SELECT COUNT(*) FROM matches WHERE match_id = ?", (MATCH_WIN,)) == [
        (1,)
    ]


def test_a_local_raw_event_match_is_never_written_into_cloud_match(client, db_path):
    written = _pull(client, _row(MATCH_WIN, _payload()), _row(MTGO_MATCH, _payload()))
    assert written == {"stored": 0, "removed": 0, "local": 2, "picks": 0}
    assert _query(db_path, "SELECT COUNT(*) FROM cloud_match") == [(0,)]


# --- picks on a local match --------------------------------------------------


def _set_local_opponent_pick(db_path: Path, updated_at: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, archetype_key, updated_at) "
        "VALUES (?, 'Rogue', NULL, ?)",
        (MATCH_WIN, updated_at),
    )
    conn.commit()
    conn.close()


def _opponent_pick(updated_at: str) -> dict:
    return {
        "opp": {"label": "Izzet  Prowess", "archetype_key": "izzet-prowess",
                "updated_at": updated_at},
        "mtgo": None,
    }


def _local_opponent_pick(db_path: Path) -> list[tuple]:
    return _query(
        db_path,
        "SELECT label, archetype_key, updated_at FROM opponent_deck_override "
        "WHERE match_id = ?",
        (MATCH_WIN,),
    )


@pytest.mark.parametrize("pulled_at", ["2026-09-30T23:59:59Z", "2026-10-01T10:00:00Z"])
def test_an_older_or_equal_pulled_opponent_pick_keeps_the_local_one(
    client, db_path, pulled_at
):
    _set_local_opponent_pick(db_path, "2026-10-01T10:00:00Z")
    written = _pull(client, _row(MATCH_WIN, _payload(picks=_opponent_pick(pulled_at))))
    assert written["picks"] == 0
    assert _local_opponent_pick(db_path) == [("Rogue", None, "2026-10-01T10:00:00Z")]


def test_a_newer_pulled_opponent_pick_wins_and_keeps_its_time(client, db_path):
    _set_local_opponent_pick(db_path, "2026-10-01T10:00:00Z")
    written = _pull(
        client, _row(MATCH_WIN, _payload(picks=_opponent_pick("2026-10-01T10:00:01Z")))
    )
    assert written == {"stored": 0, "removed": 0, "local": 1, "picks": 1}
    assert _local_opponent_pick(db_path) == [
        ("Izzet Prowess", "izzet-prowess", "2026-10-01T10:00:01Z")
    ]


def test_a_pulled_opponent_pick_with_no_local_one_is_written(client, db_path):
    _pull(client, _row(MATCH_WIN, _payload(picks=_opponent_pick("2026-10-01T10:00:00Z"))))
    assert _local_opponent_pick(db_path) == [
        ("Izzet Prowess", "izzet-prowess", "2026-10-01T10:00:00Z")
    ]


def test_a_pulled_mtgo_pick_finds_its_two_faced_deck_by_its_board(
    tmp_path, db_path, client
):
    """Another install picked the Faced deck for the MTGO match and pushed
    its payload; this one, with the same deck files and no pick, pulls it."""
    other = _build(tmp_path / "other.db")
    conn = sqlite3.connect(other)
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format, updated_at) "
        "VALUES (?, ?, 'Modern', '2026-10-05T18:20:00Z')",
        (MTGO_MATCH, _deck_id(other, "Faced")),
    )
    conn.commit()
    (pushed,) = [p for p in build_payloads(conn) if p.match_id == MTGO_MATCH]
    conn.close()

    written = _pull(client, _row(MTGO_MATCH, pushed.payload, source="mtgo"))
    assert written == {"stored": 0, "removed": 0, "local": 1, "picks": 1}
    assert _query(
        db_path,
        "SELECT deck_id, format, updated_at FROM mtgo_match_pick WHERE match_id = ?",
        (MTGO_MATCH,),
    ) == [(_deck_id(db_path, "Faced"), "Modern", "2026-10-05T18:20:00Z")]


def test_a_newer_mtgo_pick_whose_deck_is_not_here_is_skipped(client, db_path, caplog):
    sample = _deck_id(db_path, "Sample")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format, updated_at) "
        "VALUES (?, ?, 'Pioneer', '2026-10-01T10:00:00Z')",
        (MTGO_MATCH, sample),
    )
    conn.commit()
    conn.close()
    picks = {"opp": None, "mtgo": {"format": "Modern", "updated_at": "2026-10-02T10:00:00Z"}}

    written = _pull(client, _row(MTGO_MATCH, _payload(picks=picks), source="mtgo"))
    assert written["picks"] == 0
    assert _query(
        db_path,
        "SELECT deck_id, format, updated_at FROM mtgo_match_pick WHERE match_id = ?",
        (MTGO_MATCH,),
    ) == [(sample, "Pioneer", "2026-10-01T10:00:00Z")]
    assert "MTGO pick names 0 local decks" in caplog.text
