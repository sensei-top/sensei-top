"""The report's analyzer registry.

Replaces the single ``analyzers.py`` module: one file per concept in the
postmortem's own arc (``docs/review.md`` walks through why each one exists
and the article it comes from), rather than one file growing indefinitely.
``match_report.py`` runs every entry in ``ANALYZERS`` over one
``MatchSnapshot`` and concatenates the results — the registry, not import
order, is what determines which analyzers run.
"""

from __future__ import annotations

from sensei_top.review.analyzers.baseline import analyze_baseline
from sensei_top.review.analyzers.clock import analyze_clock
from sensei_top.review.analyzers.frame import analyze_frame
from sensei_top.review.analyzers.information import analyze_information
from sensei_top.review.analyzers.resources import analyze_resources
from sensei_top.review.analyzers.role_play import analyze_role_play
from sensei_top.review.analyzers.trajectory import analyze_trajectory

ANALYZERS = (
    analyze_frame,
    analyze_clock,
    analyze_trajectory,
    analyze_role_play,
    analyze_information,
    analyze_resources,
    analyze_baseline,
)

__all__ = [
    "ANALYZERS",
    "analyze_baseline",
    "analyze_clock",
    "analyze_frame",
    "analyze_information",
    "analyze_resources",
    "analyze_role_play",
    "analyze_trajectory",
]
