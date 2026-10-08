"""Validate a sideboard plan against the real 75: balanced counts, nothing
boarded out that isn't in the maindeck, nothing boarded in that isn't in
the sideboard, every sideboard card used by at least one plan.

Operates on structured data (the ``guide/narrative.py`` response), not
regex over prose — a plan the model gets wrong is caught and surfaced next
to the matchup, never silently repaired.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class _BoardCard(Protocol):
    card: str
    n: int


class _MatchupPlan(Protocol):
    archetype: str
    board_in: Sequence[_BoardCard]
    board_out: Sequence[_BoardCard]


@dataclass(frozen=True, slots=True)
class PlanProblem:
    archetype: str
    message: str


def validate_plans(
    recommended_main: Counter, recommended_side: Counter, plans: Sequence[_MatchupPlan]
) -> list[PlanProblem]:
    problems: list[PlanProblem] = []
    used_from_side: Counter = Counter()

    for plan in plans:
        in_total = sum(c.n for c in plan.board_in)
        out_total = sum(c.n for c in plan.board_out)
        if in_total != out_total:
            problems.append(PlanProblem(
                plan.archetype,
                f"IN totals {in_total} card(s), OUT totals {out_total} — a sideboard plan "
                f"must swap equal numbers.",
            ))

        for c in plan.board_in:
            available = recommended_side.get(c.card, 0)
            if c.n > available:
                problems.append(PlanProblem(
                    plan.archetype,
                    f"brings in {c.n}x {c.card}, but the sideboard only has {available}.",
                ))
            used_from_side[c.card] += 1

        for c in plan.board_out:
            available = recommended_main.get(c.card, 0)
            if c.n > available:
                problems.append(PlanProblem(
                    plan.archetype,
                    f"boards out {c.n}x {c.card}, but the maindeck only has {available}.",
                ))

    unused = [card for card in recommended_side if card not in used_from_side]
    if unused:
        problems.append(PlanProblem(
            "(sideboard)",
            f"never brought in by any matchup plan: {', '.join(sorted(unused))}.",
        ))

    return problems
