"""What the opponent might still be holding, from everything revealed about
this game so far — the same "known information" logic Duke's *Thoughtseize
You* asks a player to run in their own head, computed instead. See
docs/current-match.md, "The opponent-hand read (`table/hand_read.py`)".

The estimate rests on the one thing Arena hands us honestly: the *count* of
cards in the opponent's hand and library, never their identity. Lands are
excluded, and anything already seen (a card revealed sitting in their hand
included) is subtracted, before anything is ranked: without the land
filter, a basic Island ranked as one archetype's most-expected "threat"
against the real corpus.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import NamedTuple

from sensei_top.i18n import N_, _
from sensei_top.projector.live_state import LiveState
from sensei_top.review import effects
from sensei_top.review.consensus import ArchetypeConsensus

# The field's consensus decklist stands in for a real 60 we never see — every
# read here inherits that gap, so every "ok" result carries this caveat (the
# same sentence review/analyzers/frame.py uses for its own opponent-side
# comparison).
_CONSENSUS_CAVEAT = N_(
    "The card list is the field's typical decklist for this archetype, not their "
    "actual 60 cards, which this reader never sees."
)

# Facts-first: the page leads with what's actually known and keeps this
# estimate to a short, clearly speculative list. The dashboard doesn't draw
# threats at all, so they keep a wider cap.
_MAX_INTERACTION = 5
_MAX_CARDS_PER_LIST = 8


@dataclass(frozen=True, slots=True)
class HandCard:
    name: str
    grp_id: int | None  # None when this consensus card never matched a cards row
    type_line: str | None
    mana_cost: str | None
    mana_value: int | None
    tags: tuple[str, ...]
    tags_known: bool  # False when effects.classify never saw oracle_text for this card
    expected_copies_left: float
    p_in_hand: float
    castable_now: bool | None  # None when mana value or open mana is unknown


@dataclass(frozen=True, slots=True)
class RevealedCard:
    """One card Arena has actually shown us, by name — a fact, not an
    estimate. ``grp_id`` rides along so the tab can show its picture; it is
    ``None`` only in the same rare case an unrevealed consensus card's is —
    the name resolved but never joined to a ``cards`` row."""

    name: str
    grp_id: int | None


@dataclass(frozen=True, slots=True)
class HandRead:
    status: str  # ok | unclassified | no_consensus | format_unknown | no_game
    archetype_key: str | None
    archetype_label: str | None
    deck_count: int | None  # decks behind the consensus, when there is one
    hand_size: int | None
    hidden_pool: int | None  # opp_hand + opp_library
    open_mana: int | None  # untapped lands only — see castable_now's own note
    other_mana_sources: int | None  # untapped rocks/dorks/Treasures, a sibling count
    held_turns: int | None  # consecutive latest turns at this same hand size
    known_in_hand: tuple[RevealedCard, ...]  # revealed right now — a fact, not an estimate
    revealed_this_match: tuple[RevealedCard, ...]  # shown anywhere this game, any zone but hand
    interaction: tuple[HandCard, ...]
    threats: tuple[HandCard, ...]
    caveats: tuple[str, ...]


def _prob_at_least_one(population: int, successes: float, draws: int) -> float:
    """P(at least one of `successes` expected copies among `draws` cards
    drawn without replacement from a `population`-card pool) — the
    hypergeometric complement, run sequentially (rather than via a binomial
    coefficient) because `successes` is an expected-copy count and is rarely
    a whole number. The same read ``web/src/lib/odds.ts``'s
    ``probAtLeastOneIn`` runs for the player's own deck."""
    if population <= 0 or successes <= 0 or draws <= 0:
        return 0.0
    draws = min(draws, population)
    p_none = 1.0
    for i in range(draws):
        remaining = population - i
        non_success = remaining - successes
        if non_success <= 0:
            return 1.0
        p_none *= non_success / remaining
    return 1.0 - p_none


def _held_turns(
    conn: sqlite3.Connection, match_id: str, game_number: int, hand_size: int | None
) -> int | None:
    """How many of the most recent turns the opponent's hand has sat at
    exactly this size, counting back from the latest turn — a hand that
    hasn't shrunk in several turns is either flooding or sitting on
    reactive cards, either of which is worth surfacing even with no
    per-card read at all."""
    if hand_size is None:
        return None
    rows = conn.execute(
        "SELECT opp_hand FROM turns WHERE match_id = ? AND game_number = ? "
        "ORDER BY turn_number DESC",
        (match_id, game_number),
    ).fetchall()
    streak = 0
    for row in rows:
        if row["opp_hand"] != hand_size:
            break
        streak += 1
    return streak or None


