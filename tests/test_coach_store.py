"""Tests for coach/store.py: the coach report's own history, and the
progress-review helper that reads a report's prose back apart."""

from __future__ import annotations

import pytest

from sensei_top import db
from sensei_top.coach.store import (
    extract_focus_section,
    latest_coach_report,
    list_coach_reports,
    read_coach_report,
    write_coach_report,
)
from sensei_top.db import open_database


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _write(conn, *, generated_at, **overrides):
    defaults = dict(
        prose="## Profile\n\nSteady.\n\n## Focus areas\n\nWork on mulligans.\n",
        prompt="the whole prompt text",
        model="claude-opus-5",
        effort="high",
        sources=[{"url": "https://example.com/a", "title": "A", "cited_text": "..."}, "R3"],
        metrics={"overall_rate": 0.55, "leaks": {"race_behind": 0.4}},
        context_hash="hash1",
        input_tokens=100,
        output_tokens=200,
        web_search_requests=2,
        cost_usd=0.05,
    )
    defaults.update(overrides)
    return write_coach_report(conn, generated_at=generated_at, **defaults)


def test_fresh_database_reaches_the_latest_schema_version_and_has_the_table(conn):
    # open_database migrates all the way to HEAD, not to 039 specifically —
    # pin against discover_migrations() rather than a version number that
    # goes stale every time a later migration lands (040
    # arena_only_current_match.sql, most recently).
    assert db.applied_version(conn) == db.discover_migrations()[-1][0]
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='coach_report'"
    ).fetchone()
    assert row is not None


def test_empty_db_latest_is_none_and_list_is_empty(conn):
    assert latest_coach_report(conn) is None
    assert list_coach_reports(conn) == []


def test_unknown_id_returns_none(conn):
    _write(conn, generated_at="2026-09-01T00:00:00.000Z")
    conn.commit()
    assert read_coach_report(conn, 999) is None


def test_list_returns_newest_first_and_latest_is_the_newest(conn):
    id1 = _write(conn, generated_at="2026-09-01T00:00:00.000Z")
    id2 = _write(conn, generated_at="2026-09-05T00:00:00.000Z")
    id3 = _write(conn, generated_at="2026-09-10T00:00:00.000Z")
    conn.commit()

    reports = list_coach_reports(conn)
    assert [r.id for r in reports] == [id3, id2, id1]

    latest = latest_coach_report(conn)
    assert latest.id == id3


def test_round_trip_preserves_every_field_including_sources_and_metrics_json(conn):
    sources = [{"url": "https://example.com/x", "title": "X", "cited_text": "quoted"}, "R1", "R7"]
    metrics = {"overall_rate": 0.5, "leaks": {"mana_screwed": 0.3}, "g1_vs_post_board": [0.6, 0.4]}
    new_id = _write(
        conn,
        generated_at="2026-09-12T00:00:00.000Z",
        sources=sources,
        metrics=metrics,
        context_hash="deadbeef",
        input_tokens=1234,
        output_tokens=5678,
        web_search_requests=3,
        cost_usd=0.42,
    )
    conn.commit()

    report = read_coach_report(conn, new_id)
    assert report.id == new_id
    assert report.generated_at == "2026-09-12T00:00:00.000Z"
    assert report.model == "claude-opus-5"
    assert report.effort == "high"
    assert report.prompt == "the whole prompt text"
    assert "Focus areas" in report.prose
    assert report.sources == sources
    assert report.metrics == metrics
    assert report.context_hash == "deadbeef"
    assert report.input_tokens == 1234
    assert report.output_tokens == 5678
    assert report.web_search_requests == 3
    assert report.cost_usd == 0.42


def test_null_cost_round_trips_as_none(conn):
    new_id = _write(conn, generated_at="2026-09-01T00:00:00.000Z", cost_usd=None)
    conn.commit()
    report = read_coach_report(conn, new_id)
    assert report.cost_usd is None


def test_extract_focus_section_heading_in_the_middle():
    prose = (
        "## Profile\n\nYou play control.\n\n"
        "## Focus areas\n\nDrill mulligans.\nAlso drill blocks.\n\n"
        "## Drills\n\nDo the thing.\n"
    )
    assert extract_focus_section(prose) == "Drill mulligans.\nAlso drill blocks."


def test_extract_focus_section_heading_last():
    prose = "## Profile\n\nYou play control.\n\n## Focus areas\n\nDrill mulligans.\n"
    assert extract_focus_section(prose) == "Drill mulligans."


def test_extract_focus_section_missing_heading_returns_whole_prose_stripped():
    prose = "\n## Profile\n\nNo focus section here.\n\n"
    assert extract_focus_section(prose) == "## Profile\n\nNo focus section here."
