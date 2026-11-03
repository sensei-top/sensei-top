"""The leak finder's narrative routes: ``GET``, ``POST`` and ``PUT`` on
``/api/review/leaks/narrative``, served by ``ai/routes/leaks.py``.

Moved by test, bodies unchanged, from ``test_api.py``, ``test_api_paste.py``,
``test_answers.py`` and ``test_llm.py``; the fixtures and helpers they stood
on there are repeated here, so this file needs nothing from those."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from sensei_top.ai.llm import client as llm_client_module
from sensei_top.ai.llm import config as llm_config_module
from sensei_top.ai.llm.client import Completion
from sensei_top.ai.llm.config import LLMConfig
from sensei_top.ai.review.leaks_store import read_leaks_narrative
from sensei_top.ai.routes import leaks as leaks_routes
from sensei_top.api.app import create_app
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.review.leaks import Leak

FIXTURE = Path(__file__).parent.parent / "fixtures" / "match_session.log"
LEAKS_PATH = "/api/review/leaks/narrative"
OLDER = "0" * 64
EMPTY_PROSE = "The answer has no text in it."
BIG = {"answer": "x" * (256 * 1024 + 1)}
PROSE_TAIL_SENTENCE = (
    'Put the whole text in "prose" as a single JSON string: write each line\n'
    'break as \\n and each quotation mark as \\".'
)
CONTRACT_OPENING = "Answer with exactly one JSON object and nothing else"


@pytest.fixture(autouse=True)
def no_model_call(monkeypatch):
    """A paste route never reaches a model: any call fails the test. The
    tests that fake the model patch ``write_prose`` after this."""
    def boom(*a, **k):
        raise AssertionError("a PUT must not call a model")

    for name in ("write_json", "write_prose", "write_report"):
        if hasattr(llm_client_module, name):
            monkeypatch.setattr(llm_client_module, name, boom)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "api.db"
    conn = open_database(path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    return path


@pytest.fixture
def client(db_path, make_client):
    with make_client(create_app(db_path)) as c:
        yield c


def _fake_leak() -> Leak:
    return Leak(
        code="mana_screwed", category="deckbuilding", sample_title="Stuck on lands",
        n_with=15, win_rate_with=0.3, ci_with=(0.15, 0.5),
        n_without=40, win_rate_without=0.55, ci_without=(0.4, 0.7),
        gap=0.25, match_ids_with=("m1",),
    )


@pytest.fixture
def leaky(monkeypatch):
    """One leak, so the training plan has a prompt; the fixture's single match
    is below the leak finder's own sample."""
    leak = _fake_leak()
    monkeypatch.setattr(leaks_routes, "find_leaks", lambda conn, **kwargs: [leak])


def _db(client):
    conn = sqlite3.connect(client.app.state.database)
    conn.row_factory = sqlite3.Row
    return conn


def _count(client, table):
    conn = _db(client)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _header(prompt: str) -> dict:
    """The header lines at the end of a copied prompt, as an assistant
    copies them back."""
    out = {}
    for name in ("for", "context"):
        m = re.search(rf'^  "{name}": ("[^"]*"),?$', prompt, re.MULTILINE)
        if m:
            out[name] = json.loads(m.group(1))
    return out


def _answer(prompt: str, body: dict, **header) -> str:
    return json.dumps({**_header(prompt), **header, "answer": body})


def _prose(text):
    return {"prose": text}


def _fake_prose_writer(sent: list):
    def write(prompt, *, cfg, label):
        sent.append(prompt)
        return Completion(
            text="Some prose.", model="claude-opus-5", input_tokens=1, output_tokens=1,
            cost_usd=0.001,
        )

    return write


def _assert_prose_contract(copied: str, sent: str, for_: str, context: str, description: str):
    """The copied prompt is the generate path's prompt, then ``---``, then the
    contract with this card's own header; the generate path's carries none."""
    assert CONTRACT_OPENING not in sent
    assert '"prose"' not in sent
    assert copied.startswith(sent + "\n\n---\n\n" + CONTRACT_OPENING)
    assert f'  "for": {json.dumps(for_)},\n  "context": "{context}",\n' in copied
    assert f'"description": "{description}"' in copied
    assert copied.count(CONTRACT_OPENING) == 1
    assert copied.endswith(PROSE_TAIL_SENTENCE)


def test_review_leaks_narrative_is_no_report_when_there_is_nothing_to_synthesize(client):
    body = client.get(LEAKS_PATH).json()
    assert body["status"] == "no_report"


