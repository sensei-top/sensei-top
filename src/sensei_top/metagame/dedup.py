"""Marking twin tournament events in the metagame corpus.

The fbettega/MTG_decklistcache mirror sometimes publishes one tournament
under two or three paths — different `event_id`s (the path) and different
blob SHAs, but byte-identical decklists and rounds. Nothing upstream of this
module dedups, so every copy is stored and counted again, inflating field
share, field win rate, the consensus decklists and the matchup matrix
everywhere they are read.

Measured on the real database (2026-09, 371 events / 12,170 decks): 43
groups of identical events — 35 pairs, 7 triples, 1 quadruple — that is 52
surplus events and 1,338 surplus decks (11% of the corpus). By tier: 32
groups Tier B (MTGO challenges), 10 Tier C (leagues), 1 Tier A (tiers as
they were before migration 047). By source: 41 MTGO, 2 MTGmelee. In all 43
groups the rounds (`meta_round_match`) were identical too, on top of the
decks.

**Why no date or name in the identity key.** 33 of the 43 groups share their
event date, but the other 10 do not: all Tier C leagues, republished under a
later date folder (e.g. `.../2026/06/08/standard-league-2026-06-0810660.json`
and `.../2026/06/10/standard-league-2026-06-0810660.json`), whose
`Tournament.Date` differs too — a re-publish, not a new event. So `event_date`
cannot be part of the key: including it would let a republished league dodge
detection entirely. The event `name` was checked and makes no difference to
the grouping either way, so it is left out along with `source` and `uri` —
once the standings match, a cross-source twin (the same tournament mirrored
under both MTGO and MTGmelee paths) is still a twin.

**Why rounds are in the key even though decks alone are usually enough.**
Comparing round matches too makes the key stricter than strictly needed, but
that is deliberate: it is cheap (the two tables are loaded once, up front)
and it means a false-positive merge would require an MTGO challenge and its
would-be twin to agree not just on every player's decklist and record, but
on every round pairing too.

**The survivor.** `keep = min(event_id)` in each group. `event_id` is the
file's own path, which sorts by date folder first, so this is always the
group's earliest publication — deterministic without needing to know which
copy the source repository considers canonical.
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
       `(round_name, deck_ord_a, deck_ord_b, wins_a, wins_b, draws)`) — see
       this module's docstring for why `name`/`event_date`/`source`/`uri`
       are excluded. Decks and rounds are loaded with two ordered scans up
       front, not one query per candidate.
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
