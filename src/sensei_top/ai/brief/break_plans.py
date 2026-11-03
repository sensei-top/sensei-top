"""What the break read borrows from this package: ``table/intermission.py``'s
``BreakBriefProvider``, lent through ``sensei_top.ai.providers``.
"""

from __future__ import annotations

import sqlite3

from sensei_top.ai.brief.narrative import full_prompt
from sensei_top.ai.brief.store import is_stale, list_hash, read_brief
from sensei_top.guide.deck import DeckIdentity
from sensei_top.table.intermission import StoredPlan


class BreakBriefs:
    """``BreakBriefProvider`` over ``matchup_brief``; stateless, so one
    instance serves every app."""

    def plan(
        self, conn: sqlite3.Connection, identity: DeckIdentity, archetype_key: str
    ) -> StoredPlan | None:
        brief = read_brief(conn, identity.key, archetype_key)
        if brief is None:
            return None
        return StoredPlan(
            brief=brief,
            stale=is_stale(conn, brief, current_list_hash=list_hash(identity.current_cards)),
        )

    def prompt(
        self, conn: sqlite3.Connection, identity: DeckIdentity, archetype_key: str,
        label: str | None,
    ) -> str | None:
        """``full_prompt``'s text, the one ``/api/current-match/brief``
        offers too."""
        built = full_prompt(conn, identity, archetype_key, label)
        return built[0] if built is not None else None
