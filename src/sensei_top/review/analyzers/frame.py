"""The matchup and the role it demands — Flores' *Who's the Beatdown?* and
Duke's *Role Assignment* made computable: "Misassignment of Role = Game
Loss." Three signals, applied to each side's cards: more creatures usually
means beatdown; more removal usually means control; more card draw and
counterspells almost always means control.

Our own side reads from ``snap.own_cards`` — the *exact* decklist, weighted
by real copy counts. The opponent's side reads from ``snap.opp_consensus``'s
staples, weighted by how many of the field's own decklists for that
archetype run each card — the best available substitute for a decklist we
never get to see, and now a real creature-rate term rather than a fixed
zero: ``ConsensusCard.type_line`` (added alongside this fix) lets the
opponent's side use the same ``effects.is_creature`` check the own side
already did, since without it "more creatures ⇒ beatdown" could only ever vote
beatdown. Either side missing (an unclassified deck; a corpus too thin for
a consensus), or a consensus that resolves but carries no signal at all
(every rate at zero — a corpus of colorless artifacts, or a tagging gap),
is a gap, not a guess at the role.
"""

from __future__ import annotations

from dataclasses import dataclass

from sensei_top.review import effects
from sensei_top.review.consensus import ArchetypeConsensus
from sensei_top.review.findings import (
    AnalyzerResult,
    Category,
    Confidence,
    Evidence,
    Finding,
    Gap,
    Severity,
)
from sensei_top.review.snapshot import MatchSnapshot, OwnCard

ANALYZER = "frame"

# Below this many cards contributing to a profile, the three shares are too
# noisy to read a role from — the same sample-gating discipline the rest of
# this package already applies (PLAY_DRAW_MIN_GAMES's precedent).
MIN_PROFILE_CARDS = 6.0


@dataclass(frozen=True, slots=True)
class RoleProfile:
    total_weight: float
    creature_rate: float
    removal_rate: float
    card_advantage_rate: float


def _own_profile(cards: tuple[OwnCard, ...]) -> RoleProfile | None:
    total = creature = removal = card_adv = 0.0
    for card in cards:
        total += card.count
        if effects.is_creature(card.type_line):
            creature += card.count
        if isinstance(card.tags, frozenset):
            if "spot_removal" in card.tags or "sweeper" in card.tags:
                removal += card.count
            if "card_draw" in card.tags or "counterspell" in card.tags:
                card_adv += card.count
    if total < MIN_PROFILE_CARDS:
        return None
    return RoleProfile(total, creature / total, removal / total, card_adv / total)


def _consensus_profile(consensus: ArchetypeConsensus | None) -> RoleProfile | None:
    if consensus is None:
        return None
    staples = consensus.staples(min_share=0.3)
    total = creature = removal = card_adv = 0.0
    for card in staples:
        weight = card.share * card.copies
        total += weight
        if effects.is_creature(card.type_line):
            creature += weight
        if isinstance(card.tags, frozenset):
            if "spot_removal" in card.tags or "sweeper" in card.tags:
                removal += weight
            if "card_draw" in card.tags or "counterspell" in card.tags:
                card_adv += weight
    if total < MIN_PROFILE_CARDS:
        return None
    return RoleProfile(total, creature / total, removal / total, card_adv / total)


_MULLIGAN_CAVEAT = (
    "Arena logs the hand it offers before each mulligan decision (table/opening_hand.py), "
    "but never the hand you actually shipped after bottoming cards under the London rule — "
    "the hands you shipped are not in the log at any point, so nothing here can say "
    "whether a mulligan was right."
)


def _opening_findings(snap: MatchSnapshot) -> tuple[list[Finding], list[Gap]]:
    """Neutral context about how each game started: mulligans and the play/
    draw assignment. No mana/land content (the user's own call — see
    docs/review.md); no verdict on a mulligan, ever — this report is a
    post-game read over projected data, and the pre-decision hand offer
    that table/opening_hand.py reads live is never persisted anywhere the
    projection can see (nor should it be — a review is for what happened,
    not a re-litigation of a decision already made with the information
    available at the time).
    """
    findings: list[Finding] = []
    gaps: list[Gap] = []
    for game in snap.games:
        if game.self_mulligans is None:
            gaps.append(Gap(ANALYZER, "Your mulligan count was never observed for this game.",
                             game_number=game.game_number))
        else:
            n = game.self_mulligans
            findings.append(
                Finding(
                    code="mulligan_taken", analyzer=ANALYZER, category=Category.FRAME,
                    severity=Severity.NOTE, confidence=Confidence.OBSERVED,
                    game_number=game.game_number,
                    title="Kept your opening seven" if n == 0
                          else f"Mulliganed {n} time{'s' if n != 1 else ''}",
                    detail="You kept your opening hand without a mulligan." if n == 0
                           else f"You took {n} mulligan{'s' if n != 1 else ''} before "
                                f"keeping a hand.",
                    evidence=(Evidence("self_mulligans", "Mulligans taken", n),),
                    caveats=(_MULLIGAN_CAVEAT,),
                )
            )

        if game.on_play is None:
            gaps.append(Gap(ANALYZER, "Whether you were on the play or the draw was never "
                                       "observed for this game.", game_number=game.game_number))
        else:
            findings.append(
                Finding(
                    code="on_play_context", analyzer=ANALYZER, category=Category.FRAME,
                    severity=Severity.NOTE, confidence=Confidence.OBSERVED,
                    game_number=game.game_number,
                    title="On the play" if game.on_play else "On the draw",
                    detail="You were on the play this game." if game.on_play
                           else "You were on the draw this game.",
                )
            )
    return findings, gaps


