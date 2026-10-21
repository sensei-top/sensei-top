"""The opening-hand read: whether the specific 7 cards just dealt are worth
keeping, read from the log before the decision. The deck-relative half
(land band, ideal-hand shape, the deck's mulligan record) is
``table/keep.py``'s ``build_keep_guide``, never recomputed here. See
docs/current-match.md, "The opening-hand read (`table/opening_hand.py`)".

Traps a reader of this file would hit:

1. The offer comes from a replay of ``raw_events`` (``table/live.py``), not
   from projected tables: the mulligan window is shorter than one full
   rebuild (docs/architecture.md, "Full rebuild, always"). The code that
   knows Arena's message shapes stays in ``projector/live_state.py``; this
   module only turns the offer into a read, and writes nothing.
2. ``is_land`` is Arena's own ``CardType_Land`` from the offer
   (``MulliganCard.card_types``), never the ``cards`` table, so
   ``land_count`` is exact even for a card ``sensei-top cards`` never named.
   Everything else about a card needs the ``cards`` table and degrades to
   ``None`` (a nonland's tags to ``()`` with ``tags_known`` False)
   without it.
3. A land whose colors neither ``produced_mana`` nor
   ``effects.chosen_basic_type_colors`` resolves is read twice, as colorless
   and as every color; the verdict is published only when both agree.
   Per-card ``castable_turn``/``reduced_castable_turn`` always carry the
   colorless reading.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from sensei_top.i18n import N_, _, ngettext
from sensei_top.projector.mulligan import MulliganOffer
from sensei_top.review import effects
from sensei_top.table import live
from sensei_top.table.keep import (
    HandSlot,
    KeepGuide,
    KeyPlay,
    MulliganCost,
    MulliganRecord,
    band_word,
    build_keep_guide,
)

_LAND_TYPE = "CardType_Land"
# "Castable by turn 3" is this verdict's own threshold. keep.py's early-play
# slot ("play(s) at 1-2 mana") counts mana value <= 2 (_CHEAP_MANA_VALUE),
# a different cutoff.
_EARLY_TURN_THRESHOLD = 3
# Sentinel distinguishing "caller didn't pass an offer, replay it yourself"
# from "caller passed offer=None, meaning a live replay already found
# nothing pending" — a plain default of None cannot tell those apart, and
# the two must behave differently: only the first should trigger a replay.
_NOT_GIVEN = object()


@dataclass(frozen=True, slots=True)
class OpeningHandCard:
    """One card in the hand being evaluated."""

    grp_id: int
    name: str | None  # None only when the card table has never named this grp_id
    type_line: str | None
    mana_cost: str | None
    is_land: bool  # from Arena's own CardType_Land — always known, no cards-table dependency
    mana_value: int | None
    tags: tuple[str, ...]
    tags_known: bool
    castable_turn: int | None  # earliest turn this hand's own lands can pay for it;
    # None for a land, an unparseable cost, or one these lands never pay. With
    # colors_known False, the colorless reading of the unresolved land(s)
    reduced_castable_turn: int | None  # earliest turn this hand's own lands *and its own
    # in-hand fuel* can pay for it, for a card with a cost-reduction clause (see
    # _reduced_castable_turn below); None for a land, a card with no recognized
    # clause, or one this hand can't reach. Same colorless reading as castable_turn,
    # which it never overwrites: castable_turn stays the printed-cost answer


@dataclass(frozen=True, slots=True)
class OpeningHandRead:
    """The hand on offer right now, plus this deck's own context when a
    ``deck_id`` was available to look one up."""

    seat: int
    mulligan_count: int  # 0 on the first offer; this many mulligans already taken this game
    on_the_play: bool | None
    cards: tuple[OpeningHandCard, ...]
    land_count: int
    land_min: int | None
    land_max: int | None
    ideal_hand: tuple[HandSlot, ...]
    keep_rate: float | None
    mulligan_record: tuple[MulliganRecord, ...]
    unnamed_count: int
    colors_known: bool  # False when any land in hand resolves to neither produced_mana
    # nor effects.chosen_basic_type_colors
    verdict: str | None  # "keep" | "mulligan" | "marginal" | None (withheld — see caveats)
    reasons: tuple[str, ...]
    caveats: tuple[str, ...]
    keep_guide: KeepGuide | None = None
    # The KeepGuide this read already built from deck_id (None when deck_id
    # was None, same as every other keep-derived field above) — exposed so
    # ``/api/current-match/read`` can reuse it instead of calling
    # build_keep_guide, which re-runs list_identities and the mulligan
    # aggregate, a second time on every 1 Hz poll.


def _resolve_cards(
    conn: sqlite3.Connection, offer: MulliganOffer
) -> tuple[tuple[OpeningHandCard, ...], dict[int, str | None]]:
    grp_ids = [c.grp_id for c in offer.cards]
    by_id: dict[int, sqlite3.Row] = {}
    if grp_ids:
        placeholders = ",".join("?" * len(grp_ids))
        rows = conn.execute(
            f"SELECT grp_id, name, type_line, mana_cost, oracle_text FROM cards "
            f"WHERE grp_id IN ({placeholders})",
            grp_ids,
        ).fetchall()
        by_id = {r["grp_id"]: r for r in rows}

    cards = []
    oracle_text_by_grp: dict[int, str | None] = {}
    for card in offer.cards:
        row = by_id.get(card.grp_id)
        is_land = _LAND_TYPE in card.card_types
        name = row["name"] if row else None
        type_line = row["type_line"] if row else None
        mana_cost = row["mana_cost"] if row else None
        oracle_text = row["oracle_text"] if row else None
        oracle_text_by_grp[card.grp_id] = oracle_text

        # A land's "effect tags" are trivially none, known — same reason
        # keep.py's own per-card loop skips lands before ever calling
        # classify() on them.
        if is_land:
            tags: tuple[str, ...] = ()
            tags_known = True
            mana_value = None
        else:
            classified = effects.classify(oracle_text, type_line, mana_cost)
            tags_known = isinstance(classified, effects.EffectTags)
            tags = tuple(sorted(classified.tags)) if tags_known else ()
            mana_value = effects.mana_value(mana_cost)

        cards.append(
            OpeningHandCard(
                grp_id=card.grp_id,
                name=name,
                type_line=type_line,
                mana_cost=mana_cost,
                is_land=is_land,
                mana_value=mana_value,
                tags=tags,
                tags_known=tags_known,
                castable_turn=None,  # filled in below once land colors are known
                reduced_castable_turn=None,  # filled in below alongside castable_turn
            )
        )
    return tuple(cards), oracle_text_by_grp


def _land_colors(
    conn: sqlite3.Connection,
    land_grp_ids: list[int],
    oracle_text_by_grp: dict[int, str | None],
) -> tuple[dict[int, frozenset[str] | None], frozenset[int]]:
    """``produced_mana`` per land grp_id, falling back to
    ``effects.chosen_basic_type_colors`` on this land's own oracle text
    (already resolved by ``_resolve_cards`` — no second query for it) when
    Scryfall's own ``produced_mana`` export is blank but the land's text
    still names a real color set (Multiversal Passage). The second return
    value is the grp_ids that fallback actually resolved, so a caller can
    say which card it was for (``build_opening_hand_read``'s reason line).
    ``None`` in the dict only when neither source resolves a color set —
    the land is unnamed, or Scryfall left ``produced_mana`` blank and its
    text isn't a recognized chosen-type clause either: an honest gap
    (``migrations/021_produced_mana.sql``)."""
    result: dict[int, frozenset[str] | None] = dict.fromkeys(land_grp_ids)
    chosen_type: set[int] = set()
    if not land_grp_ids:
        return result, frozenset(chosen_type)
    placeholders = ",".join("?" * len(land_grp_ids))
    rows = conn.execute(
        f"SELECT grp_id, produced_mana FROM cards WHERE grp_id IN ({placeholders})",
        land_grp_ids,
    ).fetchall()
    for row in rows:
        if row["produced_mana"] is not None:
            result[row["grp_id"]] = frozenset(json.loads(row["produced_mana"]))
            continue
        chosen = effects.chosen_basic_type_colors(oracle_text_by_grp.get(row["grp_id"]))
        if chosen is not None:
            result[row["grp_id"]] = frozenset(chosen)
            chosen_type.add(row["grp_id"])
    return result, frozenset(chosen_type)


def _castable_with(land_colors: list[frozenset[str]], req: effects.ManaRequirement) -> bool:
    """True when some assignment of one land per colored pip — out of
    exactly the lands given — leaves enough left over for the generic
    remainder. A real matching via backtracking, not a "do we have a blue
    source" count: a hand with one dual and one Phyrexian-worst-case pip
    each needing that color cannot double-book the same land."""
    if len(land_colors) < req.generic + len(req.pips):
        return False
    return _assign_pips(list(land_colors), list(req.pips))


def _assign_pips(available: list[frozenset[str]], pips: list[frozenset[str]]) -> bool:
    if not pips:
        return True
    pip = pips[0]
    for i, colors in enumerate(available):
        if colors & pip and _assign_pips(available[:i] + available[i + 1 :], pips[1:]):
            return True
    return False


def _castable_turn(
    req: effects.ManaRequirement | None, lands: list[frozenset[str]]
) -> int | None:
    """The smallest number of this hand's own lands (played one per turn,
    any of them, in the best order) that can pay ``req`` — never a
    hypothetical future draw. ``None`` for an unparseable cost, or when no
    combination of this hand's own lands ever pays it. Exhaustive over at
    most seven lands, so a combinatorial search costs nothing worth
    measuring."""
    if req is None:
        return None
    needed = req.generic + len(req.pips)
    if needed == 0:
        return 0
    for k in range(needed, len(lands) + 1):
        for combo in itertools.combinations(lands, k):
            if _castable_with(list(combo), req):
                return k
    return None


# Cost-reduction clauses: at mulligan time the graveyard is empty, so the
# printed cost (castable_turn above) is the honest answer to "what does this
# cost right now", but the useful question is whether this hand can feed the
# reduction. Two fuel kinds are on file (effects.cost_reduction): a per-card
# graveyard count and a board-state lookup that is not a count at all. Both
# searches use only this hand's own cards, never a hypothetical draw.


def _is_instant_or_sorcery(type_line: str | None) -> bool:
    """Whether a card counts as fuel for the graveyard_instant_sorcery
    reduction. Eddymurk Crab's own clause counts only Instant/Sorcery cards;
    Hearth Elemental's broader clause also counts any card that "has an
    Adventure", but every Adventure card in this deck's fixtures is itself
    typed Sorcery on its Adventure half (Stoke Genius: "Sorcery — Adventure"),
    so checking the type line alone already covers both real clauses without
    a separate Adventure check. A card whose only Adventure marker is some
    other spell type would be undercounted here — an honest gap in the
    conservative direction (never claims an earlier turn than fuel actually
    supports), not a guess.
    """
    return type_line is not None and ("Instant" in type_line or "Sorcery" in type_line)


def _is_elemental_creature(type_line: str | None) -> bool:
    return type_line is not None and "Creature" in type_line and "Elemental" in type_line


def _reduced_castable_turn_graveyard(
    mana_cost: str | None,
    reduction: effects.CostReduction,
    fuel_cards: list[OpeningHandCard],
    lands: list[frozenset[str]],
) -> int | None:
    """Smallest turn at which this hand's own lands, minus this hand's own
    graveyard-fuel already resolved by an *earlier* turn, pay this card's
    front-face requirement. Fuel counted only from a strictly earlier turn
    (never the same turn as the reduced spell) so the search never double-
    books one turn's mana between the fuel spell and the reduced one — the
    same "can only ever be too conservative" discipline
    ``_pip_colors``/``mana_requirement`` already document. Reduction lowers
    only the generic portion of the cost, matching the real rule (a "costs
    {N} less" clause never reduces a colored pip)."""
    req = effects.mana_requirement(mana_cost)
    if req is None or reduction.per is None:
        return None
    for turn in range(1, len(lands) + 1):
        fuel = sum(
            1
            for f in fuel_cards
            if f.castable_turn is not None and f.castable_turn <= turn - 1
        )
        reduced = effects.ManaRequirement(
            generic=max(req.generic - reduction.per * fuel, 0), pips=req.pips
        )
        for combo in itertools.combinations(lands, turn):
            if _castable_with(list(combo), reduced):
                return turn
    return None


def _reduced_castable_turn_board_elemental(
    other_elemental_turns: list[int],
) -> int | None:
    """Sunderflock's clause is a board-state lookup, not a per-card count
    (see ``CostReduction.per`` being ``None`` for this fuel kind) — so this
    is not a search at all, only expressible when the hand actually holds
    another Elemental: the turn after the earliest one of them resolves.
    Withheld otherwise, rather than guessing at a generic reduction size."""
    if not other_elemental_turns:
        return None
    return min(other_elemental_turns) + 1


def _reduced_castable_turn(
    index: int,
    cards: tuple[OpeningHandCard, ...],
    oracle_text_by_grp: dict[int, str | None],
    lands: list[frozenset[str]],
) -> int | None:
    card = cards[index]
    reduction = effects.cost_reduction(oracle_text_by_grp.get(card.grp_id))
    if not isinstance(reduction, effects.CostReduction):
        # None (no clause) or UNPARSED_REDUCTION (an unrecognized "less to
        # cast" shape) — neither supports a fuel search without guessing.
        return None
    if reduction.fuel == "board_elemental_mv":
        other_elemental_turns = [
            c.castable_turn
            for i, c in enumerate(cards)
            if i != index
            and not c.is_land
            and _is_elemental_creature(c.type_line)
            and c.castable_turn is not None
        ]
        return _reduced_castable_turn_board_elemental(other_elemental_turns)
    fuel_cards = [
        c
        for i, c in enumerate(cards)
        if i != index and not c.is_land and _is_instant_or_sorcery(c.type_line)
    ]
    return _reduced_castable_turn_graveyard(card.mana_cost, reduction, fuel_cards, lands)


# A land with no produced_mana on file and no chosen_basic_type_colors match
# either (see _land_colors) is genuinely unknown, but "unknown" isn't the
# same as "could be anything" for the purpose of a keep/mulligan call: the
# honest bracket is colorless (pays only generic costs) at one end and any
# color (pays every colored pip) at the other. _PESSIMISTIC_UNKNOWN never
# satisfies a colored pip (no cost in this codebase's fixtures asks for "C"),
# so it can only ever undercount castability, never overcount it — the same
# "wrong only in the conservative direction" discipline mana_requirement's
# own pip handling already documents.
_PESSIMISTIC_UNKNOWN_LAND: frozenset[str] = frozenset({"C"})
_OPTIMISTIC_UNKNOWN_LAND: frozenset[str] = frozenset({"W", "U", "B", "R", "G"})


def _with_castability(
    cards: tuple[OpeningHandCard, ...],
    oracle_text_by_grp: dict[int, str | None],
    land_colors: list[frozenset[str]],
) -> tuple[OpeningHandCard, ...]:
    """``castable_turn`` and ``reduced_castable_turn`` for every non-land
    card, against one fixed reading of the hand's own land colors — called
    once when every land's color is on file (directly or via the chosen-type
    fallback), and twice (pessimistic, then optimistic) when one or more
    lands are still genuinely unknown, so the two bounds can be compared.
    Two passes over ``cards``: the second needs every card's own (already
    reassigned) ``castable_turn`` from the first as its fuel evidence."""
    cards = tuple(
        card
        if card.is_land
        else dataclasses.replace(
            card,
            castable_turn=_castable_turn(effects.mana_requirement(card.mana_cost), land_colors),
        )
        for card in cards
    )
    return tuple(
        card
        if card.is_land
        else dataclasses.replace(
            card,
            reduced_castable_turn=_reduced_castable_turn(
                i, cards, oracle_text_by_grp, land_colors
            ),
        )
        for i, card in enumerate(cards)
    )


# The pressure check: the land-band and early-castable cutoffs answer "can
# this hand function"; _pressure asks whether it is going anywhere, from this
# deck's own measured record (table/keep.py's key_plays). Only *measured*
# evidence moves the verdict this way; an authored mulligan plan never does.

# The mulligan brake's threshold, set from one real deck's kept-seven vs.
# mulliganed gap (docs/current-match.md, "The keep guide (`table/keep.py`)").
# A deck that pays this much for mulliganing keeps a marginal hand lacking
# pressure at marginal; a deck that pays little gets no such protection.
_MULLIGAN_BRAKE_POINTS = 13


def _win_rate(bucket) -> float | None:
    return bucket.wins / bucket.games if bucket.games else None


def _mulligan_brake_holds(mulligan_cost: MulliganCost | None) -> bool:
    """True when this deck's own kept-seven-vs-mulliganed record says
    mulliganing costs at least ``_MULLIGAN_BRAKE_POINTS`` percentage points
    -- enough that a marginal hand should not be pushed down to a mulligan
    for lack of pressure alone. False (no brake, nothing holds the verdict
    up) whenever the record is missing or either side of it has no games at
    all -- withholding a downgrade's protection is the same "don't guess"
    discipline as withholding an upgrade, just applied to the opposite
    direction."""
    if mulligan_cost is None:
        return False
    kept_rate = _win_rate(mulligan_cost.kept_seven)
    shipped_rate = _win_rate(mulligan_cost.mulliganed)
    if kept_rate is None or shipped_rate is None:
        return False
    return (kept_rate - shipped_rate) * 100 >= _MULLIGAN_BRAKE_POINTS


def _pressure(
    cards: tuple[OpeningHandCard, ...], key_plays: tuple[KeyPlay, ...]
) -> KeyPlay | None:
    """The first (highest-ranked) key play this hand actually holds and can
    reach -- via its printed cost or its own in-hand fuel (``castable_turn``
    or ``reduced_castable_turn``, either one) -- or ``None`` when this hand
    holds none of them, or holds one but cannot reach it with what's here.
    Iterates ``cards`` (not ``key_plays``) so a hand holding more than one
    threat reports the deck's biggest one first, matching key_plays' own
    finisher-first order."""
    by_name = {kp.card: kp for kp in key_plays}
    if not by_name:
        return None
    for card in cards:
        found = by_name.get(card.name)
        if found is not None and (
            card.castable_turn is not None or card.reduced_castable_turn is not None
        ):
            return found
    return None


def _mulligan_note(mulligan_count: int) -> str | None:
    if mulligan_count <= 0:
        return None
    return ngettext(
        "You've mulliganed once already this game — this is still a fresh 7 "
        "(London mulligan), but you'll bottom 1 card after keeping.",
        "You've mulliganed {n} times already this game — this is still a fresh 7 "
        "(London mulligan), but you'll bottom {n} cards after keeping.",
        mulligan_count,
    ).format(n=mulligan_count)


# The verdict is a code ("keep" | "mulligan" | "marginal"), stored and compared
# on; a sentence that names one writes it through this map.
_VERDICT_WORDS: dict[str, str] = {
    "keep": N_("Keep"),
    "mulligan": N_("Mulligan"),
    "marginal": N_("Marginal"),
}


def verdict_word(verdict: str) -> str:
    """``verdict`` capitalized as display text in the current language."""
    return _(_VERDICT_WORDS[verdict])


def _verdict(
    *,
    land_count: int,
    keep,
    cards: tuple[OpeningHandCard, ...],
    unnamed_count: int,
    deck_id: str | None,
) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    caveats: list[str] = []

    if unnamed_count > 0:
        caveats.append(
            ngettext(
                "{n} card(s) in this hand are not in the card table yet — "
                "run 'sensei-top cards' for a verdict.",
                "{n} card(s) in this hand are not in the card table yet — "
                "run 'sensei-top cards' for a verdict.",
                unnamed_count,
            ).format(n=unnamed_count)
        )
        return None, (), tuple(caveats)
    if keep is None or keep.land_min is None or keep.land_max is None:
        # "No deck_id at all" and "deck known but the band itself is
        # withheld" are different gaps with different fixes -- the second
        # one already has its own explanation sitting in keep.notes (an
        # unnamed maindeck card, or not enough curve data), so pointing at a
        # second card ("see the keep guide for why") only makes the player
        # go read it there instead of being told outright.
        if deck_id is None:
            caveats.append(
                _(
                    "Deck list not seen yet for this match — the verdict needs the deck's "
                    "land band."
                )
            )
        elif keep is not None and keep.notes:
            caveats.append(keep.notes[0])
        else:
            caveats.append(_("No land band for this deck yet — see the keep guide for why."))
        return None, (), tuple(caveats)

    in_band = keep.land_min <= land_count <= keep.land_max
    if in_band:
        land_reason = ngettext(
            "{n} land (in this deck's {land_min}-{land_max} band)",
            "{n} lands (in this deck's {land_min}-{land_max} band)",
            land_count,
        )
    else:
        land_reason = ngettext(
            "{n} land (outside this deck's {land_min}-{land_max} band)",
            "{n} lands (outside this deck's {land_min}-{land_max} band)",
            land_count,
        )
    reasons = [land_reason.format(n=land_count, land_min=keep.land_min, land_max=keep.land_max)]

    castable_early = sum(
        1
        for c in cards
        if not c.is_land
        and c.castable_turn is not None
        and c.castable_turn <= _EARLY_TURN_THRESHOLD
    )
    reasons.append(
        ngettext(
            "{n} card castable by turn {turn}",
            "{n} cards castable by turn {turn}",
            castable_early,
        ).format(n=castable_early, turn=_EARLY_TURN_THRESHOLD)
    )

    if not in_band or castable_early == 0:
        return "mulligan", tuple(reasons), tuple(caveats)

    # The pressure check. No key_plays at all means this deck hasn't cleared
    # _MIN_EVIDENCE_GAMES yet (table/keep.py) -- thin evidence, so nothing
    # below moves the verdict off the plain land/curve cutoff.
    key_plays = keep.key_plays
    pressure = _pressure(cards, key_plays) if key_plays else None
    if key_plays:
        if pressure is not None:
            record = pressure.best_band_record
            reasons.append(
                _("{card} in hand, reachable this hand ({band}: {wins}-{losses})").format(
                    card=pressure.card,
                    band=band_word(pressure.best_band),
                    wins=record.w,
                    losses=record.l,
                )
            )
        else:
            top = key_plays[0]
            record = top.best_band_record
            reasons.append(
                _(
                    "no threat like {card} in hand or reachable this hand "
                    "({card} is {wins}-{losses} from {band})"
                ).format(
                    card=top.card,
                    wins=record.w,
                    losses=record.l,
                    band=band_word(top.best_band),
                )
            )

    if castable_early >= (keep.early_plays or 0):
        if not key_plays or pressure is not None:
            return "keep", tuple(reasons), tuple(caveats)
        return "marginal", tuple(reasons), tuple(caveats)

    # castable_early < early_plays: "marginal" by the land/curve cutoff.
    # Pressure (or no measured evidence at all) leaves it there unchanged;
    # its absence, with measured evidence available, is grounds to slide
    # further to "mulligan" -- unless this deck's own mulligan_cost brake
    # says shipping this hand is worse than keeping a mediocre one.
    if not key_plays or pressure is not None:
        return "marginal", tuple(reasons), tuple(caveats)
    if _mulligan_brake_holds(keep.mulligan_cost):
        reasons.append(
            _(
                "mulliganing costs this deck at least {points} points here -- "
                "staying marginal rather than shipping"
            ).format(points=_MULLIGAN_BRAKE_POINTS)
        )
        return "marginal", tuple(reasons), tuple(caveats)
    return "mulligan", tuple(reasons), tuple(caveats)


def build_opening_hand_read(
    conn: sqlite3.Connection,
    *,
    deck_id: str | None,
    offer: MulliganOffer | None = _NOT_GIVEN,  # type: ignore[assignment]
    maindeck: Sequence[int] | None = None,
    boarded: bool = False,
) -> OpeningHandRead | None:
    """The read for a mulligan decision pending right now, or ``None`` when
    nothing is (the caller, ``api/routes/current_match.py`` through
    ``api/convert.py``, decides how "nothing pending" renders: a mulligan
    phase with no offer yet, or no match at all).

    ``deck_id`` is optional and only enriches the read with this deck's own
    land band, ideal-hand shape and mulligan record (``build_keep_guide``) —
    the hand's own facts (land count, what's castable off it) need no deck
    at all, which is what lets this read serve before ``project()`` has ever
    produced a ``matches`` row for the current match. ``maindeck`` is
    forwarded to ``build_keep_guide`` unchanged — its own fallback for a
    ``deck_id`` that has no ``v_deck_land_count`` row yet: the live replay's
    own ``LiveState.deck_maindeck``, so the first mulligan of a match has a
    land band before ``project()`` writes a ``matches`` row. ``boarded`` is
    forwarded the same way (``LiveState.deck_boarded``).

    ``offer`` defaults to replaying ``raw_events`` itself
    (``table/live.py``'s anchor plus ``projector/live_state.py``'s replay).
    Pass an already-resolved ``offer`` (including explicitly ``None``,
    meaning a live replay already ran and found nothing pending) when the
    caller is building the wider live state anyway, so one request does one
    replay of ``raw_events`` rather than two — see ``/api/current-match/read``.
    """
    if offer is _NOT_GIVEN:
        state = live.build_live_state(conn)
        offer = state.offer if state is not None else None
    if offer is None:
        return None

    cards, oracle_text_by_grp = _resolve_cards(conn, offer)
    land_grp_ids = [c.grp_id for c in cards if c.is_land]
    # One DB round trip per *distinct* grp_id, but land_colors below still
    # needs one entry per physical land card — two Islands share a grp_id
    # and must count as two color sources, not collapse into one.
    unique_land_grp_ids = list(dict.fromkeys(land_grp_ids))
    colors_by_grp, chosen_type_grp_ids = _land_colors(
        conn, unique_land_grp_ids, oracle_text_by_grp
    )
    colors_known = all(colors_by_grp.get(g) is not None for g in land_grp_ids)
    unresolved_grp_ids = [g for g in unique_land_grp_ids if colors_by_grp.get(g) is None]

    unnamed_count = sum(1 for c in cards if c.name is None)
    land_count = len(land_grp_ids)
    on_the_play = offer.active_player == offer.seat if offer.active_player is not None else None
    keep = (
        build_keep_guide(conn, deck_id, maindeck=maindeck, boarded=boarded)
        if deck_id is not None
        else None
    )

    if colors_known:
        land_colors = [colors_by_grp[g] for g in land_grp_ids]
        cards = _with_castability(cards, oracle_text_by_grp, land_colors)
        verdict, reasons, caveats = _verdict(
            land_count=land_count,
            keep=keep,
            cards=cards,
            unnamed_count=unnamed_count,
            deck_id=deck_id,
        )
    else:
        # Neither produced_mana nor chosen_basic_type_colors resolved every
        # land in hand. Rather than blank the verdict outright, bracket it:
        # the pessimistic reading (every unresolved land pays only generic
        # costs) and the optimistic one (every unresolved land pays any
        # colored pip) can only ever disagree about a hand the unresolved
        # land's real color would actually decide — everywhere else they
        # land on the same call.
        pessimistic_colors = [
            colors_by_grp[g] if colors_by_grp.get(g) is not None else _PESSIMISTIC_UNKNOWN_LAND
            for g in land_grp_ids
        ]
        optimistic_colors = [
            colors_by_grp[g] if colors_by_grp.get(g) is not None else _OPTIMISTIC_UNKNOWN_LAND
            for g in land_grp_ids
        ]
        cards_pess = _with_castability(cards, oracle_text_by_grp, pessimistic_colors)
        verdict_pess, reasons_pess, caveats_pess = _verdict(
            land_count=land_count,
            keep=keep,
            cards=cards_pess,
            unnamed_count=unnamed_count,
            deck_id=deck_id,
        )
        # Per-card fields shown in the UI are always the conservative
        # (colorless) reading, in every branch below.
        cards = cards_pess

        if verdict_pess is None:
            # Withheld for a reason that has nothing to do with color (an
            # unnamed card, or no land band yet) — the unresolved land's
            # color was never going to change that, so there's no reason to
            # run the optimistic pass at all.
            verdict, reasons, caveats = verdict_pess, reasons_pess, list(caveats_pess)
        else:
            cards_opt = _with_castability(cards, oracle_text_by_grp, optimistic_colors)
            verdict_opt, _reasons_opt, _caveats_opt = _verdict(
                land_count=land_count,
                keep=keep,
                cards=cards_opt,
                unnamed_count=unnamed_count,
                deck_id=deck_id,
            )
            names = ", ".join(
                sorted(
                    {
                        c.name
                        for c in cards
                        if c.is_land and c.grp_id in unresolved_grp_ids and c.name
                    }
                )
            )
            suffix = (
                " " + _("Run 'sensei-top cards --scryfall' to fetch it.")
                if any(oracle_text_by_grp.get(g) is None for g in unresolved_grp_ids)
                else ""
            )
            if verdict_opt == verdict_pess:
                verdict, reasons, caveats = verdict_pess, reasons_pess, list(caveats_pess)
                caveats.append(
                    _(
                        "{names}: no mana production on file — the call is the same whether "
                        "or not it makes colored mana."
                    ).format(names=names)
                    + suffix
                )
            else:
                verdict = None
                # Withheld, like every other branch of _verdict that returns
                # None -- the pessimistic pass's own reasons would justify a
                # "mulligan" call sitting right under a headline that is
                # explicitly not calling it, which is worse than saying
                # nothing.
                reasons = ()
                caveats = list(caveats_pess)
                caveats.append(
                    _(
                        "{optimistic} if {names} makes the colors this hand "
                        "needs, {pessimistic} if it doesn't — no mana "
                        "production on file for it."
                    ).format(
                        optimistic=verdict_word(verdict_opt),
                        names=names,
                        pessimistic=verdict_word(verdict_pess),
                    )
                    + suffix
                )

    caveats = tuple(caveats)

    chosen_type_names = sorted(
        {c.name for c in cards if c.is_land and c.grp_id in chosen_type_grp_ids and c.name}
    )
    if chosen_type_names:
        reasons = tuple(reasons) + tuple(
            _(
                "{name} counted as whichever basic type each spell needs — you choose it "
                "once, as it enters"
            ).format(name=name)
            for name in chosen_type_names
        )

    mulligan_note = _mulligan_note(offer.mulligan_count)
    if mulligan_note:
        caveats = (mulligan_note, *caveats)

    return OpeningHandRead(
        seat=offer.seat,
        mulligan_count=offer.mulligan_count,
        on_the_play=on_the_play,
        cards=cards,
        land_count=land_count,
        land_min=keep.land_min if keep else None,
        land_max=keep.land_max if keep else None,
        ideal_hand=keep.ideal_hand if keep else (),
        keep_rate=keep.keep_rate if keep else None,
        mulligan_record=keep.mulligan_record if keep else (),
        unnamed_count=unnamed_count,
        colors_known=colors_known,
        verdict=verdict,
        reasons=reasons,
        caveats=caveats,
        keep_guide=keep,
    )
