"""Tests for api/routes/coach.py and api/models/coach.py: the coach's own
free ``GET /api/coach`` and its three ``.../narrative`` routes.

Mirrors tests/test_llm.py's credential-gating and stored-report coverage
for the other three narrative routes, adapted for what makes this one
different (a plain history INSERT rather than a single overwritten slot, a
credential resolved through ``load_coach()`` rather than ``load()``, and a
``write_report`` call that can carry both web citations and reading-list
ids). No network call is ever made here: ``llm.config.load_coach`` and
``llm.client.write_report`` are monkeypatched throughout, the same objects
``api/routes/coach.py`` imports under, so a patch made through those module
references is visible to the route.

The "sufficient data" fixture builds a synthetic ten-match database
directly against the projected schema — the same precedent
tests/test_coach_narrative.py's own ``conn``/``_insert_match`` fixtures set
for reaching ``MIN_SAMPLE`` without a full log capture (rule 8: expectations
here are read off what was inserted, never off a first run of the code).
"""

from __future__ import annotations

import pytest

from sensei_top.api import create_app
from sensei_top.coach.canon import CANON
from sensei_top.coach.store import write_coach_report
from sensei_top.db import open_database
from sensei_top.llm import client as llm_client_module
from sensei_top.llm import config as llm_config_module
from sensei_top.llm.client import Citation, Completion, LLMError
from sensei_top.llm.config import LLMConfig


def _insert_match(
    conn, match_id, result, *, started_at="2026-01-01T00:00:00", fmt="Standard"
):
    """The minimal shape ``coach.evidence``'s population query reads: a real
    ladder ``event_id`` (so the match counts as Constructed, not excluded
    for having none), one game whose own result matches the match's."""
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, source, format) VALUES (?, 'Traditional_Ladder', NULL, "
        "1, 2, 'OPPCLIENTID0001', 'OppPlayerOne', ?, ?, ?, 1, 0, 'r', 'arena', ?)",
        (match_id, started_at, started_at, result, fmt),
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 6, 0, 0)",
        (match_id, result),
    )


@pytest.fixture
def empty_client(tmp_path, make_client):
    db_path = tmp_path / "empty.db"
    conn = open_database(db_path)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


@pytest.fixture
def client(tmp_path, make_client):
    """Ten matches, alternating win/loss, on distinct dates — exactly
    ``MIN_SAMPLE`` (``review/leaks.py``), the floor ``coach.evidence.
    build_coach_evidence`` (and so ``build_coach_prompt``) gates on."""
    db_path = tmp_path / "sufficient.db"
    conn = open_database(db_path)
    for i in range(10):
        _insert_match(
            conn, f"m{i}", "win" if i % 2 == 0 else "loss",
            started_at=f"2026-0{1 + i % 9}-0{1 + i % 9}T00:00:00",
        )
    conn.commit()
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


# --- GET routes on an empty database ---------------------------------------


def test_coach_on_empty_db_is_insufficient_but_a_200(empty_client):
    resp = empty_client.get("/api/coach")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sufficient"] is False
    assert body["evidence"] is None
    assert body["reports"] == []


def test_coach_narrative_on_empty_db_is_no_report(empty_client):
    resp = empty_client.get("/api/coach/narrative")
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_report"


def test_coach_narrative_by_id_404s_on_empty_db(empty_client):
    resp = empty_client.get("/api/coach/narrative/999")
    assert resp.status_code == 404


# --- POST /api/coach/narrative: the credential and sufficiency gates -------


def test_no_credential_means_no_client_is_constructed(monkeypatch, client):
    """The same guarantee tests/test_llm.py pins for the other four
    routes: with nothing configured, the route may not even try to build
    an Anthropic client."""
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: None)

    def _boom(*args, **kwargs):
        raise AssertionError("write_report ran with no credential configured")

    monkeypatch.setattr(llm_client_module, "write_report", _boom)

    resp = client.post("/api/coach/narrative")
    assert resp.status_code == 503
    assert "config --set-key" in resp.json()["detail"]