def analyze_frame(snap: MatchSnapshot) -> AnalyzerResult:
    findings, gaps = _opening_findings(snap)

    if snap.own_archetype is None:
        gaps.append(Gap(ANALYZER, "Your own deck did not resolve to a known Standard archetype, "
                                   "so nothing here could compare it to the opponent's.",
                         cause="own_unclassified"))
        return AnalyzerResult(tuple(findings), tuple(gaps))
    if snap.opponent_archetype_key is None:
        gaps.append(Gap(ANALYZER, "The opponent's deck was not identified as a known archetype "
                                   "for this match, so no field comparison was possible.",
                         cause="opponent_unclassified"))
        return AnalyzerResult(tuple(findings), tuple(gaps))

    own = _own_profile(snap.own_cards)
    opp = _consensus_profile(snap.opp_consensus)
    if own is None or opp is None:
        gaps.append(Gap(ANALYZER, "Too few of this match's cards carry known effect tags to "
                                   "read a role from — see the effect-tagging gap above."))
        return AnalyzerResult(tuple(findings), tuple(gaps))
    if opp.creature_rate == 0.0 and opp.removal_rate == 0.0 and opp.card_advantage_rate == 0.0:
        gaps.append(Gap(ANALYZER, "The opponent's archetype consensus carried no creature, "
                                   "removal or card-advantage signal at all, so no role vote "
                                   "could be read from it."))
        return AnalyzerResult(tuple(findings), tuple(gaps))

    votes_beatdown = 0
    votes_control = 0
    if own.creature_rate > opp.creature_rate:
        votes_beatdown += 1
    elif own.creature_rate < opp.creature_rate:
        votes_control += 1
    if own.removal_rate > opp.removal_rate:
        votes_control += 1
    elif own.removal_rate < opp.removal_rate:
        votes_beatdown += 1
    # "Almost always" control, per Flores — weighted double.
    if own.card_advantage_rate > opp.card_advantage_rate:
        votes_control += 2
    elif own.card_advantage_rate < opp.card_advantage_rate:
        votes_beatdown += 2

    if votes_beatdown == votes_control:
        role = "mixed"
        role_text = ("a mixed role — no side of this matchup clearly wins the "
                     "beatdown-versus-control read")
    elif votes_beatdown > votes_control:
        role, role_text = "beatdown", "the beatdown"
    else:
        role, role_text = "control", "the control deck"

    evidence = (
        Evidence("role", "Role this matchup assigns", role),
        Evidence("own_creature_rate", "Your own creature share", round(own.creature_rate, 2)),
        Evidence("opp_creature_rate", "Field's creature share for this archetype",
                 round(opp.creature_rate, 2)),
        Evidence("own_removal_rate", "Your own removal share", round(own.removal_rate, 2)),
        Evidence("opp_removal_rate", "Field's removal share for this archetype",
                 round(opp.removal_rate, 2)),
        Evidence("own_card_advantage_rate", "Your own draw/counter share",
                 round(own.card_advantage_rate, 2)),
        Evidence("opp_card_advantage_rate", "Field's draw/counter share for this archetype",
                 round(opp.card_advantage_rate, 2)),
    )

    findings.append(
        Finding(
            code="role_assignment",
            analyzer=ANALYZER,
            category=Category.FRAME,
            severity=Severity.NOTE if role == "mixed" else Severity.NOTICE,
            confidence=Confidence.PARTIAL,
            title=f"This matchup casts you as {role_text}",
            detail=(
                f"Against {snap.opponent_label or 'this opponent'}, comparing your deck's own "
                f"creature/removal/card-advantage mix to the field's typical build of their "
                f"archetype points to {role_text}. Misjudging this is Flores' classic "
                f"error: the beatdown has to race, the control deck has to survive to card "
                f"advantage — playing the other one's game plan loses on its own terms."
            ),
            evidence=evidence,
            caveats=(
                "The opponent's side of this comparison is the field's typical decklist for "
                "their archetype, not their actual 60 cards, which this reader never sees.",
            ),
        )
    )
    return AnalyzerResult(tuple(findings), tuple(gaps))
