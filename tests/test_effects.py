"""Tests for review/effects.py's keyword tagging.

Oracle text below is each real card's actual printed text (not invented),
so a pattern match here is evidence the pattern matches real cards, not
just a string built to satisfy it.
"""

from __future__ import annotations

from sensei_top.review.effects import (
    UNPARSED_REDUCTION,
    CostReduction,
    EffectTags,
    alternate_costs,
    chosen_basic_type_colors,
    classify,
    cost_reduction,
    is_finisher,
    mana_requirement,
    mana_value,
)


def test_unknown_when_oracle_text_was_never_populated():
    assert classify(None, "Creature — Human") == "unknown"


def test_a_vanilla_creature_has_no_tags_not_unknown():
    """Real text, no effect keywords: absence is observed, not a gap."""
    tags = classify("", "Creature — Bear")
    assert isinstance(tags, EffectTags)
    assert tags.tags == frozenset()


def test_sweeper():
    tags = classify("Destroy all creatures. They can't be regenerated.", "Sorcery")
    assert "sweeper" in tags


def test_sweeper_exile_variant():
    tags = classify("Exile all creatures.", "Sorcery")
    assert "sweeper" in tags


def test_spot_removal():
    tags = classify("Destroy target nonblack creature.", "Instant")
    assert "spot_removal" in tags
    assert "sweeper" not in tags


def test_counterspell():
    tags = classify("Counter target spell.", "Instant")
    assert "counterspell" in tags


def test_card_draw():
    tags = classify("Draw two cards.", "Sorcery")
    assert "card_draw" in tags


def test_discard():
    tags = classify(
        "Target player reveals their hand. You choose a noncreature, nonland card "
        "from it. That player discards that card.",
        "Sorcery",
    )
    assert "discard" in tags


def test_lifegain():
    tags = classify("You gain 7 life.", "Sorcery")
    assert "lifegain" in tags


def test_ramp():
    tags = classify(
        "Search your library for a basic land card, put it onto the battlefield "
        "tapped, then shuffle.",
        "Sorcery",
    )
    assert "ramp" in tags


def test_a_card_can_carry_more_than_one_tag():
    tags = classify("Draw a card. You gain 2 life.", "Instant")
    assert {"card_draw", "lifegain"} <= tags.tags


# --- mana value -------------------------------------------------------------


def test_mana_value_sums_generic_and_colored_pips():
    assert mana_value("{3}{U}{U}") == 5


def test_mana_value_counts_a_hybrid_pip_as_one():
    assert mana_value("{2/W}{2/W}") == 2


def test_mana_value_of_free_spell_is_zero_not_none():
    assert mana_value("{0}") == 0


def test_mana_value_of_none_is_none_not_zero():
    """rule 4: an unread cost is unknown, never claimed free to cast."""
    assert mana_value(None) is None


# --- mana requirement (colored pips, not just the total) --------------------


def test_mana_requirement_splits_generic_from_colored_pips():
    req = mana_requirement("{1}{U}{U}")
    assert req.generic == 1
    assert req.pips == (frozenset({"U"}), frozenset({"U"}))


def test_mana_requirement_of_pure_generic_cost():
    req = mana_requirement("{3}")
    assert req.generic == 3
    assert req.pips == ()


def test_mana_requirement_x_spell_drops_the_x_from_both():
    """Traumatic Critique's real cost — X is 0 until chosen, same rule
    mana_value() already applies."""
    req = mana_requirement("{X}{U}{R}")
    assert req.generic == 0
    assert req.pips == (frozenset({"U"}), frozenset({"R"}))


def test_mana_requirement_true_hybrid_pip_holds_both_colors():
    req = mana_requirement("{U/R}")
    assert req.generic == 0
    assert req.pips == (frozenset({"U", "R"}),)


def test_mana_requirement_monocolored_hybrid_keeps_only_the_color():
    """{2/W} can be paid with 2 generic mana or one white mana; the generic
    alternative is dropped, so this can only ever be too conservative, never
    wrongly permissive (see _pip_colors's own docstring)."""
    req = mana_requirement("{2/W}{2/W}")
    assert req.generic == 0
    assert req.pips == (frozenset({"W"}), frozenset({"W"}))


def test_mana_requirement_preserves_mana_value_invariant():
    for cost in ("{3}{U}{U}", "{1}{G}", "{U/R}{U/R}", "{2/W}", "{0}", "{X}{U}{R}"):
        req = mana_requirement(cost)
        assert req.generic + len(req.pips) == mana_value(cost)


def test_mana_requirement_of_none_is_none_not_empty():
    """rule 4: an unread cost is unknown, never claimed castable off nothing."""
    assert mana_requirement(None) is None


def test_mana_requirement_of_free_spell_is_empty_not_none():
    req = mana_requirement("{0}")
    assert req.generic == 0
    assert req.pips == ()


# --- // split (Adventure, MDFC) ----------------------------------------------
#
# Hearth Elemental // Stoke Genius's real printed cost, on file in cards.
# Summing every pip in the whole string (the pre-fix behavior) gives 8 —
# both faces double-counted as if they were one cost — when the front face,
# the one this creature is actually cast from, is 6.


def test_mana_value_reads_only_the_front_face_of_a_split_cost():
    assert mana_value("{5}{R} // {1}{R}") == 6


def test_mana_requirement_reads_only_the_front_face_of_a_split_cost():
    req = mana_requirement("{5}{R} // {1}{R}")
    assert req.generic == 5
    assert req.pips == (frozenset({"R"}),)


def test_alternate_costs_returns_the_other_faces():
    assert alternate_costs("{5}{R} // {1}{R}") == ("{1}{R}",)