def test_insufficient_data_gives_404_and_never_calls_write_report(monkeypatch, empty_client):
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: LLMConfig(api_key="k"))

    def _boom(*args, **kwargs):
        raise AssertionError("write_report ran with insufficient data")

    monkeypatch.setattr(llm_client_module, "write_report", _boom)

    resp = empty_client.post("/api/coach/narrative")
    assert resp.status_code == 404


def test_write_report_llm_error_gives_502_and_writes_no_row(monkeypatch, client):
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: LLMConfig(api_key="k"))

    def _boom(prompt, *, cfg, label, allowed_domains, max_searches=8):
        raise LLMError("Claude declined this request (category: cyber).")

    monkeypatch.setattr(llm_client_module, "write_report", _boom)

    resp = client.post("/api/coach/narrative")
    assert resp.status_code == 502

    listing = client.get("/api/coach").json()
    assert listing["reports"] == []


# --- POST /api/coach/narrative: the sufficient-data path --------------------


def test_generate_coach_narrative_stores_citations_and_reading_ids(monkeypatch, client):
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: LLMConfig(api_key="k"))
    fake_citation = Citation(url="https://mtggoldfish.com/a", title="A Page", cited_text="quote")

    def _fake_write_report(prompt, *, cfg, label, allowed_domains, max_searches=8):
        return Completion(
            text="## Focus areas\nWork on mulligans. [R1] [R999]",
            model="claude-opus-5", input_tokens=1000, output_tokens=500,
            cost_usd=0.02, citations=(fake_citation,), web_search_requests=2,
        )

    monkeypatch.setattr(llm_client_module, "write_report", _fake_write_report)

    resp = client.post("/api/coach/narrative")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "Work on mulligans" in body["narrative"]
    assert body["model"] == "claude-opus-5"
    assert body["cost_usd"] == pytest.approx(0.02)
    assert body["web_search_requests"] == 2

    kinds = {s["kind"] for s in body["sources"]}
    assert kinds == {"web", "reading"}
    reading = next(s for s in body["sources"] if s["kind"] == "reading")
    assert reading["label"] == "R1"
    r1 = next(e for e in CANON if e.id == 1)
    assert reading["url"] == r1.url
    # R999 was never offered to this prompt -- cited_ids drops it silently.
    assert not any(s["label"] == "R999" for s in body["sources"])

    again = client.get("/api/coach/narrative").json()
    assert again["status"] == "ok"
    assert again["stale"] is False
    assert again["id"] == body["id"]

    listing = client.get("/api/coach").json()
    assert len(listing["reports"]) == 1
    assert listing["reports"][0]["id"] == body["id"]

    # A second POST keeps both rows -- history, never an upsert.
    resp2 = client.post("/api/coach/narrative")
    assert resp2.status_code == 200
    listing2 = client.get("/api/coach").json()
    assert len(listing2["reports"]) == 2


def test_generate_coach_narrative_stores_and_returns_the_cache_counts(monkeypatch, client):
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: LLMConfig(api_key="k"))

    def _fake_write_report(prompt, *, cfg, label, allowed_domains, max_searches=8):
        return Completion(
            text="Report.", model="claude-opus-5", input_tokens=300, output_tokens=50,
            cost_usd=0.01, citations=(), web_search_requests=1,
            cache_creation_input_tokens=9000, cache_read_input_tokens=0,
        )

    monkeypatch.setattr(llm_client_module, "write_report", _fake_write_report)

    body = client.post("/api/coach/narrative").json()
    assert body["input_tokens"] == 300
    assert body["cache_creation_input_tokens"] == 9000
    assert body["cache_read_input_tokens"] == 0

    again = client.get("/api/coach/narrative").json()
    assert again["id"] == body["id"]
    assert again["cache_creation_input_tokens"] == 9000
    assert again["cache_read_input_tokens"] == 0


# --- GET /api/coach: the model dropdown's own data --------------------------


