"""What was still live — Duke's *Thoughtseize You*, applied without ever
actually seeing the opponent's hand. Their consensus staples (what the
field usually plays in their archetype) minus what they actually revealed
this match is a real, checkable list of "cards they could still have had",
and over-committing the board while a sweeper-tagged staple is still
unaccounted for is the single most common way that list gets punished.
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

ANALYZER = "information"

STAPLE_MIN_SHARE = 0.5
# A board worth worrying about losing to a sweeper — below this, even a
# board wipe is not much of a loss.
OVER_COMMIT_PERMANENTS = 4


def analyze_information(snap: MatchSnapshot) -> AnalyzerResult:
    findings: list[Finding] = []
    gaps: list[Gap] = []

    if snap.opp_consensus is None:
        cause = "opponent_unclassified" if snap.opponent_archetype_key is None \
            else "consensus_unavailable"
        gaps.append(
            Gap(ANALYZER, "The opponent's archetype was not identified with enough of a "
                          "corpus behind it to know what their deck usually plays, so "
                          "nothing here could be read about what was still live.",
                cause=cause)
        )
        return AnalyzerResult((), tuple(gaps))

    staples = snap.opp_consensus.staples(min_share=STAPLE_MIN_SHARE)
    still_live = [c for c in staples if c.name not in snap.opponent_revealed_names]

    if still_live:
        shown = still_live[:6]
        opponent_label = snap.opponent_label or "this archetype"
        remainder = len(still_live) - len(shown)
        names = ", ".join(c.name for c in shown)
        remainder_clause = f", and {remainder} more" if remainder > 0 else ""
        highest_share = round(shown[0].share * 100)
        lowest_share = round(shown[-1].share * 100)
        findings.append(
            Finding(
                code="still_live_staples",
                analyzer=ANALYZER, category=Category.INFORMATION, severity=Severity.NOTE,
                confidence=Confidence.PARTIAL,
                title=f"{len(still_live)} of the opponent's usual staples never showed up",
                detail=(
                    f"{highest_share}% to {lowest_share}% of {opponent_label}'s own "
                    f"tournament decklists run these, and none of them appeared this match: "
                    f"{names}{remainder_clause}."
                ),
                evidence=(
                    Evidence("still_live_count", "Field staples never revealed", len(still_live)),
                    Evidence("highest_share", "Highest share among those shown", highest_share,
                             unit="%"),
                    Evidence("lowest_share", "Lowest share among those shown", lowest_share,
                             unit="%"),
                    Evidence("staple_count", "Total staples considered", len(staples)),
                    *((Evidence("remainder", "Staples named beyond those listed", remainder),)
                      if remainder > 0 else ()),
                ),
                caveats=(
                    "This is the field's typical decklist for the archetype, not the "
                    "opponent's actual 60 cards — some of these may not be in this "
                    "specific list at all.",
                ),
            )
        )

    sweepers_live = [c for c in still_live if isinstance(c.tags, frozenset) and "sweeper" in c.tags]
    if sweepers_live:
        for game in snap.games:
            turns = snap.turns_in(game.game_number)
            if not turns:
                continue
            peak = max(turns, key=lambda t: t.self_permanents or 0)
            if (peak.self_permanents or 0) < OVER_COMMIT_PERMANENTS:
                continue
            findings.append(
                Finding(
                    code="over_committed_into_sweeper",
                    analyzer=ANALYZER, category=Category.INFORMATION, severity=Severity.NOTICE,
                    confidence=Confidence.PARTIAL, game_number=game.game_number,
                    turn_number=peak.turn_number, self_turn_index=peak.self_turn_index,
                    title=(f"Peaked at {peak.self_permanents} permanents with a sweeper "
                           f"unaccounted for"),
                    detail=(
                        f"On your turn {peak.self_turn_index} you had {peak.self_permanents} "
                        f"permanents in play. {sweepers_live[0].name}, one of "
                        f"{snap.opponent_label or 'this archetype'}'s own staples, had not "
                        f"shown up yet — a hand this wide is exactly what that card is for."
                    ),
                    evidence=(
                        Evidence("peak_permanents", "Permanents at the widest point",
                                 peak.self_permanents),
                    ),
                    caveats=(
                        "Whether the opponent actually held this card in hand at that moment "
                        "is unknown — this names a real risk taken, not a confirmed punish.",
                    ),
                    pattern="Over-committed the board with a sweeper unaccounted for",
                )
            )

    if not findings:
        gaps.append(Gap(ANALYZER, "Every one of the opponent's usual staples either showed up "
                                   "or fell below the share this reader considers a staple.",
                         game_number=None))

    return AnalyzerResult(tuple(findings), tuple(gaps))