def test_alternate_costs_of_a_single_faced_card_is_empty():
    assert alternate_costs("{3}{U}{U}") == ()


def test_alternate_costs_of_none_is_empty_not_none():
    assert alternate_costs(None) == ()


def test_alternate_costs_own_face_is_itself_parseable():
    """Stoke Genius's own adventure-spell cost, read the normal way."""
    (spell_cost,) = alternate_costs("{5}{R} // {1}{R}")
    assert mana_value(spell_cost) == 2


# --- cost_reduction (real oracle text from the Spellementals deck) ---------


def test_cost_reduction_of_none_oracle_text_is_none():
    assert cost_reduction(None) is None


def test_cost_reduction_of_ordinary_text_is_none():
    assert cost_reduction("Flying, trample") is None


def test_cost_reduction_eddymurk_crab():
    """Real oracle text on file for Eddymurk Crab (grp_id 91584)."""
    text = (
        "Flash\nThis spell costs {1} less to cast for each instant and sorcery "
        "card in your graveyard.\nThis creature enters tapped if it's not your "
        "turn.\nWhen this creature enters, tap up to two target creatures."
    )
    assert cost_reduction(text) == CostReduction(per=1, fuel="graveyard_instant_sorcery")


def test_cost_reduction_hearth_elemental():
    """Real oracle text on file for Hearth Elemental // Stoke Genius (86835)."""
    text = (
        "This spell costs {X} less to cast, where X is the number of cards in "
        "your graveyard that are instant cards, sorcery cards, and/or have an "
        "Adventure."
    )
    assert cost_reduction(text) == CostReduction(per=1, fuel="graveyard_instant_sorcery")


def test_cost_reduction_sunderflock_is_a_different_fuel_kind_not_a_per_card_count():
    """Real oracle text on file for Sunderflock (98392). The discount is one
    lookup (the board's biggest Elemental), not a per-card count, so `per`
    is None rather than a faked "1 per something"."""
    text = (
        "This spell costs {X} less to cast, where X is the greatest mana "
        "value among Elementals you control.\nFlying\nWhen this creature "
        "enters, if you cast it, return all non-Elemental creatures to "
        "their owners' hands."
    )
    reduction = cost_reduction(text)
    assert reduction == CostReduction(per=None, fuel="board_elemental_mv")


def test_cost_reduction_unparsed_shape_degrades_rather_than_guesses():
    """A "less to cast" clause of a shape this parser has never seen must
    not be silently priced at 0 or matched to an unrelated fuel — rule 4."""
    text = "This spell costs {2} less to cast if you control a Dragon."
    assert cost_reduction(text) == UNPARSED_REDUCTION


# --- finisher (approximate, documented as such) -----------------------------


def test_finisher_needs_both_type_and_mana_value():
    text = "Flying, trample"
    assert is_finisher(text, "Creature — Dragon", "{4}{R}{R}") is True
    assert is_finisher(text, "Creature — Bear", "{1}{G}") is False
    assert is_finisher(text, "Instant", "{4}{R}{R}") is False


def test_finisher_is_tagged_through_classify_when_mana_cost_is_given():
    tags = classify("Flying", "Creature — Dragon", mana_cost="{4}{R}{R}")
    assert "finisher" in tags


def test_finisher_is_never_asserted_without_a_mana_cost():
    tags = classify("Flying", "Creature — Dragon")
    assert "finisher" not in tags


# --- chosen_basic_type_colors (a land whose own text names its colors, no
# --- produced_mana export to read them from) --------------------------------


def test_chosen_basic_type_colors_multiversal_passage():
    """Real oracle text on file for Multiversal Passage (grp_id 97998, read
    read-only from data/sensei-top.db's own `cards` table — this land is not in
    any fixture). Scryfall's own produced_mana export is blank for it since
    it has no fixed mana ability, but the text itself both chooses a basic
    land type as it enters and then declares the land itself that type, so
    the real color set is a known fact despite the gap."""
    text = (
        "As this land enters, choose a basic land type. Then you may pay 2 life. "
        "If you don't, it enters tapped.\nThis land is the chosen type."
    )
    assert chosen_basic_type_colors(text) == ("W", "U", "B", "R", "G")


def test_chosen_basic_type_colors_thran_portal():
    """Real oracle text on file for Thran Portal: a different card shape
    from Multiversal Passage (it also enters tapped conditionally, and taxes
    its own mana abilities), but the same two clauses this function actually
    keys on are both present — "choose a basic land type" and "is the chosen
    type" (here followed by "in addition to its other types", which doesn't
    stop the substring match)."""
    text = (
        "This land enters tapped unless you control two or fewer other lands.\n"
        "As this land enters, choose a basic land type.\n"
        "This land is the chosen type in addition to its other types.\n"
        "Mana abilities of this land cost an additional 1 life to activate."
    )
    assert chosen_basic_type_colors(text) == ("W", "U", "B", "R", "G")


def test_chosen_basic_type_colors_none_for_a_thriving_land():
    """Real oracle text on file for Thriving Bluff, which already has its
    own produced_mana on file. This clause chooses a color, not a basic
    land type, and never says the land itself "is" that type — a different
    shape from Multiversal Passage's, so it must not match here even though
    both clauses start with "choose"."""
    text = (
        "This land enters tapped. As it enters, choose a color other than red.\n"
        "{T}: Add {R} or one mana of the chosen color."
    )
    assert chosen_basic_type_colors(text) is None


def test_chosen_basic_type_colors_none_when_oracle_text_is_none():
    assert chosen_basic_type_colors(None) is None
