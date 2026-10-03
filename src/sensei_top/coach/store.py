"""The coach report's own storage: every generated report, kept.

``review/leaks_store.py`` and ``review/narrative_store.py`` each hold a
single authored row that a regenerate overwrites — there is exactly one
current leak narrative, and one current narrative per match. A coach report
is different: a new report's "Since your last report" section compares
against the previous report's own ``metrics_json``, so writing a new report
must never erase the one it will be compared against. ``write_coach_report`` is
therefore a plain ``INSERT``, never an upsert, and this module reads back a
history rather than a single slot.

``context_hash`` is re-exported from ``review/narrative_store.py`` rather
than reimplemented, so every authored-artifact table in this project agrees
on what "the evidence changed" means: a SHA-256 of the prompt context
string itself.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from sensei_top.llm.provenance import now_iso
from sensei_top.review.narrative_store import context_hash

__all__ = [
    "CoachReport",
    "context_hash",
    "extract_focus_section",
    "latest_coach_report",
    "list_coach_reports",
    "read_coach_report",
    "write_coach_report",
]

_FOCUS_HEADING = "## Focus areas"


@dataclass(frozen=True, slots=True)
class CoachReport:
    id: int
    generated_at: str
    model: str
    effort: str | None
    prompt: str
    prose: str
    sources: list
    metrics: dict
    context_hash: str
    input_tokens: int | None
    output_tokens: int | None
    web_search_requests: int | None
    cost_usd: float | None


def write_coach_report(
    conn: sqlite3.Connection,
    *,
    prose: str,
    prompt: str,
    model: str,
    effort: str | None = None,
    sources: list,
    metrics: dict,
    context_hash: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    web_search_requests: int | None = None,
    cost_usd: float | None = None,
    generated_at: str | None = None,
) -> int:
    """Insert one new report and return its id. Never an upsert — see the
    module docstring for why a coach report is history, not a cache."""
    cur = conn.execute(
        "INSERT INTO coach_report "
        "(generated_at, model, effort, prompt, prose, sources_json, metrics_json, "
        "context_hash, input_tokens, output_tokens, web_search_requests, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            generated_at or now_iso(),
            model,
            effort,
            prompt,
            prose,
            json.dumps(sources),
            json.dumps(metrics),
            context_hash,
            input_tokens,
            output_tokens,
            web_search_requests,
            cost_usd,
        ),
    )
    return cur.lastrowid


def _row_to_report(row: sqlite3.Row) -> CoachReport:
    return CoachReport(
        id=row["id"],
        generated_at=row["generated_at"],
        model=row["model"],
        effort=row["effort"],
        prompt=row["prompt"],
        prose=row["prose"],
        sources=json.loads(row["sources_json"]),
        metrics=json.loads(row["metrics_json"]),
        context_hash=row["context_hash"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        web_search_requests=row["web_search_requests"],
        cost_usd=row["cost_usd"],
    )


def read_coach_report(conn: sqlite3.Connection, report_id: int) -> CoachReport | None:
    row = conn.execute("SELECT * FROM coach_report WHERE id = ?", (report_id,)).fetchone()
    if row is None:
        return None
    return _row_to_report(row)


def latest_coach_report(conn: sqlite3.Connection) -> CoachReport | None:
    row = conn.execute(
        "SELECT * FROM coach_report ORDER BY generated_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return _row_to_report(row)


def list_coach_reports(conn: sqlite3.Connection) -> list[CoachReport]:
    """Every report, newest first."""
    rows = conn.execute(
        "SELECT * FROM coach_report ORDER BY generated_at DESC, id DESC"
    ).fetchall()
    return [_row_to_report(row) for row in rows]


def extract_focus_section(prose: str) -> str:
    """The text under ``## Focus areas``, up to the next ``## `` heading or
    the end of the prose — the slice a progress review reads back against a
    past report. Falls back to the whole prose when the heading is absent,
    so a report written before this convention (or one where the model
    didn't use the heading) still yields something rather than nothing."""
    start = prose.find(_FOCUS_HEADING)
    if start == -1:
        return prose.strip()
    body_start = start + len(_FOCUS_HEADING)
    next_heading = prose.find("\n## ", body_start)
    section = prose[body_start:next_heading] if next_heading != -1 else prose[body_start:]
    return section.strip()
