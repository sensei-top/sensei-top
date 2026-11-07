"""Tests for api/progress.py: the stage-progress registry, the progress
route, and the guide GET recording its stages under ``?progress=``."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from sensei_top.api import create_app
from sensei_top.api.progress import ProgressRegistry, progress_key
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"

# The fixture's two matches, fd5624a4 and fa7a4d16, each end in a
# MatchScope_Match WinLoss result (entries 16 and 33 of match_session.log),
# so the all-decks leak population the guide reports is both of them.
COMPLETED_MATCHES = 2


@pytest.fixture
def client(tmp_path, make_client):
    db_path = tmp_path / "api.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


@pytest.fixture
def recorded(client, monkeypatch):
    """Every ``record`` call the app's registry receives, in order, still
    passed through to the real registry."""
    registry = client.app.state.progress
    calls: list[tuple[str, str, int | None, int | None]] = []
    real = registry.record

    def spy(key, stage, done=None, total=None):
        calls.append((key, stage, done, total))
        real(key, stage, done, total)

    monkeypatch.setattr(registry, "record", spy)
    return calls


def _stages(calls) -> list[str]:
    """The stage ids in order, a repeat (a count moving on) folded away."""
    out: list[str] = []
    for _key, stage, _done, _total in calls:
        if not out or out[-1] != stage:
            out.append(stage)
    return out


# --- registry ----------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_registry_answers_the_latest_stage_of_each_key():
    registry = ProgressRegistry()
    registry.record("a", "matches", 3, 10)
    registry.record("a", "field")
    registry.record("b", "matches")

    a = registry.read("a")
    assert (a.stage, a.done, a.total) == ("field", None, None)
    assert registry.read("b").stage == "matches"
    assert registry.read("c") is None


def test_an_entry_is_dropped_60_seconds_after_its_last_update():
    clock = _Clock()
    registry = ProgressRegistry(clock=clock)
    registry.record("a", "matches")
    clock.now += 40
    registry.record("a", "field")  # the 60 s count again from here
    clock.now += 59
    assert registry.read("a").stage == "field"
    clock.now += 2
    assert registry.read("a") is None


def test_the_registry_refuses_a_stage_the_page_has_no_words_for():
    with pytest.raises(ValueError):
        ProgressRegistry().record("a", "reading")


def test_no_key_means_a_reporter_that_records_nothing():
    registry = ProgressRegistry()
    registry.reporter(None)("matches", 1, 2)
    assert registry.read(None) is None


def test_progress_key_is_a_canonical_uuid_or_nothing():
    upper = "6F9619FF-8B86-D011-B42D-00C04FC964FF"
    assert progress_key(upper) == upper.lower()
    assert progress_key("not-a-uuid") is None
    assert progress_key("") is None
    assert progress_key(None) is None


# --- routes ------------------------------------------------------------------


def test_the_guide_records_its_three_stages_in_order(client, recorded):
    key = client.get("/api/guide/decks").json()[0]["key"]
    progress = str(uuid.uuid4())

    assert client.get(f"/api/guide/{key}", params={"progress": progress}).status_code == 200

    assert {call[0] for call in recorded} == {progress}
    assert _stages(recorded) == ["matches", "field", "together"]
    counted = [(done, total) for _k, stage, done, total in recorded if total is not None]
    assert all(stage == "matches" for _k, stage, _d, total in recorded if total is not None)
    assert counted == [(n, COMPLETED_MATCHES) for n in range(COMPLETED_MATCHES + 1)]

    body = client.get(f"/api/progress/{progress}").json()
    assert body == {"stage": "together", "done": None, "total": None}


def test_the_guide_answers_the_same_with_and_without_progress(client):
    key = client.get("/api/guide/decks").json()[0]["key"]
    plain = client.get(f"/api/guide/{key}").json()
    with_progress = client.get(f"/api/guide/{key}", params={"progress": str(uuid.uuid4())})
    assert with_progress.json() == plain


def test_an_upper_case_progress_id_is_read_back_lower_case(client):
    key = client.get("/api/guide/decks").json()[0]["key"]
    progress = str(uuid.uuid4())
    client.get(f"/api/guide/{key}", params={"progress": progress.upper()})
    assert client.get(f"/api/progress/{progress}").json()["stage"] == "together"


def test_a_progress_that_is_not_a_uuid_is_ignored(client, recorded):
    key = client.get("/api/guide/decks").json()[0]["key"]
    assert client.get(f"/api/guide/{key}", params={"progress": "nope"}).status_code == 200
    assert recorded == []


def test_the_progress_route_404s_an_unknown_id(client):
    assert client.get(f"/api/progress/{uuid.uuid4()}").status_code == 404


def test_the_progress_route_rejects_a_non_uuid(client):
    assert client.get("/api/progress/not-a-uuid").status_code == 422
