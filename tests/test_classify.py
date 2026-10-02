"""The partial-information rules.

Upstream's definitions assume a complete 60-card decklist. A match shows us
eight to fifteen of the opponent's cards, and every rule tested here follows
from that gap: an unmet requirement means "not seen yet", never "not in the
deck". Definitions are synthetic so each rule is isolated.
"""

from sensei_top.archetypes import classify
from sensei_top.archetypes.classify import (
    Definition,
    _elimination_reason,
    _rank_archetypes,
    _seen_forms,
    _signature_card_names,
    choose,
    color_label,
    colour_factor,
    confidence_of,
    evaluate,
    format_key,
    normalize,
    required_colors,
)


def seen(*names: str):
    return _seen_forms(names)


def condition(type_: str, *cards: str) -> dict:
    return {"Type": type_, "Cards": list(cards)}


def archetype(key: str, name: str, *conditions: dict, color: bool = False) -> Definition:
    return Definition(key=key, name=name, kind="archetype", include_color=color,
                      conditions=list(conditions))


def fallback(key: str, name: str, *cards: str) -> Definition:
    return Definition(key=key, name=name, kind="fallback", include_color=False,
                      common_cards=list(cards))


def colors_by_name(**by_name: str) -> dict[str, frozenset[str]]:
    """A ``colors_by_name`` map for synthetic cards, keyed the same way
    ``classify._card_colors_by_name`` keys a real one: every accepted form of
    the name, from ``normalize()``."""
    table: dict[str, frozenset[str]] = {}
    for name, identity in by_name.items():
        for form in normalize(name):
            table[form] = frozenset(identity)
    return table


# --- names ------------------------------------------------------------------


def test_double_faced_names_match_either_face_or_the_joined_form():
    """Arena stores the faces as separate cards and sometimes joins them;
    upstream writes the join with && in places and // in others."""
    forms = seen("Unholy Annex // Ritual Chamber")
    assert normalize("Unholy Annex") & forms
    assert normalize("Unholy Annex && Ritual Chamber") & forms
    assert normalize("Ritual Chamber") & forms


def test_markup_left_in_an_old_card_table_still_matches():
    """Databases written before the importer preferred the plain localization
    still hold Unity markup; matching should degrade, not break."""
    assert normalize("Deep-Cavern Bat") & seen("<nobr>Deep-Cavern</nobr> Bat")


def test_matching_ignores_case_and_stray_whitespace():
    assert normalize("stock  up") & seen("Stock Up")


def test_a_card_whose_faces_disagree_takes_the_whole_names_colours(monkeypatch):
    """Arena's card table lists an adventure's own half as a card of its own:
    ``Elusive Otter // Grove's Bounty`` is blue, while ``Grove's Bounty`` alone
    is green, so the face's key merges to blue-green. The lookup must answer
    with the whole name's colours whatever order normalize()'s set yields —
    here forced face-first, the order that used to turn a blue deck green."""
    table = {
        "elusive otter // grove's bounty": frozenset("U"),
        "elusive otter": frozenset("U"),
        "grove's bounty": frozenset("UG"),
    }
    monkeypatch.setattr(
        classify, "normalize",
        lambda name: ["grove's bounty", "elusive otter", "elusive otter // grove's bounty"],
    )
    assert classify._card_colors("Elusive Otter // Grove's Bounty", table) == frozenset("U")


# --- condition semantics ----------------------------------------------------


def test_an_unmet_requirement_is_unknown_not_a_failure():
    """The whole design: we see a fraction of the deck, so not having seen a
    card is not evidence the deck lacks it."""
    met, unknown, _ = evaluate([condition("InMainboard", "Never Seen")], seen("Something Else"))
    assert (met, unknown) == (0, 1)


def test_a_met_requirement_reports_the_card_that_met_it():
    met, unknown, evidence = evaluate(
        [condition("InMainboard", "Momo, Friendly Flier")], seen("Momo, Friendly Flier")
    )
    assert (met, unknown, evidence) == (1, 0, ["Momo, Friendly Flier"])


