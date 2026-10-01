"""Walking the tier ranking down to one quoted matchup number.

Two places in this project quote exactly one field win/loss record for a
single archetype pairing — the live brief's field-record line
(``brief/narrative.py``) and the match report's baseline finding
(``review/analyzers/baseline.py``). Both walk the ranked tiers rather than
reading one fixed tier: try the highest-ranked tier that carries rounds at
all first, and only reach for a lower one when the higher tier's sample is
too thin to trust — never blend two tiers into one number, since a blended
win rate would hide which tier it actually came from. The ranking itself —
what each tier is, and why it outranks the others — is ``docs/metagame.md``,
"The evidence tiers".

``MATCHUP_TIERS`` (``metagame/tiers.py``) is ``("A", "B", "D")`` — Tier C
never populates ``meta_round_match`` (a league dump has no losses, so there
are no rounds to record), so it is never a stop on this walk.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from sensei_top.metagame.tiers import MATCHUP_TIERS

# Mirrors web/src/theme.ts's MIN_TRUSTED_FIELD_SAMPLE: the floor below which
# the walk moves on to the next-ranked tier rather than quoting a thin one.
MIN_WALK_MATCHES = 5


@dataclass(frozen=True, slots=True)
class RankedMatchup:
    """One tier's own record for an archetype pairing — the result of the
    walk, never a blend of more than one tier."""

    tier: str
    n: int
    matches_won: int
    matches_lost: int


def ranked_field_matchup(
    conn: sqlite3.Connection,
    archetype_key: str,
    opponent_key: str,
    since: str | None,
    *,
    min_n: int = MIN_WALK_MATCHES,
) -> RankedMatchup | None:
    """Walk ``MATCHUP_TIERS`` in rank order and return the first tier whose
    round count for this pairing reaches ``min_n``. When none does, return
    the highest-ranked tier that has any rounds at all, however thin — a
    caller comparing ``n`` against its own, larger sample floor (this
    project's ``MIN_FIELD_SAMPLE`` is 20) still needs a tier to name in its
    "too few" gap. ``None`` only when the corpus has no rounds for this
    pairing in any of the three tiers.

    One query, grouped by tier, rather than one query per tier — the walk
    itself is pure Python over an already-fetched dict."""
    placeholders = ", ".join("?" for _ in MATCHUP_TIERS)
    rows = {
        row["tier"]: row
        for row in conn.execute(
            f"""
            SELECT tier, SUM(n) AS n, SUM(matches_won) AS matches_won,
                   SUM(matches_lost) AS matches_lost
              FROM v_meta_matchup
             WHERE archetype_key = ? AND opponent_key = ?
               AND tier IN ({placeholders})
               AND (? IS NULL OR event_date >= ?)
             GROUP BY tier
            """,
            (archetype_key, opponent_key, *MATCHUP_TIERS, since, since),
        )
    }

    first_with_rows: RankedMatchup | None = None
    for tier in MATCHUP_TIERS:
        row = rows.get(tier)
        if not row or not row["n"]:
            continue
        candidate = RankedMatchup(
            tier=tier, n=row["n"], matches_won=row["matches_won"] or 0,
            matches_lost=row["matches_lost"] or 0,
        )
        if first_with_rows is None:
            first_with_rows = candidate
        if candidate.n >= min_n:
            return candidate
    return first_with_rows
