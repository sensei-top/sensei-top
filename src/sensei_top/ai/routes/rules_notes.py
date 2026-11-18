"""``PUT /api/rules-notes`` stores the hosted coach's rules answers, as
received; ``POST /api/rules-questions`` lists the questions a feature would
ask and which are already answered (``docs/llm.md``, "Rules notes"). Neither
calls a model.

Only an answered or refused question is stored; ``try_again`` and ``error``
never reach the table, so they are 422 here and are never counted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, model_validator

from sensei_top.ai import rules_notes, rules_questions
from sensei_top.ai.routes.narrative import run_authored_write
from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.routes.guide import _no_deck
from sensei_top.api.routes.matches import _no_match
from sensei_top.api.sql import _shared_report_cache, default_format

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


class RulesQuestionsIn(BaseModel):
    """What each feature needs: ``match`` a ``match_id``; ``guide`` a ``key``;
    ``rcq`` a ``key`` and a ``decklist`` (``expected`` and ``own`` as the RCQ
    routes take them); ``coach`` nothing (``fmt`` defaults to the dashboard's).
    A missing one is a 422."""

    feature: Literal["match", "guide", "rcq", "coach"]
    match_id: str | None = None
    key: str | None = None
    decklist: str | None = None
    expected: list[str] = []
    own: str | None = None
    fmt: str | None = None
    rules_version: str | None = Field(
        default=None,
        description="answered means a note under this version; without it, under any",
    )

    @model_validator(mode="after")
    def _has_what_the_feature_needs(self) -> RulesQuestionsIn:
        needed = {"match": ["match_id"], "guide": ["key"], "rcq": ["key", "decklist"]}
        for field in needed.get(self.feature, []):
            if getattr(self, field) is None:
                raise ValueError(f"{field} is required for feature {self.feature}")
        return self


class RulesQuestionOut(BaseModel):
    question: str
    question_hash: str
    template: Literal["T1", "T2", "T3"]
    answered: bool


class RulesQuestionsOut(BaseModel):
    questions: list[RulesQuestionOut]
    reason: Literal[
        "no_card_text", "no_opponent_cards", "no_questions", "no_evidence"
    ] | None = None


def _reason(cards: rules_questions.FeatureCards, feature: str) -> str:
    """Why a feature has no questions, as a key for the dashboard to word."""
    if not any(c.oracle_text for c in (*cards.mine, *cards.theirs)):
        return "no_card_text"
    if not cards.theirs and feature != "coach":
        return "no_opponent_cards"
    return "no_questions"


@router.post("/api/rules-questions", response_model=RulesQuestionsOut)
def post_rules_questions(
    body: RulesQuestionsIn, request: Request, conn: Conn
) -> RulesQuestionsOut:
    """The questions the feature's prompt would ask the coach, at most 4,
    in the order they are asked. POST only because an RCQ guide carries a
    pasted list; it writes nothing, so it is not on the write allowlist. An
    unknown match or deck is a 404."""
    cache = _shared_report_cache(request, conn)
    cards: rules_questions.FeatureCards | None
    if body.feature == "match":
        if conn.execute(
            "SELECT 1 FROM matches WHERE match_id = ?", (body.match_id,)
        ).fetchone() is None:
            raise _no_match(body.match_id)
        cards = rules_questions.for_match(conn, body.match_id)
    elif body.feature == "guide":
        cards = rules_questions.for_guide(conn, body.key, report_cache=cache)
        if cards is None:
            raise _no_deck(body.key)
    elif body.feature == "rcq":
        cards = rules_questions.for_rcq(
            conn, body.key, body.decklist, expected=body.expected, own=body.own,
            report_cache=cache,
        )
        if cards is None:
            raise _no_deck(body.key)
    else:
        cards = rules_questions.for_coach(
            conn, body.fmt or default_format(conn), report_cache=cache
        )
        if cards is None:
            return RulesQuestionsOut(questions=[], reason="no_evidence")

    questions = rules_questions.build_questions(cards.mine, cards.theirs)
    if not questions:
        return RulesQuestionsOut(questions=[], reason=_reason(cards, body.feature))
    hashes = [rules_notes.question_hash(q.question) for q in questions]
    answered = rules_notes.lookup(conn, hashes, body.rules_version)
    return RulesQuestionsOut(questions=[
        RulesQuestionOut(
            question=q.question, question_hash=h, template=q.template, answered=h in answered,
        )
        for q, h in zip(questions, hashes, strict=True)
    ])
