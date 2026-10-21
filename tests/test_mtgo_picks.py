"""The pure grouping rule for waiting MTGO matches.

Hand-built inputs, one branch each. The rule knows no SQL and no files, so
nothing here needs a fixture: the numbers are chosen to land on or beside a
bar, and the expectations follow from the bar's definition.
"""

from __future__ import annotations

from sensei_top.mtgo.picks import PickList, PickMatch, group_matches


def _match(match_id, n, fmt=None):
    return PickMatch(match_id, frozenset(range(n)), fmt)


def _list(deck_id, cards, fmt=None):
    return PickList(deck_id, fmt, frozenset(cards))


def test_a_match_the_top_list_holds_in_full_is_sure():
    result = group_matches([_match("m", 10)], [_list("a", range(10)), _list("b", range(3))])
    (group,) = result.groups
    assert (group.fit, group.top, group.key) == ("sure", ("a",), "sure:a")
    assert [p.match_id for p in group.matches] == ["m"]
    assert result.unsure == ()


def _fits(played, held):
    result = group_matches([_match("m", played)], [_list("a", range(held))])
    return [g.fit for g in result.groups], [u.reason for u in result.unsure]


def test_ninety_percent_is_sure_and_just_under_is_partial():
    assert _fits(20, 18) == (["sure"], [])  # 90 % exactly
    assert _fits(19, 17) == (["partial"], [])  # 89.5 %


def test_fifty_percent_is_partial_and_just_under_is_unsure():
    assert _fits(10, 5) == (["partial"], [])  # 50 % exactly
    assert _fits(11, 5) == ([], ["low_fit"])  # 45 %


def test_fewer_than_five_cards_is_unsure_whatever_the_fit():
    result = group_matches([_match("m", 4)], [_list("a", range(4))])
    (u,) = result.unsure
    assert (u.reason, u.cards_seen, u.best) == ("few_cards", 4, ("a", 4))
    assert result.groups == ()
    # Five is enough.
    assert group_matches([_match("m", 5)], [_list("a", range(5))]).groups


def test_no_list_in_the_matchs_format_is_unsure():
    result = group_matches([_match("m", 8, "Modern")], [_list("a", range(8), "Legacy")])
    (u,) = result.unsure
    assert (u.reason, u.best, u.scores) == ("no_list", None, {})
    # No lists at all is the same.
    assert group_matches([_match("m", 8)], []).unsure[0].reason == "no_list"


def test_a_top_tie_is_one_group_with_both_lists():
    result = group_matches([_match("m", 10)], [_list("b", range(10)), _list("a", range(10))])
    (group,) = result.groups
    assert group.top == ("a", "b")
    assert group.key == "sure:a|b"


def test_matches_with_the_same_tie_share_a_group_and_other_ties_do_not():
    both = [_list("a", range(10)), _list("b", range(10))]
    result = group_matches([_match("m1", 10), _match("m2", 10)], both)
    assert len(result.groups) == 1
    assert [p.match_id for p in result.groups[0].matches] == ["m1", "m2"]
    # A match whose best is "b" alone is a different group.
    mixed = group_matches(
        [_match("m1", 10), PickMatch("m3", frozenset(range(20, 30)), None)],
        [_list("a", range(10)), _list("b", [*range(10), *range(20, 30)])],
    )
    assert sorted(g.top for g in mixed.groups) == [("a", "b"), ("b",)]


def test_a_list_within_two_cards_is_close_and_counted_per_match():
    lists = [_list("top", range(10)), _list("near", range(8)), _list("far", range(7))]
    result = group_matches([_match("m1", 10), _match("m2", 10)], lists)
    (group,) = result.groups
    # near holds 8 of the top's 10 (within 2); far holds 7 (3 behind).
    assert group.close_in == {"near": 2}
    assert group.matches[0].close == ("near",)


def test_a_list_of_another_format_neither_wins_nor_counts_as_close():
    lists = [
        _list("legacy", range(10), "Legacy"),  # would win, but wrong format
        _list("modern", range(9), "Modern"),
    ]
    result = group_matches([_match("m", 10, "Modern")], lists)
    (group,) = result.groups
    assert group.top == ("modern",)
    assert group.close_in == {}
    assert group.matches[0].scores == {"modern": 9}


def test_a_list_with_no_format_competes_in_every_format():
    result = group_matches(
        [_match("m", 10, "Modern")],
        [_list("any", range(10)), _list("legacy", range(10), "Legacy")],
    )
    assert result.groups[0].top == ("any",)


def test_no_inferred_format_means_every_list_competes():
    result = group_matches(
        [_match("m", 10)],
        [_list("legacy", range(10), "Legacy"), _list("modern", range(10), "Modern")],
    )
    assert result.groups[0].top == ("legacy", "modern")


def test_low_fit_reports_the_best_list_it_found():
    result = group_matches([_match("m", 10)], [_list("a", range(3)), _list("b", range(2))])
    (u,) = result.unsure
    assert (u.reason, u.best, u.scores) == ("low_fit", ("a", 3), {"a": 3, "b": 2})


def test_sure_and_partial_matches_of_one_top_list_are_separate_groups():
    # Same top list "a" for both; the 10-card match holds 9 (sure), the
    # 20-card match holds 15 of its own cards (partial).
    sure = PickMatch("s", frozenset(range(10)), None)
    partial = PickMatch("p", frozenset(range(100, 120)), None)
    lst = _list("a", [*range(9), *range(100, 115)])
    result = group_matches([sure, partial], [lst])
    assert {(g.fit, g.matches[0].match_id) for g in result.groups} == {
        ("sure", "s"),
        ("partial", "p"),
    }


def test_nothing_matched_means_no_best_list_not_a_guess_by_id_order():
    result = group_matches([_match("m", 10)], [_list("a", [900]), _list("b", [901])])
    (u,) = result.unsure
    assert (u.reason, u.best) == ("low_fit", None)
