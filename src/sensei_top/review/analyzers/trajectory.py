"""The shape of the whole game: the position index turn by turn, and the
turning point — the Lichess "blunder" idea, adapted to what this reader can
actually see. Never a claim about *why* on its own; attribution comes from
cross-referencing what else happened in that turn's window (damage dealt,
an opponent spell resolving, a card countered).
"""

from __future__ import annotations

from sensei_top.i18n import _, decimal
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
) -> tuple[str | None, str | int | None]:
    """What else is on record in the window the turning point falls in —
    an opponent spell resolving, or damage dealt to the player who dropped.
    Named as what was observed, never asserted as sole cause. Returns the
    kind of cause (``"card"``, ``"damage"`` or ``None``) and its value: the
    card name, or the damage total, which the caller backs with its own
    Evidence rather than leaving it citing nothing. The caller words the
    sentence, so each kind is a whole translatable sentence.
    """
    plays = [
        p for p in snap.opponent_plays
        if p.game_number == game_number and before_turn < p.turn_number <= after_turn
        and p.category == "Resolve" and p.card_name is not None
    ]
    if plays:
        return "card", plays[0].card_name

    hits = [
        d for d in snap.damage_events
        if d.game_number == game_number and d.turn_number is not None
        and before_turn < d.turn_number <= after_turn and d.target_instance_id is None
    ]
    if hits:
        total = sum(h.amount for h in hits)
        return "damage", total
    return None, None


def analyze_trajectory(snap: MatchSnapshot) -> AnalyzerResult:
    findings: list[Finding] = []
    gaps: list[Gap] = []

    for game in snap.games:
        turns = snap.turns_in(game.game_number)
        positions = _positions(turns)
        if len(positions) < 2:
            gaps.append(
                Gap(ANALYZER, _("Too few turns had both life totals recorded to trace a "
                                "position trajectory for this game."),
                    game_number=game.game_number)
            )
            continue

        point = turning_point(positions)
        if point is None:
            findings.append(
                Finding(
                    code="never_behind",
                    analyzer=ANALYZER, category=Category.TRAJECTORY, severity=Severity.NOTE,
                    confidence=Confidence.PARTIAL, game_number=game.game_number,
                    title=_("This game's position never swung against you"),
                    detail=_("Across every turn this reader could measure, the position index "
                             "never dropped from one recorded turn to the next."),
                    evidence=(
                        Evidence("turns_measured", _("Turns with a position index"),
                                 len(positions)),
                    ),
                )
            )
            continue

        before_turn = _turn_before(positions, point.turn_number)
        cause_kind, cause_value = _attribution(
            snap, game.game_number, before_turn, point.turn_number)
        # point.turn_number is Arena's shared turn counter (both players'
        # turns); "your turn" must say self_turn_index instead — the row for
        # this turn is already in `turns`, since that is what `_positions`
        # built `point` from in the first place.
        self_turn_index = next(
            t.self_turn_index for t in turns if t.turn_number == point.turn_number
        )
        before = decimal(point.index_before, 2, signed=True)
        after = decimal(point.index_after, 2, signed=True)
        if cause_kind == "card":
            detail = _(
                "Your position went from {before} to {after} by your turn {turn} — the "
                "largest single swing against you this game. In that window, {card} was on "
                "record."
            ).format(before=before, after=after, turn=self_turn_index, card=cause_value)
        elif cause_kind == "damage":
            detail = _(
                "Your position went from {before} to {after} by your turn {turn} — the "
                "largest single swing against you this game. In that window, {total} damage "
                "taken was on record."
            ).format(before=before, after=after, turn=self_turn_index, total=cause_value)
        else:
            detail = _(
                "Your position went from {before} to {after} by your turn {turn} — the "
                "largest single swing against you this game."
            ).format(before=before, after=after, turn=self_turn_index)

        evidence = [
            Evidence("index_before", _("Position index before the swing"),
                     round(point.index_before, 2)),
            Evidence("index_after", _("Position index after the swing"),
                     round(point.index_after, 2)),
            Evidence("drop", _("Size of the swing"), round(point.drop, 2),
                     display=f"{decimal(point.drop, 2)} — {swing_words(point.drop)}"),
        ]
        if cause_kind == "damage":
            evidence.append(Evidence("cause_damage", _("Damage taken in that window"),
                                     cause_value))

        findings.append(
            Finding(
                code="turning_point",
                analyzer=ANALYZER, category=Category.TRAJECTORY,
                severity=Severity.DECISIVE if point.drop >= SWING_DECISIVE else Severity.NOTICE,
                confidence=Confidence.PARTIAL, game_number=game.game_number,
                turn_number=point.turn_number, self_turn_index=self_turn_index,
                title=_("The game turned on your turn {turn}").format(turn=self_turn_index),
                detail=detail,
                evidence=tuple(evidence),
                caveats=(
                    _("The position index is a fixed-weight approximation over life, board, "
                      "hand and mana — not a rules engine, and not a claim about which single "
                      "play caused the swing."),
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
