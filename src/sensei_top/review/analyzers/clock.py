"""Who is killing whom, and how fast — Duke's *Damage Racing* and Flores'
*Philosophy of Fire* made computable from ``damage_events``: cards for life,
not cards for cards. This reader sees every point of damage dealt (the
combat/damage projection, ``migrations/014_combat.sql``), so a race's pace is
a real observed rate, not an inference from life totals alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from sensei_top.i18n import _, ngettext
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
            Gap(ANALYZER, _("No damage was observed to either player in this match, so no "
                            "race could be measured — either the game never reached combat, "
                            "or this reader's combat parsing found nothing to attribute."))
        )
        return AnalyzerResult((), tuple(gaps))

    for game in snap.games:
        state = _race_state(snap.damage_events, game.game_number)
        if state is None:
            gaps.append(
                Gap(ANALYZER, _("No damage to either player was observed this game."),
                    game_number=game.game_number)
            )
            continue
        if state.self_dealt + state.opp_dealt < MIN_DAMAGE_FOR_A_RACE:
            gaps.append(
                Gap(ANALYZER, ngettext(
                        "Only {n} total damage was observed to either player — too little "
                        "to call a race.",
                        "Only {n} total damage was observed to either player — too little "
                        "to call a race.",
                        state.self_dealt + state.opp_dealt,
                    ).format(n=state.self_dealt + state.opp_dealt),
                    game_number=game.game_number)
            )
            continue

        pace_self = state.self_dealt / state.last_turn if state.last_turn else 0.0
        pace_opp = state.opp_dealt / state.last_turn if state.last_turn else 0.0

        evidence = (
            Evidence("self_damage_dealt", _("Damage you dealt to the opponent"), state.self_dealt),
            Evidence("opp_damage_dealt", _("Damage the opponent dealt to you"), state.opp_dealt),
            Evidence("last_damage_turn", _("Last turn either side dealt damage"), state.last_turn),
        )

        if state.self_dealt == state.opp_dealt:
            findings.append(
                Finding(
                    code="race_even",
                    analyzer=ANALYZER, category=Category.CLOCK, severity=Severity.NOTE,
                    confidence=Confidence.OBSERVED, game_number=game.game_number,
                    title=ngettext("An even race: {n} damage each way",
                                   "An even race: {n} damage each way",
                                   state.self_dealt).format(n=state.self_dealt),
                    detail=ngettext(
                        "By turn {turn}, you and the opponent had each dealt {n} damage "
                        "to the other's life total — neither side was ahead in the race "
                        "by damage output alone.",
                        "By turn {turn}, you and the opponent had each dealt {n} damage "
                        "to the other's life total — neither side was ahead in the race "
                        "by damage output alone.",
                        state.self_dealt,
                    ).format(turn=state.last_turn, n=state.self_dealt),
                    evidence=evidence,
                )
            )
            continue

        margin = abs(state.self_dealt - state.opp_dealt)
        severity = Severity.DECISIVE if margin >= 10 else Severity.NOTICE
        caveats = (
            _("This counts damage dealt to a player only — creature-versus-creature "
              "combat and life lost to costs (a shockland, a payment) are excluded, "
              "since neither moves either player closer to winning the race itself."),
        )
        race_evidence = (
            *evidence,
            Evidence("pace_self", _("Your damage per player-turn"), round(pace_self, 1)),
            Evidence("pace_opp", _("Opponent's damage per player-turn"), round(pace_opp, 1)),
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
                    title=_("You were ahead in the damage race, {ours} to {theirs}"
                            ).format(ours=state.self_dealt, theirs=state.opp_dealt),
                    detail=_(
                        "You dealt {ours} damage to the opponent's life total; "
                        "they dealt {theirs} to yours, through turn "
                        "{turn}. Philosophy of Fire's own math: every card that "
                        "does not convert into damage, on either side, is a card losing this "
                        "particular race."
                    ).format(ours=state.self_dealt, theirs=state.opp_dealt,
                             turn=state.last_turn),
                    evidence=race_evidence,
                    caveats=caveats,
                    pattern=_("Led the damage race"),
                )
            )
        else:
            findings.append(
                Finding(
                    code="race_behind",
                    analyzer=ANALYZER, category=Category.CLOCK, severity=severity,
                    confidence=Confidence.OBSERVED, game_number=game.game_number,
                    title=_("The opponent was ahead in the damage race, {theirs} to {ours}"
                            ).format(ours=state.self_dealt, theirs=state.opp_dealt),
                    detail=_(
                        "They dealt {theirs} damage to your life total; you dealt "
                        "{ours} to theirs, through turn {turn}. "
                        "Philosophy of Fire's own math: every card that does not convert into "
                        "damage, on either side, is a card losing this particular race."
                    ).format(ours=state.self_dealt, theirs=state.opp_dealt,
                             turn=state.last_turn),
                    evidence=race_evidence,
                    caveats=caveats,
                    pattern=_("Fell behind in the damage race"),
                )
            )

    return AnalyzerResult(tuple(findings), tuple(gaps))
