"""The resource trade: card advantage over the course of the game, spells
that never resolved, and cards that never got the chance to matter. Duke's
*Tempo & Card Advantage* names these as the two currencies that decide
which side is winning once the board settles down; this reader can see one
of them directly and infer the other from what actually reached the stack.
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
from sensei_top.review.snapshot import MatchSnapshot

ANALYZER = "resources"

STRANDED_HAND_MIN = 3


def analyze_resources(snap: MatchSnapshot) -> AnalyzerResult:
    findings: list[Finding] = []
    gaps: list[Gap] = []

    for game in snap.games:
        turns = snap.turns_in(game.game_number)
        diffs = [
            (t.self_turn_index, t.self_hand - t.opp_hand) for t in turns
            if t.self_hand is not None and t.opp_hand is not None
        ]
        if diffs:
            best_index, best_diff = max(diffs, key=lambda pair: pair[1])
            worst_index, worst_diff = min(diffs, key=lambda pair: pair[1])
            if best_diff > 0 or worst_diff < 0:
                findings.append(
                    Finding(
                        code="card_advantage_swing",
                        analyzer=ANALYZER, category=Category.RESOURCES, severity=Severity.NOTE,
                        confidence=Confidence.PARTIAL, game_number=game.game_number,
                        title=(f"Card advantage ranged from {worst_diff:+d} to "
                               f"{best_diff:+d} this game"),
                        detail=(
                            f"Your hand size compared to the opponent's was as low as "
                            f"{worst_diff:+d} (your turn {worst_index}) and as high as "
                            f"{best_diff:+d} (your turn {best_index})."
                        ),
                        evidence=(
                            Evidence("best_diff", "High point (hand size vs. theirs)", best_diff),
                            Evidence("best_turn", "Your turn at the high point", best_index),
                            Evidence("worst_diff", "Low point (hand size vs. theirs)", worst_diff),
                            Evidence("worst_turn", "Your turn at the low point", worst_index),
                        ),
                    )
                )
        else:
            gaps.append(
                Gap(ANALYZER, "Hand sizes for both players were never recorded on the same "
                              "turn this game, so no card-advantage swing could be measured.",
                    game_number=game.game_number)
            )

        last_turn = turns[-1] if turns else None
        if (
            last_turn is not None and game.result == "loss"
            and (last_turn.self_hand or 0) >= STRANDED_HAND_MIN
        ):
            # No `pattern=` here on purpose: this finding only ever fires in a game
            # already lost, so a with/without win-rate comparison across it would
            # measure the loss condition it is defined by, not a real pattern — the
            # leak finder's own gate (test_every_pattern_..., leaks.py) would report
            # a large "gap" that is really just this code's own definition leaking
            # into the statistic.
            findings.append(
                Finding(
                    code="cards_stranded_in_a_loss",
                    analyzer=ANALYZER, category=Category.RESOURCES, severity=Severity.NOTICE,
                    confidence=Confidence.PARTIAL, game_number=game.game_number,
                    turn_number=last_turn.turn_number, self_turn_index=last_turn.self_turn_index,
                    title=f"Lost holding {last_turn.self_hand} cards",
                    detail=(
                        f"At the last turn this reader recorded for you (your turn "
                        f"{last_turn.self_turn_index}), your hand still held "
                        f"{last_turn.self_hand} cards. Resources that never get spent are "
                        f"not card advantage — they are cards that arrived too late, cost "
                        f"too much, or never had the mana to matter."
                    ),
                    evidence=(
                        Evidence("stranded_cards", "Cards in hand at the last recorded turn",
                                 last_turn.self_hand),
                    ),
                    caveats=(
                        "This is the last turn this reader captured, which may not be the "
                        "literal final turn of the game — a trailing turn can go unrecorded "
                        "(see the projector's own flush_trailing).",
                    ),
                )
            )

    game_counters = {
        g.game_number: [c for c in snap.countered if c.game_number == g.game_number]
        for g in snap.games
    }
    for game_number, events in game_counters.items():
        if not events:
            continue
        self_countered = sum(1 for e in events if e.is_self is True)
        opp_countered = sum(1 for e in events if e.is_self is False)
        findings.append(
            Finding(
                code="counters_traded",
                analyzer=ANALYZER, category=Category.RESOURCES, severity=Severity.NOTE,
                confidence=Confidence.OBSERVED, game_number=game_number,
                title=f"{self_countered} of your spells countered, {opp_countered} of theirs",
                detail=(
                    f"{self_countered} spell{'s' if self_countered != 1 else ''} of yours were "
                    f"countered this game; {opp_countered} of the opponent's were. A countered "
                    f"spell is a card lost with nothing gained, on whichever side it lands."
                ),
                evidence=(
                    Evidence("self_countered", "Your spells countered", self_countered),
                    Evidence("opp_countered", "Opponent's spells countered", opp_countered),
                ),
            )
        )

    if not findings and not gaps:
        gaps.append(Gap(ANALYZER, "Nothing about the resource trade could be measured for "
                                   "this match.", game_number=None))

    return AnalyzerResult(tuple(findings), tuple(gaps))
