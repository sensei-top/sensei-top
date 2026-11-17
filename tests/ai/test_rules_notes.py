"""``ai/rules_notes.py`` and ``PUT /api/rules-notes``: the hosted coach's
rules answers, stored as received. Expectations are the spec's (S8 of the
plan): the hash is SHA-256 over the whitespace-collapsed question, a newer
``asked_at`` replaces a row, ``try_again`` and a fifth note are 422, and the
guard header is required.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from sensei_top.ai import rules_notes
from sensei_top.ai.rules_notes import RulesNote
from sensei_top.api import create_app
from sensei_top.db import open_database
from sensei_top.projector.matches import project


def _note(question="Does it die?", version="r1", asked_at="2026-11-01T00:00:00Z", **kw):
    return RulesNote(
        question=question, rules_version=version, outcome=kw.get("outcome", "answered"),
        answer=kw.get("answer", {"verdict": "yes"}), confidence=kw.get("confidence", "high"),
        asked_at=asked_at,
    )


def _answer(conn, note):
    return rules_notes.lookup(conn, [note.question_hash])[note.question_hash].answer


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _body(n=1, **over):
    note = {
        "question": "Does it die?", "rules_version": "r1", "outcome": "answered",
        "verdict": "yes", "explanation": "because", "citations": ["704.5g"],
        "confidence": "high", "out_of_scope": False,
    } | over
    return {"notes": [dict(note, question=f"{note['question']} {i}") for i in range(n)]}


@pytest.fixture
def client(tmp_path, make_client):
    db = tmp_path / "api.db"
    open_database(db).close()
    return make_client(create_app(db)), db


def test_hash_collapses_whitespace_and_keeps_case():
    expected = hashlib.sha256(b"does it die?").hexdigest()
    assert rules_notes.question_hash("  does   it\n die? ") == expected
    assert rules_notes.question_hash("Does it die?") != expected


def test_store_lookup_round_trip(conn):
    note = _note()
    assert rules_notes.store(conn, [note]) == [note.question_hash]
    got = rules_notes.lookup(conn, [note.question_hash, "missing"])
    assert got == {note.question_hash: note}


def test_upsert_newer_replaces_older_does_not(conn):
    old = _note(asked_at="2026-11-01T00:00:00Z", answer={"verdict": "old"})
    new = _note(asked_at="2026-11-02T00:00:00Z", answer={"verdict": "new"})
    rules_notes.store(conn, [old])
    rules_notes.store(conn, [new])
    assert _answer(conn, old) == {"verdict": "new"}
    rules_notes.store(conn, [old])
    assert _answer(conn, old) == {"verdict": "new"}
    assert conn.execute("SELECT COUNT(*) FROM rules_note").fetchone()[0] == 1


def test_upsert_equal_asked_at_keeps_the_second(conn):
    first = _note(answer={"verdict": "first"})
    second = _note(answer={"verdict": "second"})
    rules_notes.store(conn, [first])
    rules_notes.store(conn, [second])
    assert _answer(conn, first) == {"verdict": "second"}


def test_lookup_latest_version_unless_asked(conn):
    a, b = _note(version="r1"), _note(version="r2")
    rules_notes.store(conn, [a, b])
    h = a.question_hash
    assert rules_notes.lookup(conn, [h])[h].rules_version == "r2"
    assert rules_notes.lookup(conn, [h], "r1")[h].rules_version == "r1"
    assert rules_notes.lookup(conn, [h], "r9") == {}


def test_put_stores_and_returns_hashes(client):
    c, db = client
    r = c.put("/api/rules-notes", json=_body(2))
    assert r.status_code == 200
    hashes = r.json()["question_hashes"]
    assert hashes == [rules_notes.question_hash(f"Does it die? {i}") for i in range(2)]
    conn = open_database(db)
    assert conn.execute("SELECT COUNT(*) FROM rules_note").fetchone()[0] == 2
    conn.close()


@pytest.mark.parametrize("outcome", ["try_again", "error"])
def test_put_refuses_outcomes_that_are_never_stored(client, outcome):
    c, db = client
    assert c.put("/api/rules-notes", json=_body(outcome=outcome)).status_code == 422
    conn = open_database(db)
    assert conn.execute("SELECT COUNT(*) FROM rules_note").fetchone()[0] == 0
    conn.close()


def test_put_refuses_five_notes_and_a_long_question(client):
    c, _ = client
    assert c.put("/api/rules-notes", json=_body(5)).status_code == 422
    assert c.put("/api/rules-notes", json=_body(question="x" * 501)).status_code == 422


def test_put_without_the_client_header_is_403(client):
    _, db = client
    bare = TestClient(create_app(db), base_url="http://127.0.0.1:8000")
    assert bare.put("/api/rules-notes", json=_body()).status_code == 403


def test_a_rebuild_leaves_rules_notes_alone(conn):
    rules_notes.store(conn, [_note()])
    project(conn)
    assert conn.execute("SELECT COUNT(*) FROM rules_note").fetchone()[0] == 1
