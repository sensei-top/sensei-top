"""Restored (cloud_match) matches in the match list and the match-level
win-rate views (migration 073).

Ground truth, from the spec and the fixture rather than the code:

- A database holding only ``cloud_match`` rows lists them, flagged
  ``restored``, newest first, and counts them in the winrate and matchup reads.
- ``match_session.log`` (``fixture_peek.py``) holds match fa7a4d16, which the
  user won (games won by 1, 2, 1, the user being team 1): a restored row
  with that id, whatever it says, is hidden by the local match.
- A ``deck_id`` filter names a local deck, which no restored match has.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sensei_top.api import create_app
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

ARENA_FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"
CLOUD_WIN = "c10ud000-0000-4000-8000-000000000001"
CLOUD_LOSS = "c10ud000-0000-4000-8000-000000000002"


def _payload(result: str, won: int, lost: int, **changes) -> dict:
    payload = {
        "schema_version": 1,
        "played_at": "2026-10-20T21:00:00Z",
        "event": "Traditional_Ladder",
        "format": "Standard",
        "best_of": 3,
        "deck": {"name": "Cloud Deck", "main": [["Island", 60]], "side": []},
        "result": result,
        "won": won,
        "lost": lost,
        "play": "play",
        "opp": {"label": "Izzet Prowess", "key": "archetype:izzet-prowess"},
        "opp_cards": ["Island", "Mountain"],
        "duration_s": 1200,
        "unknown_cards": 0,
        "picks": {"opp": None, "mtgo": None},
    }
    payload.update(changes)
    return payload


def _insert(conn: sqlite3.Connection, match_id: str, played_at: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO cloud_match (match_id, source, played_at, payload, schema_version, "
        "updated_at) VALUES (?, 'arena', ?, ?, 1, '2026-11-01T09:30:15Z')",
        (match_id, played_at, json.dumps(payload)),
    )


@pytest.fixture
def cloud_only(tmp_path, make_client):
    path = tmp_path / "cloud.db"
    conn = open_database(path)
    _insert(conn, CLOUD_WIN, "2026-10-20T21:00:00Z", _payload("win", 2, 1))
    _insert(
        conn, CLOUD_LOSS, "2026-10-21T21:00:00Z",
        _payload("loss", 0, 2, picks={"opp": {"label": "Izzet Prowess"}}),
    )
    conn.commit()
    conn.close()
    with make_client(create_app(path)) as client:
        yield client


@pytest.fixture
def local_and_cloud(tmp_path, make_client):
    path = tmp_path / "both.db"
    conn = open_database(path)
    ingest_file(conn, ARENA_FIXTURE, locale_hint="mdy")
    project(conn)
    _insert(conn, MATCH_WIN, "2026-10-20T21:00:00Z", _payload("loss", 0, 2))
    conn.commit()
    conn.close()
    with make_client(create_app(path)) as client:
        yield client


def test_a_database_with_only_cloud_rows_lists_them_newest_first(cloud_only):
    rows = cloud_only.get("/api/matches?source=all").json()
    assert [r["match_id"] for r in rows] == [CLOUD_LOSS, CLOUD_WIN]
    assert all(r["restored"] is True for r in rows)
    win = rows[1]
    assert (win["result"], win["games_won"], win["games_lost"]) == ("win", 2, 1)
    assert (win["deck_name"], win["deck_id"], win["format"]) == ("Cloud Deck", None, "Standard")
    assert (win["opponent_label"], win["opponent_key"]) == (
        "Izzet Prowess", "archetype:izzet-prowess",
    )
    assert win["opponent_cards_seen"] == 2
    assert (win["opponent_source"], win["opponent_confidence"]) == ("archetype", "unknown")
    # The user's own opponent pick is a manual, high-confidence answer.
    picked = rows[0]
    assert (picked["opponent_source"], picked["opponent_confidence"]) == ("manual", "high")
    assert win["ended_at"] is None and win["rank_class"] is None


def test_a_colours_read_is_not_presented_as_a_named_deck(tmp_path, make_client):
    path = tmp_path / "colors.db"
    conn = open_database(path)
    _insert(
        conn, CLOUD_WIN, "2026-10-20T21:00:00Z",
        _payload("win", 2, 1, opp={"label": "UR · Card", "key": "colors:UR · Card"}),
    )
    _insert(conn, CLOUD_LOSS, "2026-10-21T21:00:00Z", _payload("loss", 0, 2, opp=None))
    conn.commit()
    conn.close()
    with make_client(create_app(path)) as client:
        rows = {r["match_id"]: r for r in client.get("/api/matches?source=all").json()}
    assert (rows[CLOUD_WIN]["opponent_source"], rows[CLOUD_WIN]["opponent_confidence"]) == (
        "colors", "unknown",
    )
    assert (rows[CLOUD_LOSS]["opponent_source"], rows[CLOUD_LOSS]["opponent_key"]) == (
        "unknown", "unknown",
    )


def test_the_list_honours_the_source_filter_and_the_limit(cloud_only):
    assert len(cloud_only.get("/api/matches").json()) == 2  # arena is the default
    assert cloud_only.get("/api/matches?source=mtgo").json() == []
    rows = cloud_only.get("/api/matches?source=all&limit=1").json()
    assert [r["match_id"] for r in rows] == [CLOUD_LOSS]


def test_a_deck_filter_leaves_restored_matches_out(cloud_only):
    assert len(cloud_only.get("/api/matches?source=all").json()) == 2  # present unfiltered
    assert cloud_only.get("/api/matches?source=all&deck_id=anything").json() == []


def test_restored_matches_count_in_the_deck_winrate(cloud_only):
    rows = cloud_only.get("/api/metrics/winrate").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["deck_name"] == "Cloud Deck"
    assert (row["deck_key"], row["versions"]) == ("cloud:Cloud Deck", 0)
    assert (row["matches_completed"], row["matches_won"]) == (2, 1)
    assert (row["games_won"], row["games_lost"]) == (2, 3)
    assert row["winrate"] == 0.5


def test_restored_matches_count_in_the_matchups(cloud_only):
    rows = cloud_only.get("/api/metrics/matchups").json()
    assert len(rows) == 1
    row = rows[0]
    assert (row["opponent_key"], row["opponent_label"]) == (
        "archetype:izzet-prowess", "Izzet Prowess",
    )
    assert (row["matches_completed"], row["matches_won"]) == (2, 1)
    assert row["format"] == "Standard"


def test_a_local_match_with_the_same_id_hides_the_restored_one(local_and_cloud):
    rows = [
        r for r in local_and_cloud.get("/api/matches?source=all").json()
        if r["match_id"] == MATCH_WIN
    ]
    assert len(rows) == 1
    assert rows[0]["restored"] is False
    assert rows[0]["result"] == "win"  # the user's own log, not the cloud's "loss"


def test_a_hidden_restored_match_is_not_counted_either(local_and_cloud):
    rows = local_and_cloud.get("/api/metrics/matchups").json()
    assert all(r["opponent_key"] != "archetype:izzet-prowess" for r in rows)


def test_the_heartbeat_counts_restored_matches_apart_from_local_ones(cloud_only):
    live = cloud_only.get("/api/live").json()
    assert (live["matches"], live["restored_matches"]) == (0, 2)


def test_the_heartbeat_does_not_count_a_hidden_restored_match(local_and_cloud):
    assert local_and_cloud.get("/api/live").json()["restored_matches"] == 0