def test_does_not_contain_passes_when_the_card_was_never_seen():
    """Absence cannot violate an exclusion, and it earns no credit either."""
    assert evaluate([condition("DoesNotContain", "Jeskai Revelation")], seen("Momo")) == (0, 0, [])


def test_does_not_contain_eliminates_when_the_card_was_seen():
    """The one place partial information is decisive: seeing the card is proof."""
    assert evaluate(
        [condition("DoesNotContain", "Jeskai Revelation")], seen("Jeskai Revelation")
    ) is None


def test_one_or_more_needs_a_single_hit():
    assert evaluate(
        [condition("OneOrMoreInMainboard", "Haliya", "Abandoned Air Temple")], seen("Haliya")
    ) == (1, 0, ["Haliya"])


def test_the_upstream_lowercase_typo_is_honoured():
    """`OneorMoreInMainboard` is really in the Standard data. A typo in someone
    else's file should not silently drop a condition."""
    met, _, _ = evaluate([condition("OneorMoreInMainboard", "Haliya")], seen("Haliya"))
    assert met == 1


def test_two_or_more_needs_two_distinct_cards():
    rule = [condition("TwoOrMoreInMainboard", "A", "B", "C")]
    assert evaluate(rule, seen("A"))[0] == 0
    assert evaluate(rule, seen("A", "B"))[0] == 1


def test_all_cards_must_be_seen_for_a_multi_card_requirement():
    rule = [condition("InMainboard", "A", "B")]
    assert evaluate(rule, seen("A"))[0] == 0
    assert evaluate(rule, seen("A", "B"))[0] == 1


def test_a_sideboard_requirement_can_never_be_met():
    """We never see a sideboard. It counts as unknown rather than being ignored,
    so a sideboard-gated archetype cannot outrank one proved on the battlefield."""
    assert evaluate([condition("InSideboard", "Negate")], seen("Negate")) == (0, 1, [])


def test_a_sideboard_exclusion_is_vacuous_and_uncounted():
    assert evaluate([condition("DoesNotContainSideboard", "Negate")], seen("Negate")) == (0, 0, [])


def test_a_main_or_sideboard_requirement_is_satisfiable_from_play():
    met, unknown, _ = evaluate([condition("InMainOrSideboard", "Negate")], seen("Negate"))
    assert (met, unknown) == (1, 0)


def test_an_unrecognised_condition_type_degrades_to_unknown():
    """Upstream adds condition types without notice."""
    assert evaluate([condition("SomeNewRule", "A")], seen("A")) == (0, 1, [])


# --- complete decklists -------------------------------------------------------
# A cache decklist is 60 cards plus a real sideboard, not a dozen revealed
# cards — the asymmetry above inverts: absence is real evidence, so an unmet
# positive requirement eliminates rather than merely going unproved.


def test_complete_mode_eliminates_on_an_unmet_requirement():
    """Under partial info this is `(0, 1)`, not elimination — see
    test_an_unmet_requirement_is_unknown_not_a_failure above."""
    result = evaluate(
        [condition("InMainboard", "Never Seen")], seen("Something Else"), complete=True
    )
    assert result is None


def test_complete_mode_still_credits_a_met_requirement():
    result = evaluate(
        [condition("InMainboard", "Momo, Friendly Flier")],
        seen("Momo, Friendly Flier"),
        complete=True,
    )
    assert result == (1, 0, ["Momo, Friendly Flier"])


def test_complete_mode_reads_the_real_sideboard():
    """`InSideboard` is unconditionally unknown under partial info (see
    test_a_sideboard_requirement_can_never_be_met); a complete decklist has an
    actual sideboard to check it against."""
    rule = [condition("InSideboard", "Negate")]
    assert evaluate(rule, seen(), complete=True, sideboard_seen=seen("Negate")) == (
        1, 0, ["Negate"],
    )
    assert evaluate(rule, seen(), complete=True, sideboard_seen=seen("Something Else")) is None


