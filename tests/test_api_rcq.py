"""The RCQ guide's four routes (``/api/guide/{key}/rcq*``) and the ``rcq``
CLI subcommand, on the projected fixture database. The Claude call is always
monkeypatched; every expectation is read off the pasted list or the answer
the test itself writes, never off the code's output."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sensei_top import cli
from sensei_top.api.app import create_app
from sensei_top.db import open_database
from sensei_top.llm import client as llm_client_module
from sensei_top.llm import config as llm_config_module
from sensei_top.llm.client import Completion
from sensei_top.llm.config import LLMConfig
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
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

    def fake(prompt, schema, *, cfg, label):
        calls.append(label)
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


def test_cli_rcq_prompt_prints_without_a_call(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "cli.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    from sensei_top.guide.deck import list_identities

    deck_key = list_identities(conn)[0].key
    conn.close()
    monkeypatch.setattr(
        llm_client_module, "write_json",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call expected")),
    )
    deck_file = tmp_path / "deck.txt"
    deck_file.write_text(PASTED)
    cli.main([
        "--db", str(db_path), "rcq", "--deck", deck_key,
        "--decklist", str(deck_file), "--prompt",
    ])
    assert capsys.readouterr().out.strip()


def test_cli_rcq_import_stores_one_hand_written_row(tmp_path):
    db_path = tmp_path / "imp.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    from sensei_top.guide.deck import list_identities

    deck_key = list_identities(conn)[0].key
    conn.close()
    deck_file = tmp_path / "deck.txt"
    deck_file.write_text(PASTED)
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(_answer()))
    cli.main([
        "--db", str(db_path), "rcq", "--deck", deck_key,
        "--decklist", str(deck_file), "--import", str(answer),
    ])
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT model, cost_usd, decklist_text FROM rcq_guide").fetchall()
    conn.close()
    assert rows == [("hand-written", None, PASTED)]

    bad = _answer()
    bad["flex_notes"][0]["role"] = "keystone"
    answer.write_text(json.dumps(bad))
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "--db", str(db_path), "rcq", "--deck", deck_key,
            "--decklist", str(deck_file), "--import", str(answer),
        ])
    assert "Could not read" in str(exc.value)