def test_coach_get_lists_report_models_with_prices(monkeypatch, empty_client):
    monkeypatch.setattr(
        llm_config_module, "load_coach", lambda: LLMConfig(api_key="k", model="claude-sonnet-5")
    )
    body = empty_client.get("/api/coach").json()
    assert [m["id"] for m in body["models"]] == list(llm_client_module.REPORT_MODELS)
    for option in body["models"]:
        price = llm_client_module._PRICES[option["id"]]
        assert option["input_per_mtok"] == pytest.approx(price[0])
        assert option["output_per_mtok"] == pytest.approx(price[1])
        assert option["label"] == llm_client_module.REPORT_MODELS[option["id"]]
    assert body["default_model"] == "claude-sonnet-5"


def test_coach_get_default_model_is_none_without_a_credential(monkeypatch, empty_client):
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: None)
    body = empty_client.get("/api/coach").json()
    assert body["default_model"] is None
    # The dropdown's own options are still listed -- they don't depend on a
    # credential existing, only the ability to pick one once there is one.
    assert [m["id"] for m in body["models"]] == list(llm_client_module.REPORT_MODELS)


# --- POST /api/coach/narrative: the model dropdown's override --------------


def test_post_with_a_chosen_model_reaches_write_report_unchanged(monkeypatch, client):
    monkeypatch.setattr(
        llm_config_module, "load_coach",
        lambda: LLMConfig(api_key="k", model="claude-opus-5", effort="high"),
    )
    captured: dict = {}

    def _fake_write_report(prompt, *, cfg, label, allowed_domains, max_searches=8):
        captured["cfg"] = cfg
        return Completion(
            text="Report.", model=cfg.model, input_tokens=10, output_tokens=10,
            cost_usd=0.001, citations=(), web_search_requests=0,
        )

    monkeypatch.setattr(llm_client_module, "write_report", _fake_write_report)

    resp = client.post("/api/coach/narrative", json={"model": "claude-fable-5-1"})
    assert resp.status_code == 200
    # The chosen model overrides cfg.model; effort still comes from config.
    assert captured["cfg"].model == "claude-fable-5-1"
    assert captured["cfg"].effort == "high"


def test_post_with_no_body_still_uses_the_configured_model(monkeypatch, client):
    monkeypatch.setattr(
        llm_config_module, "load_coach",
        lambda: LLMConfig(api_key="k", model="claude-sonnet-5", effort="low"),
    )
    captured: dict = {}

    def _fake_write_report(prompt, *, cfg, label, allowed_domains, max_searches=8):
        captured["cfg"] = cfg
        return Completion(
            text="Report.", model=cfg.model, input_tokens=10, output_tokens=10,
            cost_usd=0.001, citations=(), web_search_requests=0,
        )

    monkeypatch.setattr(llm_client_module, "write_report", _fake_write_report)

    resp = client.post("/api/coach/narrative")
    assert resp.status_code == 200
    assert captured["cfg"].model == "claude-sonnet-5"


@pytest.mark.parametrize("bad_model", ["claude-haiku-4-5", "nope"])
def test_post_with_a_disallowed_model_gives_422_and_never_calls_write_report(
    monkeypatch, client, bad_model
):
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: LLMConfig(api_key="k"))

    def _boom(*args, **kwargs):
        raise AssertionError("write_report ran with a disallowed model")

    monkeypatch.setattr(llm_client_module, "write_report", _boom)

    resp = client.post("/api/coach/narrative", json={"model": bad_model})
    assert resp.status_code == 422
    for allowed in llm_client_module.REPORT_MODELS:
        assert allowed in resp.json()["detail"]


def test_post_with_a_chosen_model_but_no_credential_still_gives_503(monkeypatch, client):
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: None)

    def _boom(*args, **kwargs):
        raise AssertionError("write_report ran with no credential configured")

    monkeypatch.setattr(llm_client_module, "write_report", _boom)

    resp = client.post("/api/coach/narrative", json={"model": "claude-fable-5-1"})
    assert resp.status_code == 503


