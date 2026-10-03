"""What an archetype's decklist typically looks like, from the metagame
corpus (``metagame/``) — the *Thoughtseize You* view: knowing an opponent's
consensus staples is what makes "what was still live" a real computation
instead of a guess.

Presence is licensed for every evidence tier (``docs/metagame.md``): a
consensus card list answers "what fraction of decks play this", never a win
rate, so it may read Tier C (MTGO league) decks too — the survivorship bias
that makes a league's *share* misleading says nothing about whether a card
appears in a winning list at all. Win rates stay gated to Tier A/B/D by
``v_meta_winrate`` alone; this module never touches that view.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from sensei_top.archetypes.classify import normalize
from sensei_top.review import effects


@dataclass(frozen=True, slots=True)
class ConsensusCard:
    """One card's presence across every stored decklist for one archetype.

    ``copies`` is the average count *in decks that run it at all* (not
    diluted by decks that skip it) — the number that answers "if they have
    it, how many". ``share`` answers "how many of their decks have it".
    ``tags`` is ``effects.classify``'s output for this card, or the literal
    string ``"unknown"`` when it was never named (rule 4) — see that
    module's own docstring for what "unknown" versus an empty tag set means.
    ``type_line`` is ``None`` when the name never matched a stored ``cards``
    row (the same gap ``tags`` already accounts for) — callers reading a
    creature rate from this list, like ``review/analyzers/frame.py``, must
    treat that as unknown, not as "not a creature". ``mana_cost`` carries the
    same ``None``-when-unmatched gap, for a caller (``table/hand_read.py``)
    that needs a mana value to judge instant-speed castability.
    """

    name: str
    grp_id: int | None
    type_line: str | None
    decks_with_card: int
    copies: float
    share: float
    tags: frozenset[str] | str
    mana_cost: str | None = None


@dataclass(frozen=True, slots=True)
class ArchetypeConsensus:
    archetype_key: str
    deck_count: int
    cards: tuple[ConsensusCard, ...]

    def staples(self, *, min_share: float = 0.5) -> tuple[ConsensusCard, ...]:
        """Cards run in at least ``min_share`` of the corpus's decks for this
        archetype — the "if you know the archetype, you know this card is
        coming" list Duke's hole-finding method needs."""
        return tuple(c for c in self.cards if c.share >= min_share)

    def copies_of(self, name_lower: str) -> float:
        """Average copies for one card, by lower-cased name; 0.0 if the
        archetype's corpus never ran it — a real zero, since ``cards`` here
        is already the full set of every card seen in any stored decklist
        for this archetype, not a partial sample."""
        for c in self.cards:
            if c.name.casefold() == name_lower:
                return c.copies
        return 0.0


def _card_rows_by_name(conn: sqlite3.Connection, names: list[str]) -> dict[str, sqlite3.Row]:
    """Map each corpus decklist name to its ``cards`` row, matching through
    every legitimate written form of the name (``archetypes.classify.
    normalize``) rather than exact equality.

    A real-world MTGO/MTGmelee decklist names an adventure or split card by
    its front face alone (``"Hearth Elemental"``), while Arena's own card
    database — where this project's ``cards`` table gets its names — stores
    the combined name (``"Hearth Elemental // Stoke Genius"``). An exact
    match misses every one of these, which silently produced ``tags =
    "unknown"`` for a card whose text was on file all along, under a name
    one join away. A name with no counterpart in ``cards`` at all still
    resolves to nothing here, same as before — rule 4 is unaffected, only
    the *reach* of a real match is.
    """
    if not names:
        return {}
    # A name spans several grp_ids (one per printing/art variant), and not
    # every printing in Scryfall's own export carries oracle_text — verified:
    # of several dozen real "Island" rows in a live download, exactly one
    # had it. ORDER BY puts a row with text first, so the dict comprehensions
    # below (last-write-wins / setdefault) keep a populated printing over a
    # blank one whenever either exists.
    direct = conn.execute(
        f"SELECT name, grp_id, type_line, oracle_text, mana_cost, oracle_id FROM cards "
        f"WHERE name IN ({','.join('?' for _ in names)}) ORDER BY oracle_text IS NULL",
        names,
    ).fetchall()
    by_exact_name = {r["name"]: r for r in reversed(direct)}

    missing = [n for n in names if n not in by_exact_name]
    if not missing:
        return by_exact_name

    # A missing name may be one face of a combined Arena name — broaden the
    # search to every card whose name uses a multi-face separator, and match
    # through normalize()'s forms instead of the raw string.
    combined = conn.execute(
        "SELECT name, grp_id, type_line, oracle_text, mana_cost, oracle_id FROM cards "
        "WHERE name LIKE '%//%' ORDER BY oracle_text IS NULL"
    ).fetchall()
    by_form: dict[str, sqlite3.Row] = {}
    for row in reversed(combined):
        for form in normalize(row["name"]):
            by_form[form] = row  # last-write-wins, same text-preferring order as above

    result = dict(by_exact_name)
    for name in missing:
        for form in normalize(name):
            if form in by_form:
                result[name] = by_form[form]
                break
    return result


