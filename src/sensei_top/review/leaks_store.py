"""The leak finder's training-plan prose, stored and read back.

Single row, not a table of them: the leaks narrative routes call
``find_leaks`` with no deck scope, so there is exactly one narrative to
store, ever. See ``review/narrative_store.py`` for the
shared ``context_hash`` staleness signal this mirrors.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from sensei_top.llm.provenance import AuthoredRecord, now_iso, upsert_authored
from sensei_top.review.narrative_store import context_hash

__all__ = ["LeaksNarrative", "context_hash", "read_leaks_narrative", "write_leaks_narrative"]


@dataclass(frozen=True, slots=True)
class LeaksNarrative:
    prose: str
    prompt: str
    model: str
    generated_at: str
    context_hash: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


def write_leaks_narrative(
    conn: sqlite3.Connection,
    *,
    prose: str,
    prompt: str,
    model: str,
    context_hash: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    record = AuthoredRecord(
        prompt=prompt, model=model, generated_at=now_iso(),
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
    )
    upsert_authored(
        conn, "leaks_narrative", {"id": 1},
        {**record.columns(), "prose": prose, "context_hash": context_hash},
    )


def read_leaks_narrative(conn: sqlite3.Connection) -> LeaksNarrative | None:
    row = conn.execute("SELECT * FROM leaks_narrative WHERE id = 1").fetchone()
    if row is None:
        return None
    return LeaksNarrative(
        prose=row["prose"],
        prompt=row["prompt"],
        model=row["model"],
        generated_at=row["generated_at"],
        context_hash=row["context_hash"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cost_usd=row["cost_usd"],
    )
