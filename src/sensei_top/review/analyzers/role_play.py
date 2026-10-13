"""Did the role ``frame.py`` assigns actually get played. Reuses that
module's own profile-building (not its voting output) so this stays a pure
function of the same inputs rather than depending on another analyzer's
result — the registry runs every analyzer independently over one snapshot.

Two checks, one per role, deliberately simple and literal rather than a
general "good beatdown play" model: a beatdown deck that holds a board lead
without ever pressing it, and a control deck that never once turned its
slower plan into the card advantage it was supposed to be trading time for.
"""

from __future__ import annotations

from sensei_top.i18n import N_, _, ngettext
from sensei_top.review.analyzers.frame import _consensus_profile, _own_profile
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

ANALYZER = "role_play"

# The role codes are what findings and gaps carry; the word is only for a
# sentence that names one.
_ROLE_WORDS = {"beatdown": N_("beatdown"), "control": N_("control")}


def role_word(role: str) -> str:
    """The display word for a role code, in the current language."""
    return _(_ROLE_WORDS[role])


def _role(snap: MatchSnapshot) -> str | None:
    if snap.own_archetype is None or snap.opponent_archetype_key is None:
        return None
    own = _own_profile(snap.own_cards)
    opp = _consensus_profile(snap.opp_consensus)
    if own is None or opp is None:
        return None
    if opp.creature_rate == 0.0 and opp.removal_rate == 0.0 and opp.card_advantage_rate == 0.0:
        return None
    votes_beatdown = votes_control = 0
    if own.creature_rate != opp.creature_rate:
        votes_beatdown += 1 if own.creature_rate > opp.creature_rate else -1
        votes_control += 1 if own.creature_rate < opp.creature_rate else -1
    if own.removal_rate != opp.removal_rate:
        votes_control += 1 if own.removal_rate > opp.removal_rate else -1
        votes_beatdown += 1 if own.removal_rate < opp.removal_rate else -1
    if own.card_advantage_rate != opp.card_advantage_rate:
        votes_control += 2 if own.card_advantage_rate > opp.card_advantage_rate else -2
        votes_beatdown += 2 if own.card_advantage_rate < opp.card_advantage_rate else -2
    if votes_beatdown == votes_control:
        return None
    return "beatdown" if votes_beatdown > votes_control else "control"


def _dealt_damage_this_turn(snap: MatchSnapshot, game_number: int, turn_number: int) -> bool:
    return any(
        d.game_number == game_number and d.turn_number == turn_number
        and d.source_is_self is True and d.target_instance_id is None
        for d in snap.damage_events
    )


def analyze_role_play(snap: MatchSnapshot) -> AnalyzerResult:
    findings: list[Finding] = []
    gaps: list[Gap] = []

    role = _role(snap)
    if role is None:
        if snap.opponent_archetype_key is None:
            cause = "opponent_unclassified"
        elif snap.own_archetype is None:
            cause = "own_unclassified"
        else:
            cause = None  # a real tie or a signal-free consensus, not a classification gap
        gaps.append(
            Gap(ANALYZER, _("No clear role was assigned for this matchup — either an "
                            "archetype did not resolve for one side, or the two sides' "
                            "profiles were too close to call a role either way (see frame's "
                            "own finding or gap) — so whether it was played correctly could "
                            "not be checked."),
                cause=cause)
        )
        return AnalyzerResult((), tuple(gaps))

    if role == "beatdown":
        for game in snap.games:
            held_back = 0
            for t in snap.turns_in(game.game_number):
                if t.self_power is None or t.opp_power is None:
                    continue
                if t.self_power > t.opp_power and not _dealt_damage_this_turn(
                    snap, game.game_number, t.turn_number
                ):
                    held_back += 1
            if held_back == 0:
                continue
            findings.append(
                Finding(
                    code="beatdown_held_back",
                    analyzer=ANALYZER, category=Category.ROLE, severity=Severity.NOTICE,
                    confidence=Confidence.PARTIAL, game_number=game.game_number,
                    title=ngettext(
                        "Held a board lead without attacking on {n} turn",
                        "Held a board lead without attacking on {n} turns",
                        held_back,
                    ).format(n=held_back),
                    detail=_(
                        "This matchup casts you as the beatdown deck — you have to kill the "
                        "opponent before their plan comes online. On the turns counted here, "
                        "your side had more power on board than the opponent's, and no damage "
                        "was dealt to them that turn."
                    ),
                    evidence=(Evidence("turns_held_back",
                                       _("Turns with a board lead and no damage"),
                                       held_back),),
                    caveats=(
                        _("This reader cannot see combat tricks, blockers held back for a "
                          "reason, or a hand full of removal worth protecting — a board lead "
                          "not pressed is sometimes exactly correct play."),
                    ),
                    pattern=_("Held a board lead without attacking"),
                )
            )
    else:
        for game in snap.games:
            turns = snap.turns_in(game.game_number)
            hand_diffs = [
                t.self_hand - t.opp_hand for t in turns
                if t.self_hand is not None and t.opp_hand is not None
            ]
            if not hand_diffs:
                continue
            if max(hand_diffs) > 0:
                continue
            findings.append(
                Finding(
                    code="control_never_ahead_on_cards",
                    analyzer=ANALYZER, category=Category.ROLE, severity=Severity.NOTICE,
                    confidence=Confidence.PARTIAL, game_number=game.game_number,
                    title=_("Never held a card-advantage lead this game"),
                    detail=_(
                        "This matchup casts you as the control deck — the deck that survives "
                        "the early turns to trade one card at a time until it is ahead on "
                        "resources. Across every turn this reader could measure, your hand was "
                        "never larger than the opponent's, which is the reward that plan is "
                        "supposed to produce."
                    ),
                    evidence=(
                        Evidence("best_hand_diff", _("Largest hand-size lead reached"),
                                 max(hand_diffs)),
                        Evidence("turns_measured", _("Turns with both hand sizes recorded"),
                                 len(hand_diffs)),
                    ),
                    caveats=(
                        _("Card advantage can also cash out as board state or life total "
                          "rather than hand size — a removal spell trading one-for-one shows "
                          "up here as flat, not as a swing."),
                    ),
                    pattern=_("Never held a card-advantage lead as the control deck"),
                )
            )

    if not findings and not gaps:
        gaps.append(Gap(ANALYZER, _("Assigned role was '{role}', and nothing in this reader's "
                                    "checks found a mismatch — that is not the same as a "
                                    "perfectly played role, only that these specific checks "
                                    "found nothing.").format(role=role_word(role)),
                         game_number=None))

    return AnalyzerResult(tuple(findings), tuple(gaps))
