"""The seven paste routes (plan 24, D1/D5/D6/D12/D13): ``PUT`` on the deck
guide, one matchup brief, the coverage card and the RCQ guide (S7, the cards
with a CLI importer), and on the match report, the training plan and the
coach (S8, the prose cards) stores a pasted answer, and never calls a model.

The headers the answers carry are read off the copied prompt the matching
``GET`` serves, the way an assistant copies them back; every other
expectation is read off the answer the test writes."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from sensei_top.api.app import create_app
from sensei_top.db import open_database
from sensei_top.llm import client as llm_client_module
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
PASTED_LIST = "Deck\n4 Alpha Card\n56 Mountain\n\nSideboard\n2 Beta Card\n"
ARCHETYPE = "mardu_discard"
CONTRACT = "Answer with exactly one JSON object"


@pytest.fixture(autouse=True)
def no_model_call(monkeypatch):
    """A paste route never reaches a model: any call fails the test."""
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
_BRIEF = {
    "prose": "They race you; trade early.",
    "play_around": [{"card": "Marauding Mako", "why": "grows on every discard"}],
    "board_in": [], "board_out": [],
}
_RCQ = {
    "game_plan": "Be the beatdown.",
    "expected_field": "Mostly red.",
    "matchups": [{
        "archetype": "Some Deck", "prose": "Race.", "play_draw": "Play first.",
        "board_in": [{"card": "Beta Card", "n": 1}], "board_out": [],
    }],
    "flex_notes": [{"card": "Alpha Card", "role": "core", "why": "It is the plan."}],
    "checklist": ["Sideboard"],
}


def _guide_prompt(client, key):
    return client.get(f"/api/guide/{key}/narrative").json()["prompt"]


def _brief_prompt(client, key):
    return client.get(f"/api/guide/{key}/briefs/{ARCHETYPE}/prompt").json()["prompt"]


def _coverage_prompt(client, key):
    return client.get(f"/api/guide/{key}/coverage/prompt").json()["prompt"]


def _rcq_prompt(client, key):
    return client.get(
        f"/api/guide/{key}/rcq/preview", params={"decklist": PASTED_LIST},
    ).json()["prompt"]


def _rcq_body(prompt, body=None, **kw):
    return {
        "answer": _answer(prompt, _RCQ if body is None else body),
        "decklist": PASTED_LIST, "expected": [], **kw,
    }


# --- the deck guide -------------------------------------------------------


def test_guide_paste_stores_what_the_cli_import_stores(client, key):
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


# --- one matchup brief ------------------------------------------------------


def test_brief_paste_stores_with_the_context_it_was_written_for(client, key):
    prompt = _brief_prompt(client, key)
    header = _header(prompt)
    assert header["for"] == f"brief:{key}:{ARCHETYPE}"

    resp = client.put(
        f"/api/guide/{key}/briefs/{ARCHETYPE}", json={"answer": _answer(prompt, _BRIEF)},
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["prose"] == "They race you; trade early."
    assert out["model"] == "pasted"
    assert out["archetype_key"] == ARCHETYPE
    assert client.get(f"/api/guide/{key}/briefs").json() == [out]
    conn = _db(client)
    assert conn.execute("SELECT list_hash FROM matchup_brief").fetchone()[0] == header["context"]
    conn.close()


def test_brief_paste_records_an_unbalanced_plan_rather_than_refusing_it(client, key):
    prompt = _brief_prompt(client, key)
    body = {**_BRIEF, "board_in": [{"card": "Card The Deck Lacks", "n": 2}]}
    resp = client.put(
        f"/api/guide/{key}/briefs/{ARCHETYPE}", json={"answer": _answer(prompt, body)},
    )
    assert resp.status_code == 200
    assert resp.json()["problems"]


@pytest.mark.parametrize("make", [
    pytest.param(lambda p: _answer(p, {"play_around": []}), id="body-missing-prose"),
    pytest.param(lambda p: _answer(p, _BRIEF, **{"for": "coverage:x"}), id="another-card"),
    pytest.param(
        lambda p: _answer(p, _BRIEF, **{"for": "brief:other:other"}), id="another-brief",
    ),
    pytest.param(lambda p: json.dumps(_BRIEF), id="headerless"),
])
def test_brief_paste_that_does_not_read_is_422_and_stores_nothing(client, key, make):
    prompt = _brief_prompt(client, key)
    resp = client.put(
        f"/api/guide/{key}/briefs/{ARCHETYPE}", json={"answer": make(prompt)},
    )
    assert resp.status_code == 422
    assert _count(client, "matchup_brief") == 0


def test_brief_paste_for_an_archetype_with_no_consensus_is_409(client, key):
    prompt = _brief_prompt(client, key)
    resp = client.put(
        f"/api/guide/{key}/briefs/nobody",
        json={"answer": _answer(prompt, _BRIEF, **{"for": f"brief:{key}:nobody"})},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == (
        "The field has no consensus list for nobody yet, so there is nothing to "
        "anchor a brief to."
    )
    assert _count(client, "matchup_brief") == 0


def test_brief_paste_for_a_deck_with_no_format_is_409(client, key):
    prompt = _brief_prompt(client, key)
    conn = _db(client)
    conn.execute("UPDATE decks SET format = 'Draft'")
    conn.execute("UPDATE matches SET format = NULL")
    conn.commit()
    conn.close()
    resp = client.put(
        f"/api/guide/{key}/briefs/{ARCHETYPE}", json={"answer": _answer(prompt, _BRIEF)},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == (
        "This deck's format is not known yet, so there is no field to anchor a brief to."
    )
    assert _count(client, "matchup_brief") == 0


def test_brief_paste_for_an_unknown_deck_is_404(client):
    resp = client.put(f"/api/guide/nope/briefs/{ARCHETYPE}", json={"answer": "{}"})
    assert resp.status_code == 404


OLDER = "0" * 64


def test_brief_paste_written_for_an_older_list_is_stored_with_that_hash_and_reads_stale(
    client, key,
):
    prompt = _brief_prompt(client, key)
    resp = client.put(
        f"/api/guide/{key}/briefs/{ARCHETYPE}",
        json={"answer": _answer(prompt, _BRIEF, context=OLDER)},
    )
    assert resp.status_code == 200
    conn = _db(client)
    assert conn.execute("SELECT list_hash FROM matchup_brief").fetchone()[0] == OLDER
    conn.close()
    rows = client.get(f"/api/guide/{key}/coverage").json()["rows"]
    assert {r["archetype_key"]: r["status"] for r in rows}[ARCHETYPE] == "stale"


def test_coverage_paste_written_for_an_older_list_is_stored_with_that_hash_and_reads_stale(
    client, key,
):
    prompt = _coverage_prompt(client, key)
    body = {"briefs": [{"archetype_key": ARCHETYPE, **_BRIEF}]}
    resp = client.put(
        f"/api/guide/{key}/coverage", json={"answer": _answer(prompt, body, context=OLDER)},
    )
    assert resp.status_code == 200
    conn = _db(client)
    assert conn.execute("SELECT list_hash FROM matchup_brief").fetchone()[0] == OLDER
    conn.close()
    rows = client.get(f"/api/guide/{key}/coverage").json()["rows"]
    assert {r["archetype_key"]: r["status"] for r in rows}[ARCHETYPE] == "stale"


# --- coverage ----------------------------------------------------------------


def test_coverage_paste_stores_every_brief_and_returns_the_coverage(client, key):
    prompt = _coverage_prompt(client, key)
    assert _header(prompt)["for"] == f"coverage:{key}"
    body = {"briefs": [{"archetype_key": ARCHETYPE, **_BRIEF}]}

    resp = client.put(f"/api/guide/{key}/coverage", json={"answer": _answer(prompt, body)})
    assert resp.status_code == 200
    out = resp.json()
    assert out == client.get(f"/api/guide/{key}/coverage").json()
    assert {r["archetype_key"]: r["status"] for r in out["rows"]}[ARCHETYPE] == "ok"
    conn = _db(client)
    row = conn.execute("SELECT model, list_hash FROM matchup_brief").fetchone()
    conn.close()
    assert (row["model"], row["list_hash"]) == ("pasted", _header(prompt)["context"])


@pytest.mark.parametrize("body", [
    pytest.param({"briefs": []}, id="empty"),
    pytest.param({"briefs": [{"archetype_key": ARCHETYPE}]}, id="item-missing-prose"),
    pytest.param(
        {"briefs": [{"archetype_key": ARCHETYPE, **_BRIEF}] * 2}, id="same-key-twice",
    ),
])
def test_coverage_paste_that_does_not_read_is_422_and_stores_nothing(client, key, body):
    prompt = _coverage_prompt(client, key)
    resp = client.put(f"/api/guide/{key}/coverage", json={"answer": _answer(prompt, body)})
    assert resp.status_code == 422
    assert _count(client, "matchup_brief") == 0


def test_coverage_paste_of_a_card_that_is_not_coverage_is_422(client, key):
    prompt = _coverage_prompt(client, key)
    body = {"briefs": [{"archetype_key": ARCHETYPE, **_BRIEF}]}
    resp = client.put(
        f"/api/guide/{key}/coverage",
        json={"answer": _answer(prompt, body, **{"for": f"guide:{key}"})},
    )
    assert resp.status_code == 422
    assert "a deck guide" in resp.json()["detail"]


def test_coverage_paste_with_no_consensus_for_any_item_is_409(client, key):
    prompt = _coverage_prompt(client, key)
    body = {"briefs": [{"archetype_key": "nobody", **_BRIEF}]}
    resp = client.put(f"/api/guide/{key}/coverage", json={"answer": _answer(prompt, body)})
    assert resp.status_code == 409
    assert resp.json()["detail"] == (
        "The field has no consensus list yet for any archetype in this answer, "
        "so none of its briefs could be stored."
    )
    assert _count(client, "matchup_brief") == 0


def test_coverage_paste_stores_the_briefs_with_a_consensus_and_skips_the_rest(client, key):
    prompt = _coverage_prompt(client, key)
    body = {"briefs": [
        {"archetype_key": ARCHETYPE, **_BRIEF},
        {"archetype_key": "nobody", **_BRIEF},
    ]}
    resp = client.put(f"/api/guide/{key}/coverage", json={"answer": _answer(prompt, body)})
    assert resp.status_code == 200
    assert {r["archetype_key"]: r["status"] for r in resp.json()["rows"]}[ARCHETYPE] == "ok"
    assert _count(client, "matchup_brief") == 1


def test_brief_paste_409_names_the_archetype_by_its_label(client, key):
    prompt = _brief_prompt(client, key)
    conn = _db(client)
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
        "format, tier) VALUES ('thin', 'p', 's', 'mtgo', 'e', ?, 'Standard', 'B')",
        ((date.today() - timedelta(days=3)).isoformat(),),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, "
        "wins, losses) VALUES ('thin', 0, '[]', '[]', 5, 0)"
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
        "archetype_name, label, method, classified_at) "
        "VALUES ('thin', 0, 'izzet_prowess', 'Izzet Prowess', 'Izzet Prowess', "
        "'archetype', 'now')"
    )
    conn.commit()
    conn.close()
    resp = client.put(
        f"/api/guide/{key}/briefs/izzet_prowess",
        json={"answer": _answer(prompt, _BRIEF, **{"for": f"brief:{key}:izzet_prowess"})},
    )
    assert resp.status_code == 409
    assert "Izzet Prowess" in resp.json()["detail"]
    assert "izzet_prowess" not in resp.json()["detail"]
    assert _count(client, "matchup_brief") == 0


def _no_format(client):
    conn = _db(client)
    conn.execute("UPDATE decks SET format = 'Draft'")
    conn.execute("UPDATE matches SET format = NULL")
    conn.commit()
    conn.close()


def test_coverage_paste_for_a_deck_with_no_format_is_409(client, key):
    prompt = _coverage_prompt(client, key)
    _no_format(client)
    body = {"briefs": [{"archetype_key": ARCHETYPE, **_BRIEF}]}
    resp = client.put(f"/api/guide/{key}/coverage", json={"answer": _answer(prompt, body)})
    assert resp.status_code == 409
    assert resp.json()["detail"].startswith("This deck's format is not known yet")
    assert _count(client, "matchup_brief") == 0


def test_the_409s_follow_the_requests_language(client, key):
    prompt = _brief_prompt(client, key)
    _no_format(client)
    resp = client.put(
        f"/api/guide/{key}/briefs/{ARCHETYPE}",
        json={"answer": _answer(prompt, _BRIEF)},
        headers={"Accept-Language": "pt-BR"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == (
        "O formato deste deck ainda não é conhecido, então não há meta em que "
        "ancorar um briefing."
    )


def test_a_paste_over_256_kb_is_413_on_the_brief_and_coverage_routes(client, key):
    big = {"answer": "x" * (256 * 1024 + 1)}
    assert client.put(f"/api/guide/{key}/briefs/{ARCHETYPE}", json=big).status_code == 413
    assert client.put("/api/guide/nope/briefs/x", json=big).status_code == 413
    assert client.put(f"/api/guide/{key}/coverage", json=big).status_code == 413
    assert client.put("/api/guide/nope/coverage", json=big).status_code == 413
    assert _count(client, "matchup_brief") == 0


# --- the RCQ guide -------------------------------------------------------------


def test_rcq_paste_stores_a_row_and_serves_it_as_the_latest(client, key):
    prompt = _rcq_prompt(client, key)
    assert _header(prompt) == {"for": f"rcq:{key}"}  # no context: nothing to go stale

    resp = client.put(f"/api/guide/{key}/rcq/narrative", json=_rcq_body(prompt))
    assert resp.status_code == 200
    out = resp.json()
    assert out["status"] == "ok"
    assert out["model"] == "pasted"
    assert out["cost_usd"] is None
    assert out["decklist_text"] == PASTED_LIST
    assert out["guide"]["game_plan"] == "Be the beatdown."
    assert client.get(f"/api/guide/{key}/rcq").json() == out

    conn = _db(client)
    row = conn.execute("SELECT * FROM rcq_guide").fetchone()
    conn.close()
    assert row["model"] == "pasted"
    assert row["input_tokens"] is None and row["output_tokens"] is None
    assert CONTRACT in row["prompt"]

    again = client.put(f"/api/guide/{key}/rcq/narrative", json=_rcq_body(prompt)).json()
    assert again["id"] > out["id"]
    assert _count(client, "rcq_guide") == 2


@pytest.mark.parametrize("make", [
    pytest.param(lambda p: _answer(p, {"game_plan": "x"}), id="body-missing-fields"),
    pytest.param(lambda p: _answer(p, _RCQ, **{"for": "guide:x"}), id="another-card"),
    pytest.param(lambda p: _answer(p, _RCQ, **{"for": "rcq:other"}), id="another-deck"),
    pytest.param(lambda p: json.dumps(_RCQ), id="headerless"),
    pytest.param(
        lambda p: _answer(p, {**_RCQ, "flex_notes": [
            {"card": "Alpha Card", "role": "mystery", "why": "x"}]}),
        id="unknown-flex-role",
    ),
])
def test_rcq_paste_that_does_not_read_is_422_and_stores_nothing(client, key, make):
    prompt = _rcq_prompt(client, key)
    body = {**_rcq_body(prompt), "answer": make(prompt)}
    resp = client.put(f"/api/guide/{key}/rcq/narrative", json=body)
    assert resp.status_code == 422
    assert _count(client, "rcq_guide") == 0


def test_rcq_paste_404_and_413(client, key):
    body = {"answer": "{}", "decklist": PASTED_LIST}
    assert client.put("/api/guide/nope/rcq/narrative", json=body).status_code == 404
    body["answer"] = "x" * (256 * 1024 + 1)
    assert client.put(f"/api/guide/{key}/rcq/narrative", json=body).status_code == 413


# --- the prose cards: match report, training plan, coach -----------------------

EMPTY_PROSE = "The answer has no text in it."
BIG = {"answer": "x" * (256 * 1024 + 1)}


@pytest.fixture
def match_id(client):
    return client.get("/api/matches").json()[0]["match_id"]


def _match_path(match_id):
    return f"/api/matches/{match_id}/report/narrative"


def _prose(text):
    return {"prose": text}


def test_match_report_paste_stores_and_the_get_serves_it(client, match_id):
    before = client.get(_match_path(match_id)).json()
    assert before["status"] == "prompt"
    prompt = before["prompt"]
    header = _header(prompt)
    assert header["for"] == f"match:{match_id}"
    text = "You kept a slow hand on the draw.\n\nMulligan it next time."

    resp = client.put(
        _match_path(match_id), json={"answer": _answer(prompt, _prose(text))},
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["status"] == "ok"
    assert out["narrative"] == text
    assert out["model"] == "pasted"
    assert out["cost_usd"] is None
    assert out["stale"] is False
    assert out["prompt"] == prompt
    assert client.get(_match_path(match_id)).json() == out

    conn = _db(client)
    row = conn.execute(
        "SELECT * FROM match_narrative WHERE match_id = ?", (match_id,)
    ).fetchone()
    conn.close()
    assert row["prose"] == text
    assert row["model"] == "pasted"
    assert row["context_hash"] == header["context"]
    assert row["input_tokens"] is None and row["output_tokens"] is None
    assert row["cost_usd"] is None
    # The copied prompt, answer contract included (D13), not the generate one.
    assert row["prompt"] == prompt
    assert CONTRACT in row["prompt"]


def test_match_report_paste_written_for_older_evidence_is_stored_stale(client, match_id):
    prompt = client.get(_match_path(match_id)).json()["prompt"]
    resp = client.put(
        _match_path(match_id),
        json={"answer": _answer(prompt, _prose("Old advice."), context=OLDER)},
    )
    assert resp.status_code == 200
    assert resp.json()["stale"] is True
    assert client.get(_match_path(match_id)).json()["stale"] is True
    conn = _db(client)
    assert conn.execute("SELECT context_hash FROM match_narrative").fetchone()[0] == OLDER
    conn.close()


@pytest.mark.parametrize("make", [
    pytest.param(lambda p: json.dumps(_prose("Fine prose.")), id="headerless"),
    pytest.param(lambda p: _answer(p, _prose("x"), **{"for": "leaks"}), id="another-card"),
    pytest.param(
        lambda p: _answer(p, _prose("x"), **{"for": "match:another"}), id="another-match",
    ),
    pytest.param(lambda p: _answer(p, {"text": "x"}), id="no-prose-field"),
    pytest.param(lambda p: _answer(p, _prose("x"), context="edited"), id="edited-context"),
])
def test_match_report_paste_that_does_not_read_is_422_and_stores_nothing(
    client, match_id, make,
):
    prompt = client.get(_match_path(match_id)).json()["prompt"]
    resp = client.put(_match_path(match_id), json={"answer": make(prompt)})
    assert resp.status_code == 422
    assert resp.json()["detail"]
    assert _count(client, "match_narrative") == 0


def test_match_report_paste_names_the_card_a_wrong_answer_belongs_to(client, match_id):
    prompt = client.get(_match_path(match_id)).json()["prompt"]
    resp = client.put(
        _match_path(match_id),
        json={"answer": _answer(prompt, _prose("x"), **{"for": "leaks"})},
    )
    assert resp.status_code == 422
    assert "the training plan" in resp.json()["detail"]


@pytest.mark.parametrize("text", ["", "  \n\t "])
def test_match_report_paste_with_empty_prose_is_422(client, match_id, text):
    prompt = client.get(_match_path(match_id)).json()["prompt"]
    resp = client.put(_match_path(match_id), json={"answer": _answer(prompt, _prose(text))})
    assert resp.status_code == 422
    assert resp.json()["detail"] == EMPTY_PROSE
    assert _count(client, "match_narrative") == 0


def test_match_report_paste_refusal_follows_the_requests_language(client, match_id):
    prompt = client.get(_match_path(match_id)).json()["prompt"]
    resp = client.put(
        _match_path(match_id), json={"answer": _answer(prompt, _prose(" "))},
        headers={"Accept-Language": "pt-BR"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "A resposta não tem nenhum texto."


def test_match_report_paste_with_nothing_to_write_about_is_404(
    client, match_id, monkeypatch,
):
    from sensei_top.review import narrative as review_narrative

    monkeypatch.setattr(review_narrative, "build_narrative_context", lambda *a, **k: None)
    assert client.get(_match_path(match_id)).json()["status"] == "no_report"
    resp = client.put(
        _match_path(match_id),
        json={"answer": json.dumps({"for": f"match:{match_id}", "context": OLDER,
                                    "answer": _prose("Text.")})},
    )
    assert resp.status_code == 404
    assert _count(client, "match_narrative") == 0


def test_match_report_paste_for_an_unknown_match_is_404(client):
    resp = client.put(_match_path("no-such-match"), json={"answer": "{}"})
    assert resp.status_code == 404
    assert resp.json() == client.get(_match_path("no-such-match")).json()


def test_match_report_paste_over_256_kb_is_413_before_anything_else(client, match_id):
    assert client.put(_match_path(match_id), json=BIG).status_code == 413
    assert client.put(_match_path("no-such-match"), json=BIG).status_code == 413
    assert _count(client, "match_narrative") == 0


LEAKS_PATH = "/api/review/leaks/narrative"


@pytest.fixture
def leaky(monkeypatch):
    """One leak, so the training plan has a prompt; the fixture's single match
    is below the leak finder's own sample."""
    from sensei_top.api.routes import review as review_routes
    from sensei_top.review.leaks import Leak

    leak = Leak(
        code="mana_screwed", category="deckbuilding", sample_title="Stuck on lands",
        n_with=15, win_rate_with=0.3, ci_with=(0.15, 0.5),
        n_without=40, win_rate_without=0.55, ci_without=(0.4, 0.7),
        gap=0.25, match_ids_with=("m1",),
    )
    monkeypatch.setattr(review_routes, "find_leaks", lambda conn, **kwargs: [leak])


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