class _SeenCard(NamedTuple):
    copies: int
    grp_id: int | None


def _seen_elsewhere(
    conn: sqlite3.Connection, match_id: str, game_number: int
) -> dict[str, _SeenCard]:
    """Distinct copies of each named card the opponent has shown in any zone
    but their hand this game — battlefield, graveyard or exile — counted by
    ``instance_id`` so a card that moved zones (cast, then killed) is one
    copy, not two. ``MIN(grp_id)`` picks one printing arbitrarily when a name
    has shown up under more than one grp_id this game; the count these feed
    into (``expected_copies_left``) is name-keyed regardless, so only the
    picture shown for it is affected, never the arithmetic."""
    rows = conn.execute(
        """
        SELECT card_name, COUNT(DISTINCT instance_id) AS n, MIN(grp_id) AS grp_id
          FROM v_turn_zones
         WHERE match_id = ? AND game_number = ? AND is_self = 0
           AND grp_id IS NOT NULL AND card_name IS NOT NULL AND zone != 'hand'
         GROUP BY card_name
        """,
        (match_id, game_number),
    ).fetchall()
    return {r["card_name"]: _SeenCard(copies=r["n"], grp_id=r["grp_id"]) for r in rows}


def _known_in_hand_now(
    conn: sqlite3.Connection, match_id: str, game_number: int, turn_number: int
) -> tuple[RevealedCard, ...]:
    """Cards Arena has actually shown sitting in the opponent's hand at the
    latest turn — normally empty, since a hand's contents are hidden by
    default; non-empty only when something genuinely revealed it."""
    rows = conn.execute(
        """
        SELECT DISTINCT card_name, grp_id FROM v_turn_zones
         WHERE match_id = ? AND game_number = ? AND turn_number = ?
           AND is_self = 0 AND zone = 'hand' AND grp_id IS NOT NULL AND card_name IS NOT NULL
        """,
        (match_id, game_number, turn_number),
    ).fetchall()
    return tuple(
        sorted(
            (RevealedCard(name=r["card_name"], grp_id=r["grp_id"]) for r in rows),
            key=lambda c: c.name,
        )
    )


def _seen_elsewhere_live(
    conn: sqlite3.Connection, live: LiveState, opponent_seat: int
) -> dict[str, _SeenCard]:
    """Same result shape as ``_seen_elsewhere``, sourced from a live replay's
    ``zone_cards`` instead of the projected ``v_turn_zones`` — see
    ``build_hand_read``'s docstring for why. ``ZoneCard`` carries only
    ``grp_id``, not a resolved name, so this does its own small ``cards``
    lookup rather than reusing the view's join."""
    instances_by_grp: dict[int, set[int]] = {}
    for card in live.zone_cards:
        if card.seat != opponent_seat or card.zone == "hand" or card.grp_id is None:
            continue
        instances_by_grp.setdefault(card.grp_id, set()).add(card.instance_id)
    if not instances_by_grp:
        return {}

    rows = conn.execute(
        f"SELECT grp_id, name FROM cards WHERE grp_id IN ({','.join('?' * len(instances_by_grp))})",
        tuple(instances_by_grp),
    ).fetchall()
    name_by_grp = {r["grp_id"]: r["name"] for r in rows}

    counts: dict[str, int] = {}
    grp_ids_by_name: dict[str, list[int]] = {}
    for grp_id, instance_ids in instances_by_grp.items():
        name = name_by_grp.get(grp_id)
        if name is None:
            continue
        counts[name] = counts.get(name, 0) + len(instance_ids)
        grp_ids_by_name.setdefault(name, []).append(grp_id)

    return {
        name: _SeenCard(copies=counts[name], grp_id=min(grp_ids))
        for name, grp_ids in grp_ids_by_name.items()
    }


