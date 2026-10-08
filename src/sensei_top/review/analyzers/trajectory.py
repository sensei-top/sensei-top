"""The shape of the whole game: the position index turn by turn, and the
turning point — the Lichess "blunder" idea, adapted to what this reader can
actually see. Never a claim about *why* on its own; attribution comes from
cross-referencing what else happened in that turn's window (damage dealt,
an opponent spell resolving, a card countered).
"""

from __future__ import annotations

from sensei_top.review.findings import (
    AnalyzerResult,
    Category,
    Confidence,
    Evidence,
    Finding,
    Gap,
    Severity,
)
from sensei_top.review.position import (
    SWING_DECISIVE,
    TurnPosition,
    swing_words,
    turn_position,
    turning_point,
)
from sensei_top.review.snapshot import MatchSnapshot, SelfTurnRow

ANALYZER = "trajectory"


def _positions(turns: list[SelfTurnRow]) -> list[TurnPosition]:
    positions = []
    for t in turns:
        pos = turn_position(
            t.turn_number,
            self_life=t.self_life, opp_life=t.opp_life,
            self_power=t.self_power, opp_power=t.opp_power,
            self_permanents=t.self_permanents, opp_permanents=t.opp_permanents,
            self_hand=t.self_hand, opp_hand=t.opp_hand,
            self_lands=t.self_lands, opp_lands=t.opp_lands,
        )
        if pos is not None:
            positions.append(pos)
    return positions


def _attribution(
    snap: MatchSnapshot, game_number: int, before_turn: int, after_turn: int
) -> tuple[str, int | None]:
    """What else is on record in the window the turning point falls in —
    an opponent spell resolving, or damage dealt to the player who dropped.
    Named as what was observed, never asserted as sole cause. The second
    element is the damage total when the cause is damage, so the caller can
    back that number with its own Evidence rather than leaving it citing
    nothing (a card name carries no number, so it is always ``None`` there).
    """
    plays = [
        p for p in snap.opponent_plays
        if p.game_number == game_number and before_turn < p.turn_number <= after_turn
        and p.category == "Resolve" and p.card_name is not None
    ]
    if plays:
        return plays[0].card_name, None

    hits = [
        d for d in snap.damage_events
        if d.game_number == game_number and d.turn_number is not None
        and before_turn < d.turn_number <= after_turn and d.target_instance_id is None
    ]
    if hits:
        total = sum(h.amount for h in hits)
        return f"{total} damage taken", total
    return "", None


def analyze_trajectory(snap: MatchSnapshot) -> AnalyzerResult:
    findings: list[Finding] = []
    gaps: list[Gap] = []

    for game in snap.games:
        turns = snap.turns_in(game.game_number)
        positions = _positions(turns)
        if len(positions) < 2:
            gaps.append(
                Gap(ANALYZER, "Too few turns had both life totals recorded to trace a "
                              "position trajectory for this game.", game_number=game.game_number)
            )
            continue

        point = turning_point(positions)
        if point is None:
            findings.append(
                Finding(
                    code="never_behind",
                    analyzer=ANALYZER, category=Category.TRAJECTORY, severity=Severity.NOTE,
                    confidence=Confidence.PARTIAL, game_number=game.game_number,
                    title="This game's position never swung against you",
                    detail="Across every turn this reader could measure, the position index "
                           "never dropped from one recorded turn to the next.",
                    evidence=(
                        Evidence("turns_measured", "Turns with a position index", len(positions)),
                    ),
                )
            )
            continue

        before_turn = _turn_before(positions, point.turn_number)
        cause, cause_damage = _attribution(snap, game.game_number, before_turn, point.turn_number)
        # point.turn_number is Arena's shared turn counter (both players'
        # turns); "your turn" must say self_turn_index instead — the row for
        # this turn is already in `turns`, since that is what `_positions`
        # built `point` from in the first place.
        self_turn_index = next(
            t.self_turn_index for t in turns if t.turn_number == point.turn_number
        )
        detail = (
            f"Your position went from {point.index_before:+.2f} to {point.index_after:+.2f} "
            f"by your turn {self_turn_index} — the largest single swing against you this game."
        )
        if cause:
            detail += f" In that window, {cause} was on record."

        evidence = [
            Evidence("index_before", "Position index before the swing",
                     round(point.index_before, 2)),
            Evidence("index_after", "Position index after the swing",
                     round(point.index_after, 2)),
            Evidence("drop", "Size of the swing", round(point.drop, 2),
                     display=f"{point.drop:.2f} — {swing_words(point.drop)}"),
        ]
        if cause_damage is not None:
            evidence.append(Evidence("cause_damage", "Damage taken in that window", cause_damage))

        findings.append(
            Finding(
                code="turning_point",
                analyzer=ANALYZER, category=Category.TRAJECTORY,
                severity=Severity.DECISIVE if point.drop >= SWING_DECISIVE else Severity.NOTICE,
                confidence=Confidence.PARTIAL, game_number=game.game_number,
                turn_number=point.turn_number, self_turn_index=self_turn_index,
                title=f"The game turned on your turn {self_turn_index}",
                detail=detail,
                evidence=tuple(evidence),
                caveats=(
                    "The position index is a fixed-weight approximation over life, board, "
                    "hand and mana — not a rules engine, and not a claim about which single "
                    "play caused the swing.",
                ),
            )
        )

    return AnalyzerResult(tuple(findings), tuple(gaps))


def _turn_before(positions: list[TurnPosition], turning_turn: int) -> int:
    ordered = sorted(positions, key=lambda p: p.turn_number)
    prior = 0
    for p in ordered:
        if p.turn_number >= turning_turn:
            break
        prior = p.turn_number
    return prior