COACH_PATH = "/api/coach/narrative"


@pytest.fixture
def coach_client(tmp_path, make_client):
    """Ten completed Standard ladder matches: the leak finder's minimum sample,
    the floor the coach's prompt is built on (as in tests/test_coach_api.py)."""
    path = tmp_path / "coach.db"
    conn = open_database(path)
    for i in range(10):
        started = f"2026-0{1 + i % 9}-0{1 + i % 9}T00:00:00"
        result = "win" if i % 2 == 0 else "loss"
        conn.execute(
            "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
            "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
            "games_lost, completed_reason, source, format) VALUES (?, 'Traditional_Ladder', "
            "NULL, 1, 2, 'OPPCLIENTID0001', 'OppPlayerOne', ?, ?, ?, 1, 0, 'r', 'arena', "
            "'Standard')",
            (f"m{i}", started, started, result),
        )
        conn.execute(
            "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
            "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 6, 0, 0)",
            (f"m{i}", result),
        )
    conn.commit()
    conn.close()
    with make_client(create_app(path)) as c:
        yield c


def _offered_readings(prompt: str) -> list[str]:
    """The reading-list labels the prompt offers, one ``[R<n>] ...`` line each."""
    return re.findall(r"^\[(R\d+)\] ", prompt, re.MULTILINE)


