"""The match report's narrative routes: ``GET``, ``POST`` and ``PUT`` on
``/api/matches/{match_id}/report/narrative``, served by
``ai/routes/match_report.py``.

Moved by test, bodies unchanged, from ``test_api.py``, ``test_api_paste.py``
and ``test_llm.py``; the fixtures and helpers they stood on there are
repeated here, so this file needs nothing from those."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from sensei_top.ai.llm import client as llm_client_module
from sensei_top.ai.llm import config as llm_config_module
from sensei_top.ai.llm.client import Completion
from sensei_top.ai.llm.config import LLMConfig
from sensei_top.ai.review import narrative
from sensei_top.ai.routes import match_report as match_report_routes
from sensei_top.api.app import create_app
from sensei_top.db import open_database
from sensei_top.metagame.source import ParsedEvent
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent.parent / "fixtures" / "match_session.log"
MATCH_LOSS = "fd5624a4-d970-40eb-80aa-fba9d2ce17b3"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"
CONTRACT = "Answer with exactly one JSON object"
OLDER = "0" * 64
EMPTY_PROSE = "The answer has no text in it."
BIG = {"answer": "x" * (256 * 1024 + 1)}


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
def client(tmp_path, make_client):
    db_path = tmp_path / "api.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


def _teach(db_path, *, grp_id, name, archetype="Test Deck"):
    """Set up one match to classify and one to fall back on colours.

    ``grp_id`` gets a name and a rule that matches it, so its match resolves to
    an archetype. The other match's opponent card (69399, a card seat 1 played
    in MATCH_LOSS, read from the fixture) gets a name but no rule, so it
    exercises the colours-and-signature layer underneath. A second archetype,
    ``NeverSeen``, requires a card neither match ever reveals — it never wins
    a classification, but it makes every candidates-endpoint call exercise the
    "offered anyway, ranked last" tier.
    """
    from sensei_top.archetypes import classify_matches

    conn = open_database(db_path)
    conn.executemany(
        "INSERT OR REPLACE INTO cards (grp_id, name, type_line, rarity, colors) VALUES (?,?,?,?,?)",
        [
            (grp_id, name, "Creature — Test", "rare", '["U"]'),
            (69399, "Unruled Card", "Creature — Test", "rare", '["G"]'),
        ],
    )
    conn.execute(
        """
        INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)
             VALUES ('Standard', 'archetype', 'Test', ?, 0, ?, '2026-01-01T00:00:00Z')
        """,
        (archetype,
         json.dumps({"Name": archetype,
                     "Conditions": [{"Type": "InMainboard", "Cards": [name]}]})),
    )
    conn.execute(
        """
        INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)
             VALUES ('Standard', 'archetype', 'NeverSeen', 'Never Seen Deck', 0, ?,
                     '2026-01-01T00:00:00Z')
        """,
        (json.dumps({"Name": "Never Seen Deck",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Nonexistent Card"]}]}),),
    )
    classify_matches(conn)
    conn.close()


@pytest.fixture
def named_client(tmp_path, make_client):
    """The fixture session with one opponent card named and one rule to match it.

    grpId 98589 is a card the opponent played in MATCH_WIN, read from the
    fixture's ZoneTransfer annotations.
    """
    db_path = tmp_path / "named.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    _teach(db_path, grp_id=98589, name="Test Signature")
    with make_client(create_app(db_path)) as c:
        yield c


@pytest.fixture
def match_id(client):
    return client.get("/api/matches").json()[0]["match_id"]


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


def _match_path(match_id):
    return f"/api/matches/{match_id}/report/narrative"


def _prose(text):
    return {"prose": text}


# --- GET ---------------------------------------------------------------------


def test_narrative_route_hands_over_a_prompt_with_no_key_anywhere(client, monkeypatch):
    """The GET route never checks for a credential at all — only the POST
    generate route does — so it hands over the prompt the same way whether
    or not one is configured (AGENTS.md #5, `docs/llm.md`)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    body = client.get(f"/api/matches/{MATCH_WIN}/report/narrative").json()
    assert body["status"] == "prompt"
    assert body["narrative"] is None
    assert narrative.SYSTEM_PROMPT in body["prompt"]


def test_narrative_404s_for_an_unknown_match(client):
    assert client.get("/api/matches/nope/report/narrative").status_code == 404


def test_narrative_prompt_carries_the_evidence_and_the_framing(client):
    body = client.get(
        f"/api/matches/{MATCH_WIN}/report/narrative", params={"preview": "1"}
    ).json()
    assert body["status"] == "prompt"
    assert body["narrative"] is None
    assert "Findings:" in body["prompt"]
    assert "Not tracked by this reader at all, for any match" in body["prompt"]


def test_narrative_prompt_carries_no_local_paths(client, monkeypatch):
    """This prompt deliberately carries the game's own shape
    (ai/review/narrative.py's module docstring). What would still be wrong to
    leak is a filesystem path, which would reveal the machine and buy the
    coaching nothing."""
    body = client.get(
        f"/api/matches/{MATCH_WIN}/report/narrative", params={"preview": "1"}
    ).json()
    prompt = body["prompt"].lower()
    for leaked in ("/home/", "c:\\users", "/users/", "appdata"):
        assert leaked not in prompt


def _store_field_row(db_path, fmt: str) -> None:
    """One Tier A deck, 2-1-0, of the 'Test' archetype, in a ``fmt`` event."""
    conn = sqlite3.connect(db_path)
    event = ParsedEvent(
        event_id="e1", source="MTGmelee", name="Champs", event_date="2026-08-01",
        format=fmt, tier="A", standings_rows=1, uri=None, blob_sha="s1",
    )
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, format, "
        "tier, standings_rows, uri) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event.event_id, event.event_id, event.blob_sha, event.source, event.name,
         event.event_date, event.format, event.tier, event.standings_rows, event.uri),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, result, wins, losses, draws, "
        "mainboard_json, sideboard_json) VALUES (?, 0, '2-1-0', 2, 1, 0, '[]', '[]')",
        (event.event_id,),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "colors, label, method, classified_at) "
        "VALUES (?, 0, 'Test', 'Test Deck', '', 'Test Deck', 'archetype', '2026-08-01T00:00:00Z')",
        (event.event_id,),
    )
    conn.commit()
    conn.close()


