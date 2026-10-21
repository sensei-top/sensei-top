"""Marking twin tournament events in the metagame corpus: one tournament the
fbettega mirror published under two or more paths, with different
`event_id`s and blob SHAs but byte-identical decklists and rounds. See
docs/metagame.md, "Duplicate tournament events".

Two traps in the identity key:

1. **No date in it.** A Tier C league republished under a later date folder
   carries a later `Tournament.Date` too, so keying on `event_date` would
   let exactly that twin dodge detection.
2. **Rounds stay in it**, although decks alone usually suffice: a false
   merge would then need two events to agree on every round pairing as well
   as every decklist and record, and it is cheap: both tables are loaded
   once, up front.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3

log = logging.getLogger(__name__)


def mark_duplicate_events(conn: sqlite3.Connection) -> int:
    """Find and mark twin events, returning how many this call newly marked.

    1. Candidates are every `meta_event` with `duplicate_of IS NULL` that has
       at least one `meta_deck` row — an event with no decks has nothing to
       compare, and every empty event would otherwise share one key.
    2. Each candidate's key is a sha256 over `format`, `tier`, its decks
       (ordered by `deck_ord`) and its round matches (ordered by
       `(round_name, deck_ord_a, deck_ord_b, wins_a, wins_b, draws)`) —
       `name`, `event_date`, `source` and `uri` are excluded (docs/metagame.md,
       "Duplicate tournament events"). Decks and rounds are loaded with two
       ordered scans up front, not one query per candidate.
    3. Every group of more than one candidate keeps its lowest `event_id`;
       every other member is marked, has its `meta_deck`,
       `meta_round_match` and `meta_deck_archetype` rows deleted (every
       reader that joins those tables is then correct without a filter —
       see migration 043), and has any existing twin pointed at *it*
       repointed at the new survivor (chain collapse: a newly fetched event
       with a lower id can take over as survivor from a group an earlier
       call already marked).
    """
    candidates = conn.execute(
        "SELECT event_id, format, tier FROM meta_event WHERE duplicate_of IS NULL"
    ).fetchall()

    decks_by_event: dict[str, list[tuple]] = {}
    for row in conn.execute(
        """
        SELECT event_id, deck_ord, result, wins, losses, draws, mainboard_json, sideboard_json
          FROM meta_deck
         ORDER BY event_id, deck_ord
        """
    ):
        decks_by_event.setdefault(row["event_id"], []).append(
            (row["deck_ord"], row["result"], row["wins"], row["losses"], row["draws"],
             row["mainboard_json"], row["sideboard_json"])
        )

    rounds_by_event: dict[str, list[tuple]] = {}
    for row in conn.execute(
        """
        SELECT event_id, round_name, deck_ord_a, deck_ord_b, wins_a, wins_b, draws
          FROM meta_round_match
         ORDER BY event_id, round_name, deck_ord_a, deck_ord_b, wins_a, wins_b, draws
        """
    ):
        rounds_by_event.setdefault(row["event_id"], []).append(
            (row["round_name"], row["deck_ord_a"], row["deck_ord_b"],
             row["wins_a"], row["wins_b"], row["draws"])
        )

    groups: dict[str, list[str]] = {}
    for row in candidates:
        event_id = row["event_id"]
        decks = decks_by_event.get(event_id)
        if not decks:
            continue
        material = (row["format"], row["tier"], decks, rounds_by_event.get(event_id, []))
        digest = hashlib.sha256(json.dumps(material, separators=(",", ":")).encode()).hexdigest()
        groups.setdefault(digest, []).append(event_id)

    marked = 0
    conn.execute("BEGIN")
    try:
        for members in groups.values():
            if len(members) < 2:
                continue
            keep = min(members)
            for twin in members:
                if twin == keep:
                    continue
                conn.execute(
                    "UPDATE meta_event SET duplicate_of = ? WHERE event_id = ?", (keep, twin)
                )
                conn.execute("DELETE FROM meta_round_match WHERE event_id = ?", (twin,))
                conn.execute("DELETE FROM meta_deck_archetype WHERE event_id = ?", (twin,))
                conn.execute("DELETE FROM meta_deck WHERE event_id = ?", (twin,))
                conn.execute(
                    "UPDATE meta_event SET duplicate_of = ? WHERE duplicate_of = ?", (keep, twin)
                )
                log.info("metagame: event %s is a duplicate of %s", twin, keep)
                marked += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return marked