def test_complete_mode_does_not_contain_checks_the_real_sideboard_too():
    """`DoesNotContainSideboard` is vacuous under partial info (see
    test_a_sideboard_exclusion_is_vacuous_and_uncounted); against a real
    sideboard it is a real exclusion, both ways."""
    rule = [condition("DoesNotContainSideboard", "Negate")]
    assert evaluate(rule, seen(), complete=True, sideboard_seen=seen("Negate")) is None
    assert evaluate(rule, seen(), complete=True, sideboard_seen=seen("Something Else")) == (
        0, 0, [],
    )


def test_complete_mode_main_or_sideboard_checks_both_boards():
    rule = [condition("InMainOrSideboard", "Negate")]
    assert evaluate(rule, seen(), complete=True, sideboard_seen=seen("Negate"))[0] == 1
    assert evaluate(rule, seen("Negate"), complete=True, sideboard_seen=seen())[0] == 1
    assert evaluate(rule, seen(), complete=True, sideboard_seen=seen()) is None


def test_complete_mode_an_inmainboard_requirement_ignores_the_sideboard():
    """A card sideboarded but not maindecked does not satisfy `InMainboard` —
    it has to actually be in the 60."""
    rule = [condition("InMainboard", "Negate")]
    assert evaluate(rule, seen(), complete=True, sideboard_seen=seen("Negate")) is None


def test_choose_skips_the_confidence_gates_when_complete():
    """A weak, one-condition fit that partial matching would leave unnamed
    (below MIN_ARCHETYPE_FIT) is still the answer once the decklist is
    complete and nothing else survives elimination: there is no uncertainty
    left to gate on."""
    weak = archetype("Weak", "Weak Deck", condition("InMainboard", "Signature Card"))
    verdict = choose(
        [weak], [], seen("Signature Card"), "", {}, cards_seen=1, complete=True,
    )
    assert verdict is not None
    assert verdict.key == "Weak"


def test_choose_still_picks_the_best_fit_among_survivors_when_complete():
    """Two archetypes both fully proved: the one proved by more independent
    requirements ranks first, same fit-scoring logic as partial mode."""
    one_condition = archetype("One", "One Deck", condition("InMainboard", "Card A"))
    two_conditions = archetype(
        "Two", "Two Deck", condition("InMainboard", "Card A"), condition("InMainboard", "Card B")
    )
    verdict = choose(
        [one_condition, two_conditions], [], seen("Card A", "Card B"), "", {},
        cards_seen=2, complete=True,
    )
    assert verdict is not None
    assert verdict.key == "Two"


def test_choose_eliminates_a_definition_whose_requirement_is_absent_from_a_complete_list():
    """The core inversion: a definition that would merely go unproved under
    partial info is ruled out outright once absence is real evidence."""
    requires_absent = archetype(
        "Absent", "Absent Deck", condition("InMainboard", "Never Played")
    )
    verdict = choose(
        [requires_absent], [], seen("Something Else"), "", {}, cards_seen=1, complete=True
    )
    assert verdict is None


# --- colour agreement --------------------------------------------------------


def test_required_colors_unions_an_all_condition_and_intersects_a_one_of():
    """An `all` condition needs every card, so their colours union. A
    `one-of` only guarantees whichever colour every alternative shares."""
    table = colors_by_name(**{"White Card": "W", "Blue Card": "U", "Both Card": "WU"})
    every_card = archetype("A", "A", condition("InMainboard", "White Card", "Blue Card"))
    assert required_colors(every_card, table) == frozenset({"W", "U"})

    one_of = archetype("B", "B", condition("OneOrMoreInMainboard", "White Card", "Both Card"))
    assert required_colors(one_of, table) == frozenset({"W"})


def test_required_colors_ignores_cards_with_unknown_colour_identity():
    """A card the local `cards` table has never heard of contributes nothing —
    never guessed (rule 4), same as an unmet card requirement."""
    definition = archetype("A", "A", condition("InMainboard", "Not In Table"))
    assert required_colors(definition, {}) == frozenset()


