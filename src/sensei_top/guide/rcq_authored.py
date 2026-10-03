"""The RCQ guide's authored prose, stored and read back.

Like ``coach_report``, every generation keeps its own row: a guide is
written against the field of its day, so a later one never replaces it.
``project()`` never reads this table.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from sensei_top.guide.narrative import BoardCard
from sensei_top.guide.plans import PlanProblem
from sensei_top.guide.rcq import FlexNote, RcqMatchup, RcqNarrative
from sensei_top.llm.provenance import now_iso

__all__ = ["StoredRcq", "latest_rcq", "write_rcq"]


@dataclass(frozen=True, slots=True)
class StoredRcq:
    id: int
    deck_key: str
    generated_at: str
    model: str
    decklist_text: str
    expected: tuple[str, ...]
    own_archetype_key: str | None
    prompt: str
    guide: RcqNarrative
    corpus_latest_event: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None


def _narrative_to_json(n: RcqNarrative) -> str:
    return json.dumps({
        "game_plan": n.game_plan,
        "expected_field": n.expected_field,
        "matchups": [
            {
                "archetype": m.archetype, "prose": m.prose, "play_draw": m.play_draw,
                "board_in": [{"card": c.card, "n": c.n} for c in m.board_in],
                "board_out": [{"card": c.card, "n": c.n} for c in m.board_out],
            }
            for m in n.matchups
        ],
        "flex_notes": [{"card": f.card, "role": f.role, "why": f.why} for f in n.flex_notes],
        "checklist": list(n.checklist),
        "problems": [{"archetype": p.archetype, "message": p.message} for p in n.problems],
    })


def _narrative_from_json(raw: str) -> RcqNarrative:
    d = json.loads(raw)
    return RcqNarrative(
        game_plan=d["game_plan"],
        expected_field=d["expected_field"],
        matchups=tuple(
            RcqMatchup(
                archetype=m["archetype"], prose=m["prose"], play_draw=m["play_draw"],
                board_in=tuple(BoardCard(c["card"], c["n"]) for c in m["board_in"]),
                board_out=tuple(BoardCard(c["card"], c["n"]) for c in m["board_out"]),
            )
            for m in d["matchups"]
        ),
        flex_notes=tuple(FlexNote(f["card"], f["role"], f["why"]) for f in d["flex_notes"]),
        checklist=tuple(d["checklist"]),
        problems=tuple(PlanProblem(p["archetype"], p["message"]) for p in d["problems"]),
    )


def write_rcq(
    conn: sqlite3.Connection,
    deck_key: str,
    narrative: RcqNarrative,
    *,
    model: str,
    decklist_text: str,
    expected: list[str] | tuple[str, ...],
    own_archetype_key: str | None,
    prompt: str,
    corpus_latest_event: str | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> int:
    """Append one guide; never replaces an earlier one. Returns its id."""
    cur = conn.execute(
        """
        INSERT INTO rcq_guide (deck_key, generated_at, model, decklist_text,
            expected_json, own_archetype_key, prompt, guide_json,
            corpus_latest_event, input_tokens, output_tokens, cost_usd)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            deck_key, now_iso(), model, decklist_text, json.dumps(list(expected)),
            own_archetype_key, prompt, _narrative_to_json(narrative),
            corpus_latest_event, input_tokens, output_tokens, cost_usd,
        ),
    )
    assert cur.lastrowid is not None
    return cur.lastrowid


def latest_rcq(conn: sqlite3.Connection, deck_key: str) -> StoredRcq | None:
    row = conn.execute(
        "SELECT * FROM rcq_guide WHERE deck_key = ? ORDER BY generated_at DESC, id DESC LIMIT 1",
        (deck_key,),
    ).fetchone()
    if row is None:
        return None
    return StoredRcq(
        id=row["id"], deck_key=row["deck_key"], generated_at=row["generated_at"],
        model=row["model"], decklist_text=row["decklist_text"],
        expected=tuple(json.loads(row["expected_json"])),
        own_archetype_key=row["own_archetype_key"], prompt=row["prompt"],
        guide=_narrative_from_json(row["guide_json"]),
        corpus_latest_event=row["corpus_latest_event"],
        input_tokens=row["input_tokens"], output_tokens=row["output_tokens"],
        cost_usd=row["cost_usd"],
    )
