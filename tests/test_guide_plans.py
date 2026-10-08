"""Tests for guide/plans.py: validating a generated sideboard plan against
the synthetic maindeck (MAIN) and sideboard (SIDE) counters defined below.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sensei_top.guide.plans import validate_plans


@dataclass(frozen=True, slots=True)
class BoardCard:
    card: str
    n: int


@dataclass(frozen=True, slots=True)
class MatchupPlan:
    archetype: str
    board_in: tuple[BoardCard, ...]
    board_out: tuple[BoardCard, ...]


MAIN = Counter({"Burst Lightning": 3, "Impractical Joke": 1, "Get Out": 2})
SIDE = Counter({"Slagstorm": 2, "Ghost Vacuum": 2, "Disdainful Stroke": 1})


def test_a_balanced_valid_plan_has_no_problems():
    side = Counter({"Slagstorm": 2})
    plans = [MatchupPlan(
        archetype="Mono-Green Landfall",
        board_in=(BoardCard("Slagstorm", 2),),
        board_out=(BoardCard("Impractical Joke", 1), BoardCard("Burst Lightning", 1)),
    )]
    assert validate_plans(MAIN, side, plans) == []


def test_unbalanced_in_and_out_counts_flagged():
    plans = [MatchupPlan(
        archetype="Mono-Green Landfall",
        board_in=(BoardCard("Slagstorm", 2),),
        board_out=(BoardCard("Impractical Joke", 1),),
    )]
    problems = validate_plans(MAIN, SIDE, plans)
    assert len(problems) >= 1
    assert any("IN totals 2" in p.message for p in problems)


def test_boarding_in_more_than_the_sideboard_holds():
    plans = [MatchupPlan(
        archetype="Mardu Discard",
        board_in=(BoardCard("Disdainful Stroke", 3),),
        board_out=(BoardCard("Burst Lightning", 3),),
    )]
    problems = validate_plans(MAIN, SIDE, plans)
    assert any("only has 1" in p.message for p in problems)


def test_boarding_out_more_than_the_maindeck_holds():
    plans = [MatchupPlan(
        archetype="Jeskai Control",
        board_in=(BoardCard("Slagstorm", 2),),
        board_out=(BoardCard("Impractical Joke", 2),),
    )]
    problems = validate_plans(MAIN, SIDE, plans)
    assert any("maindeck only has 1" in p.message for p in problems)


def test_a_sideboard_card_never_brought_in_by_any_plan():
    plans = [MatchupPlan(
        archetype="Mono-Green Landfall",
        board_in=(BoardCard("Slagstorm", 2),),
        board_out=(BoardCard("Burst Lightning", 2),),
    )]
    problems = validate_plans(MAIN, SIDE, plans)
    unused = next(p for p in problems if p.archetype == "(sideboard)")
    assert "Ghost Vacuum" in unused.message
    assert "Disdainful Stroke" in unused.message
    assert "Slagstorm" not in unused.message


def test_every_sideboard_card_used_across_plans_has_no_unused_problem():
    plans = [
        MatchupPlan("A", (BoardCard("Slagstorm", 2),), (BoardCard("Burst Lightning", 2),)),
        MatchupPlan("B", (BoardCard("Ghost Vacuum", 2),), (BoardCard("Get Out", 2),)),
        MatchupPlan("C", (BoardCard("Disdainful Stroke", 1),), (BoardCard("Impractical Joke", 1),)),
    ]
    problems = validate_plans(MAIN, SIDE, plans)
    assert not any(p.archetype == "(sideboard)" for p in problems)
