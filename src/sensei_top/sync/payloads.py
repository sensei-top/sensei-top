"""One cloud-backup payload per match, built from the projected tables and the
two picks; ``GET /api/sync/payloads`` serves them (docs/architecture.md, "Cloud sync").

Contract:

- Every key a payload carries is a field the privacy policy lists for cloud
  backup ("What is uploaded for each match"); a new key is a policy change
  first. ``matches.opponent_name``, ``opponent_user_id``, ``self_seat``,
  ``deck_id`` and every raw event are never read here, so none of them can
  leak into a payload.
- Every Arena match is included; an MTGO match only once the user has
  picked its deck (``mtgo_match_pick.deck_id`` set, not a format alone).
- A card with no name in ``cards`` is left out of its list and counted in
  ``unknown_cards``, never guessed (rule 4): each deck copy (an MTGO deck's
  ``cards_json`` ``unresolved`` copies included) and each distinct opponent
  card. An Arena card event with no ``grp_id`` is a card nobody saw, so it is
  not counted.
- ``digest`` is SHA-256 over ``canonical_json(payload)``; it is the only
  change signal the caller keeps, so anything that moves a payload byte moves
  it.

Trap: ``started_at``/``ended_at`` are naive local time, the log's own clock,
so ``played_at`` is converted to UTC with the machine's zone *now*. Changing
the machine's zone changes every ``played_at``, so every digest, and the
whole history is pushed again.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

__all__ = ["SCHEMA_VERSION", "MatchPayload", "build_payloads", "canonical_json"]

SCHEMA_VERSION = 1

_PLAY, _DRAW = "play", "draw"
# SQLite's default host-parameter ceiling is far above this; a fixed chunk
# keeps one query's IN list bounded however many cards a history holds.
_CHUNK = 500


@dataclass(frozen=True, slots=True)
class MatchPayload:
    match_id: str
    source: str
    played_at: str | None
    digest: str
    payload: dict[str, Any]


def canonical_json(payload: dict[str, Any]) -> str:
    """The exact text the digest is taken over: sorted keys, no whitespace,
    UTF-8 kept as is."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _utc(text: str | None) -> datetime | None:
    """A stored timestamp as an aware UTC datetime: naive text is read as the
    machine's local time (the module docstring's trap). ``None`` when missing
    or unreadable."""
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment.astimezone(UTC)


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _duration(started: datetime | None, ended: datetime | None) -> int | None:
    if started is None or ended is None or ended < started:
        return None
    return int((ended - started).total_seconds())


def _is_token(type_line: str | None) -> bool:
    """A token is not a card the opponent showed. Read on the front face's
    type, the part before the dash, as ``v_opponent_cards`` does."""
    if not type_line:
        return False
    return "Token" in type_line.split("—", 1)[0].split()


def _names(conn: sqlite3.Connection, grp_ids: Iterable[int]) -> dict[int, str]:
    wanted = sorted(set(grp_ids))
    names: dict[int, str] = {}
    for start in range(0, len(wanted), _CHUNK):
        chunk = wanted[start:start + _CHUNK]
        rows = conn.execute(
            f"SELECT grp_id, name FROM cards WHERE grp_id IN ({','.join('?' * len(chunk))})",
            chunk,
        )
        names.update((row[0], row[1]) for row in rows)
    return names


def _deck_cards(cards_json: str | None) -> tuple[list[int], list[int], int]:
    """``(maindeck grp_ids, sideboard grp_ids, unresolved copies)`` from a
    ``decks.cards_json``; an unreadable one reads as empty."""
    try:
        cards = json.loads(cards_json) if cards_json else {}
    except json.JSONDecodeError:
        return [], [], 0
    if not isinstance(cards, dict):
        return [], [], 0
    unresolved = cards.get("unresolved") or {}
    left_out = sum(int(unresolved.get(board) or 0) for board in ("maindeck", "sideboard"))
    return (
        [int(g) for g in cards.get("maindeck") or []],
        [int(g) for g in cards.get("sideboard") or []],
        left_out,
    )


def _board(grp_ids: list[int], names: dict[int, str]) -> tuple[list[list[Any]], int]:
    """``[[name, count]]`` by name, printings of one name merged, and the
    copies with no name."""
    counts: Counter[str] = Counter()
    unknown = 0
    for grp_id in grp_ids:
        name = names.get(grp_id)
        if name is None:
            unknown += 1
        else:
            counts[name] += 1
    return [[name, counts[name]] for name in sorted(counts)], unknown


