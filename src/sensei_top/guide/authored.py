"""The deck guide's authored prose, stored and read back.

``guide/__init__.py``'s rule 2 says nothing in this package is ever
persisted, because everything else here is a *derivation* of the current
database that a rebuild could silently invalidate. Authored prose is the
stated exception, for the same reason ``brief/`` may persist: it is not
derived from anything, it is written, and it is stamped with the 75
(``list_hash``) and corpus snapshot (``corpus_commit``) it was written about
so a reader can always tell whether it still describes the deck in front of
them.

One import fills two tables: the deck-level half (engine, fix, card notes,
checklist) lands here in ``deck_narrative``, and every matchup plan lands in
``matchup_brief`` via ``brief/from_guide.py`` — so writing one guide also
lights up the live matchup brief on the Live page.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from sensei_top.guide.narrative import CardNote, GuideNarrative, MatchupPlan
from sensei_top.guide.plans import PlanProblem
from sensei_top.llm.provenance import now_iso, upsert_authored


@dataclass(frozen=True, slots=True)
class AuthoredNarrative:
    """A stored ``GuideNarrative`` plus the provenance that says whether it
    still applies. ``matchups`` is rehydrated from ``matchup_brief`` rather
    than duplicated here — one place per matchup, shared with the live
    brief."""

    deck_key: str
    list_hash: str
    engine: str
    fix: str
    card_notes: tuple[CardNote, ...]
    checklist: tuple[str, ...]
    problems: tuple[PlanProblem, ...]
    prompt: str
    author: str
    authored_at: str
    corpus_commit: str | None
    # NULL for a hand-imported narrative -- a real absence, not a cost of
    # zero (AGENTS.md non-negotiable #4).
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


def write_narrative(
    conn: sqlite3.Connection,
    deck_key: str,
    narrative: GuideNarrative,
    *,
    list_hash: str,
    prompt: str,
    author: str,
    corpus_commit: str | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """Replace this deck's stored narrative. One row per deck: re-importing
    is how a guide gets revised, so an upsert is the whole update story.

    Uses ``author``/``authored_at`` rather than the ``model``/``generated_at``
    names ``AuthoredRecord`` holds — a guide can be hand-authored as well as
    Claude-written, so it builds its own columns dict instead of that shared
    shape.
    """
    upsert_authored(
        conn, "deck_narrative", {"deck_key": deck_key},
        {
            "list_hash": list_hash,
            "engine": narrative.engine,
            "fix": narrative.fix,
            "card_notes_json": json.dumps([
                {"card": c.card, "verdict": c.verdict, "why": c.why}
                for c in narrative.card_notes
            ]),
            "checklist_json": json.dumps(list(narrative.checklist)),
            "problems_json": json.dumps([
                {"archetype": p.archetype, "message": p.message} for p in narrative.problems
            ]),
            "prompt": prompt,
            "author": author,
            "authored_at": now_iso(),
            "corpus_commit": corpus_commit,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        },
    )


def read_narrative(conn: sqlite3.Connection, deck_key: str) -> AuthoredNarrative | None:
    row = conn.execute(
        "SELECT * FROM deck_narrative WHERE deck_key = ?", (deck_key,)
    ).fetchone()
    if row is None:
        return None
    return AuthoredNarrative(
        deck_key=row["deck_key"],
        list_hash=row["list_hash"],
        engine=row["engine"],
        fix=row["fix"],
        card_notes=tuple(
            CardNote(card=d["card"], verdict=d["verdict"], why=d["why"])
            for d in json.loads(row["card_notes_json"])
        ),
        checklist=tuple(json.loads(row["checklist_json"])),
        problems=tuple(
            PlanProblem(archetype=d["archetype"], message=d["message"])
            for d in json.loads(row["problems_json"])
        ),
        prompt=row["prompt"],
        author=row["author"],
        authored_at=row["authored_at"],
        corpus_commit=row["corpus_commit"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cost_usd=row["cost_usd"],
    )


def narrative_for(
    conn: sqlite3.Connection, deck_key: str
) -> tuple[AuthoredNarrative, GuideNarrative] | None:
    """The stored narrative, rebuilt into the same ``GuideNarrative`` shape
    the frontend and ``guide/markdown.py`` already render — with
    ``matchups`` read back out of ``matchup_brief``, the one place a matchup
    plan lives.
    """
    from sensei_top.brief.store import briefs_for_deck

    stored = read_narrative(conn, deck_key)
    if stored is None:
        return None
    matchups = tuple(
        MatchupPlan(
            archetype=b.archetype_label or b.archetype_key,
            prose=b.prose,
            board_in=b.board_in,
            board_out=b.board_out,
        )
        for b in briefs_for_deck(conn, deck_key)
    )
    return stored, GuideNarrative(
        engine=stored.engine,
        fix=stored.fix,
        card_notes=stored.card_notes,
        matchups=matchups,
        checklist=stored.checklist,
        problems=stored.problems,
    )
