"""Post-game match analysis: local heuristic findings over already-projected
data, plus the prompt for an optional narrative over them (``narrative.py``).
It only ever runs once a match is over; why there is no mid-match version is
``docs/brief.md``, "Why this question is worth writing down once". The
design is ``docs/review.md``, "The match report, and its optional narrative".

Two hard rules govern it:

1. **It never imports from ``reader/`` and never reads the append-only log
   table the reader owns.** Every analyzer is a pure function of the
   projected database. (AGENTS.md non-negotiable #1.)
2. **Findings are computed on demand, at request time, never persisted.**
   Half these analyzers depend on ``cards.type_line`` (to tell a land from a
   spell), downloaded reference data the projector does not own, which
   ``sensei-top cards`` may fill long after a match was projected; and a
   match's deck is read through ``v_match_deck``, which the user's MTGO pick
   changes with no rebuild. A stored ``findings`` table would read *wrong*,
   not merely stale, for every match analyzed before either change — the
   same reasoning ``docs/opponent-deck.md`` gives for why
   ``v_match_opponent`` is a view and not a column. Nothing here needs
   ``project()`` to know it exists, so nothing in ``projector/`` may import
   this package.

Two structured types carry every analyzer's result (``findings.py``):
``Finding`` for something observed, and ``Gap`` for something an analyzer
could not evaluate — kept as its own list so a report's silence is never
mistaken for "nothing was wrong" (AGENTS.md rule 4).
"""

from sensei_top.review.findings import (
    AnalyzerResult,
    Category,
    Confidence,
    Evidence,
    Finding,
    GameFacts,
    Gap,
    MatchReport,
    Severity,
)
from sensei_top.review.match_report import build_match_report
from sensei_top.review.summary import Beat, GameLine, GapGroup, MatchSummary, build_summary

__all__ = [
    "AnalyzerResult",
    "Beat",
    "Category",
    "Confidence",
    "Evidence",
    "Finding",
    "GameFacts",
    "GameLine",
    "Gap",
    "GapGroup",
    "MatchReport",
    "MatchSummary",
    "Severity",
    "build_match_report",
    "build_summary",
]
