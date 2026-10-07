"""Rank projection: migrations/023_rank_snapshot.sql and
Projector._handle_rank_response in projector/matches.py.

``tests/fixtures/rank_session.log`` is one real RankGetCombinedRankInfo
response, reconstructed in the exact three-line shape
``reader/segmenter.py``'s own module docstring documents for a bare
response entry (header line, ``<==`` line, JSON payload) — verified to parse
to the same kind/label/timestamp a live capture produces before being
committed as a fixture. The JSON payload itself is the real field values
read via fixture_peek.py against the user's own Player.log on 2026-09-01
(season 93, Platinum 4, step 2, 2-1); the response UUID is a placeholder,
since a correlation id carries no information this feature reads. Rank
responses carry no player-identifying data at all (bare integers and a
class name), unlike a match capture, so nothing here needed scrubbing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "rank_session.log"


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "r.db")
    ingest_file(c, FIXTURE, locale_hint="mdy")
    yield c
    c.close()


def test_a_rank_response_becomes_one_snapshot_with_the_real_fixture_values(conn):
    project(conn)
    rows = conn.execute("SELECT * FROM rank_snapshot").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["observed_at"] == "2026-09-01T16:17:05"
    assert row["constructed_class"] == "Platinum"
    assert row["constructed_level"] == 4
    assert row["constructed_step"] == 2
    assert row["constructed_season"] == 93
    assert row["constructed_matches_won"] == 2
    assert row["constructed_matches_lost"] == 1


def test_a_rebuild_does_not_duplicate_rank_snapshots(conn):
    """project() is always a full rebuild (AGENTS.md rule 3) — rank rows are
    no exception, even though they carry no foreign key to a match."""
    project(conn)
    project(conn)
    assert conn.execute("SELECT COUNT(*) FROM rank_snapshot").fetchone()[0] == 1