def _known_in_hand_live(
    conn: sqlite3.Connection, live: LiveState, opponent_seat: int
) -> tuple[RevealedCard, ...]:
    """Same result shape as ``_known_in_hand_now``, sourced live."""
    hand_grp_ids = {
        card.grp_id
        for card in live.zone_cards
        if card.seat == opponent_seat and card.zone == "hand" and card.grp_id is not None
    }
    if not hand_grp_ids:
        return ()
    rows = conn.execute(
        f"SELECT grp_id, name FROM cards WHERE grp_id IN ({','.join('?' * len(hand_grp_ids))})",
        tuple(hand_grp_ids),
    ).fetchall()
    return tuple(
        sorted(
            (
                RevealedCard(name=r["name"], grp_id=r["grp_id"])
                for r in rows
                if r["name"] is not None
            ),
            key=lambda c: c.name,
        )
    )


def build_hand_read(
    conn: sqlite3.Connection,
    match_id: str,
    game_number: int,
    *,
    opponent_key: str | None,
    archetype_label: str | None,
    consensus: ArchetypeConsensus | None,
    fmt: str | None,
    live: LiveState | None = None,
) -> HandRead:
    """The opponent-hand read for one game in progress.

    ``consensus`` is passed in rather than built here: the caller
    (``api/routes/current_match.py``) already resolves ``opponent_key`` to
    an archetype and fetches/caches its consensus for the matchup brief, and
    building it a second time per request would double the corpus scan on
    every poll.

    ``live`` is the shared per-request replay from ``table/live.py``. When
    given, and it has actually reached a real turn (``live.turn_number`` is
    not ``None`` — the mulligan phase is deliberately excluded, matching the
    "no_game" status every caller already expects before the first turn),
    every observed fact below comes from that fresh replay instead of the
    latest stored ``turns`` row, which runs stale by the rebuild's lag
    (docs/current-match.md, "The live replay (`table/live.py`,
    `projector/live_state.py`)"). Falls back to the ``turns``/
    ``v_turn_zones`` rows whenever ``live`` is absent or hasn't reached a
    turn yet.

    ``fmt`` is the match's format (``None`` when nothing names one) and has no
    default: a caller must say. With ``None`` the read is ``format_unknown``,
    checked before ``unclassified`` and ``consensus`` — the classifier never
    names an opponent in a match with no format, so ``unclassified`` would
    promise a read that never comes, and ``no_consensus`` would blame a thin
    corpus for a missing format.
    """
    live_seat = (
        live.opponent_seat if live is not None and live.turn_number is not None else None
    )
    if live_seat is not None:
        hand_size = live.hand.get(live_seat)
        library = live.library.get(live_seat)
        open_mana = live.open_mana.get(live_seat)
        other_mana_sources = live.other_mana_sources.get(live_seat)
        seen_elsewhere = _seen_elsewhere_live(conn, live, live_seat)
        known_in_hand = _known_in_hand_live(conn, live, live_seat)
    else:
        latest = conn.execute(
            "SELECT turn_number, opp_hand, opp_library, opp_open_mana FROM turns "
            "WHERE match_id = ? AND game_number = ? ORDER BY turn_number DESC LIMIT 1",
            (match_id, game_number),
        ).fetchone()
        if latest is None:
            return HandRead(
                status="no_game", archetype_key=None, archetype_label=None, deck_count=None,
                hand_size=None, hidden_pool=None, open_mana=None, other_mana_sources=None,
                held_turns=None, known_in_hand=(), revealed_this_match=(), interaction=(),
                threats=(), caveats=(),
            )
        hand_size = latest["opp_hand"]
        library = latest["opp_library"]
        open_mana = latest["opp_open_mana"]
        # Not available outside a live replay — turns.opp_open_mana stays
        # lands-only (see TurnRow.other_mana_sources on why that column's
        # meaning never changes), so there is nothing to widen with here.
        # None, not 0: genuinely unknown, not "no other sources".
        other_mana_sources = None
        seen_elsewhere = _seen_elsewhere(conn, match_id, game_number)
        known_in_hand = _known_in_hand_now(conn, match_id, game_number, latest["turn_number"])

    hidden_pool = hand_size + library if hand_size is not None and library is not None else None
    held_turns = _held_turns(conn, match_id, game_number, hand_size)
    known_copies_by_name: dict[str, int] = {}
    for revealed in known_in_hand:
        known_copies_by_name[revealed.name] = known_copies_by_name.get(revealed.name, 0) + 1
    revealed_this_match = tuple(
        sorted(
            (RevealedCard(name=name, grp_id=seen.grp_id) for name, seen in seen_elsewhere.items()),
            key=lambda c: c.name,
        )
    )

    base = dict(
        hand_size=hand_size,
        hidden_pool=hidden_pool,
        open_mana=open_mana,
        other_mana_sources=other_mana_sources,
        held_turns=held_turns,
        known_in_hand=known_in_hand,
        revealed_this_match=revealed_this_match,
    )

    archetype_key = (
        opponent_key.removeprefix("archetype:")
        if opponent_key and opponent_key.startswith("archetype:")
        else None
    )
    if fmt is None:
        return HandRead(
            status="format_unknown", archetype_key=archetype_key,
            archetype_label=archetype_label, deck_count=None, interaction=(),
            threats=(), caveats=(), **base,
        )
    if archetype_key is None:
        return HandRead(
            status="unclassified", archetype_key=None, archetype_label=archetype_label,
            deck_count=None, interaction=(), threats=(), caveats=(), **base,
        )
    if consensus is None:
        return HandRead(
            status="no_consensus", archetype_key=archetype_key, archetype_label=archetype_label,
            deck_count=None, interaction=(), threats=(), caveats=(), **base,
        )
    if hand_size is None or hidden_pool is None:
        return HandRead(
            status="ok", archetype_key=archetype_key, archetype_label=archetype_label,
            deck_count=consensus.deck_count, interaction=(), threats=(),
            caveats=(_(_CONSENSUS_CAVEAT),), **base,
        )

    interaction: list[HandCard] = []
    threats: list[HandCard] = []
    for card in consensus.cards:
        # A land is never a "threat" or something to "hold up" — filtering it
        # out here, before ranking, is what keeps a deck's own basics from
        # outranking its real spells (see module docstring).
        if effects.is_land(card.type_line):
            continue
        seen = seen_elsewhere.get(card.name)
        known = known_copies_by_name.get(card.name, 0)
        expected_copies_left = max(
            0.0, card.share * card.copies - (seen.copies if seen else 0) - known
        )
        if expected_copies_left <= 0:
            continue
        p_in_hand = _prob_at_least_one(hidden_pool, expected_copies_left, hand_size)
        if p_in_hand <= 0:
            continue

        tags_known = isinstance(card.tags, frozenset)
        tags = card.tags if tags_known else frozenset()
        mana_value = effects.mana_value(card.mana_cost)
        # Open lands plus any known non-land sources (rocks, dorks,
        # Treasures) — an upper bound ("could have"), not a certainty:
        # a summoning-sick creature still counts here, since Arena's
        # isTapped says nothing about legal-to-tap-right-now.
        available_mana = (
            None
            if open_mana is None
            else open_mana + (other_mana_sources if other_mana_sources is not None else 0)
        )
        castable_now = (
            None
            if mana_value is None or available_mana is None
            else "Instant" in (card.type_line or "") and mana_value <= available_mana
        )
        hand_card = HandCard(
            name=card.name,
            grp_id=card.grp_id,
            type_line=card.type_line,
            mana_cost=card.mana_cost,
            mana_value=mana_value,
            tags=tuple(sorted(tags)),
            tags_known=tags_known,
            expected_copies_left=expected_copies_left,
            p_in_hand=p_in_hand,
            castable_now=castable_now,
        )
        is_interaction = (
            "spot_removal" in tags
            or "sweeper" in tags
            or "counterspell" in tags
            or "Instant" in (card.type_line or "")
        )
        (interaction if is_interaction else threats).append(hand_card)

    # Ranked by expected copies left, not p_in_hand: a 3-or-4-of and a 1-of
    # cluster to similar-looking probabilities once the pool is large.
    # p_in_hand rides along as the displayed badge.
    interaction.sort(key=lambda c: -c.expected_copies_left)
    threats.sort(key=lambda c: -c.expected_copies_left)

    return HandRead(
        status="ok", archetype_key=archetype_key, archetype_label=archetype_label,
        deck_count=consensus.deck_count,
        interaction=tuple(interaction[:_MAX_INTERACTION]),
        threats=tuple(threats[:_MAX_CARDS_PER_LIST]),
        caveats=(_(_CONSENSUS_CAVEAT),), **base,
    )