def test_required_colors_skips_negative_and_sideboard_only_conditions():
    table = colors_by_name(**{"Excluded": "B", "Hidden": "R"})
    definition = archetype(
        "A", "A",
        condition("DoesNotContain", "Excluded"),
        condition("InSideboard", "Hidden"),
    )
    assert required_colors(definition, table) == frozenset()


def test_colour_factor_is_one_when_nothing_required_is_missing():
    assert colour_factor(frozenset(), "UB", cards_seen=10) == 1.0
    assert colour_factor(frozenset({"U"}), "UB", cards_seen=10) == 1.0


def test_colour_factor_has_a_floor_regardless_of_how_many_colours_are_missing():
    """The penalty demotes a guess, it never erases it — one missing colour
    and two missing colours both bottom out at the same floor."""
    one_missing = colour_factor(frozenset({"G"}), "UB", cards_seen=1000)
    two_missing = colour_factor(frozenset({"G", "R"}), "UB", cards_seen=1000)
    assert one_missing == two_missing == 0.1


def test_colour_factor_sharpens_as_more_cards_are_seen():
    early = colour_factor(frozenset({"G"}), "UB", cards_seen=1)
    late = colour_factor(frozenset({"G"}), "UB", cards_seen=20)
    assert early > late


# --- selection --------------------------------------------------------------


def test_fewer_unknowns_wins_at_equal_evidence():
    """The bug this pins: ranking on met alone picked an archetype with an
    outstanding requirement over one whose every requirement was proved."""
    proved = archetype("Control", "Jeskai Control", condition("InMainboard", "Jeskai Revelation"))
    partial = archetype("Harmonizer", "Harmonizer",
                        condition("InMainboard", "Stock Up"),
                        condition("InMainboard", "Never Seen"))
    verdict = choose([partial, proved], [], seen("Jeskai Revelation", "Stock Up"), "WUR", {}, 10)
    assert verdict.name == "Jeskai Control"


def test_a_tie_still_ranks_reproducibly_by_file_stem():
    """Even though choose() now refuses to *name* a tie (below), the shortlist
    behind it still needs to order tied candidates the same way every time."""
    first = archetype("Alpha", "Alpha", condition("InMainboard", "Shared"))
    second = archetype("Beta", "Beta", condition("InMainboard", "Shared"))
    ranked = _rank_archetypes([second, first], seen("Shared"), {}, "", 10)
    assert [d.key for d, *_ in ranked] == ["Alpha", "Beta"]


def test_a_full_tie_is_left_unclear_rather_than_broken_arbitrarily():
    """The old behaviour broke a tie by file stem and named the winner — but a
    coin flip is not evidence that one is more likely than the other."""
    first = archetype("Alpha", "Alpha", condition("InMainboard", "Shared"))
    second = archetype("Beta", "Beta", condition("InMainboard", "Shared"))
    assert choose([second, first], [], seen("Shared"), "", {}, 10) is None


def test_two_close_rivals_with_different_names_stay_unclear():
    """Closeness itself is the signal here: neither a raw-met ranking nor a
    plain tie-break should apply, because the two are close but not equal."""
    leader = archetype("A", "Alpha Deck", condition("InMainboard", "X"))
    rival = archetype(
        "B", "Beta Deck",
        condition("InMainboard", "Y1"), condition("InMainboard", "Y2"),
        condition("InMainboard", "N1"), condition("InMainboard", "N2"),
    )
    showed = seen("X", "Y1", "Y2")
    assert choose([leader, rival], [], showed, "", {}, 10) is None


def test_a_single_met_requirement_with_others_outstanding_is_only_a_lead():
    """Not confirmed, so a well-evidenced fallback should be preferred."""
    lead = archetype("Burn", "Burn",
                     condition("InMainboard", "Burst Lightning"),
                     condition("InMainboard", "Unseen One"),
                     condition("InMainboard", "Unseen Two"))
    counted = fallback("Elementals", "Elementals", "Vibrance", "Wistfulness", "Deceit", "D", "E")
    showed = seen("Burst Lightning", "Vibrance", "Wistfulness", "Deceit")
    verdict = choose([lead], [counted], showed, "", {}, 10)
    assert (verdict.name, verdict.method) == ("Elementals", "fallback")