def build_consensus(
    conn: sqlite3.Connection,
    archetype_key: str,
    *,
    min_decks: int = 5,
    since: str | None = None,
    min_wins: int | None = None,
    tiers: tuple[str, ...] | None = None,
    board: str = "main",
) -> ArchetypeConsensus | None:
    """Aggregate every stored ``meta_deck`` classified as ``archetype_key``.

    Returns ``None`` below ``min_decks`` — the same sample-gating discipline
    ``PLAY_DRAW_MIN_GAMES`` already uses elsewhere in this package: a
    consensus list from 2 decklists is not a consensus, it is 2 decklists.
    Costs one scan of ``meta_deck``; callers needing this more than once
    per request should cache it themselves rather than this module caching
    silently underneath them.

    ``since``/``min_wins``/``tiers`` narrow the corpus to, respectively,
    events on or after a date, decks with at least that many recorded wins,
    and a set of evidence tiers (``docs/metagame.md``) — added for
    ``guide/``'s "consensus among winning post-reset lists" question. For a
    Tier C deck (a league) every stored record already reads as a win
    (``d.result`` is always ``"5-0"``), so ``min_wins`` is a no-op there by
    construction, not by a special case here.

    ``board`` selects ``"main"`` (the default, and every caller before
    ``guide/`` ever needed only this — role assignment reads an opponent's
    likely *maindeck*, not their sideboard) or ``"side"``. The two boards
    are entirely different card pools reported separately, never merged:
    comparing a player's own sideboard against the field's *maindeck*
    consensus would recommend they board in cards they already run.

    Card names are canonicalised on ``cards.oracle_id`` where it is known
    for *every* name being merged — the fix for one card counted under two
    Universes Beyond printings (see ``migrations/017_card_legality.sql``).
    A name with no ``oracle_id`` on file is left alone rather than merged.
    """
    json_field = "mainboard_json" if board == "main" else "sideboard_json"
    clauses = ["da.archetype_key = ?"]
    params: list = [archetype_key]
    if since is not None:
        clauses.append("e.event_date >= ?")
        params.append(since)
    if min_wins is not None:
        clauses.append("d.wins >= ?")
        params.append(min_wins)
    if tiers is not None:
        clauses.append(f"e.tier IN ({','.join('?' for _ in tiers)})")
        params.extend(tiers)

    rows = conn.execute(
        f"""
        SELECT d.{json_field} AS board_json
          FROM meta_deck d
          JOIN meta_deck_archetype da ON da.event_id = d.event_id AND da.deck_ord = d.deck_ord
          JOIN meta_event e ON e.event_id = d.event_id
         WHERE {' AND '.join(clauses)}
        """,
        params,
    ).fetchall()
    if len(rows) < min_decks:
        return None

    # name -> [total copies across decks that ran it, decks that ran it]
    totals: dict[str, list[int]] = {}
    for row in rows:
        try:
            mainboard = json.loads(row["board_json"])
        except json.JSONDecodeError:
            continue
        per_deck: dict[str, int] = {}
        for entry in mainboard:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            count = entry.get("count") or entry.get("quantity") or 1
            if not isinstance(name, str):
                continue
            per_deck[name] = per_deck.get(name, 0) + int(count)
        for name, count in per_deck.items():
            bucket = totals.setdefault(name, [0, 0])
            bucket[0] += count
            bucket[1] += 1

    names = list(totals)
    by_name = _card_rows_by_name(conn, names)

    # oracle_id -> canonical name, chosen as whichever spelling has the most
    # total copies so the merged card keeps its dominant printing's name.
    oracle_id_totals: dict[str, list[tuple[str, int]]] = {}
    for name, (total_copies, _) in totals.items():
        found = by_name.get(name)
        oid = found["oracle_id"] if found is not None else None
        if oid:
            oracle_id_totals.setdefault(oid, []).append((name, total_copies))
    canonical_name: dict[str, str] = {}
    for _oid, entries in oracle_id_totals.items():
        if len(entries) < 2:
            continue
        best = max(entries, key=lambda pair: pair[1])[0]
        for name, _ in entries:
            canonical_name[name] = best

    merged: dict[str, list[int]] = {}
    for name, (total_copies, decks_with_card) in totals.items():
        target = canonical_name.get(name, name)
        bucket = merged.setdefault(target, [0, 0])
        bucket[0] += total_copies
        bucket[1] += decks_with_card

    cards = []
    deck_count = len(rows)
    for name, (total_copies, decks_with_card) in merged.items():
        found = by_name.get(name)
        tags = (
            effects.classify(found["oracle_text"], found["type_line"], found["mana_cost"])
            if found is not None
            else effects.UNKNOWN
        )
        cards.append(
            ConsensusCard(
                name=name,
                grp_id=found["grp_id"] if found is not None else None,
                type_line=found["type_line"] if found is not None else None,
                decks_with_card=decks_with_card,
                copies=total_copies / decks_with_card,
                share=decks_with_card / deck_count,
                tags=tags.tags if isinstance(tags, effects.EffectTags) else tags,
                mana_cost=found["mana_cost"] if found is not None else None,
            )
        )
    cards.sort(key=lambda c: (-c.share, -c.copies, c.name))
    return ArchetypeConsensus(
        archetype_key=archetype_key, deck_count=deck_count, cards=tuple(cards)
    )
