"""The matchup brief's routes: the briefs and their coverage per deck
(``/api/guide/{key}/briefs*``, ``/coverage*``), the paste routes behind the
brief and coverage cards, and the live brief (``/api/current-match/brief``).
A paste route never calls a model.

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

from sensei_top.ai.llm import client as llm_client_module
from sensei_top.api.app import create_app
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent.parent / "fixtures" / "match_session.log"
ARCHETYPE = "mardu_discard"
OLDER = "0" * 64


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


_BRIEF = {
    "prose": "They race you; trade early.",
    "play_around": [{"card": "Marauding Mako", "why": "grows on every discard"}],
    "board_in": [], "board_out": [],
}


def _brief_prompt(client, key):
    return client.get(f"/api/guide/{key}/briefs/{ARCHETYPE}/prompt").json()["prompt"]


def _coverage_prompt(client, key):
    return client.get(f"/api/guide/{key}/coverage/prompt").json()["prompt"]


@pytest.fixture
def bare_client(tmp_path, make_client):
    """The fixture session with no metagame corpus loaded."""
    db_path = tmp_path / "bare.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


@pytest.fixture
def guide_key(bare_client):
    return bare_client.get("/api/guide/decks").json()[0]["key"]


@pytest.fixture
def live_client(tmp_path, make_client):
    """The fixture session with its final MatchCompleted cut off, so the last
    match (fa7a4d16, the newest by started_at) is still being played."""
    lines = FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    trimmed = tmp_path / "in_progress.log"
    trimmed.write_text("".join(lines[:63]), encoding="utf-8")

    db_path = tmp_path / "live.db"
    conn = open_database(db_path)
    ingest_file(conn, trimmed, locale_hint="mdy")
    project(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


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


def test_guide_coverage_200_shape(bare_client, guide_key):
    body = bare_client.get(f"/api/guide/{guide_key}/coverage").json()
    assert body["fmt"] == "Standard"
    assert isinstance(body["rows"], list)
    assert "matches_covered_numerator" in body
    assert "matches_covered_denominator" in body
    assert "field_covered" in body
    for row in body["rows"]:
        assert row["status"] in ("ok", "stale", "missing")


def test_guide_coverage_404_for_unknown_deck(bare_client):
    resp = bare_client.get("/api/guide/nope/coverage")
    assert resp.status_code == 404


def test_guide_brief_prompt_no_consensus_with_no_corpus_loaded(bare_client, guide_key):
    """The fixture-backed client has no metagame corpus at all, so any
    archetype key asked about here has no field consensus to anchor a
    brief to -- the ordinary 'not yet' outcome, not a server error."""
    resp = bare_client.get(f"/api/guide/{guide_key}/briefs/some_archetype/prompt")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_consensus"
    assert body["archetype_key"] == "some_archetype"
    assert body["prompt"] is None


def test_guide_brief_prompt_404_for_unknown_deck(bare_client):
    resp = bare_client.get("/api/guide/nope/briefs/some_archetype/prompt")
    assert resp.status_code == 404


def test_guide_coverage_prompt_200_with_no_gaps_or_consensus(bare_client, guide_key):
    """No metagame corpus means build_coverage names no archetypes at all
    (nothing faced resolves to a classified archetype_key in this fixture,
    and the field has no top archetypes to report), so there is nothing
    missing to prompt for."""
    resp = bare_client.get(f"/api/guide/{guide_key}/coverage/prompt")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("nothing_missing", "no_consensus")
    assert body["included"] == []
    assert body["deferred"] == []


def test_guide_coverage_prompt_404_for_unknown_deck(bare_client):
    resp = bare_client.get("/api/guide/nope/coverage/prompt")
    assert resp.status_code == 404


def test_guide_coverage_for_a_deck_with_no_format_is_200_with_a_null_format(bare_client, guide_key):
    """With no resolvable format there is no field to list, so
    coverage answers with ``fmt`` null and no rows."""
    conn = sqlite3.connect(bare_client.app.state.database)
    conn.execute("UPDATE decks SET format = 'Draft'")
    conn.execute("UPDATE matches SET format = NULL")
    conn.commit()
    conn.close()

    resp = bare_client.get(f"/api/guide/{guide_key}/coverage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fmt"] is None
    assert body["rows"] == []


def _make_deck_formatless(bare_client):
    conn = sqlite3.connect(bare_client.app.state.database)
    conn.execute("UPDATE decks SET format = 'Draft'")
    conn.execute("UPDATE matches SET format = NULL")
    conn.commit()
    conn.close()


def test_guide_brief_prompt_for_a_deck_with_no_format_is_format_unknown(bare_client, guide_key):
    _make_deck_formatless(bare_client)
    body = bare_client.get(f"/api/guide/{guide_key}/briefs/some_archetype/prompt").json()
    assert body["status"] == "format_unknown"
    assert body["archetype_key"] == "some_archetype"
    assert body["prompt"] is None


def test_guide_coverage_prompt_for_a_deck_with_no_format_is_format_unknown(bare_client, guide_key):
    _make_deck_formatless(bare_client)
    body = bare_client.get(f"/api/guide/{guide_key}/coverage/prompt").json()
    assert body["status"] == "format_unknown"
    assert body["prompt"] is None
    assert body["included"] == [] and body["no_consensus"] == [] and body["deferred"] == []


def test_current_match_brief_for_a_deck_with_no_format_is_format_unknown(live_client):
    """No opponent override: the format is checked before ``unclassified``."""
    _make_deck_formatless(live_client)
    body = live_client.get("/api/current-match/brief").json()
    assert body["status"] == "format_unknown"
    assert body["brief"] is None and body["prompt"] is None


def test_current_match_brief_returns_a_stored_brief_even_with_no_format(live_client):
    """A brief written while the deck had a format is still the user's: with
    the format gone and the opponent picked, the stored brief comes back
    ``ok`` (with its staleness), not ``format_unknown``."""
    from sensei_top.ai.brief.store import Brief, write_brief
    from sensei_top.guide.deck import list_identities

    match_id = "fa7a4d16-afb7-4094-bae2-111092fc71d2"
    conn = sqlite3.connect(live_client.app.state.database)
    conn.row_factory = sqlite3.Row
    identity = list_identities(conn)[0]
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, updated_at, archetype_key) "
        "VALUES (?, 'Some Deck', 't', 'some_deck')",
        (match_id,),
    )
    conn.commit()
    conn.close()
    _make_deck_formatless(live_client)

    # Nothing stored yet: the format is the answer.
    assert live_client.get("/api/current-match/brief").json()["status"] == "format_unknown"

    conn = sqlite3.connect(live_client.app.state.database)
    conn.row_factory = sqlite3.Row
    write_brief(conn, Brief(
        deck_key=identity.key, archetype_key="some_deck", archetype_label="Some Deck",
        archetype_share=None, personal_matches=None, personal_wins=None,
        personal_losses=None, prose="Stored earlier.", play_around=(),
        board_in=(), board_out=(), staples=(), problems=(), prompt="p",
        model="pasted", generated_at="2026-09-01T00:00:00.000Z",
        corpus_commit=None, list_hash="old", source="live",
    ))
    conn.commit()
    conn.close()

    body = live_client.get("/api/current-match/brief").json()
    assert body["status"] == "ok"
    assert body["brief"]["prose"] == "Stored earlier."
    assert body["stale"] is True
    assert body["prompt"] is None
