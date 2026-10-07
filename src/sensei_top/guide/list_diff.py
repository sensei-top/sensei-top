"""Your 75 against the field's consensus — the data behind the guide's "The list" section.

Classifies the player's own current decklist with the same
``archetypes.classify`` rule engine ``review/snapshot.py`` already uses for
one match at a time (``_classify_own_deck``, reused here rather than
duplicated — one classification path, one place to fix a bug in it), then
compares it against ``review.consensus.build_consensus`` for that archetype,
windowed to winning post-reset lists.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass

from sensei_top.archetypes.classify import normalize
from sensei_top.guide.deck import DeckIdentity, identity_format
from sensei_top.guide.window import FormatReset, deck_cards, window_start
from sensei_top.review.consensus import ArchetypeConsensus, build_consensus
from sensei_top.review.snapshot import _classify_own_deck

STAPLE_SHARE = 0.5


@dataclass(frozen=True, slots=True)
class CardVerdict:
    card: str
    yours: int
    board: str  # "main" | "side"
    consensus_copies: float | None
    consensus_share: float | None
    recommended: int
    verdict: str  # "correct" | "add" | "trim" | "cut" | "flex"


@dataclass(frozen=True, slots=True)
class ListDiff:
    archetype_key: str
    archetype_name: str
    winning_decks: int
    min_wins: int
    maindeck: tuple[CardVerdict, ...]
    sideboard: tuple[CardVerdict, ...]
    duplicate_warnings: tuple[str, ...]


def _recommended(consensus_copies: float | None) -> int:
    if consensus_copies is None:
        return 0
    return round(consensus_copies)


def _verdict_for(yours: int, share: float | None, recommended: int) -> str:
    if share is None:
        return "flex"  # you play it, the corpus has never seen it
    if yours == 0:
        return "add" if share >= STAPLE_SHARE else "correct"
    if yours == recommended:
        return "correct"
    return "trim" if yours > recommended else "add"


def _consensus_lookup(consensus: ArchetypeConsensus) -> dict[str, object]:
    """Every consensus card, keyed by each legitimate written form of its
    name (``normalize``) rather than the exact string. A real decklist
    names an adventure or split card by its front face alone
    ("Hearth Elemental"), while Arena's own card database — where the
    player's own card names come from — stores the combined name
    ("Hearth Elemental // Stoke Genius"); an exact match between the two
    misses every one of these and reports a card the player already runs
    as missing."""
    lookup: dict[str, object] = {}
    for card in consensus.cards:
        for form in normalize(card.name):
            lookup.setdefault(form, card)
    return lookup


def _find_consensus_card(lookup: dict[str, object], name: str):
    for form in normalize(name):
        if form in lookup:
            return lookup[form]
    return None


def _board_verdicts(
    own_counts: Counter, board: str, consensus: ArchetypeConsensus, card_names: dict[int, str],
) -> tuple[CardVerdict, ...]:
    lookup = _consensus_lookup(consensus)
    matched_consensus_names: set[str] = set()
    verdicts: list[CardVerdict] = []

    for grp_id, count in own_counts.items():
        name = card_names.get(grp_id)
        if name is None:
            continue
        card = _find_consensus_card(lookup, name)
        if card is not None:
            matched_consensus_names.add(card.name)
        share = card.share if card else None
        copies = card.copies if card else None
        recommended = _recommended(copies) if card and share and share >= STAPLE_SHARE else count
        verdicts.append(CardVerdict(
            card=name, yours=count, board=board, consensus_copies=copies,
            consensus_share=share, recommended=recommended,
            verdict=_verdict_for(count, share, recommended),
        ))

    # staples the player does not run at all
    for card in consensus.staples(min_share=STAPLE_SHARE):
        if card.name in matched_consensus_names:
            continue
        verdicts.append(CardVerdict(
            card=card.name, yours=0, board=board, consensus_copies=card.copies,
            consensus_share=card.share, recommended=_recommended(card.copies), verdict="add",
        ))

    verdicts.sort(key=lambda v: (-(v.consensus_share or 0), v.card))
    return tuple(verdicts)


def _duplicate_warnings(
    consensus: ArchetypeConsensus, conn: sqlite3.Connection, archetype_key: str,
    *, fmt: str, since: str | None, min_wins: int, board: str = "main",
) -> tuple[str, ...]:
    """Flag (never merge) two consensus cards that share an identical
    type_line and mana_cost and never co-occur in one decklist — the shape
    of the guide's own third correction, for whatever ``oracle_id``
    canonicalisation in ``build_consensus`` did not already catch (no
    ``oracle_id`` on file for either printing)."""
    rows = {
        row["name"]: (row["type_line"], row["mana_cost"])
        for row in conn.execute(
            f"SELECT name, type_line, mana_cost FROM cards WHERE name IN "
            f"({','.join('?' for _ in consensus.cards)})",
            [c.name for c in consensus.cards],
        )
    } if consensus.cards else {}

    by_shape: dict[tuple, list[str]] = {}
    for card in consensus.cards:
        shape = rows.get(card.name)
        if shape is None or shape[0] is None:
            continue
        by_shape.setdefault(shape, []).append(card.name)
    candidate_pairs = [names for names in by_shape.values() if len(names) >= 2]
    if not candidate_pairs:
        return ()

    # A real per-deck co-occurrence check: same query build_consensus itself
    # ran, re-scanned here only because a pair of same-shape names surfaced.
    json_field = "mainboard_json" if board == "main" else "sideboard_json"
    clauses = ["da.archetype_key = ?", "e.format = ?"]
    params: list = [archetype_key, fmt]
    if since is not None:
        clauses.append("e.event_date >= ?")
        params.append(since)
    if min_wins is not None:
        clauses.append("d.wins >= ?")
        params.append(min_wins)
    deck_rows = conn.execute(
        f"""
        SELECT d.{json_field} AS board_json FROM meta_deck d
          JOIN meta_deck_archetype da ON da.event_id = d.event_id AND da.deck_ord = d.deck_ord
          JOIN meta_event e ON e.event_id = d.event_id
         WHERE {' AND '.join(clauses)}
        """,
        params,
    ).fetchall()

    warnings = []
    for names in candidate_pairs:
        co_occurs = any(
            len(set(deck_cards(row, "board_json")) & set(names)) >= 2
            for row in deck_rows
        )
        if co_occurs:
            continue
        pct = ", ".join(
            f"{name} ({next(c.share for c in consensus.cards if c.name == name):.0%})"
            for name in names
        )
        warnings.append(
            f"{' and '.join(names)} share an identical type line and mana cost and never "
            f"co-occur in one decklist — they may be the same card under two names: {pct}."
        )
    return tuple(warnings)


def build_list_diff(
    conn: sqlite3.Connection,
    identity: DeckIdentity,
    *,
    reset: FormatReset | None = None,
    min_wins: int = 3,
    min_decks: int = 5,
    cards: dict | None = None,
    verdict=None,
    fmt: str | None = None,
) -> ListDiff | None:
    """``None`` when the player's own deck cannot be classified, or the
    field's consensus for that archetype does not clear ``min_decks`` —
    both real gaps, never guessed around.

    ``fmt`` is the deck's format; omitted, it is read from ``identity``
    (``guide/deck.py``'s ``identity_format``, D15). It classifies the deck and
    picks the corpus for both consensus lists and the duplicate-warning scan,
    whether or not ``verdict`` is given. A deck with no format gets no diff.

    ``cards`` (``{"maindeck": [grp_id, ...], "sideboard": [...]}``, one entry
    per copy) compares that list instead of ``identity.current_cards`` — the
    RCQ guide's pasted 75 (``guide/rcq.py``). ``verdict`` (anything with a
    ``key`` and a ``name``) names the archetype instead of classifying the
    identity's most recent deck. Neither given, this is the guide's own diff.
    """
    if fmt is None:
        fmt = identity_format(conn, identity)
    if fmt is None:
        return None

    if verdict is None:
        deck_ids = identity.deck_ids
        if not deck_ids:
            return None
        # the most recently played version is what _classify_own_deck should read
        current_deck_id = None
        for row in conn.execute(
            f"""
            SELECT md.deck_id FROM matches m
              JOIN v_match_deck md ON md.match_id = m.match_id
              JOIN decks d ON d.deck_id = md.deck_id
             WHERE md.deck_id IN ({','.join('?' for _ in deck_ids)})
             GROUP BY md.deck_id ORDER BY MAX(m.started_at) DESC LIMIT 1
            """,
            deck_ids,
        ):
            current_deck_id = row["deck_id"]
        if current_deck_id is None:
            return None

        verdict, _own_cards = _classify_own_deck(conn, current_deck_id, None, fmt=fmt)
        if verdict is None:
            return None

    since = None
    if reset is not None:
        since = window_start(reset)

    main_consensus = build_consensus(
        conn, verdict.key, fmt=fmt, min_decks=min_decks, since=since, min_wins=min_wins,
        board="main",
    )
    if main_consensus is None:
        return None
    # A separate consensus for the sideboard — comparing the player's own
    # sideboard against the field's *maindeck* staples would recommend
    # boarding in cards they already run (the bug this split fixes).
    # Missing entirely (e.g. a corpus source that never records sideboards)
    # is a real, empty consensus, not an error — every sideboard card then
    # reads as "flex" rather than the whole list diff failing.
    side_consensus = build_consensus(
        conn, verdict.key, fmt=fmt, min_decks=min_decks, since=since, min_wins=min_wins,
        board="side",
    ) or ArchetypeConsensus(
        archetype_key=verdict.key, deck_count=main_consensus.deck_count, cards=()
    )

    own_cards = identity.current_cards if cards is None else cards
    maindeck_ids = own_cards.get("maindeck") or []
    sideboard_ids = own_cards.get("sideboard") or []
    all_grp_ids = list({*maindeck_ids, *sideboard_ids})
    card_names = {
        row["grp_id"]: row["name"]
        for row in conn.execute(
            f"SELECT grp_id, name FROM cards WHERE grp_id IN "
            f"({','.join('?' for _ in all_grp_ids)})",
            all_grp_ids,
        )
    } if all_grp_ids else {}

    main_counts = Counter(maindeck_ids)
    side_counts = Counter(sideboard_ids)

    duplicate_warnings = _duplicate_warnings(
        main_consensus, conn, verdict.key, fmt=fmt, since=since, min_wins=min_wins, board="main",
    )
    for warning in _duplicate_warnings(
        side_consensus, conn, verdict.key, fmt=fmt, since=since, min_wins=min_wins, board="side",
    ):
        if warning not in duplicate_warnings:
            duplicate_warnings += (warning,)

    return ListDiff(
        archetype_key=verdict.key,
        archetype_name=verdict.name,
        winning_decks=main_consensus.deck_count,
        min_wins=min_wins,
        maindeck=_board_verdicts(main_counts, "main", main_consensus, card_names),
        sideboard=_board_verdicts(side_counts, "side", side_consensus, card_names),
        duplicate_warnings=duplicate_warnings,
    )
