"""Post-game match analysis: local heuristic findings over already-projected
data, plus an opt-in Claude narrative that turns them into prose
(``narrative.py``).

This is the report the retired live hint (once ``advisor.py``) became.
Mid-match, the projector only has an end-of-turn snapshot to reason from —
no combat, no stack, no opponent hand — so advice built on it was advice
built on a board the player could not fully verify, offered at the moment
they could least afford to be wrong. After a match, the constraint inverts:
the whole game is on disk, verbatim, and there is no clock, so this package
only ever runs once a match is over.

Two hard rules govern it:

1. **It never imports from ``reader/`` and never reads the append-only log
   table the reader owns.** Every analyzer is a pure function of the
   projected database — the same tables and views ``api/app.py`` already
   reads (``matches``, ``games``, ``turns``, ``turn_zones``, ``card_events``,
   ``cards``, ``decks``, plus the views ``migrations/011_review_views.sql``
   adds). (AGENTS.md non-negotiable #1.)
2. **Findings are computed on demand, at request time, never persisted.**
   Half these analyzers depend on ``cards.type_line`` (to tell a land from a
   spell) and ``decks.cards_json`` — neither owned by the projector, and
   both may be populated (``sensei-top cards``) long after a match was
   projected. A stored ``findings`` table would read *wrong*, not merely
   stale, for every match analyzed before that download finished — the same
   reasoning ``docs/opponent-deck.md`` gives for why ``v_match_opponent`` is a
   view and not a column. Nothing here needs ``project()`` to know it
   exists, so nothing in ``projector/`` may import this package.

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
