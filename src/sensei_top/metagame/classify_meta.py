"""Naming every stored tournament decklist's archetype — the field side of
the personal-vs-field matchup join.

Reuses ``archetypes.classify``'s rule engine in its ``complete=True`` mode
(see that module's docstring on the governing asymmetry, and this project's
own inversion of it for a full decklist): a cache decklist is 60 cards plus a
real sideboard, not a dozen revealed cards, so absence is real evidence and
the same ``Definition`` objects that classify a personal match classify a
corpus decklist too — one rule vocabulary, one place to fix a bug, and one
``archetype_key`` both sides can join on.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime

from sensei_top.archetypes.classify import (
    _card_colors,
    _card_colors_by_name,
    _load_definitions,
    _seen_forms,
    choose,
)

log = logging.getLogger(__name__)


def _colors_of(mainboard_names: list[str], colors_by_name: dict[str, frozenset[str]]) -> str:
    """WUBRG letters actually present among a deck's own cards, from known
    colour identities only — never guessed for a card whose identity we do
    not have on file (rule 4)."""
    present: set[str] = set()
    for name in mainboard_names:
        if (card_colors := _card_colors(name, colors_by_name)) is not None:
            present |= card_colors
    return "".join(letter for letter in "WUBRG" if letter in present)


def classify_meta_decks(conn: sqlite3.Connection) -> dict[str, int]:
    """Classify every stored corpus decklist. Recomputed in full, like
    ``classify_matches`` — a corpus refresh may replace a decklist's own row,
    so a classification kept from a previous run could point at a deck that
    no longer exists.
    """
    definitions = _load_definitions(conn)
    colors_by_name = _card_colors_by_name(conn)
    counts = {"classified": 0, "unclassified": 0, "skipped_format": 0}
    # Event format strings are free text upstream; match them to the stored
    # definitions' spelling case-insensitively. A format with no definitions
    # (Premodern) is counted under skipped_format, never warned about per deck.
    by_format = {name.lower(): defs for name, defs in definitions.items()}

    rows = []
    classified_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for deck_row in conn.execute(
        """
        SELECT d.event_id, d.deck_ord, d.mainboard_json, d.sideboard_json, e.format
          FROM meta_deck d JOIN meta_event e ON e.event_id = d.event_id
        """
    ):
        fmt = (deck_row["format"] or "").lower()
        if fmt not in by_format:
            counts["skipped_format"] += 1
            continue

        try:
            mainboard = json.loads(deck_row["mainboard_json"])
            sideboard = json.loads(deck_row["sideboard_json"])
        except json.JSONDecodeError:
            counts["unclassified"] += 1
            continue

        main_names = [c["name"] for c in mainboard if isinstance(c, dict) and "name" in c]
        side_names = [c["name"] for c in sideboard if isinstance(c, dict) and "name" in c]
        seen = _seen_forms(main_names)
        sideboard_seen = _seen_forms(side_names)
        colors = _colors_of(main_names, colors_by_name)

        verdict = choose(
            by_format[fmt]["archetype"], by_format[fmt]["fallback"], seen, colors,
            colors_by_name, cards_seen=len(main_names),
            complete=True, sideboard_seen=sideboard_seen,
        )
        if verdict is None:
            counts["unclassified"] += 1
            continue

        counts["classified"] += 1
        rows.append(
            (deck_row["event_id"], deck_row["deck_ord"], verdict.key, verdict.name, colors,
             verdict.name, verdict.method, classified_at)
        )

    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM meta_deck_archetype")
        conn.executemany(
            """
            INSERT INTO meta_deck_archetype
                 (event_id, deck_ord, archetype_key, archetype_name, colors, label,
                  method, classified_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return counts
