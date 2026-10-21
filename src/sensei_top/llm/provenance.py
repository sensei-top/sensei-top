"""Shared plumbing for the authored-prose tables: a timestamp helper and the
upsert that writes a table's provenance columns beside its feature-specific
ones.

``upsert_authored`` backs the four one-slot tables (``match_narrative``,
``leaks_narrative``, ``deck_narrative``, ``matchup_brief``), four of AGENTS.md
non-negotiable #6's write allowlist. ``coach_report`` and ``rcq_guide`` keep
every row, so their stores ``INSERT`` and take only ``now_iso`` from here.
This module never grows that allowlist:
``tests/test_api.py::test_only_authored_artifact_routes_write`` pins the
route set that may write it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

__all__ = ["AuthoredRecord", "now_iso", "upsert_authored"]


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass(frozen=True, slots=True)
class AuthoredRecord:
    """The provenance six most authored tables carry: what asked for it,
    what wrote it and when, and what it cost. ``cost``/token fields are
    ``None`` for a hand-imported narrative — a real absence, never a
    fabricated zero (AGENTS.md non-negotiable #4).

    ``match_narrative`` and ``leaks_narrative`` write it as is.
    ``deck_narrative`` names two of the columns differently: a guide can be
    hand-authored as well as Claude-written, so it stores
    ``author``/``authored_at`` in place of ``model``/``generated_at`` — see
    ``guide/authored.py::write_narrative``, which builds its own columns
    dict instead.
    """

    prompt: str
    model: str
    generated_at: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None

    def columns(self) -> dict[str, object]:
        return {
            "prompt": self.prompt,
            "model": self.model,
            "generated_at": self.generated_at,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


def upsert_authored(
    conn: sqlite3.Connection,
    table: str,
    key: dict[str, object],
    columns: dict[str, object],
) -> None:
    """``INSERT ... ON CONFLICT(key) DO UPDATE`` for one row of an
    authored-artifact table. ``key`` identifies the row (e.g.
    ``{"match_id": match_id}`` or ``{"deck_key": ..., "archetype_key": ...}``);
    ``columns`` is everything else to write, feature-specific columns and
    the provenance six together. Both are internal call sites' own
    hardcoded column names, never external input, going straight into the
    SQL text the same way a hand-written ``INSERT`` already would.
    """
    all_columns = {**key, **columns}
    names = list(all_columns.keys())
    conn.execute(
        f"""
        INSERT INTO {table} ({", ".join(names)})
        VALUES ({", ".join("?" for _ in names)})
        ON CONFLICT ({", ".join(key)}) DO UPDATE SET
            {", ".join(f"{c} = excluded.{c}" for c in columns)}
        """,
        tuple(all_columns.values()),
    )