def test_coach_paste_stores_a_report_with_its_cited_readings(coach_client):
    before = coach_client.get(COACH_PATH).json()
    assert before["status"] == "prompt"
    assert before["format"] == "Standard"
    prompt = before["prompt"]
    header = _header(prompt)
    assert header["for"] == "coach:Standard"
    offered = _offered_readings(prompt)
    assert offered
    cited = offered[0]
    never_offered = f"R{max(int(r[1:]) for r in offered) + 1000}"
    focus = "Mulligan seven-landers on the draw."
    text = f"## Focus areas\n{focus} [{cited}] [{never_offered}]"

    resp = coach_client.put(COACH_PATH, json={"answer": _answer(prompt, _prose(text))})
    assert resp.status_code == 200
    out = resp.json()
    assert out["status"] == "ok"
    assert out["format"] == "Standard"
    assert out["narrative"] == text
    assert out["model"] == "pasted"
    for field in ("effort", "cost_usd", "input_tokens", "output_tokens",
                  "web_search_requests"):
        assert out[field] is None
    assert out["stale"] is False
    assert [s["label"] for s in out["sources"] if s["kind"] == "reading"] == [cited]
    # The PUT answers with the prompt it stored, as the POST answers with the
    # one it sent; the next GET's prompt lists this report as the previous one.
    assert out["prompt"] == prompt
    after = coach_client.get(COACH_PATH).json()
    assert {k: v for k, v in after.items() if k != "prompt"} == {
        k: v for k, v in out.items() if k != "prompt"
    }
    # The stored metrics are a snapshot the next report measures progress
    # against: the next prompt quotes this report's focus areas and compares.
    assert focus in after["prompt"]
    assert "progress can't be measured" not in after["prompt"]

    conn = _db(coach_client)
    row = conn.execute("SELECT * FROM coach_report").fetchone()
    conn.close()
    assert row["format"] == "Standard"
    assert row["model"] == "pasted"
    assert row["context_hash"] == header["context"]
    assert json.loads(row["sources_json"]) == [cited]
    assert json.loads(row["metrics_json"])  # the snapshot at paste time
    assert row["prompt"] == prompt
    assert CONTRACT in row["prompt"]

    # A second paste is a second report: history, never an upsert.
    again = coach_client.get(COACH_PATH).json()["prompt"]
    resp2 = coach_client.put(
        COACH_PATH, json={"answer": _answer(again, _prose("## Focus areas\nAgain."))},
    )
    assert resp2.json()["id"] > out["id"]
    assert _count(coach_client, "coach_report") == 2


