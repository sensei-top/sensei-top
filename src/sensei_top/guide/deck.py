"""Deck identity, stitched across list edits: one Arena deck mints a new
``decks`` row every time a maindeck card changes, and the SQL view
``v_deck_identity`` (which ``/api/metrics/winrate`` reads too, so the two
never disagree) groups them back by Arena's GUID. This module reads that view and attaches match
records, names and current cards; ``deck_format`` is the format the guide
and the brief read the field under. See docs/guide.md,
"`deck.py` — deck identity, stitched across list edits".
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from sensei_top.formats import deck_format_name


@dataclass(frozen=True, slots=True)
class DeckIdentity:
    key: str  # "guid:<arena_deck_id>" or "deck:<deck_id>" — the API path segment
    arena_deck_id: str | None
    name: str | None
    format: str | None
    deck_ids: tuple[str, ...]
    matches: int
    match_wins: int
    match_losses: int
    games_won: int
    games_lost: int
    first_played: str | None
    last_played: str | None
    current_cards: dict  # decks.cards_json of the most recently played version


def _played_per_deck(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Every played deck id's record and its ``decks`` row, from one pass over
    ``matches`` joined to ``v_match_deck`` on ``match_id``: the deck as the user
    has it, so an MTGO match counts under the deck its pick names (its
    ``matches.deck_id`` is NULL). A ``LEFT JOIN`` to ``decks``, so a played deck
    id with no ``decks`` row still has its record, and no cards or format.

    One pass, not a scan of ``matches`` per identity: nothing indexes the
    view's COALESCEd ``deck_id`` (migration 050's header).
    """
    return {
        row["deck_id"]: row
        for row in conn.execute(
            """
            SELECT md.deck_id,
                   COUNT(*) AS matches,
                   SUM(CASE WHEN m.result = 'win' THEN 1 ELSE 0 END) AS match_wins,
                   SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) AS match_losses,
                   SUM(COALESCE(m.games_won, 0)) AS games_won,
                   SUM(COALESCE(m.games_lost, 0)) AS games_lost,
                   MIN(m.started_at) AS first_played,
                   MAX(m.started_at) AS last_played,
                   d.format AS format,
                   d.cards_json AS cards_json
              FROM matches m
              JOIN v_match_deck md ON md.match_id = m.match_id
              LEFT JOIN decks d ON d.deck_id = md.deck_id
             WHERE md.deck_id IS NOT NULL
             GROUP BY md.deck_id
            """
        )
    }


def list_identities(conn: sqlite3.Connection) -> list[DeckIdentity]:
    """Every deck the player has played, one row per ``v_deck_identity``
    key (``guid:<arena_deck_id>``, or ``deck:<deck_id>`` for a deck_id with
    no ``deck_guids`` row at all), newest-played first."""
    groups: dict[str, set[str]] = {}
    lookup: dict[str, dict] = {}
    for row in conn.execute(
        "SELECT deck_id, deck_key, arena_deck_id, deck_name FROM v_deck_identity"
    ):
        groups.setdefault(row["deck_key"], set()).add(row["deck_id"])
        lookup[row["deck_key"]] = {
            "arena_deck_id": row["arena_deck_id"],
            "name": row["deck_name"],
        }

    played = _played_per_deck(conn)

    identities: list[DeckIdentity] = []
    for deck_key, deck_ids in groups.items():
        deck_ids_t = tuple(sorted(deck_ids))
        versions = [played[d] for d in deck_ids_t if d in played]
        matches = sum(v["matches"] for v in versions)
        if matches == 0:
            continue
        starts = [v["first_played"] for v in versions if v["first_played"] is not None]
        ends = [v["last_played"] for v in versions if v["last_played"] is not None]
        # The most recently played version that has a decks row: its cards are
        # the current list and its format the deck's, consistent with deck_name
        # (v_deck_identity picks the same version's name). Ties go to the
        # smaller deck id, which deck_ids_t's order already puts first.
        # "Most recently played" is matches.started_at, not decks.last_seen: the
        # projector's seen_decks guard (projector/matches.py) never updates
        # last_seen past a deck's first match.
        newest = max(
            (v for v in versions if v["cards_json"] is not None),
            key=lambda v: v["last_played"] or "",
            default=None,
        )
        current_cards: dict = {}
        if newest is not None:
            try:
                current_cards = json.loads(newest["cards_json"])
            except json.JSONDecodeError:
                current_cards = {}
        identities.append(DeckIdentity(
            key=deck_key,
            arena_deck_id=lookup[deck_key]["arena_deck_id"],
            name=lookup[deck_key]["name"],
            format=newest["format"] if newest is not None else None,
            deck_ids=deck_ids_t,
            current_cards=current_cards,
            matches=matches,
            match_wins=sum(v["match_wins"] or 0 for v in versions),
            match_losses=sum(v["match_losses"] or 0 for v in versions),
            games_won=sum(v["games_won"] or 0 for v in versions),
            games_lost=sum(v["games_lost"] or 0 for v in versions),
            first_played=min(starts) if starts else None,
            last_played=max(ends) if ends else None,
        ))

    identities.sort(key=lambda d: d.last_played or "", reverse=True)
    return identities


def resolve(conn: sqlite3.Connection, key: str) -> DeckIdentity | None:
    """One identity by its API key, found by scanning ``list_identities``'s
    own result, so the two can never disagree. Costs a full
    ``list_identities`` call — no cheaper than that."""
    for identity in list_identities(conn):
        if identity.key == key:
            return identity
    return None


def identity_format(conn: sqlite3.Connection, identity: DeckIdentity) -> str | None:
    """``identity``'s format: its ``decks.format`` as one of
    ``formats.FORMATS`` (``TraditionalStandard`` is Standard; Draft and every
    other non-constructed spelling is nothing), else the format most of its
    matches resolve to in ``v_match_format`` (log, pick, then inference), else
    ``None``.

    A tie between two formats goes to the one played most recently, then to
    the lower name, so the answer never depends on row order. A match with no
    resolved format does not count toward any.
    """
    named = deck_format_name(identity.format)
    if named is not None or not identity.deck_ids:
        return named
    row = conn.execute(
        f"""
        SELECT f.format
          FROM v_match_format f
          JOIN v_match_deck md ON md.match_id = f.match_id
          JOIN matches m ON m.match_id = f.match_id
         WHERE md.deck_id IN ({','.join('?' for _ in identity.deck_ids)})
           AND f.format IS NOT NULL
         GROUP BY f.format
         ORDER BY COUNT(*) DESC, MAX(m.started_at) DESC, f.format
         LIMIT 1
        """,
        identity.deck_ids,
    ).fetchone()
    return row["format"] if row is not None else None


def deck_format(conn: sqlite3.Connection, key: str) -> str | None:
    """The format of the deck with API key ``key`` (``identity_format``),
    or ``None`` for an unknown key or a deck nothing names a format for."""
    identity = resolve(conn, key)
    if identity is None:
        return None
    return identity_format(conn, identity)