# --- GET routes on a stored report: read-time prose cleaning and web sources ---


def test_stored_report_prose_is_cleaned_and_web_sources_are_appended(tmp_path, make_client):
    """A stored report carrying both shapes measured on the real DB on
    2026-09-22 (docs/coach.md): narration glued mid-line to the first
    heading, and a ``## Sources`` section whose web line was never
    recorded in ``sources_json`` because the call returned no citation
    object. Written directly with ``write_coach_report`` -- this is a
    read-time fix (1a/1b), so it only needs a row already in that shape,
    never a real ``write_report`` call."""
    db_path = tmp_path / "stored.db"
    conn = open_database(db_path)
    r1 = next(e for e in CANON if e.id == 1)
    prose = (
        "I'll start by gathering the current-format facts.## Player profile\n\n"
        "You are a 50% player.\n\n"
        "## Sources\n\n"
        f'- [R1] {r1.author}, "{r1.title}"\n'
        "Web:\n"
        '- mtgdecks.net, "Standard metagame" — https://mtgdecks.net/Standard\n'
        '- Some Blog, "Not on the allowlist" — https://example.com/article\n'
    )
    write_coach_report(
        conn, format="Standard", prose=prose, prompt="prompt text", model="claude-opus-5",
        sources=["R1"], metrics={"version": 1}, context_hash="hash1",
    )
    conn.commit()
    conn.close()

    with make_client(create_app(db_path)) as c:
        resp = c.get("/api/coach/narrative")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["narrative"].startswith("## Player profile")
    assert "I'll start by gathering" not in body["narrative"]

    # The reading id (already in sources_json) comes first, then the web
    # source parsed from the prose's own "## Sources" section; the
    # non-allowlisted URL never appears.
    assert [s["kind"] for s in body["sources"]] == ["reading", "web"]
    assert body["sources"][0]["label"] == "R1"
    assert body["sources"][1]["url"] == "https://mtgdecks.net/Standard"
    assert not any(s["url"] == "https://example.com/article" for s in body["sources"])


# --- the format parameter (plan 13, D12/D13) -------------------------------


def _fake_completion(prompt, *, cfg, label, allowed_domains, max_searches=8):
    return Completion(
        text="## Focus areas\nReport.", model="claude-opus-5", input_tokens=10,
        output_tokens=10, cost_usd=0.001, citations=(), web_search_requests=0,
    )


def test_every_route_names_the_default_format_when_none_is_asked_for(client, empty_client):
    """All ten matches are Standard, so D13's default is Standard; an empty
    database has no match at all, and the default falls back to Standard."""
    assert client.get("/api/coach").json()["format"] == "Standard"
    assert client.get("/api/coach/narrative").json()["format"] == "Standard"
    assert empty_client.get("/api/coach").json()["format"] == "Standard"
    assert empty_client.get("/api/coach/narrative").json()["format"] == "Standard"


def _recent_modern_db(tmp_path):
    """Ten Standard matches in 2026-01..09, then one Modern match on
    2026-09-20: the most recent match is Modern, so Modern is D13's default."""
    db_path = tmp_path / "recent-modern.db"
    conn = open_database(db_path)
    for i in range(10):
        _insert_match(
            conn, f"m{i}", "win" if i % 2 == 0 else "loss",
            started_at=f"2026-0{1 + i % 9}-0{1 + i % 9}T00:00:00",
        )
    _insert_match(conn, "modern1", "win", started_at="2026-09-20T00:00:00", fmt="Modern")
    conn.commit()
    conn.close()
    return db_path


def test_the_default_follows_the_most_recent_match(tmp_path, make_client):
    db_path = _recent_modern_db(tmp_path)
    with make_client(create_app(db_path)) as c:
        assert c.get("/api/coach").json()["format"] == "Modern"
        assert c.get("/api/coach/narrative").json()["format"] == "Modern"
        assert c.get("/api/coach?format=Standard").json()["format"] == "Standard"


