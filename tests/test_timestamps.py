"""Every UTC value the server sends ends in ``Z`` (plan 24, D8).

The dashboard reads a bare timestamp as the log's own local clock
(``web/src/lib/time.ts::parseTimestamp``), so a UTC value that lost its
``Z`` would shift by the viewer's offset. Each producer is called and the
string it returns is checked for the suffix.
"""

import re
from datetime import UTC, datetime

from sensei_top.db import open_database
from sensei_top.llm.provenance import now_iso
from sensei_top.metagame import source, topdeck
from sensei_top.metagame.holds import apply_outcome, read_hold
from sensei_top.metagame.source import Answer, AnswerKind

UTC_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def test_provenance_now_iso_ends_in_z():
    assert UTC_STAMP.match(now_iso())


def test_raw_events_ingested_at_default_ends_in_z(tmp_path):
    conn = open_database(tmp_path / "t.db")
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(raw_events)")]
        assert "ingested_at" in cols
        default = next(
            r[4] for r in conn.execute("PRAGMA table_info(raw_events)") if r[1] == "ingested_at"
        )
        stamp = conn.execute(f"SELECT {default}").fetchone()[0]
        assert UTC_STAMP.match(stamp)
    finally:
        conn.close()


def test_metagame_hold_times_end_in_z(tmp_path):
    conn = open_database(tmp_path / "t.db")
    try:
        now = datetime(2026, 10, 5, 12, 0, 30, tzinfo=UTC)
        answer = Answer(
            kind=AnswerKind.RATE, reason="HTTP 429", at=now, http_status=429,
            place="index", retry_after=None, retry_after_s=None, first_request=True,
        )
        apply_outcome(conn, "mtgo", before=None, answer=answer, page_read=False,
                      completed=False, now=now)
        assert read_hold(conn, "mtgo") is not None
        row = conn.execute(
            "SELECT since, last_at, not_before FROM meta_fetch_hold WHERE source = 'mtgo'"
        ).fetchone()
        assert all(UTC_STAMP.match(value) for value in row)
    finally:
        conn.close()


def _fetched_at(conn, name):
    row = conn.execute(
        "SELECT fetched_at FROM meta_fetch_source WHERE source = ?", (name,)
    ).fetchone()
    assert row is not None
    return row[0]


def test_topdeck_fetched_at_ends_in_z(tmp_path, monkeypatch):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    conn = open_database(tmp_path / "t.db")
    try:
        topdeck.refresh_topdeck(
            conn, force=True, fetch=lambda **kw: [], sleep=lambda s: None,
            now=lambda: datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC),
        )
        assert UTC_STAMP.match(_fetched_at(conn, "topdeck"))
    finally:
        conn.close()


def test_fbettega_fetched_at_ends_in_z(tmp_path, monkeypatch):
    conn = open_database(tmp_path / "t.db")
    try:
        tree = [{"path": "Tournaments/MTGO/2026/08/16/standard-b.json", "type": "blob",
                 "sha": "abc123"}]
        monkeypatch.setattr(source, "resolve_commit_sha", lambda *a, **k: "c")
        monkeypatch.setattr(source, "list_tree", lambda *a, **k: tree)
        monkeypatch.setattr(
            source, "fetch_event",
            lambda commit, path: {"Tournament": {"Name": "B", "Formats": "Standard"},
                                  "Decks": [], "Rounds": [], "Standings": []},
        )
        source.refresh_metagame(conn, window_days=100000, force=True)
        assert UTC_STAMP.match(_fetched_at(conn, "fbettega"))
    finally:
        conn.close()
