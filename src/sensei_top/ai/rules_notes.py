"""The ``rules_note`` store: the hosted coach's answers to rules questions,
kept so the same question is never asked twice (``docs/llm.md``, "Rules
notes").

``question_hash`` is the one definition of "the same question"; every reader
and writer keys through it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RulesNote:
    """One stored answer. ``answer`` is the coach's response as received."""

    question: str
    rules_version: str
    outcome: str
    answer: dict[str, Any]
    confidence: str | None
    asked_at: str

    @property
    def question_hash(self) -> str:
        return question_hash(self.question)


def question_hash(question: str) -> str:
    """SHA-256 hex of ``question`` after ``strip()`` and whitespace collapse;
    case is kept, since a card name's case is not noise."""
    return hashlib.sha256(" ".join(question.split()).encode("utf-8")).hexdigest()


def store(conn: sqlite3.Connection, notes: Iterable[RulesNote]) -> list[str]:
    """Upsert ``notes``; a row is replaced only by one with a newer or equal
    ``asked_at`` for the same ``(question_hash, rules_version)``. Returns the
    hashes, in order. The caller owns the transaction."""
    hashes = []
    for note in notes:
        digest = note.question_hash
        conn.execute(
            "INSERT INTO rules_note (question_hash, rules_version, question, outcome, "
            "answer_json, confidence, asked_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (question_hash, rules_version) DO UPDATE SET "
            "question = excluded.question, outcome = excluded.outcome, "
            "answer_json = excluded.answer_json, confidence = excluded.confidence, "
            "asked_at = excluded.asked_at WHERE excluded.asked_at >= rules_note.asked_at",
            (
                digest, note.rules_version, note.question, note.outcome,
                json.dumps(note.answer, sort_keys=True), note.confidence, note.asked_at,
            ),
        )
        hashes.append(digest)
    return hashes


def lookup(
    conn: sqlite3.Connection, hashes: Sequence[str], rules_version: str | None = None
) -> dict[str, RulesNote]:
    """The stored note per hash. With ``rules_version`` None, the latest
    version for each hash (the greatest ``rules_version`` string, then the
    newest ``asked_at``). The greatest string is the latest because the
    coach's ``rules_version`` is the Comprehensive Rules' ISO effective date
    (YYYY-MM-DD), so string order is date order; a hash with no row is absent from the result."""
    found: dict[str, RulesNote] = {}
    if not hashes:
        return found
    marks = ",".join("?" * len(hashes))
    sql = (
        "SELECT question_hash, rules_version, question, outcome, answer_json, "
        f"confidence, asked_at FROM rules_note WHERE question_hash IN ({marks})"
    )
    params: list[str] = list(hashes)
    if rules_version is not None:
        sql += " AND rules_version = ?"
        params.append(rules_version)
    sql += " ORDER BY rules_version, asked_at"
    for row in conn.execute(sql, params):
        found[row[0]] = RulesNote(
            question=row[2], rules_version=row[1], outcome=row[3],
            answer=json.loads(row[4]), confidence=row[5], asked_at=row[6],
        )
    return found
