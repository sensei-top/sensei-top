"""The rules-notes block (``ai/rules_notes.py``: ``notes_for_prompt``,
``render_block``, ``parse_block``, ``cited_notes``). The block's wording is the
orchestrator's verbatim input; every expectation here is written by hand from
that format, never copied from a run."""

from __future__ import annotations

import logging

from sensei_top.ai import rules_notes
from sensei_top.ai.rules_notes import (
    CLOSING_INSTRUCTION,
    RULES_NOTES_HEADING,
    RulesNote,
    append_block,
    cited_notes,
    notes_for_prompt,
    parse_block,
    render_block,
)
from sensei_top.ai.rules_questions import RulesQuestion
from sensei_top.db import open_database

V = "2026-11-01"
Q1 = "How does Test Bolt interact with Test Bear?"
Q2 = "How does flashback work on Test Spell?"
Q3 = "What happens if my opponent casts Test Trick in response to Test Bolt?"
RULE = {"type": "rule", "ref": "704.5g", "quote": "q"}
CARD = {"type": "card", "ref": "Test Bear", "quote": "q"}
Q4 = "How does Test Wall interact with Test Bear?"


def _q(text: str) -> RulesQuestion:
    return RulesQuestion(text, "T1", ())


def _note(question, *, outcome="answered", confidence="high", **answer) -> RulesNote:
    answer.setdefault("verdict", "Yes.")
    answer.setdefault("explanation", "It works.")
    answer.setdefault("citations", [])
    answer.setdefault("out_of_scope", False)
    return RulesNote(question, V, outcome, answer, confidence, "2026-11-17T00:00:00Z")


def _db(tmp_path, notes):
    conn = open_database(tmp_path / "n.db")
    rules_notes.store(conn, notes)
    return conn


def test_the_block_is_the_heading_numbered_lines_a_blank_line_and_the_instruction(tmp_path):
    conn = _db(tmp_path, [
        _note(Q1, confidence="medium", citations=[RULE, CARD],
              verdict="No.", explanation="Because of a rule."),
        _note(Q2, confidence=None),
    ])
    notes = notes_for_prompt(conn, [_q(Q1), _q(Q2)])
    assert render_block(notes) == (
        RULES_NOTES_HEADING + "\n"
        f"N1 (medium) Q: {Q1} A: No. Because of a rule. (cites 704.5g, Test Bear)\n"
        f"N2 (unrated) Q: {Q2} A: Yes. It works.\n\n" + CLOSING_INSTRUCTION
    )
    assert RULES_NOTES_HEADING == (
        "Rules notes (a rules assistant's answers to questions about cards in this "
        "evidence; each one can be wrong):"
    )


def test_no_notes_renders_nothing_and_leaves_the_prompt_alone():
    assert render_block([]) == ""
    assert append_block("prompt", "") == "prompt"
    assert append_block("prompt", "block") == "prompt\n\n---\n\nblock"


def test_a_note_stays_on_one_line(tmp_path):
    conn = _db(tmp_path, [_note(Q1, verdict="Yes.\n", explanation="One\n\n  two\tthree.")])
    block = render_block(notes_for_prompt(conn, [_q(Q1)]))
    lines = block.split("\n")
    assert lines[1] == f"N1 (high) Q: {Q1} A: Yes. One two three."
    assert lines[2] == ""


def test_refused_out_of_scope_and_unanswered_questions_are_left_out(tmp_path):
    conn = _db(tmp_path, [
        _note(Q1, outcome="refused"),
        _note(Q2, out_of_scope=True),
        _note(Q4),
    ])
    notes = notes_for_prompt(conn, [_q(Q1), _q(Q2), _q(Q3), _q(Q4)])
    assert [n.question for n in notes] == [Q4]
    assert render_block(notes).split("\n")[1].startswith(f"N1 (high) Q: {Q4} A:")


def test_notes_follow_the_questions_order_and_the_latest_rules_version(tmp_path):
    conn = _db(tmp_path, [_note(Q2), _note(Q1)])
    rules_notes.store(conn, [RulesNote(
        Q1, "2026-12-01", "answered",
        {"verdict": "Newer.", "explanation": "Newest rules.", "citations": []},
        "low", "2026-11-18T00:00:00Z",
    )])
    notes = notes_for_prompt(conn, [_q(Q2), _q(Q1)])
    assert [n.question for n in notes] == [Q2, Q1]
    assert notes[1].verdict == "Newer." and notes[1].confidence == "low"


def test_parse_round_trips_the_markers_and_questions(tmp_path):
    conn = _db(tmp_path, [_note(Q1), _note(Q3)])
    block = render_block(notes_for_prompt(conn, [_q(Q1), _q(Q3)]))
    prompt = append_block("framing\n\n---\n\nevidence", block) + "\n\n---\n\ncontract"
    assert parse_block(prompt) == [("N1", Q1), ("N2", Q3)]
    assert parse_block("framing\n\n---\n\nevidence") == []


def test_cited_notes_read_lone_grouped_and_adjacent_markers(tmp_path):
    conn = _db(tmp_path, [
        _note(Q1, citations=[RULE]), _note(Q2, confidence="low"), _note(Q3), _note(Q4),
    ])
    questions = [_q(Q1), _q(Q2), _q(Q3), _q(Q4)]
    prompt = append_block("evidence", render_block(notes_for_prompt(conn, questions)))
    text = "A [N3]. B [N1, N4]. C [N4][N2]. D [N1]."
    cited = cited_notes(conn, prompt, text)
    assert [c["marker"] for c in cited] == ["N3", "N1", "N4", "N2"]
    by_marker = {c["marker"]: c for c in cited}
    assert by_marker["N1"]["citations"] == ["704.5g"]
    assert by_marker["N1"]["question"] == Q1
    assert by_marker["N2"]["confidence"] == "low"
    assert by_marker["N3"]["confidence"] == "high"
    assert by_marker["N3"]["rules_version"] == V


def test_an_unknown_marker_is_dropped_with_one_warning(tmp_path, caplog):
    conn = _db(tmp_path, [_note(Q1)])
    prompt = append_block("evidence", render_block(notes_for_prompt(conn, [_q(Q1)])))
    with caplog.at_level(logging.WARNING, logger="sensei_top.ai.rules_notes"):
        cited = cited_notes(conn, prompt, "Yes [N1]. No [N7]. Again [N7].")
    assert [c["marker"] for c in cited] == ["N1"]
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert cited_notes(conn, "no block here", "[N1]") == []
