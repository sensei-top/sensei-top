"""Deck identity, stitched across list edits.

``decks.deck_id`` is a content hash of the maindeck
(``projector/matches.py``'s ``deck_identity``), so one Arena deck — the same
GUID the client itself uses — mints a new row every time a single card
changes. ``deck_guids`` records that stable GUID beside each content hash
and is written on every match.

The grouping itself lives in ``v_deck_identity`` (migration 033), a SQL view
``/api/metrics/winrate`` reads too, so the two can never disagree.
The view resolves each content hash to exactly one identity
(tie-broken by ``deck_guids.last_seen``, so a hash registered under two Arena
decks is not double-counted) — this module just reads it and attaches match
records, names and current cards.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


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


def _record(conn: sqlite3.Connection, deck_ids: tuple[str, ...]) -> dict:
    if not deck_ids:
        return {
            "matches": 0, "match_wins": 0, "match_losses": 0,
            "games_won": 0, "games_lost": 0, "first_played": None, "last_played": None,
        }
    placeholders = ",".join("?" for _ in deck_ids)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS matches,
               SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS match_wins,
               SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS match_losses,
               SUM(COALESCE(games_won, 0)) AS games_won,
               SUM(COALESCE(games_lost, 0)) AS games_lost,
               MIN(started_at) AS first_played,
               MAX(started_at) AS last_played
          FROM matches
         WHERE deck_id IN ({placeholders})
        """,
        deck_ids,
    ).fetchone()
    return {
        "matches": row["matches"] or 0,
        "match_wins": row["match_wins"] or 0,
        "match_losses": row["match_losses"] or 0,
        "games_won": row["games_won"] or 0,
        "games_lost": row["games_lost"] or 0,
        "first_played": row["first_played"],
        "last_played": row["last_played"],
    }


def _current_cards(conn: sqlite3.Connection, deck_ids: tuple[str, ...]) -> dict:
    """The maindeck/sideboard of whichever version was played most recently —
    not ``decks.last_seen``, which the projector never actually updates past
    the first match it sees for a deck (``projector/matches.py``'s
    ``seen_decks`` guard leaves its ``ON CONFLICT`` branch unreachable)."""
    if not deck_ids:
        return {}
    placeholders = ",".join("?" for _ in deck_ids)
    row = conn.execute(
        f"""
        SELECT d.cards_json
          FROM decks d
          JOIN matches m ON m.deck_id = d.deck_id
         WHERE d.deck_id IN ({placeholders})
         GROUP BY d.deck_id
         ORDER BY MAX(m.started_at) DESC
         LIMIT 1
        """,
        deck_ids,
    ).fetchone()
    if row is None:
        return {}
    try:
        return json.loads(row["cards_json"])
    except json.JSONDecodeError:
        return {}


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

    identities: list[DeckIdentity] = []
    for deck_key, deck_ids in groups.items():
        deck_ids_t = tuple(sorted(deck_ids))
        rec = _record(conn, deck_ids_t)
        if rec["matches"] == 0:
            continue
        # Most recently played version's format, consistent with deck_name
        # (v_deck_identity picks the same version's name).
        placeholders = ",".join("?" for _ in deck_ids_t)
        fmt_row = conn.execute(
            f"""
            SELECT d.format
              FROM decks d
              JOIN matches m ON m.deck_id = d.deck_id
             WHERE d.deck_id IN ({placeholders})
             GROUP BY d.deck_id
             ORDER BY MAX(m.started_at) DESC
             LIMIT 1
            """,
            deck_ids_t,
        ).fetchone()
        identities.append(DeckIdentity(
            key=deck_key,
            arena_deck_id=lookup[deck_key]["arena_deck_id"],
            name=lookup[deck_key]["name"],
            format=fmt_row["format"] if fmt_row else None,
            deck_ids=deck_ids_t,
            current_cards=_current_cards(conn, deck_ids_t),
            **rec,
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
