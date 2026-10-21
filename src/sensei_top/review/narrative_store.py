"""The match report's coaching prose, stored and read back.

``review/__init__.py``'s rule that findings are never persisted is about
*derived* data — analyzer output that a later change could make wrong for
matches computed before it. This table holds the opposite kind of thing:
prose written once (generated or pasted), from a prompt that is stored right
beside it so a reader can always check the two against each other.

``context_hash`` plays the role ``matchup_brief.list_hash`` plays for a
brief: a SHA-256 of the prompt context string itself, so any change to the
evidence — a new finding, an updated field record — is caught without a
per-feature hashing rule. It is reported, never acted on: nothing here
regenerates itself, same posture ``brief/store.py::is_stale`` documents.

``review/leaks_store.py`` is the same pattern for the leak finder's own
narrative, and imports ``context_hash`` from here rather than duplicating it
— the two tables must agree on what "the evidence changed" means.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from sensei_top.llm.provenance import AuthoredRecord, now_iso, upsert_authored

__all__ = [
    "MatchNarrative",
    "context_hash",
    "read_match_narrative",
    "write_match_narrative",
]


def context_hash(context: str) -> str:
    return hashlib.sha256(context.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MatchNarrative:
    match_id: str
    prose: str
    prompt: str
    model: str
    generated_at: str
    context_hash: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


def write_match_narrative(
    conn: sqlite3.Connection,
    match_id: str,
    *,
    prose: str,
    prompt: str,
    model: str,
    context_hash: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """One row per match: re-generating replaces it, the same "write again
    to revise" story ``deck_narrative`` and ``matchup_brief`` use."""
    record = AuthoredRecord(
        prompt=prompt, model=model, generated_at=now_iso(),
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
    )
    upsert_authored(
        conn, "match_narrative", {"match_id": match_id},
        {**record.columns(), "prose": prose, "context_hash": context_hash},
    )


def read_match_narrative(conn: sqlite3.Connection, match_id: str) -> MatchNarrative | None:
    row = conn.execute(
        "SELECT * FROM match_narrative WHERE match_id = ?", (match_id,)
    ).fetchone()
    if row is None:
        return None
    return MatchNarrative(
        match_id=row["match_id"],
        prose=row["prose"],
        prompt=row["prompt"],
        model=row["model"],
        generated_at=row["generated_at"],
        context_hash=row["context_hash"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cost_usd=row["cost_usd"],
    )
