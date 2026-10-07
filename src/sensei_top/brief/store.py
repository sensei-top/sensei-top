"""The cache, and the only module in this package that writes.

A brief is keyed on ``(deck_key, archetype_key)`` and stamped with the 75 it
was written for (``list_hash``) and the corpus snapshot it reasoned from
(``corpus_commit``). Both feed ``is_stale``: a changed 75 means the board
plan may name cards the deck no longer holds, and a moved corpus means the
field it reasoned about has shifted. Neither is acted on automatically —
nothing in this project writes a brief on its own (AGENTS.md non-negotiable
#5) — so staleness is reported and the reader decides whether to rewrite.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from sensei_top.guide.narrative import BoardCard
from sensei_top.guide.plans import PlanProblem
from sensei_top.llm.provenance import upsert_authored


@dataclass(frozen=True, slots=True)
class PlayAround:
    card: str
    why: str


@dataclass(frozen=True, slots=True)
class Staple:
    name: str
    copies: float
    share: float


@dataclass(frozen=True, slots=True)
class Brief:
    deck_key: str
    archetype_key: str
    archetype_label: str | None
    archetype_share: float | None  # this archetype's share of the classified field
    personal_matches: int | None
    personal_wins: int | None
    personal_losses: int | None
    prose: str
    play_around: tuple[PlayAround, ...]
    board_in: tuple[BoardCard, ...]
    board_out: tuple[BoardCard, ...]
    staples: tuple[Staple, ...]
    problems: tuple[PlanProblem, ...]
    prompt: str
    model: str
    generated_at: str
    corpus_commit: str | None
    list_hash: str
    source: str  # "live" | "guide"
    # NULL for a hand-imported brief, or one written via `store_guide_matchups`
    # -- the guide's one Claude call is priced once, on `deck_narrative`, and
    # splitting it across the matchups it also filled would be a fabricated
    # number rather than a measured one (AGENTS.md non-negotiable #4).
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


def list_hash(current_cards: dict) -> str:
    """A stable hash of both boards, in the order they'd have to change in
    for a stored plan to go wrong: a sideboard edit invalidates the IN half
    of a plan just as much as a maindeck edit invalidates the play-around
    list, so both boards are hashed, not just one."""
    maindeck = sorted(dict(_counts(current_cards.get("maindeck") or [])).items())
    sideboard = sorted(dict(_counts(current_cards.get("sideboard") or [])).items())
    payload = json.dumps({"maindeck": maindeck, "sideboard": sideboard}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _counts(grp_ids: list[int]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for grp_id in grp_ids:
        counts[grp_id] = counts.get(grp_id, 0) + 1
    return counts


def _dump_play_around(items: tuple[PlayAround, ...]) -> str:
    return json.dumps([{"card": p.card, "why": p.why} for p in items])


def _load_play_around(raw: str) -> tuple[PlayAround, ...]:
    return tuple(PlayAround(card=d["card"], why=d["why"]) for d in json.loads(raw))


def _dump_board(items: tuple[BoardCard, ...]) -> str:
    return json.dumps([{"card": c.card, "n": c.n} for c in items])


def _load_board(raw: str) -> tuple[BoardCard, ...]:
    return tuple(BoardCard(card=d["card"], n=d["n"]) for d in json.loads(raw))


def _dump_staples(items: tuple[Staple, ...]) -> str:
    return json.dumps([{"name": s.name, "copies": s.copies, "share": s.share} for s in items])


def _load_staples(raw: str) -> tuple[Staple, ...]:
    return tuple(
        Staple(name=d["name"], copies=d["copies"], share=d["share"]) for d in json.loads(raw)
    )


def _dump_problems(items: tuple[PlanProblem, ...]) -> str:
    return json.dumps([{"archetype": p.archetype, "message": p.message} for p in items])


def _load_problems(raw: str) -> tuple[PlanProblem, ...]:
    return tuple(
        PlanProblem(archetype=d["archetype"], message=d["message"]) for d in json.loads(raw)
    )


def _brief_from_row(row: sqlite3.Row) -> Brief:
    return Brief(
        deck_key=row["deck_key"],
        archetype_key=row["archetype_key"],
        archetype_label=row["archetype_label"],
        archetype_share=row["archetype_share"],
        personal_matches=row["personal_matches"],
        personal_wins=row["personal_wins"],
        personal_losses=row["personal_losses"],
        prose=row["prose"],
        play_around=_load_play_around(row["play_around_json"]),
        board_in=_load_board(row["board_in_json"]),
        board_out=_load_board(row["board_out_json"]),
        staples=_load_staples(row["staples_json"]),
        problems=_load_problems(row["problems_json"]),
        prompt=row["prompt"],
        model=row["model"],
        generated_at=row["generated_at"],
        corpus_commit=row["corpus_commit"],
        list_hash=row["list_hash"],
        source=row["source"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cost_usd=row["cost_usd"],
    )


def read_brief(conn: sqlite3.Connection, deck_key: str, archetype_key: str) -> Brief | None:
    row = conn.execute(
        "SELECT * FROM matchup_brief WHERE deck_key = ? AND archetype_key = ?",
        (deck_key, archetype_key),
    ).fetchone()
    return _brief_from_row(row) if row is not None else None


def write_brief(conn: sqlite3.Connection, brief: Brief) -> None:
    upsert_authored(
        conn, "matchup_brief",
        {"deck_key": brief.deck_key, "archetype_key": brief.archetype_key},
        {
            "list_hash": brief.list_hash,
            "archetype_label": brief.archetype_label,
            "archetype_share": brief.archetype_share,
            "personal_matches": brief.personal_matches,
            "personal_wins": brief.personal_wins,
            "personal_losses": brief.personal_losses,
            "prose": brief.prose,
            "play_around_json": _dump_play_around(brief.play_around),
            "board_in_json": _dump_board(brief.board_in),
            "board_out_json": _dump_board(brief.board_out),
            "staples_json": _dump_staples(brief.staples),
            "problems_json": _dump_problems(brief.problems),
            "prompt": brief.prompt,
            "model": brief.model,
            "generated_at": brief.generated_at,
            "corpus_commit": brief.corpus_commit,
            "source": brief.source,
            "input_tokens": brief.input_tokens,
            "output_tokens": brief.output_tokens,
            "cost_usd": brief.cost_usd,
        },
    )


def is_stale(
    conn: sqlite3.Connection, brief: Brief, *, current_list_hash: str | None = None
) -> bool:
    """Whether a stored brief no longer describes the situation it was
    written for — either the 75 changed under it (so its board plan may name
    cards the deck no longer holds) or the corpus moved (so the field it
    reasoned about has shifted). Reported, never acted on: rewriting is the
    reader's call, since writing is something they do, not something this
    tool does.
    """
    if current_list_hash is not None and brief.list_hash != current_list_hash:
        return True
    return brief.corpus_commit != corpus_commit(conn)


def corpus_commit(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT commit_sha FROM meta_fetch WHERE id = 1").fetchone()
    return row["commit_sha"] if row else None


def briefs_for_deck(conn: sqlite3.Connection, deck_key: str) -> list[Brief]:
    rows = conn.execute(
        "SELECT * FROM matchup_brief WHERE deck_key = ? ORDER BY generated_at DESC", (deck_key,)
    ).fetchall()
    return [_brief_from_row(row) for row in rows]