def test_a_format_asked_for_is_the_one_used(client):
    """A Modern report on ten Standard matches: the skill population (10)
    still clears the minimum, so there is evidence and a prompt, for Modern."""
    body = client.get("/api/coach?format=Modern").json()
    assert body["format"] == "Modern"
    assert body["sufficient"] is True
    assert body["evidence"]["population"] == 10
    narrative = client.get("/api/coach/narrative?format=Modern").json()
    assert (narrative["format"], narrative["status"]) == ("Modern", "prompt")
    assert "This report is about their Modern play." in narrative["prompt"]


@pytest.mark.parametrize("path", ["/api/coach", "/api/coach/narrative"])
def test_an_unknown_format_is_a_422_on_the_get_routes(client, path):
    assert client.get(f"{path}?format=Commander").status_code == 422


def test_an_unknown_format_is_a_422_on_post_and_never_calls_write_report(monkeypatch, client):
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: LLMConfig(api_key="k"))

    def _boom(*args, **kwargs):
        raise AssertionError("write_report ran for an unknown format")

    monkeypatch.setattr(llm_client_module, "write_report", _boom)
    assert client.post("/api/coach/narrative?format=Commander").status_code == 422


def test_a_report_is_stored_under_its_format_and_is_only_that_formats_latest(
    monkeypatch, client
):
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(llm_client_module, "write_report", _fake_completion)

    posted = client.post("/api/coach/narrative?format=Modern").json()
    assert (posted["status"], posted["format"]) == ("ok", "Modern")

    listing = client.get("/api/coach").json()
    assert [(r["id"], r["format"]) for r in listing["reports"]] == [(posted["id"], "Modern")]

    # The default (Standard) has no report of its own yet.
    standard = client.get("/api/coach/narrative").json()
    assert (standard["format"], standard["status"]) == ("Standard", "prompt")

    modern = client.get("/api/coach/narrative?format=Modern").json()
    assert (modern["status"], modern["id"], modern["stale"]) == ("ok", posted["id"], False)

    by_id = client.get(f"/api/coach/narrative/{posted['id']}").json()
    assert by_id["format"] == "Modern"


def test_a_report_from_before_formats_reads_as_standard(tmp_path, make_client):
    """Migration 059 leaves every earlier row's format NULL, which every
    reader takes as Standard."""
    db_path = tmp_path / "pre059.db"
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO coach_report (generated_at, format, model, effort, prompt, prose, "
        "sources_json, metrics_json, context_hash) VALUES ('2026-08-01T00:00:00', NULL, "
        "'claude-opus-5', 'high', 'p', '## Player profile\nOld.', '[]', '{\"version\": 1}', 'h')"
    )
    conn.commit()
    conn.close()
    with make_client(create_app(db_path)) as c:
        listing = c.get("/api/coach").json()
        assert [r["format"] for r in listing["reports"]] == ["Standard"]
        latest = c.get("/api/coach/narrative?format=Standard").json()
        assert (latest["status"], latest["format"]) == ("ok", "Standard")
        assert c.get("/api/coach/narrative?format=Modern").json()["status"] == "no_report"


def test_a_post_with_no_format_stores_the_resolved_default(monkeypatch, tmp_path, make_client):
    """The default is Modern here, so the stored row must say Modern: a
    route that stored the unresolved None would read back as Standard."""
    monkeypatch.setattr(llm_config_module, "load_coach", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(llm_client_module, "write_report", _fake_completion)
    db_path = _recent_modern_db(tmp_path)
    with make_client(create_app(db_path)) as c:
        posted = c.post("/api/coach/narrative").json()
    assert (posted["status"], posted["format"]) == ("ok", "Modern")

    conn = open_database(db_path)
    stored = conn.execute(
        "SELECT format FROM coach_report WHERE id = ?", (posted["id"],)
    ).fetchone()
    conn.close()
    assert stored[0] == "Modern"