def test_coach_paste_is_for_the_format_the_page_asks_for(coach_client):
    # Ten Standard matches clear the skill sample for a Modern report too
    # (tests/test_coach_api.py), so the Modern page has its own prompt.
    standard = coach_client.get(COACH_PATH).json()["prompt"]
    resp = coach_client.put(
        f"{COACH_PATH}?format=Modern",
        json={"answer": _answer(standard, _prose("## Focus areas\nx"))},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == (
        "This answer is for a coach report of another format. Paste it there."
    )
    assert _count(coach_client, "coach_report") == 0

    modern = coach_client.get(f"{COACH_PATH}?format=Modern").json()["prompt"]
    assert _header(modern)["for"] == "coach:Modern"
    resp = coach_client.put(
        f"{COACH_PATH}?format=Modern",
        json={"answer": _answer(modern, _prose("## Focus areas\nx"))},
    )
    assert resp.status_code == 200
    assert resp.json()["format"] == "Modern"
    conn = _db(coach_client)
    assert conn.execute("SELECT format FROM coach_report").fetchone()[0] == "Modern"
    conn.close()
    assert coach_client.get(COACH_PATH).json()["status"] == "prompt"


def test_coach_paste_written_for_older_evidence_is_stored_stale(coach_client):
    prompt = coach_client.get(COACH_PATH).json()["prompt"]
    resp = coach_client.put(
        COACH_PATH, json={"answer": _answer(prompt, _prose("## Focus areas\nx"), context=OLDER)},
    )
    assert resp.status_code == 200
    assert resp.json()["stale"] is True
    assert coach_client.get(COACH_PATH).json()["stale"] is True
    conn = _db(coach_client)
    assert conn.execute("SELECT context_hash FROM coach_report").fetchone()[0] == OLDER
    conn.close()


@pytest.mark.parametrize("make", [
    pytest.param(lambda p: json.dumps(_prose("## Focus areas\nx")), id="headerless"),
    pytest.param(lambda p: _answer(p, _prose("x"), **{"for": "leaks"}), id="another-card"),
    pytest.param(
        lambda p: _answer(p, _prose("x"), **{"for": "coach:Modern"}), id="another-format",
    ),
    pytest.param(lambda p: _answer(p, _prose("\n\n")), id="empty-prose"),
])
def test_coach_paste_that_does_not_read_is_422_and_stores_nothing(coach_client, make):
    prompt = coach_client.get(COACH_PATH).json()["prompt"]
    resp = coach_client.put(COACH_PATH, json={"answer": make(prompt)})
    assert resp.status_code == 422
    assert _count(coach_client, "coach_report") == 0


def test_coach_paste_with_empty_prose_says_so_in_pt_br(coach_client):
    prompt = coach_client.get(COACH_PATH).json()["prompt"]
    resp = coach_client.put(
        COACH_PATH, json={"answer": _answer(prompt, _prose(""))},
        headers={"Accept-Language": "pt-BR"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "A resposta não tem nenhum texto."


def test_coach_paste_with_too_few_matches_is_404_and_413_comes_first(client):
    # The fixture's one match is below the coach's minimum sample.
    assert client.get(COACH_PATH).json()["status"] == "no_report"
    assert client.put(COACH_PATH, json={"answer": "{}"}).status_code == 404
    assert client.put(COACH_PATH, json=BIG).status_code == 413
    assert _count(client, "coach_report") == 0


def test_coach_paste_without_a_format_is_for_the_default_format(coach_client):
    # A Modern match after the ten Standard ones: the latest match's format
    # is the default (tests/test_coach_api.py).
    conn = _db(coach_client)
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, source, format) VALUES ('modern1', "
        "'Traditional_Ladder', NULL, 1, 2, 'OPPCLIENTID0001', 'OppPlayerOne', "
        "'2026-09-20T00:00:00', '2026-09-20T00:00:00', 'win', 1, 0, 'r', 'arena', 'Modern')"
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES ('modern1', 1, 1, 'win', NULL, "
        "6, 0, 0)"
    )
    conn.commit()
    conn.close()

    before = coach_client.get(COACH_PATH).json()
    assert before["format"] == "Modern"
    assert _header(before["prompt"])["for"] == "coach:Modern"
    resp = coach_client.put(
        COACH_PATH, json={"answer": _answer(before["prompt"], _prose("## Focus areas\nx"))},
    )
    assert resp.status_code == 200
    assert resp.json()["format"] == "Modern"
    conn = _db(coach_client)
    assert conn.execute("SELECT format FROM coach_report").fetchone()[0] == "Modern"
    conn.close()


def test_coach_paste_over_256_kb_is_413_before_anything_else(coach_client):
    assert coach_client.put(COACH_PATH, json=BIG).status_code == 413
    assert coach_client.put(f"{COACH_PATH}?format=Modern", json=BIG).status_code == 413
    assert _count(coach_client, "coach_report") == 0


# --- the guard -----------------------------------------------------------------

PASTE_ROUTES = [
    "/api/guide/k/narrative",
    "/api/guide/k/rcq/narrative",
    f"/api/guide/k/briefs/{ARCHETYPE}",
    "/api/guide/k/coverage",
    "/api/matches/m/report/narrative",
    "/api/review/leaks/narrative",
    "/api/coach/narrative",
]


@pytest.mark.parametrize("path", PASTE_ROUTES)
def test_guard_refuses_a_paste_without_the_header_or_from_a_foreign_origin(
    tmp_path, path
):
    from fastapi.testclient import TestClient

    from sensei_top.api.guard import CLIENT_HEADER

    db_path = tmp_path / "g.db"
    open_database(db_path).close()
    with TestClient(create_app(db_path), base_url="http://127.0.0.1:8000") as bare:
        missing = bare.put(path, json={"answer": "{}", "decklist": ""})
        foreign = bare.put(
            path, json={"answer": "{}", "decklist": ""},
            headers={CLIENT_HEADER: "dashboard", "Origin": "https://example.org"},
        )
    assert missing.status_code == 403
    assert foreign.status_code == 403