def _opponent_cards(conn: sqlite3.Connection) -> dict[str, tuple[list[str], int]]:
    """Per match, the opponent's distinct card names and how many distinct
    cards they showed that have no name. An MTGO card the projector could not
    resolve keeps ``grp_id`` NULL and its transcript name in ``mtgo_name``;
    that name is used only to tell one unknown card from another."""
    seen: dict[str, set[str]] = {}
    unknown: dict[str, set[str]] = {}
    rows = conn.execute(
        """
        SELECT DISTINCT ce.match_id, ce.grp_id, ce.mtgo_name, c.name, c.type_line
          FROM card_events ce
          JOIN matches m    ON m.match_id = ce.match_id
          LEFT JOIN cards c ON c.grp_id = ce.grp_id
         WHERE ce.seat = m.opponent_seat
           AND (ce.grp_id IS NOT NULL OR ce.mtgo_name IS NOT NULL)
        """
    )
    for match_id, grp_id, mtgo_name, name, type_line in rows:
        if name is not None:
            if not _is_token(type_line):
                seen.setdefault(match_id, set()).add(name)
        else:
            key = f"g:{grp_id}" if grp_id is not None else f"n:{mtgo_name}"
            unknown.setdefault(match_id, set()).add(key)
    return {
        match_id: (sorted(seen.get(match_id, ())), len(unknown.get(match_id, ())))
        for match_id in seen.keys() | unknown.keys()
    }


_MATCHES = """
    SELECT m.match_id, m.source, m.event_id, m.started_at, m.ended_at, m.result,
           m.games_won, m.games_lost, m.best_of,
           f.format, d.name AS deck_name, d.cards_json, md.deck_id IS NOT NULL AS has_deck,
           o.opponent_label, o.opponent_key, o.opponent_source,
           (SELECT g.on_play FROM games g
             WHERE g.match_id = m.match_id AND g.game_number = 1) AS game1_on_play,
           op.label AS opp_pick_label, op.archetype_key AS opp_pick_key,
           op.updated_at AS opp_pick_at,
           mp.format AS mtgo_pick_format, mp.updated_at AS mtgo_pick_at
      FROM matches m
      JOIN v_match_deck md                ON md.match_id = m.match_id
      LEFT JOIN v_match_format f          ON f.match_id = m.match_id
      LEFT JOIN decks d                   ON d.deck_id = md.deck_id
      LEFT JOIN v_match_opponent o        ON o.match_id = m.match_id
      LEFT JOIN opponent_deck_override op ON op.match_id = m.match_id
      LEFT JOIN mtgo_match_pick mp        ON mp.match_id = m.match_id AND m.source = 'mtgo'
     WHERE m.source <> 'mtgo' OR mp.deck_id IS NOT NULL
     ORDER BY COALESCE(m.started_at, ''), m.match_id
"""


def build_payloads(conn: sqlite3.Connection) -> list[MatchPayload]:
    """Every backed-up match's payload, oldest first. Reads only, so a
    ``query_only`` connection serves it; any ``row_factory`` will do."""
    cursor = conn.execute(_MATCHES)
    columns = [column[0] for column in cursor.description]
    rows = [dict(zip(columns, row, strict=True)) for row in cursor]
    decks = {row["match_id"]: _deck_cards(row["cards_json"]) for row in rows}
    names = _names(conn, (g for main, side, _ in decks.values() for g in (*main, *side)))
    opponent = _opponent_cards(conn)

    payloads: list[MatchPayload] = []
    for row in rows:
        match_id = row["match_id"]
        deck = None
        unknown = 0
        if row["has_deck"]:
            main_ids, side_ids, unknown = decks[match_id]
            main, main_unknown = _board(main_ids, names)
            side, side_unknown = _board(side_ids, names)
            unknown += main_unknown + side_unknown
            deck = {"name": row["deck_name"], "main": main, "side": side}
        opp_cards, opp_unknown = opponent.get(match_id, ([], 0))
        on_play = row["game1_on_play"]
        started, ended = _utc(row["started_at"]), _utc(row["ended_at"])
        played_at = _iso(started)
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "played_at": played_at,
            "event": row["event_id"],
            "format": row["format"],
            "best_of": row["best_of"],
            "deck": deck,
            "result": row["result"],
            "won": row["games_won"],
            "lost": row["games_lost"],
            "play": None if on_play is None else (_PLAY if on_play else _DRAW),
            # "unknown" is the view's placeholder ('Unknown deck'), not a name
            # the app gave the opponent's deck.
            "opp": (
                None if row["opponent_source"] in (None, "unknown")
                else {"label": row["opponent_label"], "key": row["opponent_key"]}
            ),
            "opp_cards": opp_cards,
            # An MTGO match's started_at is when its log was first seen, not when
            # it began (near its end for a back-filled one), so no duration.
            "duration_s": None if row["source"] == "mtgo" else _duration(started, ended),
            "unknown_cards": unknown + opp_unknown,
            "picks": {
                "opp": None if row["opp_pick_label"] is None else {
                    "label": row["opp_pick_label"],
                    "archetype_key": row["opp_pick_key"],
                    "updated_at": row["opp_pick_at"],
                },
                "mtgo": None if row["mtgo_pick_at"] is None else {
                    "format": row["mtgo_pick_format"],
                    "updated_at": row["mtgo_pick_at"],
                },
            },
        }
        payloads.append(
            MatchPayload(
                match_id=match_id,
                source=row["source"],
                played_at=played_at,
                digest=_digest(payload),
                payload=payload,
            )
        )
    return payloads