def test_generate_leaks_narrative_stores_and_returns_it(monkeypatch, client, leaky):
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(
        llm_client_module, "write_prose",
        lambda prompt, *, cfg, label: Completion(
            text="Work on mulligans.", model="claude-opus-5",
            input_tokens=300, output_tokens=100, cost_usd=0.004,
        ),
    )

    resp = client.post(LEAKS_PATH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["narrative"] == "Work on mulligans."

    again = client.get(LEAKS_PATH).json()
    assert again["status"] == "ok"
    assert again["narrative"] == "Work on mulligans."


def test_the_leak_plan_prompt_asks_for_prose_and_the_call_does_not(
    monkeypatch, client, db_path, leaky,
):
    sent: list = []
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(llm_client_module, "write_prose", _fake_prose_writer(sent))
    assert client.post(LEAKS_PATH).status_code == 200

    conn = open_database(db_path)
    try:
        stored = read_leaks_narrative(conn)
    finally:
        conn.close()
    body = client.get(LEAKS_PATH).json()
    assert body["stale"] is False
    _assert_prose_contract(body["prompt"], sent[0], "leaks", stored.context_hash, "plain prose")
    assert stored.prompt == sent[0]


def test_leaks_paste_stores_and_the_get_serves_it(client, leaky):
    before = client.get(LEAKS_PATH).json()
    assert before["status"] == "prompt"
    prompt = before["prompt"]
    header = _header(prompt)
    assert header["for"] == "leaks"
    text = "Count your lands before keeping."

    resp = client.put(LEAKS_PATH, json={"answer": _answer(prompt, _prose(text))})
    assert resp.status_code == 200
    out = resp.json()
    assert (out["status"], out["narrative"], out["model"]) == ("ok", text, "pasted")
    assert out["cost_usd"] is None
    assert out["stale"] is False
    assert client.get(LEAKS_PATH).json() == out

    conn = _db(client)
    row = conn.execute("SELECT * FROM leaks_narrative").fetchone()
    conn.close()
    assert row["model"] == "pasted"
    assert row["context_hash"] == header["context"]
    assert row["input_tokens"] is None and row["cost_usd"] is None
    assert row["prompt"] == prompt


def test_leaks_paste_written_for_older_evidence_is_stored_stale(client, leaky):
    prompt = client.get(LEAKS_PATH).json()["prompt"]
    resp = client.put(
        LEAKS_PATH, json={"answer": _answer(prompt, _prose("Old plan."), context=OLDER)},
    )
    assert resp.status_code == 200
    assert resp.json()["stale"] is True
    assert client.get(LEAKS_PATH).json()["stale"] is True
    conn = _db(client)
    assert conn.execute("SELECT context_hash FROM leaks_narrative").fetchone()[0] == OLDER
    conn.close()


@pytest.mark.parametrize("make", [
    pytest.param(lambda p: json.dumps(_prose("Fine prose.")), id="headerless"),
    pytest.param(
        lambda p: _answer(p, _prose("x"), **{"for": "match:abc"}), id="another-card",
    ),
    pytest.param(lambda p: _answer(p, _prose("  ")), id="empty-prose"),
])
def test_leaks_paste_that_does_not_read_is_422_and_stores_nothing(client, leaky, make):
    prompt = client.get(LEAKS_PATH).json()["prompt"]
    resp = client.put(LEAKS_PATH, json={"answer": make(prompt)})
    assert resp.status_code == 422
    assert _count(client, "leaks_narrative") == 0


def test_leaks_paste_with_empty_prose_says_so(client, leaky):
    prompt = client.get(LEAKS_PATH).json()["prompt"]
    resp = client.put(LEAKS_PATH, json={"answer": _answer(prompt, _prose(""))})
    assert resp.json()["detail"] == EMPTY_PROSE


def test_leaks_paste_over_256_kb_is_413(client, leaky):
    assert client.put(LEAKS_PATH, json=BIG).status_code == 413
    assert _count(client, "leaks_narrative") == 0


def test_leaks_paste_with_nothing_to_plan_from_is_404_and_413_comes_first(client):
    # The fixture's one match is below the leak finder's sample: no leaks.
    assert client.get(LEAKS_PATH).json()["status"] == "no_report"
    assert client.put(LEAKS_PATH, json={"answer": "{}"}).status_code == 404
    assert client.put(LEAKS_PATH, json=BIG).status_code == 413
    assert _count(client, "leaks_narrative") == 0
