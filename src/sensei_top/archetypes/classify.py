"""Naming the opponent's deck from the handful of cards they showed.

The definitions in ``source.py`` were written to classify a *complete* 60-card
decklist. We never have one: Arena hides the opponent's hand and library, and a
match reveals perhaps eight to fifteen of their cards. Every rule here follows
from that one difference.

The governing asymmetry is that **absence proves nothing**. Not having seen a
card an archetype requires means we have not seen it yet, not that the deck
lacks it — so an unmet requirement is *unknown*, never a failure. The single
exception runs the other way: a ``DoesNotContain`` naming a card we *did* see
is real evidence, and it eliminates the archetype outright.

That asymmetry is also the safety margin. A definition that stops matching —
after a rename, a rotation, a card we never happened to see — degrades to
*unclassified*, which the dashboard shows as colours and a signature card and
offers to let the user correct. It does not degrade to a confident wrong
answer.

Two more things follow from that same gap, both found from a real match
rather than reasoned out in the abstract. First, *how much* of a definition is
proved matters as much as whether anything is: a one-condition definition
proved outright and a ten-condition one nine-tenths proved both look like "one
requirement short of certain" if you only count met conditions — and a real
opponent was named by a single seen card (Stock Up, one of two the Harmonizer
definition needs) for twenty-odd turns before their actual signature card
(Doomsday Excruciator, the whole of a one-condition definition) ever showed
up. Second, an archetype's own colours are free evidence nothing here used to
check: that wrong guess was green, and the opponent had shown ten cards of
straight Dimir, none of them green. ``_fit_score`` and ``colour_factor`` below
fold both signals into a single number instead of a raw condition count.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sensei_top.formats import FORMATS, arena_format, is_within
from sensei_top.i18n import _, decimal, ngettext

if TYPE_CHECKING:
    # Type-checking only: archetypes.corpus imports classify.normalize at
    # module scope, so importing this back at runtime would cycle. PEP 563
    # (see the `from __future__ import annotations` above) means annotations
    # are never evaluated at def time, so this guard is enough.
    from sensei_top.archetypes.corpus import CorpusPrior

log = logging.getLogger(__name__)

# Old databases still hold Unity markup in card names, from before the importer
# learned to prefer the plain localization. Stripping it here costs nothing and
# means a stale `cards` table degrades matching rather than breaking it.
_MARKUP = re.compile(r"<[^>]*>")
_SPLIT_FORMS = (" // ", " && ")

_COLOR_NAMES = {
    "": "Colorless",
    "W": "Mono-White", "U": "Mono-Blue", "B": "Mono-Black",
    "R": "Mono-Red", "G": "Mono-Green",
    "WU": "Azorius", "WB": "Orzhov", "WR": "Boros", "WG": "Selesnya",
    "UB": "Dimir", "UR": "Izzet", "UG": "Simic",
    "BR": "Rakdos", "BG": "Golgari", "RG": "Gruul",
    "WUB": "Esper", "WUR": "Jeskai", "WUG": "Bant", "WBR": "Mardu", "WBG": "Abzan",
    "WRG": "Naya", "UBR": "Grixis", "UBG": "Sultai", "URG": "Temur", "BRG": "Jund",
}

# Upstream's threshold is 10% of a fallback's CommonCards, which assumes a full
# decklist. Against a dozen revealed cards, 10% of a six-card list is a single
# hit — noise. The absolute floor is what makes the ratio meaningful. This is
# a pre-filter on which fallbacks are even considered; fit (below) ranks and
# gates what survives it.
FALLBACK_MIN_CARDS = 2
FALLBACK_MIN_RATIO = 0.10


@dataclass(frozen=True, slots=True)
class Verdict:
    key: str
    name: str
    method: str            # 'archetype' | 'fallback'
    met: int
    unknown: int
    evidence: tuple[str, ...]
    fit: float
    margin: float           # fit / the best differently-labelled rival's fit; inf if none


@dataclass(slots=True)
class Definition:
    key: str               # the file stem: upstream names are not unique
    name: str
    kind: str
    include_color: bool
    conditions: list[dict[str, Any]] = field(default_factory=list)
    common_cards: list[str] = field(default_factory=list)
    variants: list[dict[str, Any]] = field(default_factory=list)




def normalize(name: str) -> frozenset[str]:
    """Every form a card name may legitimately be written as.

    Sets are compared to sets, so a definition naming a double-faced card by
    either face, by its joined name, or by upstream's ``&&`` spelling all meet
    the same card as Arena reported it.
    """
    plain = " ".join(_MARKUP.sub("", name).split()).casefold()
    forms = {plain}
    for separator in _SPLIT_FORMS:
        if separator in plain:
            forms.update(part.strip() for part in plain.split(separator) if part.strip())
    # Upstream and Arena disagree about the separator, so normalise both to one.
    forms.add(plain.replace(" && ", " // "))
    return frozenset(forms)


def _seen_forms(names: Iterable[str]) -> frozenset[str]:
    seen: set[str] = set()
    for name in names:
        seen |= normalize(name)
    return frozenset(seen)




# Scope names, not booleans: a complete decklist can check the sideboard for
# real (below), which a single 'sideboard_only' flag could not express once a
# third state ('either') needed telling apart from 'main' too.
_POSITIVE_SCOPES = {"inmainboard": "main", "insideboard": "side", "inmainorsideboard": "either"}
_NEGATIVE_SCOPES = {
    "": "main", "mainboard": "main", "sideboard": "side", "mainorsideboard": "either",
}


def _parse_type(raw: str) -> tuple[str, str]:
    """Return ``(quantifier, scope)`` for a condition type, ``scope`` one of
    ``'main'``, ``'side'``, ``'either'``.

    Matched case-insensitively and whitespace-insensitively on purpose:
    upstream ships ``OneorMoreInMainboard`` with a lowercase 'o' alongside the
    correctly spelled one, and a typo in someone else's data file should not
    silently drop a condition.

    Anything not recognised yields ``'unknown'``. Upstream adds condition types
    without notice, and a rule we cannot read must never be counted as *met* —
    that would let an unimplemented rule confirm an archetype on no evidence.
    """
    text = "".join(str(raw).lower().split())
    if text.startswith("doesnotcontain"):
        rest, quantifier = text.removeprefix("doesnotcontain"), "negative"
        scopes = _NEGATIVE_SCOPES
    elif text.startswith("oneormore"):
        rest, quantifier = text.removeprefix("oneormore"), "one"
        scopes = _POSITIVE_SCOPES
    elif text.startswith("twoormore"):
        rest, quantifier = text.removeprefix("twoormore"), "two"
        scopes = _POSITIVE_SCOPES
    else:
        rest, quantifier = text, "all"
        scopes = _POSITIVE_SCOPES

    if rest not in scopes:
        log.warning("unrecognised archetype condition type %r", raw)
        return "unknown", "main"
    return quantifier, scopes[rest]


def _pool(
    scope: str, seen: frozenset[str], sideboard_seen: frozenset[str], complete: bool
) -> frozenset[str]:
    """Which cards a condition's scope can draw evidence from.

    Reached with ``scope == 'side'`` only when ``complete`` is true — the
    partial-match callers below special-case a sideboard scope before ever
    calling this, because we never observe a sideboard mid-match.
    """
    if scope == "side":
        return sideboard_seen
    if scope == "either" and complete:
        return seen | sideboard_seen
    return seen


def evaluate(
    conditions: Iterable[dict[str, Any]],
    seen: frozenset[str],
    *,
    complete: bool = False,
    sideboard_seen: frozenset[str] = frozenset(),
) -> tuple[int, int, list[str]] | None:
    """Score one definition against what we saw. ``None`` means eliminated.

    ``complete`` switches the governing asymmetry described in this module's
    docstring: against a handful of revealed cards, absence proves nothing, so
    an unmet requirement is ``unknown``. Against a *complete* decklist —
    ``sideboard_seen`` is the real sideboard, not "unseen" — absence is real
    evidence, so an unmet positive requirement eliminates the definition just
    as a violated ``DoesNotContain`` always has.
    """
    met = unknown = 0
    evidence: list[str] = []

    for condition in conditions:
        quantifier, scope = _parse_type(condition.get("Type", ""))
        if quantifier == "unknown":
            unknown += 1
            continue

        cards = [c for c in (condition.get("Cards") or []) if isinstance(c, str)]

        if quantifier == "negative":
            if scope == "side" and not complete:
                # A sideboard exclusion can never be violated by anything we
                # can observe mid-match, so it is vacuously satisfied.
                continue
            pool = _pool(scope, seen, sideboard_seen, complete)
            matched = [card for card in cards if normalize(card) & pool]
            if matched:
                return None
            # Passing only means we did not see the card. Under partial
            # information that proves nothing about the deck, so it earns no
            # credit; under a complete list an absent card is not "passing"
            # evidence either — DoesNotContain is silent on cards it doesn't name.
            continue

        if scope == "side" and not complete:
            # We never see a sideboard mid-match. Counting these as unknown
            # rather than ignoring them is what stops a sideboard-gated
            # archetype from outranking one actually proved from the battlefield.
            unknown += 1
            continue

        if not cards:
            unknown += 1
            continue

        pool = _pool(scope, seen, sideboard_seen, complete)
        matched = [card for card in cards if normalize(card) & pool]
        satisfied = {
            "all": len(matched) == len(cards),
            "one": len(matched) >= 1,
            "two": len(matched) >= 2,
        }[quantifier]
        if satisfied:
            met += 1
            evidence.extend(matched)
        elif complete:
            return None
        else:
            unknown += 1

    return met, unknown, evidence




def color_label(colors: str) -> str:
    """Guild and shard names for the colours we saw, in WUBRG order."""
    ordered = "".join(letter for letter in "WUBRG" if letter in (colors or ""))
    if name := _COLOR_NAMES.get(ordered):
        return name
    return {4: "4c", 5: "5c"}.get(len(ordered), "Colorless")


# Below this many distinct non-token cards revealed, an MTGO match's own
# legality read is still cheaply explained by "we just haven't seen enough
# of the deck yet" — the same reasoning `arena_format`'s Arena branch never
# needs, because Arena hands us the format outright instead of asking us to
# infer it from a card list.
MIN_REVEALED = 5

# match_format_inference.reason's vocabulary (migrations/056_format_fit.sql),
# in the order infer_formats checks them: a match whose cards cannot all be
# read is never judged on the ones that can.
FORMAT_REASONS: tuple[str, ...] = (
    "unresolved_cards", "unknown_legality", "no_fit", "too_few_cards", "fit", "ambiguous",
)

# Names MTGO's transcript brackets like a card that are not a card in anyone's
# deck: game markers a card puts into play. Each one is observed, as an
# unresolved card event name in a real MTGO history (plan 13, S5d), never
# guessed: "The Initiative" (the designation an initiative card gives a
# player) and "Undercity" (the dungeon taking the initiative ventures into).
# Like a token, neither says anything about the match's format.
_MTGO_NON_CARDS = ("The Initiative", "Undercity")


@dataclass(frozen=True, slots=True)
class FormatInference:
    """What an MTGO match's revealed cards say about its format.

    ``fit`` is every format none of the cards is ``not_legal`` in (D3), empty
    when the cards cannot all be read (``unresolved_cards``,
    ``unknown_legality``) or when nothing fits. ``format`` is the single
    narrowest of them (D4), set only when ``reason`` is ``"fit"``.
    """
    fit: frozenset[str]
    format: str | None
    reason: str


def narrowest_format(fit: Iterable[str]) -> str | None:
    """The unique minimal format in ``fit`` under ``formats.BROADER``, or
    None when there are none or more than one (D4).

    Never a tiebreak: Standard and Pauper both minimal is None, not the
    bigger pool, which is why Pauper is only ever confirmed by a pick.
    """
    candidates = set(fit)
    minimal = [f for f in candidates if not any(is_within(g, f) for g in candidates)]
    return minimal[0] if len(minimal) == 1 else None


def infer_formats(conn: sqlite3.Connection) -> dict[str, FormatInference]:
    """The format read of every MTGO match, from both seats' revealed cards.

    Arena matches are not here: Arena's log names the format
    (``matches.format``). Nothing here reads ``mtgo_match_pick``; the pick
    outranks this at read time, in ``v_match_format`` (D6).

    Token rows are skipped before any check: ``cards.py``'s name backfill
    leaves a token's legality missing on purpose (a token shares its name
    with unrelated Scryfall objects), and a token says nothing about the
    deck's format either way. A card whose type merely mentions Token after
    the dash (``Creature — Token Soldier``) is not a token.

    Checked in this order (``FORMAT_REASONS``):
      1. ``unresolved_cards``: a card event whose ``grp_id`` never resolved.
         It could be any card, so the match is not judged on the cards that
         did resolve. Two exceptions, by the transcript name
         ``card_events.mtgo_name`` keeps for an unresolved MTGO event
         (migration 060): a token (MTGO's ``"<Base> Token"`` spelling, the one
         ``projector/mtgo/project.py::_resolve_grp_id`` relies on) or a game
         marker in ``_MTGO_NON_CARDS``. Such an event is left out of the fit,
         like a resolved token. A NULL ``mtgo_name`` (a row projected before
         migration 060) is not known to be either, so it still blocks.
      2. ``unknown_legality``: a resolved non-token card with no ``cards``
         row, or without a ``card_legality`` row for each of the seven
         formats. Unknown is never read as legal (rule 4).
      3. ``no_fit``: every format has a card ``not_legal`` in it. Each
         format is judged on its own rows: a card ``not_legal`` in Standard
         rules out Standard however legal it is elsewhere. ``banned`` and
         ``restricted`` still fit (D3: Scryfall's ban list is today's).
      4. ``too_few_cards``: fewer than ``MIN_REVEALED`` distinct non-token
         names. The fit is kept, since it is exact; only the inference
         waits for more evidence.
      5. ``fit`` with the narrowest format, or ``ambiguous``.
    """
    legality: dict[str, dict[tuple[int, str | None], dict[str, str]]] = {}
    for row in conn.execute(
        """
        SELECT ce.match_id, ce.grp_id, c.name, cl.format, cl.legality
          FROM (SELECT DISTINCT match_id, grp_id FROM card_events
                 WHERE grp_id IS NOT NULL) ce
          JOIN matches m ON m.match_id = ce.match_id
          LEFT JOIN cards c ON c.grp_id = ce.grp_id
          LEFT JOIN card_legality cl ON cl.grp_id = c.grp_id
         WHERE m.source = 'mtgo'
           AND COALESCE(
                   instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))),
                         'Token'),
                   0
               ) = 0
        """
    ):
        by_format = legality.setdefault(row["match_id"], {}).setdefault(
            (row["grp_id"], row["name"]), {}
        )
        if row["format"] is not None:
            by_format[row["format"]] = row["legality"]

    unresolved = {
        row["match_id"]
        for row in conn.execute(
            """
            SELECT DISTINCT ce.match_id, ce.mtgo_name
              FROM card_events ce
              JOIN matches m ON m.match_id = ce.match_id
             WHERE m.source = 'mtgo' AND ce.grp_id IS NULL
            """
        )
        if row["mtgo_name"] is None
        or not (row["mtgo_name"].endswith(" Token") or row["mtgo_name"] in _MTGO_NON_CARDS)
    }

    inferences: dict[str, FormatInference] = {}
    for (match_id,) in conn.execute("SELECT match_id FROM matches WHERE source = 'mtgo'"):
        cards = legality.get(match_id, {})
        if match_id in unresolved:
            inferences[match_id] = FormatInference(frozenset(), None, "unresolved_cards")
            continue
        if any(name is None or len(by_format) < len(FORMATS)
               for (_grp_id, name), by_format in cards.items()):
            inferences[match_id] = FormatInference(frozenset(), None, "unknown_legality")
            continue
        fit = frozenset(
            fmt for fmt in FORMATS
            if not any(by_format[fmt] == "not_legal" for by_format in cards.values())
        )
        if not fit:
            inferences[match_id] = FormatInference(fit, None, "no_fit")
            continue
        if len({name for _grp_id, name in cards}) < MIN_REVEALED:
            inferences[match_id] = FormatInference(fit, None, "too_few_cards")
            continue
        narrowest = narrowest_format(fit)
        inferences[match_id] = FormatInference(
            fit, narrowest, "fit" if narrowest is not None else "ambiguous"
        )
    return inferences


# Below this many nonland cards seen, a missing colour is still cheaply
# explained by bad luck; belief that "we'd have seen it by now" grows with
# more cards but is capped short of certainty, because a screwed colour is
# real even on turn twenty.
_COLOUR_RAMP_CARDS = 12
_COLOUR_BELIEF_CAP = 0.9
# A colour mismatch demotes a guess, it never erases it: a signature card the
# opponent actually played stays real evidence even against a colour gap, so
# the factor can never fall all the way to zero.
_COLOUR_FLOOR = 0.1


def _card_colors_by_name(conn: sqlite3.Connection) -> dict[str, frozenset[str]]:
    """Every locally known card's colour identity, keyed by every form its
    name may appear in — the same normalisation ``normalize()`` gives card
    names, so a definition's or Arena's own spelling always finds it. A card
    absent here (never downloaded, or a name mismatch) is simply missing from
    the map, and every caller below treats an absent colour as unknown, never
    as colourless (rule 4).
    """
    table: dict[str, frozenset[str]] = {}
    for row in conn.execute("SELECT name, colors FROM cards WHERE colors IS NOT NULL"):
        try:
            identity = frozenset(json.loads(row["colors"]) or ())
        except (json.JSONDecodeError, TypeError):
            continue
        for form in normalize(row["name"]):
            table[form] = table.get(form, frozenset()) | identity
    return table


def _card_colors(
    name: str, colors_by_name: Mapping[str, frozenset[str]]
) -> frozenset[str] | None:
    """The first known form's colours, the whole name before either face.

    The order is fixed on purpose: ``normalize()`` returns a set, whose
    iteration order follows the per-process hash seed, and a card's forms
    can disagree — Arena lists an adventure's own half as a card of its own,
    so ``grove's bounty`` carries green while ``elusive otter // grove's
    bounty`` is blue only. Taking whichever form the set yielded first made
    a deck's colours, and so its archetype, change from one run to the next.
    The whole name is always the longest form.
    """
    for form in sorted(normalize(name), key=lambda form: (-len(form), form)):
        if form in colors_by_name:
            return colors_by_name[form]
    return None


def required_colors(
    definition: Definition, colors_by_name: Mapping[str, frozenset[str]]
) -> frozenset[str]:
    """The colours a definition's own positive requirements imply, from cards
    whose colour identity we actually know — never guessed for one we don't
    (rule 4).

    An ``all`` condition needs every listed card, so their colours union. A
    ``one-of``/``two-of`` condition only guarantees whichever colours *every*
    alternative shares, so those intersect instead: Reanimator's "Zombify or
    Bringer of the Last Gift" should never accuse a deck of white just because
    one of its two alternatives happens to be.
    """
    required: set[str] = set()
    for condition in definition.conditions:
        quantifier, scope = _parse_type(condition.get("Type", ""))
        if quantifier in ("negative", "unknown") or scope == "side":
            continue
        cards = [c for c in (condition.get("Cards") or []) if isinstance(c, str)]
        known = [
            colours for name in cards
            if (colours := _card_colors(name, colors_by_name)) is not None
        ]
        if not known:
            continue
        if quantifier == "all":
            required |= known[0].union(*known[1:])
        else:
            required |= known[0].intersection(*known[1:])
    return frozenset(required)


def colour_factor(required: frozenset[str], observed: str, cards_seen: int) -> float:
    """How much a definition's own colours agree with what the opponent has
    actually shown, in ``[_COLOUR_FLOOR, 1.0]``.

    1.0 when the definition names no colours we can check, or every one of
    them has been seen. Otherwise the penalty grows with how many cards we've
    watched go by without it — early in a match a missing colour is still
    cheap luck, by the midgame it is real evidence — but it never drops below
    the floor.
    """
    missing = required - set(observed or "")
    if not missing:
        return 1.0
    belief = min(cards_seen / _COLOUR_RAMP_CARDS, _COLOUR_BELIEF_CAP)
    return max((1 - belief) ** len(missing), _COLOUR_FLOOR)



# Diminishing returns on raw proof count: one met requirement should never
# outrank two independently met ones, but the gap between two and three
# matters far less than the gap between one and two.
_FIT_SUPPORT_BASE = 0.5

# A fallback names a family, not a specific deck ("Control" plays Negate and a
# boardwipe; so does half the format) — so even a great overlap is capped
# below what a single proved archetype condition already reaches on its own.
_FALLBACK_FIT_CAP = 0.5
_FALLBACK_FIT_RAMP = 4  # matched common cards beyond this add nothing more

# A verdict is named only when it clears an absolute floor and beats the best
# *differently labelled* rival by a real margin. Both were fitted against a
# validation pass over real matches (see docs/opponent-deck.md) — tune them if
# real data disagrees, don't treat them as derived.
MIN_ARCHETYPE_FIT = 0.20
MIN_FALLBACK_FIT = 0.25
MIN_MARGIN = 1.5

_HIGH_FIT, _HIGH_MARGIN, _HIGH_CARDS_SEEN = 0.45, 2.5, 6
_MEDIUM_FIT, _MEDIUM_MARGIN = 0.30, 2.0

# The corpus evidence source's own gates (archetypes/corpus.py's naive-Bayes
# log-odds score), mirroring the shape of the rule engine's own floors above
# rather than reusing their numbers — the two scores live on entirely
# different scales (a bounded [0, 1] fit versus an unbounded log-odds ratio),
# so nothing here is comparable to MIN_ARCHETYPE_FIT or MIN_MARGIN. Tunable,
# not derived, like every other floor in this module.
#
# CORPUS_MIN_CARDS guards against a single rare, high-signal card producing
# overwhelming odds on almost no evidence — the corpus equivalent of
# FALLBACK_MIN_CARDS above. CORPUS_MIN_ODDS is the floor to name anything at
# all: how many times more likely the leading archetype's corpus decks are to
# explain the cards seen than the runner-up's.
CORPUS_MIN_CARDS = 3
CORPUS_MIN_ODDS = 25.0
_CORPUS_MEDIUM_ODDS, _CORPUS_MEDIUM_CARDS = 60.0, 4
_CORPUS_HIGH_ODDS, _CORPUS_HIGH_CARDS = 200.0, 8


def _fit_score(met: int, unknown: int, colour: float) -> float:
    """How well a definition fits what we've seen, in ``[0, 1]``.

    ``proof`` is the fraction of the definition's *observable* requirements
    (met + unknown; sideboard-only ones enter neither count) that came back
    met — a one-condition definition proved outright scores the same proof as
    a ten-condition one nine-tenths proved, which is the point: a raw count of
    met conditions can't tell 1-of-1 from 1-of-2 apart (see the module
    docstring). ``support`` keeps one lone hit from ever outweighing two
    independent ones. ``colour`` folds in whether the definition's own
    colours agree with what has been shown.
    """
    if met + unknown == 0:
        return 0.0
    proof = met / (met + unknown)
    support = 1 - _FIT_SUPPORT_BASE**met
    return proof * support * colour


def _rank_archetypes(
    definitions: Iterable[Definition],
    seen: frozenset[str],
    colors_by_name: Mapping[str, frozenset[str]],
    observed_colors: str,
    cards_seen: int,
    *,
    complete: bool = False,
    sideboard_seen: frozenset[str] = frozenset(),
) -> list[tuple[Definition, int, int, list[str], float]]:
    scored = []
    for definition in definitions:
        result = evaluate(
            definition.conditions, seen, complete=complete, sideboard_seen=sideboard_seen
        )
        if result is None:
            continue
        met, unknown, evidence = result
        if not met:
            continue
        # A complete decklist's own colours are simply read off it elsewhere;
        # colour_factor exists to manage uncertainty that a full list no
        # longer has, so it is skipped rather than fed a belief ramp over
        # cards that were never partially observed to begin with.
        colour = (
            1.0 if complete
            else colour_factor(
                required_colors(definition, colors_by_name), observed_colors, cards_seen
            )
        )
        scored.append((definition, met, unknown, evidence, _fit_score(met, unknown, colour)))
    # Highest fit first, then the file stem so a genuine tie still orders
    # reproducibly. choose() itself refuses to *name* a tie (see MIN_MARGIN);
    # the shortlist behind it still needs a stable order regardless.
    scored.sort(key=lambda row: (-row[4], row[0].key))
    return scored


def _rank_fallbacks(
    definitions: Iterable[Definition],
    seen: frozenset[str],
    colors_by_name: Mapping[str, frozenset[str]],
    observed_colors: str,
    cards_seen: int,
    *,
    complete: bool = False,
    sideboard_seen: frozenset[str] = frozenset(),
) -> list[tuple[Definition, int, list[str], float]]:
    scored = []
    pool = seen | sideboard_seen if complete else seen
    for definition in definitions:
        matched = [card for card in definition.common_cards if normalize(card) & pool]
        if len(matched) < FALLBACK_MIN_CARDS:
            continue
        if len(matched) < FALLBACK_MIN_RATIO * max(len(definition.common_cards), 1):
            continue
        colour = (
            1.0 if complete
            else colour_factor(
                required_colors(definition, colors_by_name), observed_colors, cards_seen
            )
        )
        fit = _FALLBACK_FIT_CAP * min(len(matched) / _FALLBACK_FIT_RAMP, 1.0) * colour
        scored.append((definition, len(matched), matched, fit))
    scored.sort(key=lambda row: (-row[3], row[0].key))
    return scored


def _margins(
    ranked: Sequence[tuple], label_for: Callable[[Definition], str]
) -> list[float]:
    """Each candidate's fit divided by the fit of the next one below it with
    a *different* label — infinity when nothing distinct remains below it.

    The same question ``choose()`` asks of its leader ("how decisively did
    this beat a real alternative"), generalised down the whole ranked list so
    every candidate's confidence means the same thing, not only the winner's.
    A rival with the same label — two definitions for the same archetype
    under different colours, or a fully-proved variant of the same deck — is
    not a disagreement and is skipped when looking for one.
    """
    margins = []
    for i, row in enumerate(ranked):
        label = label_for(row[0])
        rival_fit = next((r[-1] for r in ranked[i + 1 :] if label_for(r[0]) != label), 0.0)
        margins.append(row[-1] / rival_fit if rival_fit > 0 else float("inf"))
    return margins


def _base_label(definition: Definition, colors: str) -> str:
    if not definition.include_color:
        return definition.name
    return f"{color_label(colors)} {definition.name}"


def _variant_name(
    definition: Definition,
    seen: frozenset[str],
    *,
    complete: bool = False,
    sideboard_seen: frozenset[str] = frozenset(),
) -> str | None:
    """A variant refines the name only when it is fully proved.

    Half-matching a variant under partial information is a guess on top of a
    guess, and a wrong specific name is worse than a right general one.
    """
    for variant in definition.variants:
        result = evaluate(
            variant.get("Conditions") or [], seen, complete=complete, sideboard_seen=sideboard_seen
        )
        if result is None:
            continue
        met, unknown, _ = result
        if met and not unknown and variant.get("Name"):
            return str(variant["Name"])
    return None


def _archetype_label(
    definition: Definition,
    seen: frozenset[str],
    colors: str,
    *,
    complete: bool = False,
    sideboard_seen: frozenset[str] = frozenset(),
) -> str:
    """The display name for an archetype we have real evidence for: the
    colour prefix (if the definition wants one) plus a fully-proved variant
    refinement, if one applies."""
    name = definition.name
    if variant := _variant_name(definition, seen, complete=complete, sideboard_seen=sideboard_seen):
        name = f"{name} {variant}"
    return f"{color_label(colors)} {name}" if definition.include_color else name


def choose(
    archetypes: Iterable[Definition],
    fallbacks: Iterable[Definition],
    seen: frozenset[str],
    colors: str,
    colors_by_name: Mapping[str, frozenset[str]],
    cards_seen: int,
    *,
    complete: bool = False,
    sideboard_seen: frozenset[str] = frozenset(),
) -> Verdict | None:
    """Pick the best-evidenced name for a deck, or ``None`` when nothing leads
    clearly enough to state as an answer.

    Two gates, not one: the leader's fit must clear an absolute floor (weak
    evidence stays unnamed even with no rival at all), and it must beat the
    best *differently labelled* rival by a real margin — two definitions that
    happen to print the same name, or a genuine tie, are not a settled answer
    and are left for the candidate shortlist instead of an arbitrary pick.

    ``complete=True`` is for a real, full decklist (the metagame corpus, never
    a live Arena match): ``evaluate`` already eliminates a definition outright
    on an unmet requirement rather than merely discounting it, so anything
    that survives to be ranked is a decklist that actually satisfies every
    condition it was scored on. The two gates below exist to suppress a guess
    made from a dozen revealed cards; there is no such guess to suppress here,
    so they are skipped and the top-ranked survivor is the answer.
    """
    ranked = _rank_archetypes(
        archetypes, seen, colors_by_name, colors, cards_seen,
        complete=complete, sideboard_seen=sideboard_seen,
    )
    def _label(d: Definition) -> str:
        return _archetype_label(d, seen, colors, complete=complete, sideboard_seen=sideboard_seen)

    if ranked:
        margin = _margins(ranked, _label)[0]
        definition, met, unknown, evidence, fit = ranked[0]
        if complete or (fit >= MIN_ARCHETYPE_FIT and margin >= MIN_MARGIN):
            label = _label(definition)
            return Verdict(
                definition.key, label, "archetype", met, unknown, tuple(evidence), fit, margin
            )

    ranked_fallbacks = _rank_fallbacks(
        fallbacks, seen, colors_by_name, colors, cards_seen,
        complete=complete, sideboard_seen=sideboard_seen,
    )
    if ranked_fallbacks:
        margin = _margins(ranked_fallbacks, lambda d: _base_label(d, colors))[0]
        definition, overlap, matched, fit = ranked_fallbacks[0]
        if complete or (fit >= MIN_FALLBACK_FIT and margin >= MIN_MARGIN):
            label = _base_label(definition, colors)
            return Verdict(
                definition.key, label, "fallback", overlap, 0, tuple(matched), fit, margin
            )

    return None


def confidence_of(verdict: Verdict, cards_seen: int) -> str:
    """How much to trust a named verdict, in terms the dashboard can act on.

    Gated on fit and margin, not raw condition counts: ``_fit_score`` already
    saturates fast on proof count (see its docstring), so what actually
    distinguishes a decisive read from a lucky one is how far ahead it is of
    the next real alternative. A fallback never reads 'high' even though
    ``_FALLBACK_FIT_CAP`` (0.5) can exceed ``_HIGH_FIT`` (0.45) on its own —
    the explicit method check here is what holds that line, because "well
    matched to a broad family" should never read as confidently as "proved a
    specific deck".
    """
    if (
        verdict.method == "archetype"
        and verdict.fit >= _HIGH_FIT
        and verdict.margin >= _HIGH_MARGIN
        and cards_seen >= _HIGH_CARDS_SEEN
    ):
        return "high"
    if verdict.fit >= _MEDIUM_FIT and verdict.margin >= _MEDIUM_MARGIN:
        return "medium"
    return "low"


def _corpus_confidence(odds: float, cards_matched: int) -> str | None:
    """How much to trust a corpus-sourced verdict — the same ladder shape as
    ``confidence_of``, but gated on the corpus score's own two numbers:
    ``odds`` (how many times more likely the leader is than the runner-up)
    and how many of the archetype's own corpus cards this match actually
    showed. ``None`` below the naming floor, exactly like ``choose()``
    returning ``None``: not every match has enough corpus evidence to say
    anything, and silence is the correct answer then.
    """
    if cards_matched < CORPUS_MIN_CARDS or odds < CORPUS_MIN_ODDS:
        return None
    if odds >= _CORPUS_HIGH_ODDS and cards_matched >= _CORPUS_HIGH_CARDS:
        return "high"
    if odds >= _CORPUS_MEDIUM_ODDS and cards_matched >= _CORPUS_MEDIUM_CARDS:
        return "medium"
    return "low"


def _corpus_label(
    key: str,
    archetype_name: str,
    kind: str,
    colors: str,
    seen: frozenset[str],
    definitions_for_format: Mapping[str, list[Definition]],
) -> str:
    """The display name for a corpus-won verdict.

    When a rule ``Definition`` happens to exist for this same
    ``archetype_key`` — the ordinary case, since most corpus archetypes are
    the very definitions ``choose()`` also uses — reuse ``_archetype_label``/
    ``_base_label`` so a corpus-named deck reads exactly like a rule-named
    one, variant refinement included. This is the gap-filling case the
    corpus source exists for: a brand-new set's archetypes have real corpus
    decks before anyone has written a rule definition for them at all, so
    there is nothing to look up and the corpus's own stored name, with a
    colour prefix, is the whole answer.
    """
    pool = definitions_for_format.get(kind, [])
    for definition in pool:
        if definition.key == key:
            if kind == "archetype":
                return _archetype_label(definition, seen, colors)
            return _base_label(definition, colors)
    return f"{color_label(colors)} {archetype_name}"


_CORPUS_BONUS = {"high": 0.30, "medium": 0.15, "low": 0.05}
# The largest odds a candidate's corpus reason prints as a figure: five times
# the top tier (_CORPUS_HIGH_ODDS), above which it reads "over 1,000x".
_ODDS_TEXT_CAP = 1000.0


def _odds_text(odds: float) -> str:
    """How a candidate's corpus reason states its odds against the next best
    archetype. The odds are ``exp()`` of a log-odds gap, which runs to
    sixteen digits and more on a well-evidenced read; past the top confidence
    tier the exact figure says nothing, so it is stated as a floor."""
    if math.isinf(odds):
        return _("no rival")
    if odds >= _ODDS_TEXT_CAP:
        return _("over {cap}x the next best").format(
            cap=decimal(_ODDS_TEXT_CAP, 0, grouped=True)
        )
    return _("{odds}x the next best").format(odds=decimal(odds, 0))


def _corpus_bonus(odds: float, cards_matched: int) -> float:
    """How much of a fit boost a ``rank_candidates`` candidate earns from the
    corpus evidence source, reusing ``_corpus_confidence``'s own tiers rather
    than inventing a second threshold ladder: nothing below the naming floor,
    rising with the same odds/cards gates that would let the corpus source
    name a match outright on its own. Capped well under 1.0 — corpus evidence
    nudges a rule candidate's ranking, it never manufactures fit the rule
    engine itself found no support for.
    """
    confidence = _corpus_confidence(odds, cards_matched)
    return _CORPUS_BONUS.get(confidence, 0.0)




@dataclass(frozen=True, slots=True)
class SignatureCard:
    name: str
    seen: bool


@dataclass(frozen=True, slots=True)
class Candidate:
    key: str
    label: str
    kind: str               # 'archetype' | 'fallback'
    confidence: str         # 'high' | 'medium' | 'low' | 'none'
    evidence: tuple[str, ...]
    signature_cards: tuple[SignatureCard, ...] = ()
    fit: float = 0.0
    reasons: tuple[str, ...] = ()
    picked: bool = False    # this match's current opponent_deck_override, if any


def _signature_card_names(definition: Definition) -> list[str]:
    """Cards worth showing as "this archetype's signature cards" — every
    positive, observable requirement, plus the fallback's common cards.

    Sideboard-only requirements are excluded: we never see a sideboard (see
    ``evaluate``), so a seen flag for one would always read False and mislead
    a "play around" hint rather than inform it. Order is preserved and
    deduplicated, conditions before common cards, so the most defining cards
    lead the list.
    """
    names: list[str] = []
    already: set[str] = set()
    for condition in definition.conditions:
        quantifier, scope = _parse_type(condition.get("Type", ""))
        if quantifier in ("negative", "unknown") or scope == "side":
            continue
        for card in condition.get("Cards") or []:
            if isinstance(card, str) and card not in already:
                already.add(card)
                names.append(card)
    for card in definition.common_cards:
        if card not in already:
            already.add(card)
            names.append(card)
    return names


def _signature_cards(definition: Definition, seen: frozenset[str]) -> tuple[SignatureCard, ...]:
    return tuple(
        SignatureCard(name, bool(normalize(name) & seen))
        for name in _signature_card_names(definition)
    )


def _reasons(
    definition: Definition,
    evidence: Sequence[str],
    colors_by_name: Mapping[str, frozenset[str]],
    observed_colors: str,
    cards_seen: int,
) -> list[str]:
    """Why a genuinely evidenced candidate sits where it does: what it
    matched, and, when relevant, what still argues against it. An unmet card
    requirement earns no line here — it is simply unseen, not a reason (see
    the module docstring) — only a colour gap, which is real evidence."""
    reasons = [_("matched {card}").format(card=card) for card in dict.fromkeys(evidence)]
    missing = required_colors(definition, colors_by_name) - set(observed_colors or "")
    if missing:
        message = ngettext(
            "needs {colors} — none shown in {n} cards",
            "needs {colors} — none shown in {n} cards",
            cards_seen,
        )
        reasons.append(message.format(colors="/".join(sorted(missing)), n=cards_seen))
    return reasons


def _elimination_reason(definition: Definition, seen: frozenset[str]) -> str | None:
    """The seen card that ruled a definition out, for a 'none'-confidence
    candidate the picker still offers. The player watched the match and may
    know better than the heuristic, but "ruled out by X" is worth showing
    even for a pick the classifier itself would never make on its own."""
    for condition in definition.conditions:
        quantifier, scope = _parse_type(condition.get("Type", ""))
        if quantifier != "negative" or scope == "side":
            continue
        for card in condition.get("Cards") or []:
            if isinstance(card, str) and normalize(card) & seen:
                return card
    return None


def _match_seen_forms(conn: sqlite3.Connection, match_id: str) -> frozenset[str]:
    rows = conn.execute(
        """
        SELECT c.name
          FROM card_events ce
          JOIN matches m ON m.match_id = ce.match_id
          JOIN cards   c ON c.grp_id   = ce.grp_id
         WHERE ce.match_id = ?
           AND ce.seat = m.opponent_seat
           AND ce.grp_id IS NOT NULL
           AND instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))),
                     'Token') = 0
        """,
        (match_id,),
    )
    return _seen_forms(row["name"] for row in rows)


def rank_candidates(
    conn: sqlite3.Connection,
    match_id: str,
    *,
    colors_by_name: Mapping[str, frozenset[str]] | None = None,
    prior: CorpusPrior | None = None,
    opponent_cards: Mapping[str, tuple[str, int]] | None = None,
    seen_names: Iterable[str] | None = None,
) -> list[Candidate]:
    """Every named deck for this match's format, best-fit first, for the user
    to pick from when the classifier's own automatic guess is not good enough
    — or simply wrong.

    Unlike ``choose()``, which commits to one verdict (or none), this returns
    everything — including an archetype the cards actively contradict, or one
    we simply have not seen supporting evidence for. The player watched the
    match and may know better than a heuristic reasoning over a dozen revealed
    cards, so a definition earning no evidence is still worth offering; it is
    just ranked last, at confidence ``'none'``, with a reason when there is
    one (a card seen that the definition explicitly excludes).

    A candidate matching this match's ``opponent_deck_override`` — if any —
    is flagged ``picked``, so the dashboard and the advisor's hint context can
    both follow the same identification the player already made.

    ``colors_by_name`` lets a caller rebuilding this for many matches in one
    request (``review/leaks.py``'s ``find_leaks``) pass an already-computed
    table rather than pay ``_card_colors_by_name``'s full-table scan again —
    it depends only on ``cards``, not on the match, so it is safe to reuse
    for the lifetime of one request. Omitted, this computes its own, exactly
    as before.

    ``prior`` — an ``archetypes.corpus.CorpusPrior``, when the caller has one
    cached — folds the corpus evidence source into the *existing* rule-engine
    candidates' ``fit`` (never invents a candidate for a corpus archetype
    lacking any rule ``Definition``: this is a picker over defined decks, and
    the corpus source's own job is done in ``classify_matches`` instead).
    Omitted, behaviour is unchanged from before this source existed.

    ``opponent_cards`` is the same idea as ``colors_by_name`` but for
    ``v_opponent_cards`` — a caller rebuilding this for many matches
    (``review/snapshot.py``'s ``view_cache``) can pass an already-fetched
    ``match_id -> (colors, cards_seen)`` mapping rather than pay this
    expensive view's per-match_id query again. A match present in the
    mapping uses its values exactly as given (including a NULL or ``''``
    ``colors``); a match absent from it reads ``("", 0)``, exactly as a
    missing row does today. Omitted, this queries the view itself, exactly
    as before.

    ``seen_names`` replaces the ``card_events`` lookup (``_match_seen_forms``)
    with an already-gathered set of raw card names, the same contract as
    ``opponent_cards`` above — a caller with its own name set in hand (a live
    read, S4's break read, which unions ``card_events`` with the live
    replay's own revealed zones) skips the query entirely rather than
    forcing a name set built at request time back through ``card_events``.
    Omitted, this queries ``card_events`` itself, exactly as before.
    """
    match = conn.execute(
        """
        SELECT m.event_id, d.format AS deck_format,
               (SELECT f.format FROM v_match_format f WHERE f.match_id = m.match_id)
                   AS match_format
          FROM matches m
          LEFT JOIN decks d ON d.deck_id = m.deck_id
         WHERE m.match_id = ?
        """,
        (match_id,),
    ).fetchone()
    if match is None:
        return []

    # The match's read-time format (log, pick, then inference — D6), so an
    # MTGO match, which carries neither an event id nor an Arena deck, still
    # gets its format's definitions. arena_format is the fallback for a
    # database migrated by 055 whose matches.format is still unprojected.
    fmt = match["match_format"] or arena_format(match["deck_format"], match["event_id"])
    definitions = _load_definitions(conn)
    if fmt is None or fmt not in definitions:
        return []

    seen = _seen_forms(seen_names) if seen_names is not None else _match_seen_forms(conn, match_id)
    if not seen:
        return []

    if opponent_cards is not None:
        colors, cards_seen = opponent_cards.get(match_id, ("", 0))
    else:
        summary = conn.execute(
            "SELECT colors, cards_seen FROM v_opponent_cards WHERE match_id = ?", (match_id,)
        ).fetchone()
        colors = summary["colors"] if summary else ""
        cards_seen = summary["cards_seen"] if summary else 0
    if colors_by_name is None:
        colors_by_name = _card_colors_by_name(conn)

    archetypes = definitions[fmt]["archetype"]
    fallbacks = definitions[fmt]["fallback"]

    def archetype_label(definition: Definition) -> str:
        return _archetype_label(definition, seen, colors)

    def fallback_label(definition: Definition) -> str:
        return _base_label(definition, colors)

    candidates: list[Candidate] = []
    ranked_keys: set[str] = set()

    ranked_archetypes = _rank_archetypes(archetypes, seen, colors_by_name, colors, cards_seen)
    for (definition, met, unknown, evidence, fit), margin in zip(
        ranked_archetypes, _margins(ranked_archetypes, archetype_label), strict=True
    ):
        label = archetype_label(definition)
        verdict = Verdict(
            definition.key, label, "archetype", met, unknown, tuple(evidence), fit, margin
        )
        candidates.append(
            Candidate(
                definition.key, label, "archetype", confidence_of(verdict, cards_seen),
                tuple(evidence), _signature_cards(definition, seen), fit,
                tuple(_reasons(definition, evidence, colors_by_name, colors, cards_seen)),
            )
        )
        ranked_keys.add(definition.key)

    ranked_fallbacks = _rank_fallbacks(fallbacks, seen, colors_by_name, colors, cards_seen)
    for (definition, overlap, matched, fit), margin in zip(
        ranked_fallbacks, _margins(ranked_fallbacks, fallback_label), strict=True
    ):
        label = fallback_label(definition)
        verdict = Verdict(
            definition.key, label, "fallback", overlap, 0, tuple(matched), fit, margin
        )
        candidates.append(
            Candidate(
                definition.key, label, "fallback", confidence_of(verdict, cards_seen),
                tuple(matched), _signature_cards(definition, seen), fit,
                tuple(_reasons(definition, matched, colors_by_name, colors, cards_seen)),
            )
        )
        ranked_keys.add(definition.key)

    # The prior is the caller's, built for this match's format: api/sql.py's
    # cached prior (passed in by api/routes/matches.py) and
    # table/intermission.py's both pass v_match_format.format to build_prior.
    # review/snapshot.py passes none.
    if prior is not None and candidates:
        # Function-scoped import: see classify_matches's own docstring for
        # the cycle this avoids (archetypes.corpus imports classify.normalize
        # at module scope).
        from sensei_top.archetypes.corpus import matched_cards, read_corpus

        ranked_corpus = read_corpus(prior, seen)
        corpus_scores = dict(ranked_corpus)
        top_key, top_score = ranked_corpus[0] if ranked_corpus else (None, None)
        second_score = ranked_corpus[1][1] if len(ranked_corpus) > 1 else None

        folded: list[Candidate] = []
        for candidate in candidates:
            if candidate.key not in corpus_scores:
                folded.append(candidate)
                continue
            cards_matched = matched_cards(prior, candidate.key, seen)
            if len(cards_matched) < CORPUS_MIN_CARDS:
                folded.append(candidate)
                continue
            score = corpus_scores[candidate.key]
            rival_score = second_score if candidate.key == top_key else top_score
            odds = math.inf if rival_score is None else math.exp(score - rival_score)
            bonus = _corpus_bonus(odds, len(cards_matched))
            if bonus <= 0:
                folded.append(candidate)
                continue
            reason = ngettext(
                "corpus: {n} of its own cards seen ({odds})",
                "corpus: {n} of its own cards seen ({odds})",
                len(cards_matched),
            ).format(n=len(cards_matched), odds=_odds_text(odds))
            folded.append(
                replace(candidate, fit=min(1.0, candidate.fit + bonus),
                        reasons=(*candidate.reasons, reason))
            )
        # Re-sort: a fold can move a candidate past one that outranked it
        # before, and the shortlist consumer (OpponentRead.tsx) relies on
        # this list already being best-fit first.
        candidates = sorted(folded, key=lambda c: -c.fit)

    remaining = sorted(
        (
            Candidate(
                d.key,
                archetype_label(d) if d.kind == "archetype" else fallback_label(d),
                d.kind, "none", (), (), 0.0,
                tuple(reason for reason in (_elimination_reason(d, seen),) if reason is not None),
            )
            for d in (*archetypes, *fallbacks)
            if d.key not in ranked_keys
        ),
        key=lambda c: c.label,
    )

    picked_row = conn.execute(
        "SELECT archetype_key FROM opponent_deck_override WHERE match_id = ?", (match_id,)
    ).fetchone()
    picked_key = picked_row["archetype_key"] if picked_row else None

    all_candidates = [*candidates, *remaining]
    if picked_key is None:
        return all_candidates
    return [replace(c, picked=True) if c.key == picked_key else c for c in all_candidates]




def _load_definitions(conn: sqlite3.Connection) -> dict[str, dict[str, list[Definition]]]:
    loaded: dict[str, dict[str, list[Definition]]] = {}
    for row in conn.execute(
        "SELECT format, kind, source, name, include_color, definition FROM archetypes"
    ):
        try:
            body = json.loads(row["definition"])
        except json.JSONDecodeError:
            log.warning("unparseable stored definition %s/%s", row["format"], row["source"])
            continue
        loaded.setdefault(row["format"], {"archetype": [], "fallback": []})[row["kind"]].append(
            Definition(
                key=row["source"],
                name=row["name"],
                kind=row["kind"],
                include_color=bool(row["include_color"]),
                conditions=body.get("Conditions") or [],
                common_cards=body.get("CommonCards") or [],
                variants=body.get("Variants") or [],
            )
        )
    return loaded


_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True, slots=True)
class SeenVerdict:
    """The one classifier decision ``classify_matches`` writes per match,
    pulled out of its loop so a *live* read — ``table/intermission.py``'s
    break read (S4), naming an in-progress opponent from a name set built at
    request time — can call the identical rule-engine/corpus/tie-break logic
    without touching ``opponent_archetype`` or waiting for ``project()``.

    ``met``/``unknown`` are the exact ints ``classify_matches`` stores in
    ``opponent_archetype.conditions_met``/``conditions_unknown``: a rule
    verdict's own condition counts, or — a corpus verdict has no conditions —
    the corpus cards matched and zero, mirroring the pre-refactor rows
    exactly. ``evidence`` is already the JSON string the ``evidence_json``
    column stores rather than a raw structure, since the shape differs by
    method (a plain list of matched cards for a rule verdict, a
    ``{matched_cards, odds}`` dict for a corpus one) and there is nothing
    shared worth factoring out of it.
    """
    key: str
    label: str
    name: str
    confidence: str          # 'high' | 'medium' | 'low'
    method: str              # 'archetype' | 'fallback' | 'corpus' (opponent_archetype's CHECK)
    evidence: str            # JSON, ready for evidence_json
    met: int
    unknown: int


def classify_seen(
    names: Iterable[str],
    colors: str,
    cards_seen: int,
    *,
    fmt: str,
    definitions: Mapping[str, dict[str, list[Definition]]],
    colors_by_name: Mapping[str, frozenset[str]],
    prior: CorpusPrior | None,
) -> SeenVerdict | None:
    """The rule engine plus the corpus read, tie-broken exactly as
    ``classify_matches`` does for every match in its own loop — extracted so
    a caller with a name set already in hand (built at request time, not
    from a completed projection) gets the identical decision.

    ``names`` need not be deduplicated or already in every form a card's name
    can take — this normalizes them itself, the same as ``classify_matches``
    does before calling in. Returns ``None`` when there is nothing to
    classify (no names, or ``fmt`` has no definitions loaded) or nothing
    clears the naming floor; ``classify_matches``'s own
    ``counts["unclassified"]`` and this function returning ``None`` are the
    same outcome, it is simply not this function's job to count them.

    ``prior`` must be the corpus prior for ``fmt`` (``None`` when that
    format has none): it is applied as given, so the caller keys it by
    format, as ``classify_matches`` does.
    """
    seen = _seen_forms(names)
    if not seen:
        return None

    pool = definitions.get(fmt, {})
    archetypes = pool.get("archetype", [])
    fallbacks = pool.get("fallback", [])

    verdict = choose(archetypes, fallbacks, seen, colors, colors_by_name, cards_seen)
    rule_confidence = confidence_of(verdict, cards_seen) if verdict is not None else None
    rule_rank = _CONFIDENCE_RANK.get(rule_confidence, 0)

    corpus_pick: tuple[str, str, str, str, list[str], float] | None = None
    corpus_rank = 0
    if prior is not None:
        # Function-scoped import: archetypes.corpus imports classify.normalize
        # at module scope, so importing it back from here at module scope
        # would be a direct cycle within the same package (corpus.py's own
        # docstring).
        from sensei_top.archetypes.corpus import matched_cards, read_corpus

        ranked = read_corpus(prior, seen)
        if ranked:
            top_key, top_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else None
            odds = math.inf if second_score is None else math.exp(top_score - second_score)
            cards_matched = matched_cards(prior, top_key, seen)
            corpus_confidence = _corpus_confidence(odds, len(cards_matched))
            if corpus_confidence is not None:
                corpus_pick = (top_key, corpus_confidence, prior.labels[top_key],
                                prior.kinds[top_key], cards_matched, odds)
                corpus_rank = _CONFIDENCE_RANK[corpus_confidence]

    # Corpus only overrides the rule engine on a strictly higher confidence —
    # an exact tie keeps the rule verdict, the more legible of the two when
    # both agree (classify_matches's own docstring).
    if corpus_pick is not None and corpus_rank > rule_rank:
        key, confidence, archetype_name, kind, cards_matched, odds = corpus_pick
        label = _corpus_label(key, archetype_name, kind, colors, seen, pool)
        evidence = {
            "matched_cards": cards_matched,
            "odds": None if math.isinf(odds) else round(odds, 2),
        }
        return SeenVerdict(
            key, label, archetype_name, confidence, "corpus",
            json.dumps(evidence), len(cards_matched), 0,
        )

    if verdict is None:
        return None

    return SeenVerdict(
        verdict.key, verdict.name, verdict.name, rule_confidence, verdict.method,
        json.dumps(sorted(set(verdict.evidence))), verdict.met, verdict.unknown,
    )


_COLOR_ORDER = "WUBRG"


def live_opponent_colors(conn: sqlite3.Connection, names: Iterable[str]) -> tuple[str, int]:
    """``(colors, cards_seen)`` for a name set gathered at request time, by
    exactly the rule ``v_opponent_cards`` uses: nonland, nontoken cards only
    (checked against the supertype text before a type line's own em dash,
    the same substring test as that view's ``instr(...) = 0`` guards and
    ``_match_seen_forms``'s Token-only one above), deduplicated by name,
    colours unioned across whichever of them are known.

    This re-runs the view's arithmetic in Python instead of querying it,
    because the view keys off ``card_events``/``match_id`` and this name set
    can include cards the projector has not caught up to yet — S4's break
    before game 3 pools games 1 and 2 even when projection has only reached
    game 1, which ``v_opponent_cards`` for this ``match_id`` alone cannot
    reflect. One deliberate difference: the view counts one per
    ``(name, rarity, colors)`` among the printings actually seen, while a
    bare name set has no printing to pick, so this counts distinct names —
    the same number except for a name seen in two printings that differ in
    rarity or colours. A name absent from ``cards`` entirely (never downloaded, or a
    spelling mismatch) is silently excluded from both the count and the
    colours, the same as an absent row in ``_card_colors_by_name`` — rule 4,
    never a guess.
    """
    unique = {name for name in names if name}
    if not unique:
        return "", 0
    placeholders = ",".join("?" for _ in unique)
    rows = conn.execute(
        f"SELECT DISTINCT name, colors, type_line FROM cards WHERE name IN ({placeholders})",
        tuple(unique),
    )
    seen_colors: set[str] = set()
    counted: set[str] = set()
    for row in rows:
        type_line = row["type_line"] or ""
        supertype = type_line.split("—", 1)[0]
        if "Land" in supertype or "Token" in supertype:
            continue
        counted.add(row["name"])
        try:
            identity = json.loads(row["colors"]) or ()
        except (json.JSONDecodeError, TypeError):
            identity = ()
        seen_colors.update(identity)
    colors = "".join(c for c in _COLOR_ORDER if c in seen_colors)
    return colors, len(counted)


def _priors(conn: sqlite3.Connection, formats: Iterable[str]) -> dict[str, CorpusPrior | None]:
    """The corpus prior for each format about to be classified, built once
    per run. Each format's prior learns only from that format's corpus
    labels; one with nothing to say is ``None`` and is named by the rule
    engine alone.
    """
    # Function-scoped import: archetypes.corpus imports classify.normalize at
    # module scope, so importing it back from here at module scope would be
    # a direct cycle within the same package (see corpus.py's own docstring).
    from sensei_top.archetypes.corpus import build_prior

    return {fmt: build_prior(conn, fmt) for fmt in set(formats)}


def classify_matches(conn: sqlite3.Connection) -> dict[str, int]:
    """Name every match's opponent deck, under every format it could be.
    Recomputed in full, like the projector.

    Cheap enough to redo wholesale: the work is proportional to the cards each
    opponent revealed, not to the number of definitions, because an archetype
    that shares no card with what we saw can never be selected.

    An Arena match is named under ``matches.format``, which its log gave. An
    MTGO match is named under every format in its fit (``infer_formats``)
    that has definitions, so a Modern-shaped match gets Modern, Legacy and
    Vintage rows; ``v_match_opponent`` reads the one ``v_match_format``
    picks. This never reads the pick itself (``mtgo_match_pick``, or
    ``v_match_format``, which folds it in): the pick is the user's, and a
    rebuild must come out the same whatever they have answered. The same
    run rewrites ``match_format_fit`` and ``match_format_inference``.

    Two evidence sources are combined here, never one replacing the other:
    ``choose()``'s rule engine (exact, but silent on an archetype nobody has
    written a definition for yet) and ``archetypes.corpus``'s naive-Bayes
    read over the field's own classified decklists (fuzzier, but able to name
    a deck the rule engine has never heard of, and to keep strengthening past
    where the rule engine's fit already saturated). Whichever reports the
    higher confidence wins; the rule engine wins an exact tie, since it is
    the more legible answer of the two when both agree. The corpus enters
    only for a format with a prior (``_priors``), and only when one could be
    built (``build_prior`` returns ``None`` on a corpus with nothing to say)
    — a machine that has never fetched or classified the corpus behaves
    exactly as before this feature existed.

    The counts are per match, under the format the match reads without a
    pick (Arena's log, MTGO's inference): ``classified``, ``unclassified``
    and ``skipped_format`` (no such format, or no definitions for it) add up
    to the number of matches. ``rows`` is every ``opponent_archetype`` row
    written, other fitting formats included.
    """
    definitions = _load_definitions(conn)
    colors_by_name = _card_colors_by_name(conn)
    inferences = infer_formats(conn)
    counts = {"classified": 0, "high": 0, "medium": 0, "low": 0,
              "unclassified": 0, "skipped_format": 0, "corpus": 0, "rows": 0}

    # Colours and the card count come from the same view the fallback label
    # uses, so the two can never disagree. Aggregation stays in SQL.
    summary = {
        row["match_id"]: row
        for row in conn.execute("SELECT * FROM v_opponent_cards")
    }

    # Lands are included here although they are excluded from the colours:
    # archetypes genuinely name lands, and Arena reports every land as
    # colourless so they would only ever dilute a colour identity.
    names: dict[str, list[str]] = {}
    for row in conn.execute(
        """
        SELECT m.match_id, c.name
          FROM card_events ce
          JOIN matches m ON m.match_id = ce.match_id
          JOIN cards   c ON c.grp_id   = ce.grp_id
         WHERE ce.seat = m.opponent_seat
           AND ce.grp_id IS NOT NULL
           AND instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))),
                     'Token') = 0
         GROUP BY m.match_id, c.name
        """
    ):
        names.setdefault(row["match_id"], []).append(row["name"])

    # (match_id, formats to name it under, the format it reads without a pick)
    plans: list[tuple[str, list[str], str | None]] = []
    for match in conn.execute("SELECT match_id, source, format FROM matches"):
        match_id = match["match_id"]
        if match["source"] == "mtgo":
            inference = inferences.get(match_id)
            candidates = sorted(inference.fit) if inference is not None else []
            primary = inference.format if inference is not None else None
        else:
            candidates = [match["format"]] if match["format"] is not None else []
            primary = match["format"]
        plans.append(
            (match_id, [fmt for fmt in candidates if fmt in definitions], primary)
        )
    priors = _priors(conn, (fmt for _id, formats, _primary in plans for fmt in formats))

    rows = []
    classified_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for match_id, formats, primary in plans:
        if primary is None or primary not in formats:
            counts["skipped_format"] += 1
        row = summary.get(match_id)
        colors = row["colors"] if row else ""
        cards_seen = row["cards_seen"] if row else 0

        for fmt in formats:
            seen_verdict = classify_seen(
                names.get(match_id, []), colors, cards_seen,
                fmt=fmt, definitions=definitions, colors_by_name=colors_by_name,
                prior=priors.get(fmt),
            )
            if fmt == primary:
                if seen_verdict is None:
                    counts["unclassified"] += 1
                else:
                    counts["classified"] += 1
                    counts[seen_verdict.confidence] += 1
                    if seen_verdict.method == "corpus":
                        counts["corpus"] += 1
            if seen_verdict is None:
                continue
            rows.append(
                (match_id, fmt, seen_verdict.key, seen_verdict.name, colors, seen_verdict.label,
                 seen_verdict.method, seen_verdict.confidence, cards_seen, seen_verdict.met,
                 seen_verdict.unknown, seen_verdict.evidence, classified_at)
            )
    counts["rows"] = len(rows)

    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM opponent_archetype")
        conn.executemany(
            """
            INSERT INTO opponent_archetype
                 (match_id, format, archetype_key, archetype_name, colors, label, method,
                  confidence, cards_seen, conditions_met, conditions_unknown,
                  evidence_json, classified_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.execute("DELETE FROM match_format_fit")
        conn.executemany(
            "INSERT INTO match_format_fit (match_id, format) VALUES (?, ?)",
            [(match_id, fmt) for match_id, inference in inferences.items()
             for fmt in sorted(inference.fit)],
        )
        conn.execute("DELETE FROM match_format_inference")
        conn.executemany(
            "INSERT INTO match_format_inference (match_id, format, reason) VALUES (?, ?, ?)",
            [(match_id, inference.format, inference.reason)
             for match_id, inference in inferences.items()],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return counts


def opponent_source_breakdown(conn: sqlite3.Connection, fmt: str) -> dict[str, int]:
    """How the classifier resolves for completed matches of ``fmt`` — the
    number a stale archetype cache would move.

    A match's format is ``v_match_format``'s: Arena's log, else the user's
    MTGO pick, else the inference. A diagnostic, read once by ``report`` and
    the metagame status route, not a metric view.
    """
    counts = {"archetype": 0, "fallback": 0, "corpus": 0, "colors": 0, "unknown": 0,
              "manual": 0, "total": 0}
    rows = conn.execute(
        """
        SELECT COALESCE(vo.opponent_source, 'unknown') AS opponent_source
          FROM matches m
          JOIN v_match_format f       ON f.match_id = m.match_id
          LEFT JOIN v_match_opponent vo ON vo.match_id = m.match_id
         WHERE m.result IN ('win', 'loss', 'draw')
           AND f.format = ?
        """,
        (fmt,),
    ).fetchall()
    for row in rows:
        counts["total"] += 1
        source = row["opponent_source"]
        if source in counts:
            counts[source] += 1
    return counts
