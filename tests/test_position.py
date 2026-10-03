"""Tests for review/position.py: the transparent, fixed-weight position
index and the turning-point finder built on it.

This index's real-world separation was measured against the live database
and is documented in the module's own docstring, not re-verified here —
that number depends on one user's actual match history and cannot be a
committed fixture (AGENTS.md's privacy rule). These tests instead pin down
the formula's own documented properties: what each term contributes, the
clamp, the stage ramp, the fallback when power is unobserved, and rule 4's
"no life means no index" refusal.
"""

from __future__ import annotations

from sensei_top.review.position import TurnPosition, turn_position, turning_point


def _base(**overrides):
    base = dict(
        self_life=20, opp_life=20, self_power=0, opp_power=0,
        self_permanents=0, opp_permanents=0, self_hand=7, opp_hand=7,
        self_lands=0, opp_lands=0,
    )
    base.update(overrides)
    return base


def test_no_index_without_both_life_totals():
    """rule 4: life has no substitute term, so a turn missing either side's
    life produces no index rather than one computed from three resources."""
    assert turn_position(5, **_base(self_life=None)) is None
    assert turn_position(5, **_base(opp_life=None)) is None


def test_equal_state_is_a_zero_index():
    pos = turn_position(5, **_base())
    assert pos.index == 0.0


def test_life_advantage_alone_gives_a_positive_index():
    pos = turn_position(1, **_base(self_life=20, opp_life=10))
    assert pos.index > 0
    assert pos.life_diff == 0.5  # (20-10)/20


def test_board_term_prefers_power_over_permanent_count():
    pos = turn_position(1, **_base(self_power=6, opp_power=0, self_permanents=1, opp_permanents=3))
    assert pos.board_from_power is True
    assert pos.board_diff == 0.6  # 6/10, ignoring the permanent counts entirely


def test_board_term_falls_back_to_permanents_when_power_is_unobserved():
    pos = turn_position(
        1, **_base(self_power=None, opp_power=None, self_permanents=3, opp_permanents=1)
    )
    assert pos.board_from_power is False
    assert pos.board_diff == 0.4  # (3-1)/5, the coarser fallback span


def test_index_is_clamped_to_plus_minus_one():
    pos = turn_position(1, **_base(self_life=20, opp_life=-40, self_power=50, opp_power=0))
    assert pos.index == 1.0


def test_board_weight_shrinks_and_cards_weight_grows_with_turn_number():
    """Tempo & Card Advantage's own framing: an identical card-advantage
    lead should count for more late than early, and an identical board lead
    should count for less."""
    early = turn_position(1, **_base(self_hand=7, opp_hand=0))
    late = turn_position(25, **_base(self_hand=7, opp_hand=0))  # stage clamps at 1.0 past turn 20
    assert late.index > early.index

    early_board = turn_position(1, **_base(self_power=6))
    late_board = turn_position(25, **_base(self_power=6))
    assert early_board.index > late_board.index


def test_turning_point_is_none_below_two_positions():
    assert turning_point([]) is None
    assert turning_point([turn_position(1, **_base())]) is None


def test_turning_point_finds_the_largest_drop_across_a_gap():
    """Consecutive in the list, not in turn number — a drop spanning a real
    gap in what was recorded is still the information a caller wants."""
    positions = [
        turn_position(1, **_base(self_life=20, opp_life=20)),
        turn_position(2, **_base(self_life=18, opp_life=19)),  # small drop
        turn_position(6, **_base(self_life=4, opp_life=20)),   # steep drop, across a gap
        turn_position(7, **_base(self_life=4, opp_life=15)),   # recovers a little
    ]
    point = turning_point(positions)
    assert point.turn_number == 6
    assert point.drop > 0


def test_turning_point_is_none_when_the_index_never_drops():
    positions = [
        turn_position(1, **_base(self_life=10, opp_life=20)),
        turn_position(2, **_base(self_life=15, opp_life=15)),
        turn_position(3, **_base(self_life=20, opp_life=10)),
    ]
    assert turning_point(positions) is None


def test_turn_position_is_a_plain_frozen_dataclass():
    """Contract check for downstream analyzers: field names must not drift
    silently, since Evidence keys will reference them by name."""
    pos = turn_position(1, **_base())
    assert isinstance(pos, TurnPosition)
    assert pos.turn_number == 1
