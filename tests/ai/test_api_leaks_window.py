"""The leak finder's two call sites share one per-format consensus window.
Split from ``tests/test_api.py``; the narrative route is ``ai/``'s.
"""

from pathlib import Path

import pytest

from sensei_top.ai.routes import leaks as leaks_routes
from sensei_top.api import create_app
from sensei_top.api.routes import review as review_routes
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent.parent / "fixtures" / "match_session.log"


@pytest.fixture
def client(tmp_path, make_client):
    db_path = tmp_path / "api.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


def test_review_leaks_routes_pass_a_per_format_consensus_window(client, monkeypatch):
    """Both `find_leaks` call sites — the GET list route and the narrative
    route's own `build_context` — must hand over a `consensus_window`
    resolver, so each match's report is windowed by its own format's reset
    and the field record inside
    `review/analyzers/baseline.py` never pools rounds from across one
    (`docs/metagame.md`'s format-reset boundary). The window lookup is
    replaced with one that names the format it was asked for, so this pins
    that the resolver asks for the format it is given, not one fixed
    format's window."""
    calls = []

    def fake_find_leaks(conn, **kwargs):
        calls.append(kwargs)
        return []

    def fake_window(conn, fmt):
        return f"window-for-{fmt}"

    monkeypatch.setattr(review_routes, "find_leaks", fake_find_leaks)
    monkeypatch.setattr(leaks_routes, "find_leaks", fake_find_leaks)
    monkeypatch.setattr(review_routes, "_consensus_window", fake_window)

    client.get("/api/review/leaks")
    client.get("/api/review/leaks/narrative")

    assert len(calls) == 2
    for call in calls:
        assert "consensus_since" not in call
        assert call["consensus_window"]("Modern") == "window-for-Modern"
        assert call["consensus_window"]("Standard") == "window-for-Standard"
