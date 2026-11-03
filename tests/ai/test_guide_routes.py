"""The deck guide's narrative routes: ``GET``, ``POST`` and ``PUT`` on
``/api/guide/{key}/narrative``, served by ``ai/routes/guide.py``.

Moved by test, bodies unchanged, from ``test_api_paste.py`` and
``test_llm.py``; the fixtures and helpers they stood on there are repeated
here, so this file needs nothing from those."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from sensei_top import claude_config as llm_config_module
from sensei_top.ai.llm import client as llm_client_module
from sensei_top.ai.llm.client import Completion
from sensei_top.api.app import create_app
from sensei_top.claude_config import LLMConfig
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent.parent / "fixtures" / "match_session.log"
ARCHETYPE = "mardu_discard"
CONTRACT = "Answer with exactly one JSON object"


@pytest.fixture(autouse=True)
def no_model_call(monkeypatch):
    """A paste route never reaches a model: any call fails the test. The
    generate test patches ``write_json`` after this."""
    def boom(*a, **k):
        raise AssertionError("a PUT must not call a model")

    for name in ("write_json", "write_prose", "write_report"):
        if hasattr(llm_client_module, name):
            monkeypatch.setattr(llm_client_module, name, boom)


@pytest.fixture
def client(tmp_path, make_client):
    db_path = tmp_path / "api.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    recent = (date.today() - timedelta(days=3)).isoformat()
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) "
        "VALUES (900001, 'Marauding Mako', '{1}', 'Creature', 'Text.')"
    )
    for i in range(6):
        conn.execute(
            "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
            "format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', ?, 'Standard', 'B')",
            (f"e{i}", recent),
        )
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, "
            "wins, losses) VALUES (?, 0, ?, '[]', 5, 0)",
            (f"e{i}", json.dumps([{"count": 4, "name": "Marauding Mako"}])),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) "
            "VALUES (?, 0, ?, 'Mardu Discard', 'Mardu Discard', 'archetype', 'now')",
            (f"e{i}", ARCHETYPE),
        )
    conn.commit()
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


@pytest.fixture
def key(client):
    return client.get("/api/guide/decks").json()[0]["key"]


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


_GUIDE = {
    "engine": "Cheap spells trigger prowess.",
    "fix": "Deploy earlier.",
    "card_notes": [],
    "matchups": [{
        "archetype": "Mardu Discard", "prose": "Board in sweepers.",
        "board_in": [], "board_out": [],
    }],
    "checklist": ["Am I racing?"],
}


def _guide_prompt(client, key):
    return client.get(f"/api/guide/{key}/narrative").json()["prompt"]


def test_guide_paste_stores_a_pasted_row_for_the_copied_list(client, key):
    prompt = _guide_prompt(client, key)
    header = _header(prompt)
    assert header["for"] == f"guide:{key}"

    resp = client.put(
        f"/api/guide/{key}/narrative", json={"answer": _answer(prompt, _GUIDE)},
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["status"] == "ok"
    assert out["guide"]["engine"] == "Cheap spells trigger prowess."
    assert out["author"] == "pasted"
    assert out["cost_usd"] is None
    assert out["stale"] is False
    # The same body the GET serves afterwards.
    assert client.get(f"/api/guide/{key}/narrative").json() == out

    conn = _db(client)
    row = conn.execute("SELECT * FROM deck_narrative WHERE deck_key = ?", (key,)).fetchone()
    assert row["author"] == "pasted"
    assert row["list_hash"] == header["context"]
    assert row["input_tokens"] is None and row["output_tokens"] is None
    assert row["cost_usd"] is None
    # The prompt column holds the copied prompt, answer contract included.
    assert CONTRACT in row["prompt"]
    brief = conn.execute(
        "SELECT model, list_hash FROM matchup_brief WHERE deck_key = ?", (key,)
    ).fetchall()
    assert [(b["model"], b["list_hash"]) for b in brief] == [("pasted", header["context"])]
    conn.close()


def test_guide_paste_unwraps_a_fence_and_surrounding_text(client, key):
    prompt = _guide_prompt(client, key)
    text = "Here you go:\n```json\n" + _answer(prompt, _GUIDE) + "\n```\nHope that helps."
    assert client.put(f"/api/guide/{key}/narrative", json={"answer": text}).status_code == 200


def test_guide_paste_written_for_an_older_list_is_stored_stale(client, key):
    prompt = _guide_prompt(client, key)
    older = "0" * 64
    resp = client.put(
        f"/api/guide/{key}/narrative",
        json={"answer": _answer(prompt, _GUIDE, context=older)},
    )
    assert resp.status_code == 200
    assert resp.json()["stale"] is True
    conn = _db(client)
    stored = conn.execute("SELECT list_hash FROM deck_narrative").fetchone()[0]
    briefs = [r[0] for r in conn.execute("SELECT list_hash FROM matchup_brief")]
    conn.close()
    assert stored == older
    assert briefs and set(briefs) == {older}


@pytest.mark.parametrize("make", [
    pytest.param(lambda p: "not json at all", id="not-json"),
    pytest.param(lambda p: json.dumps(_GUIDE), id="headerless"),
    pytest.param(lambda p: _answer(p, _GUIDE, context="edited"), id="edited-context"),
    pytest.param(lambda p: _answer(p, {"engine": "x"}), id="body-missing-fields"),
    pytest.param(lambda p: _answer(p, _GUIDE, **{"for": "match:abc"}), id="another-card"),
    pytest.param(lambda p: _answer(p, _GUIDE, **{"for": "guide:other"}), id="another-deck"),
])
def test_guide_paste_that_does_not_read_is_422_and_stores_nothing(client, key, make):
    prompt = _guide_prompt(client, key)
    resp = client.put(f"/api/guide/{key}/narrative", json={"answer": make(prompt)})
    assert resp.status_code == 422
    assert resp.json()["detail"]
    assert _count(client, "deck_narrative") == 0
    assert _count(client, "matchup_brief") == 0


def test_guide_paste_names_the_card_a_wrong_answer_belongs_to(client, key):
    prompt = _guide_prompt(client, key)
    resp = client.put(
        f"/api/guide/{key}/narrative",
        json={"answer": _answer(prompt, _GUIDE, **{"for": "match:abc"})},
    )
    assert resp.status_code == 422
    assert "a match report" in resp.json()["detail"]


def test_guide_paste_for_an_unknown_deck_is_404(client):
    resp = client.put("/api/guide/nope/narrative", json={"answer": "{}"})
    assert resp.status_code == 404


def test_guide_paste_over_256_kb_is_413_before_anything_else(client, key):
    resp = client.put(
        f"/api/guide/{key}/narrative", json={"answer": "x" * (256 * 1024 + 1)},
    )
    assert resp.status_code == 413
    assert client.put(
        "/api/guide/nope/narrative", json={"answer": "x" * (256 * 1024 + 1)},
    ).status_code == 413
    assert _count(client, "deck_narrative") == 0


def test_generate_guide_narrative_converges_with_the_paste_parser(
    monkeypatch, client, key
):
    """The whole reason the generate path is safe: a ``write_json`` payload
    shaped like ``_GUIDE_TOOL``'s schema must parse through the exact same
    ``guide_narrative_from_json`` the paste route uses, and land in both
    ``deck_narrative`` and ``matchup_brief`` — proving the generate path and
    the paste path converge on one validator, not two."""
    conn = sqlite3.connect(client.app.state.database)
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
        "format, tier) VALUES ('e', 'p', 's', 'mtgo', 'e', '2026-08-15', 'Standard', 'B')"
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins, "
        "losses) VALUES ('e', 0, '[]', '[]', 5, 0)"
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES ('e', 0, 'boros_convoke', 'Boros Convoke', "
        "'Boros Convoke', 'archetype', 'now')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    payload = {
        "engine": "Cheap spells trigger prowess.",
        "fix": "Deploy earlier.",
        "card_notes": [],
        "matchups": [{
            "archetype": "Boros Convoke", "prose": "Board in sweepers.",
            "board_in": [], "board_out": [],
        }],
        "checklist": ["Am I racing?"],
    }
    prompts = []

    def fake(prompt, schema, *, cfg, label):
        prompts.append(prompt)
        return Completion(
            text=json.dumps(payload), model="claude-opus-5",
            input_tokens=2000, output_tokens=1500, cost_usd=0.0475,
        )

    monkeypatch.setattr(llm_client_module, "write_json", fake)

    resp = client.post(f"/api/guide/{key}/narrative")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # The generate path keeps its own prompt; the answer contract ends only
    # the copied one the GET serves.
    assert "Answer as a single JSON object matching this schema" in prompts[0]
    assert "Answer with exactly one JSON object" not in prompts[0]
    copied = client.get(f"/api/guide/{key}/narrative").json()["prompt"]
    assert "Answer with exactly one JSON object" in copied
    assert "Answer as a single JSON object matching this schema" not in copied
    assert body["guide"]["engine"] == "Cheap spells trigger prowess."
    assert body["cost_usd"] == pytest.approx(0.0475)

    conn = sqlite3.connect(client.app.state.database)
    conn.row_factory = sqlite3.Row
    narrative_row = conn.execute(
        "SELECT * FROM deck_narrative WHERE deck_key = ?", (key,)
    ).fetchone()
    assert narrative_row is not None
    assert narrative_row["cost_usd"] == pytest.approx(0.0475)

    brief_row = conn.execute(
        "SELECT * FROM matchup_brief WHERE deck_key = ? AND archetype_key = 'boros_convoke'",
        (key,),
    ).fetchone()
    assert brief_row is not None
    assert brief_row["prose"] == "Board in sweepers."
    conn.close()
