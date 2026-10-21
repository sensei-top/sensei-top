"""Sideboard diffing: resolving a grpId-count delta between two decklists
into named cards. Shared by the post-match ``/api/matches/{id}/sideboarding``
route and the live break read (``table/intermission.py``); it lives in
``table/`` because ``table/`` must never import from ``api/``.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any


def named_diff(
    conn: sqlite3.Connection, before: Counter, after: Counter
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(cards_in, cards_out) between two grpId->count counters, names
    resolved in one query. A card whose count only partially changed (3 of 4
    copies swapped) reports the net difference, same as any other diff."""
    changed = {
        grp_id
        for grp_id in set(before) | set(after)
        if before.get(grp_id, 0) != after.get(grp_id, 0)
    }
    if not changed:
        return [], []
    names = [
        dict(row)
        for row in conn.execute(
            f"SELECT grp_id, name FROM cards WHERE grp_id IN ({','.join('?' * len(changed))})",
            tuple(changed),
        )
    ]
    name_by_id = {row["grp_id"]: row["name"] for row in names}
    cards_in, cards_out = [], []
    for grp_id in changed:
        delta = after.get(grp_id, 0) - before.get(grp_id, 0)
        entry = {"grp_id": grp_id, "card": name_by_id.get(grp_id), "n": abs(delta)}
        (cards_in if delta > 0 else cards_out).append(entry)
    cards_in.sort(key=lambda c: c["card"] or "")
    cards_out.sort(key=lambda c: c["card"] or "")
    return cards_in, cards_out
