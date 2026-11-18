"""The RCQ guide's four routes (``/api/guide/{key}/rcq*``) on the projected
fixture database. The Claude call is always
monkeypatched; every expectation is read off the pasted list or the answer
the test itself writes, never off the code's output."""

from __future__ import annotations

import json
import re
import sqlite3
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
PASTED = "Deck\n4 Alpha Card\n56 Mountain\n\nSideboard\n2 Beta Card\n"


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
def known(client):
    """An archetype key the seeded corpus carries."""
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
    return "boros_convoke"


@pytest.fixture
def key(client):
    return client.get("/api/guide/decks").json()[0]["key"]


def _answer():
    return {
        "game_plan": "Be the beatdown.",
        "expected_field": "Mostly red.",
        "matchups": [{
            "archetype": "Some Deck", "prose": "Race.", "play_draw": "Play first.",
            "board_in": [{"card": "Beta Card", "n": 1}], "board_out": [],
        }],
        "flex_notes": [{"card": "Alpha Card", "role": "core", "why": "It is the plan."}],
        "checklist": ["Sideboard"],
    }


def test_preview_reads_the_pasted_list_back(client, key, known):
    resp = client.get(
        f"/api/guide/{key}/rcq/preview",
        params={"decklist": PASTED, "expected": [known, "no_such_key"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["main_count"] == 60
    assert body["side_count"] == 2
    assert isinstance(body["prompt"], str) and body["prompt"]
    assert [x["key"] for x in body["expected"]] == [known]  # the unknown key is dropped
    assert (
        "Expected at the store (the player's own read of their local field, "
        "not evidence)" in body["prompt"]
    )
    for field in ("warnings", "unresolved", "recent_shares", "recent_events",
                  "freshness", "expected"):
        assert isinstance(body[field], list)


def test_preview_carries_the_decks_format_and_null_when_unknown(client, key):
    body = client.get(f"/api/guide/{key}/rcq/preview", params={"decklist": PASTED}).json()
    assert body["format"] == "Standard"

    conn = sqlite3.connect(client.app.state.database)
    conn.execute("UPDATE decks SET format = 'Draft'")
    conn.execute("UPDATE matches SET format = NULL")
    conn.commit()
    conn.close()
    body = client.get(f"/api/guide/{key}/rcq/preview", params={"decklist": PASTED}).json()
    assert body["format"] is None


def test_preview_404s_for_an_unknown_deck(client):
    resp = client.get("/api/guide/nope/rcq/preview", params={"decklist": PASTED})
    assert resp.status_code == 404


def test_latest_is_none_before_any_generation(client, key):
    assert client.get(f"/api/guide/{key}/rcq").json()["status"] == "none"
    assert client.get(f"/api/guide/{key}/rcq/markdown").status_code == 404


def test_generate_stores_every_row_and_serves_the_latest(monkeypatch, client, key, known):
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    calls = []
    prompts = []

    def fake(prompt, schema, *, cfg, label):
        calls.append(label)
        prompts.append(prompt)
        return Completion(
            text=json.dumps(_answer()), model="claude-opus-5",
            input_tokens=10, output_tokens=20, cost_usd=0.5,
        )

    monkeypatch.setattr(llm_client_module, "write_json", fake)
    body = {"decklist": PASTED, "expected": [known], "own": None}
    first = client.post(f"/api/guide/{key}/rcq/narrative", json=body)
    assert first.status_code == 200
    out = first.json()
    assert calls == ["rcq"]
    # The generate path keeps its own prompt: structured
    # outputs carry the schema, and the copied prompt's answer contract is
    # the preview's alone.
    assert "Answer as a single JSON object matching this schema" in prompts[0]
    assert "Answer with exactly one JSON object" not in prompts[0]
    copied = client.get(
        f"/api/guide/{key}/rcq/preview", params={"decklist": PASTED, "expected": [known]},
    ).json()["prompt"]
    assert "Answer with exactly one JSON object" in copied
    assert "Answer as a single JSON object matching this schema" not in copied
    assert out["status"] == "ok"
    assert out["cost_usd"] == pytest.approx(0.5)
    assert out["decklist_text"] == PASTED
    assert out["expected"] == [known]
    assert out["guide"]["game_plan"] == "Be the beatdown."
    assert out["guide"]["matchups"][0]["board_in"] == [{"card": "Beta Card", "n": 1}]

    second = client.post(f"/api/guide/{key}/rcq/narrative", json=body).json()
    assert second["id"] > out["id"]
    conn = sqlite3.connect(client.app.state.database)
    assert conn.execute("SELECT COUNT(*) FROM rcq_guide").fetchone()[0] == 2
    conn.close()

    latest = client.get(f"/api/guide/{key}/rcq").json()
    assert latest["id"] == second["id"]
    md = client.get(f"/api/guide/{key}/rcq/markdown").json()["markdown"]
    assert "Be the beatdown." in md
    assert "Some Deck" in md


def test_generate_502s_on_an_unreadable_answer(monkeypatch, client, key):
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(
        llm_client_module, "write_json",
        lambda prompt, schema, *, cfg, label: Completion(
            text="not json", model="m", input_tokens=1, output_tokens=1, cost_usd=None,
        ),
    )
    resp = client.post(
        f"/api/guide/{key}/rcq/narrative", json={"decklist": PASTED, "expected": []}
    )
    assert resp.status_code == 502
    conn = sqlite3.connect(client.app.state.database)
    assert conn.execute("SELECT COUNT(*) FROM rcq_guide").fetchone()[0] == 0
    conn.close()


# --- Rules notes -------------------------------------------------------------

LANDFALL_QUESTION = "How does landfall work on Test Bear?"
DIVIDER = "\n\n---\n\n"
CONTRACT = "Answer with exactly one JSON object"


@pytest.fixture
def asked(monkeypatch):
    """A card source whose only question is the landfall one; records the
    deck key of the evidence the route hands it."""
    from sensei_top.ai import rules_questions

    keys = []

    def rcq_cards(conn, evidence):
        keys.append(evidence.guide.provenance.deck.key)
        return rules_questions.FeatureCards(
            (rules_questions.CardRow("Test Bear", "Creature — Bear", "", ("Landfall",)),), (),
        )

    monkeypatch.setattr(rules_questions, "rcq_cards", rcq_cards)
    return keys


def _store_note(client):
    from sensei_top.ai import rules_notes

    conn = sqlite3.connect(client.app.state.database)
    rules_notes.store(conn, [rules_notes.RulesNote(
        LANDFALL_QUESTION, "2026-11-01", "answered",
        {"verdict": "Once per land.", "explanation": "It triggers on each land.",
         "citations": [{"type": "card", "ref": "Test Bear", "quote": "q"}], "out_of_scope": False},
        "medium", "2026-11-17T00:00:00Z",
    )])
    conn.commit()
    conn.close()


def _expected_block():
    from sensei_top.ai import rules_notes

    return (
        rules_notes.RULES_NOTES_HEADING + "\n"
        "N1 (medium) Q: " + LANDFALL_QUESTION
        + " A: Once per land. It triggers on each land. (cites Test Bear)"
        + "\n\n" + rules_notes.CLOSING_INSTRUCTION
    )


def _copied(client, key):
    return client.get(
        f"/api/guide/{key}/rcq/preview", params={"decklist": PASTED},
    ).json()["prompt"]


def _stored_prompt(client):
    conn = sqlite3.connect(client.app.state.database)
    try:
        return conn.execute("SELECT prompt FROM rcq_guide ORDER BY id DESC").fetchone()[0]
    finally:
        conn.close()


def _paste(client, key, body, copied=None):
    copied = copied or _copied(client, key)
    header = {}
    for name in ("for", "context"):
        m = re.search(rf'^  "{name}": ("[^"]*"),?$', copied, re.MULTILINE)
        if m:
            header[name] = json.loads(m.group(1))
    return client.put(
        f"/api/guide/{key}/rcq/narrative",
        json={"answer": json.dumps({**header, "answer": body}), "decklist": PASTED,
              "expected": []},
    )


def _generate_with(monkeypatch, client, key, body):
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    sent = []

    def fake(prompt, schema, *, cfg, label):
        sent.append(prompt)
        return Completion(
            text=json.dumps(body), model="claude-opus-5",
            input_tokens=1, output_tokens=1, cost_usd=0.01,
        )

    monkeypatch.setattr(llm_client_module, "write_json", fake)
    out = client.post(f"/api/guide/{key}/rcq/narrative", json={"decklist": PASTED, "expected": []})
    return out, sent


def test_the_prompt_without_a_note_is_unchanged_and_with_one_carries_the_block(
    monkeypatch, client, key, asked,
):
    from sensei_top.ai.guide.rcq_prompt import rcq_prompt
    from sensei_top.guide.rcq import build_rcq

    out, sent = _generate_with(monkeypatch, client, key, _answer())
    assert out.status_code == 200 and asked == [key]
    conn = sqlite3.connect(client.app.state.database)
    conn.row_factory = sqlite3.Row
    try:
        before = rcq_prompt(
            build_rcq(conn, key, PASTED, [], None), conn=conn, answer_contract=False,
        )
    finally:
        conn.close()
    assert sent[0] == before
    assert "Rules notes (" not in sent[0]

    _store_note(client)
    _, sent = _generate_with(monkeypatch, client, key, _answer())
    block = DIVIDER + _expected_block()
    assert sent[0].endswith(block)
    assert sent[0].replace(block, "") == before
    assert _stored_prompt(client) == sent[0]


def test_the_copied_prompt_carries_the_block_before_the_contract(client, key, asked):
    from sensei_top.ai.guide.rcq_prompt import rcq_prompt
    from sensei_top.guide.rcq import build_rcq

    without = _copied(client, key)
    conn = sqlite3.connect(client.app.state.database)
    conn.row_factory = sqlite3.Row
    try:
        assert without == rcq_prompt(build_rcq(conn, key, PASTED, [], None), conn=conn)
    finally:
        conn.close()
    assert "Rules notes (" not in without
    _store_note(client)
    with_note = _copied(client, key)
    block = DIVIDER + _expected_block()
    assert with_note.count(block) == 1
    assert with_note.replace(block, "") == without
    assert with_note.index(block) < with_note.index(CONTRACT)


def test_a_paste_stores_the_block_before_the_contract(client, key, asked):
    _store_note(client)
    assert _paste(client, key, _answer()).status_code == 200
    stored = _stored_prompt(client)
    block = DIVIDER + _expected_block()
    assert stored.count(block) == 1
    assert stored.index(block) < stored.index(CONTRACT)


def test_a_note_stored_after_copying_does_not_make_the_answer_for_another_list(
    client, key, asked,
):
    copied = _copied(client, key)
    _store_note(client)
    out = _paste(client, key, _answer(), copied).json()
    assert out["answered_for_another_list"] is False


def test_a_stored_guide_citing_a_note_returns_it_on_put_and_get(client, key, asked):
    _store_note(client)
    body = {**_answer(), "game_plan": "Be the beatdown [N1].", "checklist": ["Race? [N2]"]}
    put = _paste(client, key, body).json()
    expected = [{
        "marker": "N1", "question": LANDFALL_QUESTION, "verdict": "Once per land.",
        "explanation": "It triggers on each land.", "citations": ["Test Bear"],
        "confidence": "medium", "rules_version": "2026-11-01",
    }]
    assert put["notes"] == expected
    assert client.get(f"/api/guide/{key}/rcq").json()["notes"] == expected


def test_generate_returns_the_cited_note(monkeypatch, client, key, asked):
    _store_note(client)
    body = {**_answer(), "expected_field": "Landfall decks [N1]."}
    out, _ = _generate_with(monkeypatch, client, key, body)
    assert [n["marker"] for n in out.json()["notes"]] == ["N1"]


def test_none_stored_has_no_notes(client, key):
    assert client.get(f"/api/guide/{key}/rcq").json()["notes"] == []


def test_the_rcq_evidence_is_built_once_per_request(monkeypatch, client, key, asked):
    from sensei_top.ai import rules_questions
    from sensei_top.ai.routes import rcq as rcq_routes
    from sensei_top.api.routes import rcq as preview_routes
    from sensei_top.guide import rcq as guide_rcq

    built = []
    real = guide_rcq.build_rcq

    def counting(conn, deck_key, decklist, expected, own, **kwargs):
        built.append((deck_key, decklist, list(expected), own))
        return real(conn, deck_key, decklist, expected, own, **kwargs)

    # Every module that binds the name: a route that went back to for_rcq
    # would build through rules_questions'.
    monkeypatch.setattr(rcq_routes, "build_rcq", counting)
    monkeypatch.setattr(rules_questions, "build_rcq", counting)
    monkeypatch.setattr(preview_routes, "build_rcq", counting)
    _store_note(client)
    copied = _copied(client, key)
    built.clear()
    assert _paste(client, key, _answer(), copied).status_code == 200
    assert built == [(key, PASTED, [], None)]

    built.clear()
    out, _ = _generate_with(monkeypatch, client, key, _answer())
    assert out.status_code == 200
    assert built == [(key, PASTED, [], None)]

    built.clear()
    assert _copied(client, key)
    assert built == [(key, PASTED, [], None)]
