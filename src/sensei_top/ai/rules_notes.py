"""The ``rules_note`` store: the hosted coach's answers to rules questions,
kept so the same question is never asked twice (``docs/llm.md``, "Rules
notes").

``question_hash`` is the one definition of "the same question"; every reader
and writer keys through it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

RULES_NOTES_HEADING = (
    "Rules notes (a rules assistant's answers to questions about cards in this "
    "evidence; each one can be wrong):"
)
CLOSING_INSTRUCTION = (
    "Use a note only where it bears on what you are writing, and only for what it says. "
    "When a sentence relies on a note, end that sentence with the note's marker in "
    "brackets, such as [N1]; in a JSON answer, the marker goes inside the text field it "
    "supports. Never state a note's confidence level."
)
_DIVIDER = "\n\n---\n\n"


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


@dataclass(frozen=True, slots=True)
class PromptNote:
    """One note as the prompt shows it; ``citations`` already rendered."""

    question: str
    verdict: str
    explanation: str
    citations: tuple[str, ...]
    confidence: str | None
    rules_version: str


def _flat(text: Any) -> str:
    return " ".join(str(text or "").split())


def _citation(raw: Any) -> str:
    """A citation as the coach returns it, ``{"type", "ref", "quote"}``, rendered
    as its ``ref`` (the rule number, or the card's name); a plain string is
    kept as is."""
    if isinstance(raw, dict):
        return _flat(raw.get("ref"))
    return _flat(raw)


def notes_for_prompt(conn: sqlite3.Connection, questions: Sequence[Any]) -> list[PromptNote]:
    """The stored notes for ``questions`` (``rules_questions.RulesQuestion``,
    in the order given): latest rules version, only ``answered`` and not
    ``out_of_scope``; a question with no stored note is skipped."""
    hashes = [question_hash(q.question) for q in questions]
    found = lookup(conn, hashes)
    notes = []
    for q, digest in zip(questions, hashes, strict=True):
        note = found.get(digest)
        if note is None or note.outcome != "answered" or note.answer.get("out_of_scope"):
            continue
        verdict = _flat(note.answer.get("verdict"))
        explanation = _flat(note.answer.get("explanation"))
        if not verdict and not explanation:
            continue
        cites = tuple(c for c in map(_citation, note.answer.get("citations") or []) if c)
        notes.append(PromptNote(
            _flat(q.question), verdict, explanation, cites, note.confidence,
            note.rules_version,
        ))
    return notes


def render_block(notes: Sequence[PromptNote]) -> str:
    """The prompt's notes block, or ``""`` for no notes."""
    if not notes:
        return ""
    lines = [RULES_NOTES_HEADING]
    for n, note in enumerate(notes, 1):
        answer = " ".join(part for part in (note.verdict, note.explanation) if part)
        cites = f" (cites {', '.join(note.citations)})" if note.citations else ""
        lines.append(
            f"N{n} ({note.confidence or 'unrated'}) Q: {note.question} A: {answer}{cites}"
        )
    return "\n".join(lines) + "\n\n" + CLOSING_INSTRUCTION


def append_block(prompt: str, block: str) -> str:
    """``prompt`` then the block after the prompts' divider; ``prompt``
    itself, byte for byte, when ``block`` is empty."""
    return f"{prompt}{_DIVIDER}{block}" if block else prompt


_LINE_RE = re.compile(r"^(N\d+) \([a-z]+\) Q: (.*?) A: ")


def parse_block(prompt: str) -> list[tuple[str, str]]:
    """``(marker, question)`` for each line of the notes block in ``prompt``,
    in order; empty when there is no block."""
    at = prompt.find(RULES_NOTES_HEADING + "\n")
    if at < 0:
        return []
    found = []
    for line in prompt[at:].split("\n")[1:]:
        match = _LINE_RE.match(line)
        if match is None:
            break
        found.append((match.group(1), match.group(2)))
    return found


_MARKER_GROUP_RE = re.compile(r"\[N\d+(?:\s*[;,]\s*N\d+)*\]")
_MARKER_RE = re.compile(r"N\d+")
_STRIP_RE = re.compile(
    r"^[ \t]*" + _MARKER_GROUP_RE.pattern + r"[ \t]*|[ \t]*" + _MARKER_GROUP_RE.pattern,
    re.MULTILINE,
)


def strip_markers(text: str) -> str:
    """``text`` without its ``[N<n>]`` markers (lone or grouped) and the
    spaces before them (after them, for one that starts the text or a line),
    for a reader that carries no notes."""
    return _STRIP_RE.sub("", text)


def cited_notes(conn: sqlite3.Connection, prompt: str, text: str) -> list[dict[str, Any]]:
    """The notes ``text`` cites with ``[N<n>]`` (lone, grouped ``[N1, N3]`` or
    adjacent), in first-appearance order, deduplicated, as ``RulesNoteOut``
    fields. A marker the prompt's block never offered, or whose note is gone,
    is dropped and logged once at WARNING, never raised."""
    block = dict(parse_block(prompt))
    cited: list[str] = []
    for group in _MARKER_GROUP_RE.finditer(text):
        for marker in _MARKER_RE.findall(group.group()):
            if marker not in cited:
                cited.append(marker)
    found = lookup(conn, [question_hash(q) for q in block.values()])
    result = []
    for marker in cited:
        question = block.get(marker)
        note = found.get(question_hash(question)) if question is not None else None
        if note is None:
            log.warning("text cited rules note %s, which the prompt did not offer", marker)
            continue
        result.append({
            "marker": marker,
            "question": _flat(question),
            "verdict": _flat(note.answer.get("verdict")),
            "explanation": _flat(note.answer.get("explanation")),
            "citations": [c for c in map(_citation, note.answer.get("citations") or []) if c],
            "confidence": note.confidence,
            "rules_version": note.rules_version,
        })
    return result
