"""/api/metrics/matchups groups by (format, opponent_key)
(migrations/058_matchup_format.sql).

The schema is built directly, as test_match_formats.py does. Every opponent is
named by a manual override, so they share the key 'manual:Rakdos Midrange'
without any classifier run. The expected counts are read off the seeded rows:

  match   format    result  games
  std-1   Standard  win     2-0
  std-2   Standard  loss    1-2
  std-3   Standard  win     2-1
  mod-1   Modern    loss    0-2
  mod-2   Modern    loss    1-2
  none-1  (null)    win     2-0

Standard: 3 completed, 2 won, games 5-3. Modern: 2 completed, 0 won, games 1-4.
No format: 1 completed, 1 won, games 2-0.
"""

from __future__ import annotations

import pytest

from sensei_top.api import create_app
from sensei_top.db import open_database

_DECK = "deck-a"
_KEY = "manual:Rakdos Midrange"

_MATCHES = [
    ("std-1", "Standard", "win", 2, 0),
    ("std-2", "Standard", "loss", 1, 2),
    ("std-3", "Standard", "win", 2, 1),
    ("mod-1", "Modern", "loss", 0, 2),
    ("mod-2", "Modern", "loss", 1, 2),
    ("none-1", None, "win", 2, 0),
]


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "matchups.db"
    conn = open_database(path)
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json) VALUES (?, 'Deck A', '{}')", (_DECK,)
    )
    for i, (match_id, fmt, result, won, lost) in enumerate(_MATCHES):
        conn.execute(
            "INSERT INTO matches (match_id, deck_id, started_at, result, games_won,"
            " games_lost, source, format) VALUES (?, ?, ?, ?, ?, ?, 'arena', ?)",
            (match_id, _DECK, f"2026-09-30T10:0{i}:00", result, won, lost, fmt),
        )
        conn.execute(
            "INSERT INTO opponent_deck_override (match_id, label) VALUES (?, 'Rakdos Midrange')",
            (match_id,),
        )
    conn.commit()
    conn.close()
    return path


def test_one_opponent_key_is_one_row_per_format(db_path, make_client):
    with make_client(create_app(db_path)) as c:
        rows = c.get("/api/metrics/matchups").json()

    got = {
        r["format"]: (r["matches_completed"], r["matches_won"], r["games_won"], r["games_lost"])
        for r in rows
    }
    assert {r["opponent_key"] for r in rows} == {_KEY}
    assert len(rows) == 3
    assert got == {
        "Standard": (3, 2, 5, 3),
        "Modern": (2, 0, 1, 4),
        None: (1, 1, 2, 0),
    }


def test_each_format_row_carries_its_own_formats_label(tmp_path, make_client):
    """One archetype key, named "Dimir Midrange" on Standard matches and
    "Dimir Frog" on Modern ones. The Modern match has the lowest match_id, so
    a label chosen per key alone (ties broken by match_id) gives both rows the
    Modern name."""
    path = tmp_path / "labels.db"
    conn = open_database(path)
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json) VALUES (?, 'Deck A', '{}')", (_DECK,)
    )
    seeded = [
        ("a-mod", "Modern", "Dimir Frog"),
        ("b-std", "Standard", "Dimir Midrange"),
        ("c-std", "Standard", "Dimir Midrange"),
    ]
    for i, (match_id, fmt, label) in enumerate(seeded):
        conn.execute(
            "INSERT INTO matches (match_id, deck_id, started_at, result, games_won,"
            " games_lost, source, format) VALUES (?, ?, ?, 'win', 2, 0, 'arena', ?)",
            (match_id, _DECK, f"2026-09-30T10:0{i}:00", fmt),
        )
        conn.execute(
            "INSERT INTO opponent_archetype (match_id, format, archetype_key, archetype_name,"
            " label, method, confidence, cards_seen, conditions_met, conditions_unknown,"
            " evidence_json, classified_at)"
            " VALUES (?, ?, 'dimir', ?, ?, 'archetype', 'high', 5, 1, 0, '{}',"
            " '2026-09-30T12:00:00Z')",
            (match_id, fmt, label, label),
        )
    conn.commit()
    conn.close()

    with make_client(create_app(path)) as c:
        rows = c.get("/api/metrics/matchups").json()

    assert {r["opponent_key"] for r in rows} == {"archetype:dimir"}
    assert {r["format"]: (r["opponent_label"], r["matches_completed"]) for r in rows} == {
        "Standard": ("Dimir Midrange", 2),
        "Modern": ("Dimir Frog", 1),
    }
