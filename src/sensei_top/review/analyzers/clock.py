"""Who is killing whom, and how fast — Duke's *Damage Racing* and Flores'
*Philosophy of Fire* made computable from ``damage_events``: cards for life,
not cards for cards. This reader sees every point of damage dealt (the
combat/damage projection, ``migrations/014_combat.sql``), so a race's pace is
a real observed rate, not an inference from life totals alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from sensei_top.review.findings import (
    AnalyzerResult,
    Category,
    Confidence,
    Evidence,
    Finding,
    Gap,
    Severity,
)
from sensei_top.review.snapshot import DamageRow, MatchSnapshot

ANALYZER = "clock"

# Below this much damage dealt by either side, a "pace" is not a race yet —
# a single early hit should not be extrapolated into a turn-to-kill estimate.
MIN_DAMAGE_FOR_A_RACE = 6


@dataclass(frozen=True, slots=True)
class RaceState:
    self_dealt: int
    opp_dealt: int
    last_turn: int


def _race_state(rows: tuple[DamageRow, ...], game_number: int) -> RaceState | None:
    """Damage dealt to a *player* by each side, in one game — creature
    trades (a non-None ``target_instance_id``) are not life loss and do not
    belong in a race calculation."""
    self_dealt = opp_dealt = 0
    last_turn = 0
    for row in rows:
        if row.game_number != game_number or row.target_instance_id is not None:
            continue
        if row.turn_number is not None:
            last_turn = max(last_turn, row.turn_number)
        if row.source_is_self is True:
            self_dealt += row.amount
        elif row.source_is_self is False:
            opp_dealt += row.amount
    if self_dealt == 0 and opp_dealt == 0:
        return None
    return RaceState(self_dealt, opp_dealt, last_turn)


def analyze_clock(snap: MatchSnapshot) -> AnalyzerResult:
    findings: list[Finding] = []
    gaps: list[Gap] = []

    if not snap.damage_events:
        gaps.append(
            Gap(ANALYZER, "No damage was observed to either player in this match, so no race "
                          "could be measured — either the game never reached combat, or this "
                          "reader's combat parsing found nothing to attribute.")
        )
        return AnalyzerResult((), tuple(gaps))

    for game in snap.games:
        state = _race_state(snap.damage_events, game.game_number)
        if state is None:
            gaps.append(
                Gap(ANALYZER, "No damage to either player was observed this game.",
                    game_number=game.game_number)
            )
            continue
        if state.self_dealt + state.opp_dealt < MIN_DAMAGE_FOR_A_RACE:
            gaps.append(
                Gap(ANALYZER, f"Only {state.self_dealt + state.opp_dealt} total damage was "
                              f"observed to either player — too little to call a race.",
                    game_number=game.game_number)
            )
            continue

        pace_self = state.self_dealt / state.last_turn if state.last_turn else 0.0
        pace_opp = state.opp_dealt / state.last_turn if state.last_turn else 0.0

        evidence = (
            Evidence("self_damage_dealt", "Damage you dealt to the opponent", state.self_dealt),
            Evidence("opp_damage_dealt", "Damage the opponent dealt to you", state.opp_dealt),
            Evidence("last_damage_turn", "Last turn either side dealt damage", state.last_turn),
        )

        if state.self_dealt == state.opp_dealt:
            findings.append(
                Finding(
                    code="race_even",
                    analyzer=ANALYZER, category=Category.CLOCK, severity=Severity.NOTE,
                    confidence=Confidence.OBSERVED, game_number=game.game_number,
                    title=f"An even race: {state.self_dealt} damage each way",
                    detail=f"By turn {state.last_turn}, you and the opponent had each dealt "
                           f"{state.self_dealt} damage to the other's life total — neither side "
                           f"was ahead in the race by damage output alone.",
                    evidence=evidence,
                )
            )
            continue

        margin = abs(state.self_dealt - state.opp_dealt)
        severity = Severity.DECISIVE if margin >= 10 else Severity.NOTICE
        caveats = (
            "This counts damage dealt to a player only — creature-versus-creature "
            "combat and life lost to costs (a shockland, a payment) are excluded, "
            "since neither moves either player closer to winning the race itself.",
        )
        race_evidence = (
            *evidence,
            Evidence("pace_self", "Your damage per player-turn", round(pace_self, 1)),
            Evidence("pace_opp", "Opponent's damage per player-turn", round(pace_opp, 1)),
        )
        # Two codes rather than one code plus a variable subject: "the opponent were
        # ahead" is a grammar bug this used to have, and a bare "race_leader" code
        # cannot become a leak pattern — leading and trailing a race are opposite
        # signals, not one pattern with two subjects.
        if state.self_dealt > state.opp_dealt:
            findings.append(
                Finding(
                    code="race_ahead",
                    analyzer=ANALYZER, category=Category.CLOCK, severity=severity,
                    confidence=Confidence.OBSERVED, game_number=game.game_number,
                    title=f"You were ahead in the damage race, {state.self_dealt} to "
                          f"{state.opp_dealt}",
                    detail=(
                        f"You dealt {state.self_dealt} damage to the opponent's life total; "
                        f"they dealt {state.opp_dealt} to yours, through turn "
                        f"{state.last_turn}. Philosophy of Fire's own math: every card that "
                        f"does not convert into damage, on either side, is a card losing this "
                        f"particular race."
                    ),
                    evidence=race_evidence,
                    caveats=caveats,
                    pattern="Led the damage race",
                )
            )
        else:
            findings.append(
                Finding(
                    code="race_behind",
                    analyzer=ANALYZER, category=Category.CLOCK, severity=severity,
                    confidence=Confidence.OBSERVED, game_number=game.game_number,
                    title=f"The opponent was ahead in the damage race, {state.opp_dealt} to "
                          f"{state.self_dealt}",
                    detail=(
                        f"They dealt {state.opp_dealt} damage to your life total; you dealt "
                        f"{state.self_dealt} to theirs, through turn {state.last_turn}. "
                        f"Philosophy of Fire's own math: every card that does not convert into "
                        f"damage, on either side, is a card losing this particular race."
                    ),
                    evidence=race_evidence,
                    caveats=caveats,
                    pattern="Fell behind in the damage race",
                )
            )

    return AnalyzerResult(tuple(findings), tuple(gaps))
