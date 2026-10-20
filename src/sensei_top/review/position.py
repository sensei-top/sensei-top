"""The position index: one number per turn saying who is ahead, and by how
much — Duke's *Playing From Ahead, Playing From Behind* and *Tempo & Card
Advantage* made into a transparent, fixed-weight formula.

Deliberately not fitted to this player's own outcomes: a heuristic that
predicts nothing is information about the heuristic, not a reason to fit it.
Verified against a real database of 116-117 completed games (2026-08-20):
at turn 6 the index's sign matched the eventual result only 59.5% of the
time (mean +0.003 in wins vs. -0.067 in losses), at turn 10 70.9%, and at
each game's own last recorded turn 92.3% (mean +0.283 in wins vs. -0.341 in
losses). So the index tracks how decided a game has *become*: a caller
anchoring "the moment it turned" to a late, large drop is on solid ground;
a caller expecting a confident verdict at turn 6 is asking the wrong
question of it. These numbers were not tuned toward; report them again if
a change here moves them meaningfully.

Every weight below is commented with the principle it encodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from sensei_top.i18n import _

# Normalizers: roughly the swing that "matters a lot" for each resource, so
# a turn where every resource moved by its own normalizer lands near the
# clamp rather than a fraction of it.
_LIFE_SPAN = 20.0      # a full starting life total swinging hands
_BOARD_SPAN = 10.0     # two average creatures' worth of power difference
_BOARD_SPAN_FALLBACK = 5.0  # permanent-count proxy, a coarser unit than power
_CARDS_SPAN = 7.0      # a full opening hand's worth of card advantage
_MANA_SPAN = 6.0       # most games are decided well before 6 lands matter more

# Game-stage ramp: tempo (board) dominates the early turns, card advantage
# grows in weight as the game runs long — Tempo & Card Advantage's own
# framing, not a fitted curve. Stage reaches 1.0 (fully "late game") at
# turn 20, roughly a long Bo1 game's length.
_STAGE_TURNS = 20.0
_LIFE_WEIGHT = 0.30           # life matters at a constant rate throughout
_BOARD_WEIGHT_EARLY = 0.45    # tempo is the dominant early resource
_BOARD_WEIGHT_LATE = 0.30     # (0.45 - 0.15 at full stage)
_CARDS_WEIGHT_EARLY = 0.15    # card advantage barely matters turn 1
_CARDS_WEIGHT_LATE = 0.35     # (0.15 + 0.20 at full stage)
_MANA_WEIGHT = 0.10           # a steady, minor tiebreaker throughout

# Words for a swing's size, shared by trajectory.py's severity call and
# summary.py's phrasing. See docs/review.md,
# "`trajectory.py` — the shape of the whole game".
SWING_DECISIVE = 0.30
SWING_NOTABLE = 0.15


def swing_words(drop: float) -> str:
    """A swing's size in words, in the reader's language."""
    if drop >= SWING_DECISIVE:
        return _("a decisive swing")
    if drop >= SWING_NOTABLE:
        return _("a notable swing")
    return _("a small swing")


@dataclass(frozen=True, slots=True)
class TurnPosition:
    """One turn's position index and the raw differentials behind it —
    every number here is what the index was actually computed from, the
    same discipline ``Finding``/``Evidence`` already requires elsewhere."""

    turn_number: int
    index: float
    life_diff: float
    board_diff: float
    cards_diff: float
    mana_diff: float
    board_from_power: bool  # False when the board term fell back to permanent count


def _stage(turn_number: int) -> float:
    return min(turn_number / _STAGE_TURNS, 1.0)


def turn_position(
    turn_number: int,
    *,
    self_life: int | None,
    opp_life: int | None,
    self_power: int | None,
    opp_power: int | None,
    self_permanents: int | None,
    opp_permanents: int | None,
    self_hand: int | None,
    opp_hand: int | None,
    self_lands: int | None,
    opp_lands: int | None,
) -> TurnPosition | None:
    """One turn's index, or ``None`` when too little was observed to say
    anything (rule 4) — life is the one term with no substitute, so a turn
    missing either life total produces no index at all rather than one
    silently computed from three resources instead of four.
    """
    if self_life is None or opp_life is None:
        return None

    life_diff = (self_life - opp_life) / _LIFE_SPAN

    board_from_power = self_power is not None and opp_power is not None
    if board_from_power:
        board_diff = (self_power - opp_power) / _BOARD_SPAN
    elif self_permanents is not None and opp_permanents is not None:
        board_diff = (self_permanents - opp_permanents) / _BOARD_SPAN_FALLBACK
    else:
        board_diff = 0.0

    cards_diff = (
        (self_hand - opp_hand) / _CARDS_SPAN if self_hand is not None and opp_hand is not None
        else 0.0
    )
    mana_diff = (
        (self_lands - opp_lands) / _MANA_SPAN if self_lands is not None and opp_lands is not None
        else 0.0
    )

    stage = _stage(turn_number)
    board_weight = _BOARD_WEIGHT_EARLY - (_BOARD_WEIGHT_EARLY - _BOARD_WEIGHT_LATE) * stage
    cards_weight = _CARDS_WEIGHT_EARLY + (_CARDS_WEIGHT_LATE - _CARDS_WEIGHT_EARLY) * stage

    index = (
        _LIFE_WEIGHT * life_diff
        + board_weight * board_diff
        + cards_weight * cards_diff
        + _MANA_WEIGHT * mana_diff
    )
    index = max(-1.0, min(1.0, index))

    return TurnPosition(
        turn_number=turn_number,
        index=index,
        life_diff=life_diff,
        board_diff=board_diff,
        cards_diff=cards_diff,
        mana_diff=mana_diff,
        board_from_power=board_from_power,
    )


@dataclass(frozen=True, slots=True)
class TurningPoint:
    """The turn with the largest single-turn drop in the index — the moment
    ``Finding``s point to as "this is where it turned", not a claim about
    why (a caller attributes cause from damage_events/opponent_plays)."""

    turn_number: int
    drop: float
    index_before: float
    index_after: float


def turning_point(positions: list[TurnPosition]) -> TurningPoint | None:
    """The steepest single-step decline across consecutive recorded turns.

    Consecutive in *the list*, not in turn number — this reader can have
    gaps, and a "drop" spanning a gap is real information (a lot changed
    between two observed turns) rather than something to skip. Returns
    ``None`` for fewer than two positions, or when the index never dropped
    (a game that was never really contested from this player's side).
    """
    if len(positions) < 2:
        return None
    ordered = sorted(positions, key=lambda p: p.turn_number)
    worst: TurningPoint | None = None
    for before, after in pairwise(ordered):
        drop = before.index - after.index
        if drop > 0 and (worst is None or drop > worst.drop):
            worst = TurningPoint(
                turn_number=after.turn_number,
                drop=drop,
                index_before=before.index,
                index_after=after.index,
            )
    return worst
