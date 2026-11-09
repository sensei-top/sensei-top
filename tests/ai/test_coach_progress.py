"""The coach's two evidence-building GETs, ``/api/coach`` and
``/api/coach/narrative``, recording their stages under ``?progress=``
(``api/progress.py``; docs/coach.md, "Stage progress").

The database is synthetic, built against the projected schema the way
tests/ai/test_coach_api.py builds its own: the expected count is the number
of matches inserted here (rule 8), never a first run of the code.
"""

from __future__ import annotations

import uuid

import pytest

from sensei_top import claude_config as llm_config_module
from sensei_top.ai.coach import evidence as evidence_module
from sensei_top.ai.coach import narrative as narrative_module
from sensei_top.ai.coach.store import write_coach_report
from sensei_top.ai.llm import client as llm_client_module
from sensei_top.ai.llm.client import Completion
from sensei_top.api import create_app
from sensei_top.claude_config import LLMConfig
from sensei_top.db import open_database

# Ten completed Standard ladder matches: exactly MIN_SAMPLE, every one in
# the coach's population, so each is one match reported.
POPULATION = 10


def _insert_match(conn, match_id, result, started_at):
    """A ladder ``event_id`` and a format, so the match is in the coach's
    population; one game whose result matches the match's."""
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, source, format) VALUES (?, 'Traditional_Ladder', NULL, "
        "1, 2, 'OPPCLIENTID0001', 'OppPlayerOne', ?, ?, ?, 1, 0, 'r', 'arena', 'Standard')",
        (match_id, started_at, started_at, result),
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 6, 0, 0)",
        (match_id, result),
    )


def _db(tmp_path, *, previous_report: bool = False):
    db_path = tmp_path / "coach.db"
    conn = open_database(db_path)
    for i in range(POPULATION):
        _insert_match(
            conn, f"m{i}", "win" if i % 2 == 0 else "loss", f"2026-01-{10 + i:02d}T00:00:00",
        )
    if previous_report:
        # Written before every match above, with a leak code to look for, so
        # the narrative's "since your last report" lines read a report for
        # each of them, after the evidence.
        write_coach_report(
            conn, format="Standard", prose="## Focus areas\nEarlier.", prompt="p",
            model="pasted", sources=[], context_hash="h",
            metrics={"version": 2, "fmt": "Standard", "as_of": "2026-01-01T00:00:00",
                     "leaks": [{"code": "mana_screwed"}]},
        )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def client(tmp_path, make_client):
    with make_client(create_app(_db(tmp_path))) as c:
        yield c


@pytest.fixture
def recorded(client):
    return _spy(client)


def _spy(client):
    """Every ``record`` call the app's registry receives, in order, still
    passed through to the real registry."""
    registry = client.app.state.progress
    calls: list[tuple[str, str, int | None, int | None]] = []
    real = registry.record

    def spy(key, stage, done=None, total=None):
        calls.append((key, stage, done, total))
        real(key, stage, done, total)

    registry.record = spy
    return calls


def _stages(calls) -> list[str]:
    """The stage ids in order, a repeat (a count moving on) folded away."""
    out: list[str] = []
    for _key, stage, _done, _total in calls:
        if not out or out[-1] != stage:
            out.append(stage)
    return out


def _assert_three_stages(client, calls, progress):
    assert {call[0] for call in calls} == {progress}
    assert _stages(calls) == ["matches", "field", "together"]
    counted = [(done, total) for _k, _stage, done, total in calls if total is not None]
    assert all(stage == "matches" for _k, stage, _d, total in calls if total is not None)
    assert counted == [(n, POPULATION) for n in range(POPULATION + 1)]
    body = client.get(f"/api/progress/{progress}").json()
    assert body == {"stage": "together", "done": None, "total": None}


@pytest.mark.parametrize("path", ["/api/coach", "/api/coach/narrative"])
def test_a_coach_get_records_its_three_stages_in_order(client, recorded, path):
    progress = str(uuid.uuid4())
    assert client.get(path, params={"progress": progress}).status_code == 200
    _assert_three_stages(client, recorded, progress)


def test_the_reports_since_the_last_one_are_the_evidences_own(
    tmp_path, make_client, monkeypatch,
):
    """Every match is newer than the stored report, so ``progress_since``
    reads all ten reports, and finds each in the cache the evidence filled:
    it adds no key to it and builds no report, and so no count after
    ``together``."""
    seen: list[tuple[int, set, set, int]] = []
    real = narrative_module.progress_since
    real_build = evidence_module.build_match_report

    def spy(conn, metrics, *, source="all", report_cache=None):
        assert report_cache is not None
        before = set(report_cache)
        builds = 0

        def counting_build(*args, **kwargs):
            nonlocal builds
            builds += 1
            return real_build(*args, **kwargs)

        # Only around progress_since, so the evidence build before it is
        # not counted.
        evidence_module.build_match_report = counting_build
        try:
            lines = real(conn, metrics, source=source, report_cache=report_cache)
        finally:
            evidence_module.build_match_report = real_build
        seen.append((len(before), before, set(report_cache), builds))
        return lines

    monkeypatch.setattr(narrative_module, "progress_since", spy)
    with make_client(create_app(_db(tmp_path, previous_report=True))) as client:
        calls = _spy(client)
        progress = str(uuid.uuid4())
        resp = client.get("/api/coach/narrative", params={"progress": progress})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        _assert_three_stages(client, calls, progress)

    [(size, before, after, builds)] = seen
    assert size >= POPULATION
    assert after == before
    assert builds == 0


@pytest.mark.parametrize("path", ["/api/coach", "/api/coach/narrative"])
def test_a_coach_get_answers_the_same_with_and_without_progress(client, path):
    plain = client.get(path).json()
    with_progress = client.get(path, params={"progress": str(uuid.uuid4())}).json()
    assert with_progress == plain


@pytest.mark.parametrize("path", ["/api/coach", "/api/coach/narrative"])
def test_a_progress_that_is_not_a_uuid_is_ignored(client, recorded, path):
    assert client.get(path, params={"progress": "nope"}).status_code == 200
    assert recorded == []


def test_below_the_minimum_only_the_first_stage_is_recorded(tmp_path, make_client):
    db_path = tmp_path / "empty.db"
    open_database(db_path).close()
    with make_client(create_app(db_path)) as client:
        calls = _spy(client)
        progress = str(uuid.uuid4())
        body = client.get("/api/coach", params={"progress": progress}).json()
        assert body["sufficient"] is False
        assert [(stage, done, total) for _k, stage, done, total in calls] == [
            ("matches", None, None),
        ]


def test_the_metered_post_records_no_progress(monkeypatch, client, recorded):
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: LLMConfig(api_key="k"))

    def _fake_write_report(prompt, *, cfg, label, allowed_domains, max_searches=8):
        return Completion(
            text="## Focus areas\nReport.", model=cfg.model, input_tokens=10,
            output_tokens=10, cost_usd=0.001, citations=(), web_search_requests=0,
        )

    monkeypatch.setattr(llm_client_module, "write_report", _fake_write_report)
    progress = str(uuid.uuid4())
    resp = client.post("/api/coach/narrative", params={"progress": progress})
    assert resp.status_code == 200
    assert recorded == []
    assert client.get(f"/api/progress/{progress}").status_code == 404
