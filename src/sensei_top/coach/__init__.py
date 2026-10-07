"""The player-level coach: a cross-deck report and training plan over every
Arena/MTGO match — see ``docs/coach.md`` for the full design.

``store.py`` is the report's own history (one row per generation, never
upserted). ``canon.py`` is the curated reading list a report's prompt may
cite by id, plus the domain allowlist its web search is restricted to.
"""

from sensei_top.coach.canon import (
    ALLOWED_DOMAINS,
    BROAD_TAGS,
    CANON,
    CORE_IDS,
    LEAK_CODES,
    CanonEntry,
    entries_for,
)
from sensei_top.coach.evidence import (
    CoachEvidence,
    DeckLeaks,
    DeckLine,
    DeckList,
    ExampleGame,
    FieldLine,
    LeakLine,
    MatchupLine,
    Rate,
    TurningBucket,
    build_coach_evidence,
    format_rate,
    metrics_snapshot,
    progress_since,
)
from sensei_top.coach.narrative import (
    HEADINGS,
    CoachPrompt,
    build_coach_context,
    build_coach_prompt,
    cited_ids,
    full_prompt,
    reading_list,
    system_prompt,
)
from sensei_top.coach.store import (
    CoachReport,
    context_hash,
    extract_focus_section,
    latest_coach_report,
    list_coach_reports,
    read_coach_report,
    write_coach_report,
)

__all__ = [
    "ALLOWED_DOMAINS",
    "BROAD_TAGS",
    "CANON",
    "CORE_IDS",
    "HEADINGS",
    "LEAK_CODES",
    "CanonEntry",
    "CoachEvidence",
    "CoachPrompt",
    "CoachReport",
    "DeckLeaks",
    "DeckLine",
    "DeckList",
    "ExampleGame",
    "FieldLine",
    "LeakLine",
    "MatchupLine",
    "Rate",
    "TurningBucket",
    "build_coach_context",
    "build_coach_evidence",
    "build_coach_prompt",
    "cited_ids",
    "context_hash",
    "entries_for",
    "extract_focus_section",
    "format_rate",
    "full_prompt",
    "latest_coach_report",
    "list_coach_reports",
    "metrics_snapshot",
    "progress_since",
    "read_coach_report",
    "reading_list",
    "system_prompt",
    "write_coach_report",
]