def test_a_confirmed_archetype_beats_a_fallback():
    confirmed = archetype("Momo", "Momo", condition("InMainboard", "Momo, Friendly Flier"))
    generic = fallback("Control", "Control", "Momo, Friendly Flier", "X", "Y")
    verdict = choose([confirmed], [generic], seen("Momo, Friendly Flier", "X"), "WU", {}, 10)
    assert verdict.method == "archetype"


def test_a_proved_archetype_is_never_vetoed_by_a_better_matched_fallback():
    """A fallback names a family, not a specific deck: however many of its
    common cards line up, it should never outrank a genuinely proved
    archetype condition."""
    confirmed = archetype("Momo", "Momo", condition("InMainboard", "Momo, Friendly Flier"))
    generic = fallback("Control", "Control", *[f"Card {n}" for n in range(8)])
    showed = seen("Momo, Friendly Flier", *[f"Card {n}" for n in range(6)])
    verdict = choose([confirmed], [generic], showed, "WU", {}, 10)
    assert (verdict.name, verdict.method) == ("Momo", "archetype")


def test_a_missing_required_colour_can_push_a_guess_below_the_naming_floor():
    """The bug this pins: 'Dimir Harmonizer' named itself off a single generic
    card while every card seen was blue-black and the archetype's own
    signature creature is green."""
    green_card = archetype("Harmonizer", "Harmonizer", condition("InMainboard", "Green Thing"))
    table = colors_by_name(**{"Green Thing": "G"})
    on_color = choose([green_card], [], seen("Green Thing"), "G", table, 10)
    off_color = choose([green_card], [], seen("Green Thing"), "UB", table, 10)
    assert on_color is not None
    assert off_color is None


def test_more_cards_seen_sharpens_a_missing_colours_penalty():
    green_card = archetype("Harmonizer", "Harmonizer", condition("InMainboard", "Green Thing"))
    table = colors_by_name(**{"Green Thing": "G"})
    early = choose([green_card], [], seen("Green Thing"), "UB", table, 1)
    late = choose([green_card], [], seen("Green Thing"), "UB", table, 20)
    assert early is not None
    assert late is None


def test_a_one_card_fallback_hit_is_noise_and_is_rejected():
    """10% of a six-card list is a single card. The absolute floor is what makes
    the ratio meaningful against a dozen revealed cards."""
    thin_fallback = fallback("Artifacts", "Artifacts", *"ABCDEF")
    assert choose([], [thin_fallback], seen("A"), "", {}, 10) is None


def test_a_fallback_below_the_ratio_is_rejected():
    thin = fallback("Ramp", "Ramp", *[f"Card {n}" for n in range(40)])
    assert choose([], [thin], seen("Card 1", "Card 2"), "", {}, 10) is None


def test_nothing_matching_returns_no_verdict():
    unmatched = archetype("A", "A", condition("InMainboard", "X"))
    assert choose([unmatched], [], seen("Y"), "", {}, 10) is None


def test_a_variant_refines_the_name_only_when_fully_proved():
    parent = archetype("Momo", "Momo", condition("InMainboard", "Momo, Friendly Flier"))
    parent.variants = [
        {"Name": "Flash", "Conditions": [condition("InMainboard", "Split Up")]},
        {"Name": "Ramp", "Conditions": [condition("InMainboard", "Never Seen")]},
    ]
    verdict = choose([parent], [], seen("Momo, Friendly Flier", "Split Up"), "WU", {}, 10)
    assert verdict.name == "Momo Flash"


# --- signature cards ---------------------------------------------------------


def test_signature_card_names_include_common_cards_after_conditions():
    definition = archetype("Momo", "Momo", condition("InMainboard", "A", "B"))
    definition.common_cards = ["B", "C"]
    assert _signature_card_names(definition) == ["A", "B", "C"]