def test_narrative_prompt_includes_field_context_for_a_classified_opponent(
    named_client, monkeypatch
):
    """MATCH_WIN resolves to the 'Test' archetype in named_client — with
    metagame data stored for that same archetype_key, the prompt must carry
    the field figure. The vocabulary is shared on purpose: the
    same archetype_key names both a personal match and a corpus decklist."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _store_field_row(named_client.app.state.database, "Standard")

    body = named_client.get(
        f"/api/matches/{MATCH_WIN}/report/narrative", params={"preview": "1"}
    ).json()
    assert "Field context" in body["prompt"]
    assert "Test Deck has won" in body["prompt"]


def test_narrative_prompt_field_context_is_the_matchs_own_formats(named_client, monkeypatch):
    """MATCH_WIN is Standard by its log; the same archetype key in a Modern
    event is another format's field and stays out of its prompt."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _store_field_row(named_client.app.state.database, "Modern")

    body = named_client.get(
        f"/api/matches/{MATCH_WIN}/report/narrative", params={"preview": "1"}
    ).json()
    assert body["prompt"] is not None
    assert "Field context" not in body["prompt"]


def test_narrative_prompt_omits_field_context_for_a_colours_only_opponent(
    named_client, monkeypatch
):
    """MATCH_LOSS falls back to a colours-only label in named_client — its
    opponent_key never starts with 'archetype:', so there is no shared
    vocabulary to join field data on, and the prompt must not claim one."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    body = named_client.get(
        f"/api/matches/{MATCH_LOSS}/report/narrative", params={"preview": "1"}
    ).json()
    if body["prompt"] is not None:
        assert "Field context" not in body["prompt"]


# --- PUT ---------------------------------------------------------------------


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
    # The copied prompt, answer contract included, not the generate one.
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
    monkeypatch.setattr(narrative, "build_narrative_context", lambda *a, **k: None)
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


# --- POST --------------------------------------------------------------------


def test_generate_match_report_narrative_stores_and_returns_it(monkeypatch, client):
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(
        llm_client_module, "write_prose",
        lambda prompt, *, cfg, label: Completion(
            text="You won because of X.", model="claude-opus-5",
            input_tokens=500, output_tokens=200, cost_usd=0.0075,
        ),
    )

    resp = client.post(f"/api/matches/{MATCH_WIN}/report/narrative")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["narrative"] == "You won because of X."
    assert body["cost_usd"] == pytest.approx(0.0075)

    again = client.get(f"/api/matches/{MATCH_WIN}/report/narrative").json()
    assert again["status"] == "ok"
    assert again["narrative"] == "You won because of X."
    assert again["stale"] is False


def test_generate_match_report_narrative_404s_with_nothing_to_narrate(monkeypatch, client):
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(
        match_report_routes, "build_match_report",
        lambda conn, match_id, **kwargs: SimpleNamespace(
            findings=(), gaps=(), games=(), result=None,
        ),
    )
    resp = client.post(f"/api/matches/{MATCH_WIN}/report/narrative")
    assert resp.status_code == 404

