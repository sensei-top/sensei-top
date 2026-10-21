"""Backfill the brief cache from a deck guide's narrative, for free: each
``MatchupPlan`` a generated, pasted or imported guide carries becomes a
brief (``source='guide'``) unless ``store_guide_matchups`` skips it, with
the guide's own ``FieldEvidence`` for the share and personal-record numbers
rather than re-querying them. Callers:
``guide --deck KEY --import FILE`` and ``POST``/``PUT
/api/guide/{key}/narrative``. See docs/brief.md,
"Backfill: a generated guide is a free source of briefs".
"""

from __future__ import annotations

import sqlite3

from sensei_top.brief import store
from sensei_top.guide.bundle import DeckGuide
from sensei_top.guide.field import archetype_key_by_name
from sensei_top.guide.narrative import GuideNarrative
from sensei_top.llm.provenance import now_iso


def store_guide_matchups(
    conn: sqlite3.Connection, guide: DeckGuide, narrative: GuideNarrative, *, model: str,
    list_hash: str | None = None,
) -> int:
    """Write one ``Brief`` per matchup plan in ``narrative.matchups``.
    Returns the number actually written.

    Skips a plan whose archetype display name has no corresponding
    ``archetype_key`` in the corpus — the guide names archetypes for
    readability and this backfill has nothing to key a cache row on without
    the corpus's own vocabulary, so it leaves the gap rather than guessing
    one. The lookup is ``guide.field.archetype_key_by_name``, the same one
    the guide prompt chose its sections with. Never overwrites an existing
    ``source='live'`` row whose ``list_hash`` already matches the current
    75 — a brief written for this exact matchup, from a smaller and cheaper
    prompt, is not improved by a guide's broader sweep.

    ``list_hash`` is the hash of the 75 the guide was written for, when an
    imported answer says so (``answers.read_answer``'s ``context``): each
    brief is stored with it, so a guide answered for an older list leaves
    briefs that read as stale, like the guide itself. ``None`` is the
    current 75. The skip above always compares with the current one.
    """
    identity = guide.provenance.deck
    key_by_name = archetype_key_by_name(conn)
    share_by_name = {s.archetype: s.share for s in guide.field.shares}
    rate_by_name = {r.archetype: r for r in guide.field.personal_rates}
    hash_now = store.list_hash(identity.current_cards)
    written_for = list_hash if list_hash is not None else hash_now
    written = 0

    for plan in narrative.matchups:
        archetype_key = key_by_name.get(plan.archetype)
        if archetype_key is None:
            continue

        existing = store.read_brief(conn, identity.key, archetype_key)
        if existing is not None and existing.source == "live" and existing.list_hash == hash_now:
            continue

        rate = rate_by_name.get(plan.archetype)
        brief = store.Brief(
            deck_key=identity.key,
            archetype_key=archetype_key,
            archetype_label=plan.archetype,
            archetype_share=share_by_name.get(plan.archetype),
            personal_matches=rate.matches if rate is not None else None,
            personal_wins=rate.wins if rate is not None else None,
            personal_losses=rate.losses if rate is not None else None,
            prose=plan.prose,
            play_around=(),  # the guide's shape carries no separate play-around list
            board_in=plan.board_in,
            board_out=plan.board_out,
            staples=(),
            problems=tuple(p for p in narrative.problems if p.archetype == plan.archetype),
            prompt=(
                f"(from a full deck guide run for {identity.name or identity.key}, "
                f"model {model})"
            ),
            model=model,
            generated_at=now_iso(),
            corpus_commit=store.corpus_commit(conn),
            list_hash=written_for,
            source="guide",
        )
        store.write_brief(conn, brief)
        written += 1

    return written
