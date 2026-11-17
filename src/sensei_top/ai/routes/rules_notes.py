"""``PUT /api/rules-notes``: store the hosted coach's rules answers, as
received (``docs/llm.md``, "Rules notes"). Calls no model.

Only an answered or refused question is stored; ``try_again`` and ``error``
never reach the table, so they are 422 here and are never counted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from sensei_top.ai import rules_notes
from sensei_top.ai.routes.narrative import run_authored_write
from sensei_top.api.deps import WritableConn

router = APIRouter()

MAX_NOTES = 4
MAX_QUESTION_CHARS = 500


class RulesNoteIn(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    rules_version: str = Field(min_length=1)
    outcome: Literal["answered", "refused"]
    verdict: str | None = None
    explanation: str | None = None
    citations: list[Any] = Field(default_factory=list)
    confidence: str | None = None
    out_of_scope: bool = False


class RulesNotesIn(BaseModel):
    notes: list[RulesNoteIn] = Field(min_length=1, max_length=MAX_NOTES)


class RulesNotesOut(BaseModel):
    question_hashes: list[str]


@router.put("/api/rules-notes", response_model=RulesNotesOut)
def put_rules_notes(body: RulesNotesIn, conn: WritableConn) -> RulesNotesOut:
    asked_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    notes = [
        rules_notes.RulesNote(
            question=n.question,
            rules_version=n.rules_version,
            outcome=n.outcome,
            answer=n.model_dump(
                include={"verdict", "explanation", "citations", "out_of_scope"}
            ),
            confidence=n.confidence,
            asked_at=asked_at,
        )
        for n in body.notes
    ]
    hashes: list[str] = []
    run_authored_write(conn, lambda: hashes.extend(rules_notes.store(conn, notes)))
    return RulesNotesOut(question_hashes=hashes)
