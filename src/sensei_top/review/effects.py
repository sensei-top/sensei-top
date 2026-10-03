"""Tag a card with the effect classes a postmortem reasons about.

Keyword matching over ``cards.oracle_text``/``type_line`` — deliberately not
a rules engine. Each pattern is commented with the real card that motivated
it, so a false negative can be traced back to what the pattern was actually
checking for. ``oracle_text`` is ``NULL`` whenever a card was only ever named
by the Arena-client import (``migrations/015_card_text.sql``); every
function here returns ``"unknown"`` in that case rather than guessing a tag
from the name alone (AGENTS.md rule 4) — a caller must treat "unknown"
differently from "confirmed absent".

``EffectTags`` is a frozenset of the tags that matched, empty (not
"unknown") when text was available but nothing matched — that is a real,
observed absence, unlike a missing oracle_text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNKNOWN = "unknown"

_SWEEPER_RE = re.compile(
    r"destroy all creatures"          # Wrath of God
    r"|exile all creatures"           # Sunfall
    r"|each creature (?:gets|deals)"  # Pyroclasm-style ("deals 2 damage to each creature")
    r"|all creatures get -\d+/-\d+",  # Damnation-style anthem-negative
    re.IGNORECASE,
)
_SPOT_REMOVAL_RE = re.compile(
    r"destroy target [a-z ]*creature"   # Doom Blade ("target nonblack creature")
    r"|exile target [a-z ]*creature"    # Swords to Plowshares
    r"|target creature gets -\d+/-\d+"  # Defile-style
    r"|damage to target creature"       # Lightning Strike-style
    r"|damage to (?:target creature or planeswalker|any target)",  # Lightning Bolt
    re.IGNORECASE,
)
_COUNTERSPELL_RE = re.compile(r"counter target spell", re.IGNORECASE)
_CARD_DRAW_RE = re.compile(r"draw (?:a|two|three|\d+) cards?", re.IGNORECASE)
_DISCARD_RE = re.compile(r"discards? [a-z0-9 ]*cards?", re.IGNORECASE)  # Duress, Mind Rot
_LIFEGAIN_RE = re.compile(r"gain \d+ life|you gain life", re.IGNORECASE)
_RAMP_RE = re.compile(
    r"search your library for a(?:n?) (?:basic )?land"  # Rampant Growth
    r"|add \{?[wubrgc0-9]+\}? mana",  # Llanowar Elves-style ability text
    re.IGNORECASE,
)

_PATTERNS: dict[str, re.Pattern[str]] = {
    "sweeper": _SWEEPER_RE,
    "spot_removal": _SPOT_REMOVAL_RE,
    "counterspell": _COUNTERSPELL_RE,
    "card_draw": _CARD_DRAW_RE,
    "discard": _DISCARD_RE,
    "lifegain": _LIFEGAIN_RE,
    "ramp": _RAMP_RE,
}

# Finisher is not a rules-text concept, so it is not in _PATTERNS: a big
# creature or planeswalker rarely announces itself as a "finisher" in its
# own text. Approximated instead from mana value + type, and named as an
# approximation everywhere it is used — see finisher_tag()'s own docstring.
_FINISHER_MANA_VALUE = 5
_FINISHER_TYPES = ("Creature", "Planeswalker")

_PIP_RE = re.compile(r"\{([^}]+)\}")
_HYBRID_GENERIC_RE = re.compile(r"^\d+$")
_FACE_SEP_RE = re.compile(r"\s*//\s*")


def _front_face(mana_cost: str) -> str:
    """The face a card is cast from at its normal cost: the first half of a
    ``//`` pair (an Adventure's creature/planeswalker/land side, an MDFC's
    front), or the whole string when there is no second face.

    Arena/Scryfall-style cost strings for a split cost print both faces
    joined by ``" // "`` — e.g. Hearth Elemental // Stoke Genius is
    ``"{5}{R} // {1}{R}"``. Summing pips across the whole string (the bug
    this fixes) double-counts both faces as if they were one cost; a card is
    only ever cast from one face at a time, so ``mana_value``/
    ``mana_requirement`` read only this one. ``alternate_costs`` below
    surfaces the rest for a caller that needs it.
    """
    return _FACE_SEP_RE.split(mana_cost, maxsplit=1)[0]


def alternate_costs(mana_cost: str | None) -> tuple[str, ...]:
    """The other face(s) of a ``//`` cost — an Adventure spell's own cost, an
    MDFC's back face — as raw cost strings, in print order after the front
    face `mana_value`/`mana_requirement` read. Empty for a single-faced card
    or an absent cost. Each returned string is parseable by
    ``mana_value``/``mana_requirement`` in its own right (neither re-splits
    on ``//``, since a single face never contains one).
    """
    if not mana_cost:
        return ()
    faces = _FACE_SEP_RE.split(mana_cost)
    return tuple(faces[1:])


@dataclass(frozen=True, slots=True)
class EffectTags:
    """One card's effect classes. ``tags`` is empty, not unknown, when text
    was available but matched nothing — a vanilla creature is a real,
    observed absence of these effects, not a gap."""

    tags: frozenset[str]

    def __contains__(self, tag: str) -> bool:
        return tag in self.tags


def mana_value(mana_cost: str | None) -> int | None:
    """Sum a Scryfall/Arena-style mana cost string's pips: ``"{3}{U}{U}"`` -> 5.

    Returns ``None`` for an unparseable or absent cost — never 0, which
    would claim "free to cast" for a card whose cost was simply not read.
    A hybrid pip (``{U/R}``, ``{2/W}``) counts as 1, matching how mana value
    is defined for a hybrid symbol in the comprehensive rules; a Phyrexian
    pip (``{U/P}``) also counts as 1, its worst-case colored value.

    A ``//`` cost (Adventure, MDFC) is read from its front face alone —
    see ``_front_face`` — so this is the cost this card is *normally* cast
    for; ``alternate_costs`` surfaces the rest.
    """
    if not mana_cost:
        return None
    mana_cost = _front_face(mana_cost)
    pips = _PIP_RE.findall(mana_cost)
    if not pips and mana_cost.strip():
        return None
    total = 0
    for pip in pips:
        if _HYBRID_GENERIC_RE.match(pip):
            total += int(pip)
        elif pip.upper() == "X":
            continue  # X costs 0 on the stack until chosen; never observed here
        else:
            total += 1
    return total


def _pip_colors(pip: str) -> frozenset[str] | None:
    """Which colors satisfy one cost symbol, or ``None`` for a pip that is
    pure generic mana (a plain number, or X — already excluded by the
    caller). A hybrid pip (``U/R``) is satisfied by either color. A
    monocolored-hybrid pip (``2/W``) can *also* be paid with 2 generic mana,
    but that alternative is dropped here and only the colored option kept —
    the same "worst-case colored value" rule ``mana_value()`` already applies
    to a Phyrexian pip, so ``mana_requirement`` never calls a hand castable
    on an alternative it has not actually checked; it can only ever be wrong
    in the conservative direction (calling a castable hand uncastable), never
    the other way. A Phyrexian pip (``U/P``) keeps only its color, since the
    life-payment alternative is not a land in the hand either.
    """
    parts = [p for p in pip.upper().split("/") if p != "P" and not p.isdigit()]
    return frozenset(parts) if parts else None


@dataclass(frozen=True, slots=True)
class ManaRequirement:
    """One card's colored mana demands, split from its total the way
    ``mana_value()`` cannot: ``{1}{U}{U}`` and ``{3}`` are both mana value 3,
    but only one of them needs blue sources. ``generic`` is payable with any
    mana; each entry in ``pips`` is one colored symbol, holding every color
    that satisfies it (more than one only for a true hybrid pip like
    ``U/R``) — see ``_pip_colors`` for what a monocolored-hybrid pip
    (``2/W``) collapses to and why.
    """

    generic: int
    pips: tuple[frozenset[str], ...]


def mana_requirement(mana_cost: str | None) -> ManaRequirement | None:
    """Parse a cost into its generic amount and its colored pips.

    Returns ``None`` for an unparseable or absent cost — never a zero-pip
    requirement, which would claim "castable off any land" for a card whose
    cost was simply not read. Uses the same pip tokenizer as ``mana_value()``
    and keeps its invariant: ``generic + len(pips) == mana_value(cost)`` for
    any cost with no ``X`` (X is excluded from both, the same "0 until
    chosen" rule ``mana_value`` already documents).

    Reads a ``//`` cost's front face alone, the same as ``mana_value()`` —
    see ``_front_face``.
    """
    if not mana_cost:
        return None
    mana_cost = _front_face(mana_cost)
    pips = _PIP_RE.findall(mana_cost)
    if not pips and mana_cost.strip():
        return None
    generic = 0
    colored: list[frozenset[str]] = []
    for pip in pips:
        if pip.upper() == "X":
            continue
        if _HYBRID_GENERIC_RE.match(pip):
            generic += int(pip)
            continue
        colors = _pip_colors(pip)
        if colors:
            colored.append(colors)
        else:
            generic += 1
    return ManaRequirement(generic=generic, pips=tuple(colored))


def classify(
    oracle_text: str | None, type_line: str | None, mana_cost: str | None = None
) -> EffectTags | str:
    """Every matching effect tag for one card, or ``"unknown"`` when
    ``oracle_text`` was never populated for it."""
    if oracle_text is None:
        return UNKNOWN
    matched = {tag for tag, pattern in _PATTERNS.items() if pattern.search(oracle_text)}
    if is_finisher(oracle_text, type_line, mana_cost):
        matched.add("finisher")
    return EffectTags(frozenset(matched))


_EM_DASH = "—"


def is_creature(type_line: str | None) -> bool:
    """No em-dash split needed, unlike ``is_land``: unlike "Land", nothing in
    Magic's own type vocabulary embeds "Creature" as a spurious substring of
    an unrelated type. Lifted out of ``review/analyzers/frame.py`` once
    ``table/keep.py`` needed the same rule, rather than adding a second
    private copy."""
    return type_line is not None and "Creature" in type_line


def is_land(type_line: str | None) -> bool:
    """Same em-dash split every SQL view in this project uses to keep a land
    out of a spell count (``migrations/011_review_views.sql``'s own comment
    explains why the whole line can't be tested: ``"Token Artifact — Lander"``
    would misread). Lifted out of ``table/keep.py`` once another caller (the
    draft assistant's pool read, deleted 2026-10-01) needed the same rule,
    rather than adding a second private copy."""
    if not type_line:
        return False
    head = type_line.split(_EM_DASH, 1)[0]
    return "Land" in head


_CHOOSES_BASIC_LAND_TYPE_RE = re.compile(r"choose a basic land type", re.IGNORECASE)
_IS_THE_CHOSEN_TYPE_RE = re.compile(r"is the chosen type", re.IGNORECASE)
_ALL_FIVE_COLORS: tuple[str, ...] = ("W", "U", "B", "R", "G")


def chosen_basic_type_colors(oracle_text: str | None) -> tuple[str, ...] | None:
    """All five colors, for a land whose text both chooses a basic land type
    as it enters and then declares itself that type — Multiversal Passage
    and Thran Portal (A-Thran Portal too) in today's card database.
    ``produced_mana`` is blank for a land like this (no fixed mana ability
    to export), so this is still a known color set, not a guess (rule 4);
    used by ``table/opening_hand.py``'s ``_land_colors`` only as that
    fallback. A weaker "choose a color" clause that never calls the land
    itself that type (a Thriving land's) is a different shape and returns
    ``None``, like any other non-matching or missing text.
    """
    if oracle_text is None:
        return None
    if _CHOOSES_BASIC_LAND_TYPE_RE.search(oracle_text) and _IS_THE_CHOSEN_TYPE_RE.search(
        oracle_text
    ):
        return _ALL_FIVE_COLORS
    return None


UNPARSED_REDUCTION = "unparsed_reduction"

# Both graveyard clauses discount at the same rate (1 per qualifying card);
# only what counts as "qualifying" differs, and that difference does not
# change anything a caller currently does with `per`, so one fuel label
# covers both. Matched against the real oracle text on file for each card —
# see tests/test_effects.py.
_GRAVEYARD_INSTANT_SORCERY_RE = re.compile(
    r"less to cast for each instant and sorcery card in your graveyard"  # Eddymurk Crab
    r"|less to cast, where x is the number of cards in your graveyard "
    r"that are instant cards, sorcery cards, and/or have an adventure",  # Hearth Elemental
    re.IGNORECASE,
)
_BOARD_ELEMENTAL_MV_RE = re.compile(
    # Sunderflock: the discount is a single lookup (the board's biggest
    # Elemental), not a per-card count, so it gets its own fuel kind rather
    # than a `per` value — see CostReduction's docstring.
    r"less to cast, where x is the greatest mana value among elementals you control",
    re.IGNORECASE,
)
_ANY_REDUCTION_RE = re.compile(r"costs? \{[^}]+\} less to cast", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CostReduction:
    """One card's own cost-reduction clause, kept as a labelled fact rather
    than folded into an "effective mana value" — a number nobody printed,
    which AGENTS.md rule 4 forbids synthesizing. ``per`` is the amount
    knocked off for each unit of ``fuel``; ``None`` when the reduction is not
    a per-unit count at all (``fuel="board_elemental_mv"``: the discount is
    the greatest mana value among Elementals you control, a single lookup,
    not one per something). A caller that needs a turn number off this
    supplies its own fuel count — see ``table/opening_hand.py``'s
    ``reduced_castable_turn``.
    """

    per: int | None
    fuel: str


def cost_reduction(oracle_text: str | None) -> CostReduction | str | None:
    """This card's own "costs ... less to cast" clause, structurally parsed.

    Returns ``None`` when there is no such clause (or no oracle text to read
    at all — the same "unknown, not absent" gap ``classify()`` documents,
    except a caller here already has ``oracle_text is None`` in hand and can
    tell the two apart itself). Returns a ``CostReduction`` for one of the
    two recognized clause shapes in this codebase's fixtures. Returns
    ``UNPARSED_REDUCTION`` — a plain sentinel, mirroring ``classify()``'s
    ``UNKNOWN`` — when a "less to cast" clause exists but matches neither
    pattern: the card renders at printed cost with that flag, which
    suppresses a deck-level curve/band claim rather than silently
    understating it. Same discipline as ``keep.py``'s ``unnamed_count``.
    """
    if oracle_text is None:
        return None
    if _BOARD_ELEMENTAL_MV_RE.search(oracle_text):
        return CostReduction(per=None, fuel="board_elemental_mv")
    if _GRAVEYARD_INSTANT_SORCERY_RE.search(oracle_text):
        return CostReduction(per=1, fuel="graveyard_instant_sorcery")
    if _ANY_REDUCTION_RE.search(oracle_text):
        return UNPARSED_REDUCTION
    return None


def is_finisher(
    oracle_text: str | None, type_line: str | None, mana_cost: str | None
) -> bool:
    """Approximate "this is a game-ending threat", not a rules concept.

    A creature or planeswalker at mana value 5+ — deliberately coarse (many
    5-drops are not finishers, and a real finisher can cost less with an
    alternative cost this cannot see), used only where the caller already
    says "approximately" or "likely" rather than stating it as fact.
    """
    if oracle_text is None or type_line is None:
        return False
    if not any(t in type_line for t in _FINISHER_TYPES):
        return False
    value = mana_value(mana_cost)
    return value is not None and value >= _FINISHER_MANA_VALUE