def test_signature_card_names_exclude_negative_and_sideboard_only_conditions():
    """A DoesNotContain names what the deck avoids, not what it plays; a
    sideboard-only requirement can never be observed, so flagging it 'unseen'
    would always be true and mislead a play-around hint rather than inform it."""
    definition = archetype(
        "Momo", "Momo",
        condition("InMainboard", "A"),
        condition("DoesNotContain", "Excluded"),
        condition("InSideboard", "Hidden"),
    )
    assert _signature_card_names(definition) == ["A"]


def test_signature_card_names_drop_duplicates_but_keep_first_order():
    definition = archetype("Momo", "Momo", condition("InMainboard", "A", "B", "A"))
    definition.common_cards = ["A"]
    assert _signature_card_names(definition) == ["A", "B"]


# --- elimination reasons -----------------------------------------------------


_KAITO = "Kaito, Bane of Nightmares"


def test_elimination_reason_names_the_seen_card_that_ruled_it_out():
    definition = archetype("Control", "Control", condition("DoesNotContain", _KAITO))
    assert _elimination_reason(definition, seen(_KAITO)) == _KAITO


def test_elimination_reason_is_none_when_nothing_was_seen_or_nothing_is_negative():
    definition = archetype("Control", "Control", condition("DoesNotContain", _KAITO))
    assert _elimination_reason(definition, seen("Something Else")) is None
    positive = archetype("A", "A", condition("InMainboard", "X"))
    assert _elimination_reason(positive, seen("X")) is None


# --- colours and formats ----------------------------------------------------


def test_colour_names_cover_mono_guild_shard_and_beyond():
    assert color_label("") == "Colorless"
    assert color_label("G") == "Mono-Green"
    assert color_label("WU") == "Azorius"
    assert color_label("UR") == "Izzet"
    assert color_label("WUR") == "Jeskai"
    assert color_label("WUBR") == "4c"
    assert color_label("WUBRG") == "5c"


def test_colours_are_read_in_wubrg_order_not_the_order_given():
    assert color_label("RW") == "Boros"


def test_include_color_in_name_is_honoured_both_ways():
    coloured = archetype("Momo", "Momo", condition("InMainboard", "M"), color=True)
    plain = archetype("Control", "Jeskai Control", condition("InMainboard", "M"))
    assert choose([coloured], [], seen("M"), "WU", {}, 10).name == "Azorius Momo"
    assert choose([plain], [], seen("M"), "WUBR", {}, 10).name == "Jeskai Control"


def test_standard_brawl_is_not_standard():
    """It contains the word, which is exactly why this is a lookup and not a
    substring test."""
    assert format_key("TraditionalStandard", None) == "Standard"
    assert format_key("Standard", None) == "Standard"
    assert format_key("StandardBrawl", None) is None
    assert format_key("Historic", None) is None
    assert format_key("Alchemy", "Traditional_Ladder") is None


def test_the_event_names_the_format_when_the_deck_does_not():
    assert format_key(None, "Traditional_Ladder") == "Standard"
    assert format_key(None, "Historic_Ladder") is None
    assert format_key(None, None) is None


# --- confidence -------------------------------------------------------------


def test_confidence_needs_fit_margin_and_a_look_at_the_deck():
    from sensei_top.archetypes.classify import Verdict

    decisive = Verdict("k", "n", "archetype", 2, 0, (), fit=0.5, margin=3.0)
    assert confidence_of(decisive, cards_seen=15) == "high"
    assert confidence_of(decisive, cards_seen=3) == "medium"  # too few cards seen for 'high'

    close_call = Verdict("k", "n", "archetype", 1, 0, (), fit=0.5, margin=2.2)
    assert confidence_of(close_call, cards_seen=15) == "medium"  # margin short of the 'high' bar

    weak = Verdict("k", "n", "archetype", 1, 2, (), fit=0.15, margin=5.0)
    assert confidence_of(weak, cards_seen=15) == "low"

    # A fallback never reads 'high', even with a fit and margin that would
    # clear the bar for an archetype: it names a family, not a specific deck.
    generic = Verdict("k", "n", "fallback", 5, 0, (), fit=0.5, margin=10.0)
    assert confidence_of(generic, cards_seen=15) == "medium"
