"""Store an authored matchup brief.

This replaces what used to be ``brief/worker.py``: a background thread that
polled for a live, unbriefed opponent and made a Claude API call to fill the
gap. That thread is gone for good — a scheduled or triggered call is a
different feature from the opt-in, button-pressed one AGENTS.md
non-negotiable #5 now permits elsewhere (``docs/llm.md``), and this module
still has no automatic path at all. What is left is the half that was always
the real work — resolving the deck, validating the plan against the actual
75, and recording the provenance — with the prose supplied by whoever (or
whatever) wrote it, never fetched by this module itself.

Two ways in, both landing in the same ``matchup_brief`` table:

* ``sensei-top brief --deck KEY --archetype KEY --import FILE`` — one
  matchup, written from ``brief/narrative.py``'s own prompt.
* ``sensei-top guide --deck KEY --import FILE`` or ``POST
  /api/guide/{key}/narrative`` — every matchup a full deck-guide narrative
  covers, via ``brief/from_guide.py``. This is the ordinary path;
  per-matchup imports are for filling a gap the guide missed.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass

from sensei_top.brief import narrative as brief_narrative
from sensei_top.brief import store
from sensei_top.brief.store import Brief
from sensei_top.guide.deck import DeckIdentity
from sensei_top.guide.narrative import BoardCard
from sensei_top.guide.plans import validate_plans
from sensei_top.llm.provenance import now_iso


@dataclass(frozen=True, slots=True)
class _AuthoredPlan:
    """The minimal shape ``guide.plans.validate_plans`` needs (its
    ``_MatchupPlan`` protocol) for the one plan a brief carries."""

    archetype: str
    board_in: tuple[BoardCard, ...]
    board_out: tuple[BoardCard, ...]


def own_counters(
    conn: sqlite3.Connection, identity: DeckIdentity
) -> tuple[Counter, Counter]:
    """``(maindeck, sideboard)`` counted by card *name* — the vocabulary a
    written plan uses, so a plan naming a card the deck does not actually
    hold is caught rather than stored."""
    maindeck = identity.current_cards.get("maindeck") or []
    sideboard = identity.current_cards.get("sideboard") or []
    grp_ids = list({*maindeck, *sideboard})
    names = {
        row["grp_id"]: row["name"]
        for row in conn.execute(
            f"SELECT grp_id, name FROM cards WHERE grp_id IN ({','.join('?' for _ in grp_ids)})",
            grp_ids,
        )
    } if grp_ids else {}
    main_counts = Counter(names.get(g) for g in maindeck if names.get(g))
    side_counts = Counter(names.get(g) for g in sideboard if names.get(g))
    return main_counts, side_counts


def _reraw(parsed: dict) -> dict:
    """``briefs_from_json``'s per-item ``parsed`` value is already
    ``brief_from_json``'s own output — ``play_around``/``board_in``/
    ``board_out`` are tuples of ``PlayAround``/``BoardCard``, not the raw
    JSON list of dicts ``brief_from_json`` itself expects on the way in.
    ``import_brief`` calls ``brief_from_json`` again internally (so a single
    import and a multi-brief import converge on exactly one parser), so
    this rebuilds the plain-dict shape it needs from those dataclasses
    rather than duplicating any of ``import_brief``'s own logic."""
    return {
        "prose": parsed["prose"],
        "play_around": [{"card": p.card, "why": p.why} for p in parsed["play_around"]],
        "board_in": [{"card": c.card, "n": c.n} for c in parsed["board_in"]],
        "board_out": [{"card": c.card, "n": c.n} for c in parsed["board_out"]],
    }


def import_briefs(
    conn: sqlite3.Connection,
    identity: DeckIdentity,
    raw: str | dict,
    *,
    author: str,
    labels: dict[str, str | None] | None = None,
    fmt: str = "Standard",
) -> tuple[list[Brief], list[tuple[str, str]]]:
    """Store every brief in a ``full_multi_prompt`` answer, one
    ``import_brief`` call per item so each stored row gets exactly the
    context and facts a one-at-a-time import would have given it
    (``brief/narrative.py``'s own docstring on ``full_multi_prompt``).

    ``briefs_from_json`` is all-or-nothing on the JSON itself: a malformed
    item or a duplicate ``archetype_key`` raises ``NarrativeError`` before
    anything is written. Past that point, each item is stored
    independently — a ``LookupError`` from one archetype having no field
    consensus (a real gap ``import_brief`` itself refuses to guess around)
    is collected as ``(archetype_key, message)`` rather than aborting the
    rest of the batch, since the other archetypes' consensus is unrelated
    evidence. Returns ``(stored, skipped)``.

    ``labels`` supplies the display label for each archetype key (typically
    ``brief/coverage.py``'s own rows) — falls back to the bare key when a
    label is not given, the same fallback ``import_brief`` itself already
    tolerates for a single import.
    """
    parsed_items = brief_narrative.briefs_from_json(raw)
    labels = labels or {}

    stored: list[Brief] = []
    skipped: list[tuple[str, str]] = []
    for archetype_key, parsed in parsed_items:
        label = labels.get(archetype_key, archetype_key)
        try:
            brief = import_brief(
                conn, identity, archetype_key, label, _reraw(parsed), author=author, fmt=fmt,
            )
        except LookupError as exc:
            skipped.append((archetype_key, str(exc)))
            continue
        stored.append(brief)
    return stored, skipped


def import_brief(
    conn: sqlite3.Connection,
    identity: DeckIdentity,
    archetype_key: str,
    archetype_label: str | None,
    raw: str | dict,
    *,
    author: str,
    fmt: str = "Standard",
) -> Brief:
    """Parse, validate and store one authored brief.

    Raises ``NarrativeError`` (from ``brief/narrative.py``) on malformed
    input, and ``LookupError`` when the archetype has no field consensus to
    anchor the brief's own stored numbers to. A sideboard plan that does not
    balance, or names a card the deck does not hold, is **stored with the
    problem recorded** rather than rejected or silently repaired — the same
    posture ``guide/plans.py`` has always taken, so the dashboard shows the
    problem next to the plan.
    """
    parsed = brief_narrative.brief_from_json(raw)

    built = brief_narrative.build_brief_context(
        conn, identity, archetype_key, archetype_label, fmt=fmt
    )
    if built is None:
        raise LookupError(
            f"no field consensus for archetype {archetype_key!r} — nothing to anchor a brief to."
        )
    context, facts = built

    recommended_main, recommended_side = own_counters(conn, identity)
    plan = _AuthoredPlan(
        archetype=archetype_label or archetype_key,
        board_in=parsed["board_in"], board_out=parsed["board_out"],
    )
    problems = tuple(validate_plans(recommended_main, recommended_side, [plan]))

    brief = Brief(
        deck_key=identity.key,
        archetype_key=archetype_key,
        archetype_label=archetype_label,
        archetype_share=facts.archetype_share,
        personal_matches=facts.personal_matches,
        personal_wins=facts.personal_wins,
        personal_losses=facts.personal_losses,
        prose=parsed["prose"],
        play_around=parsed["play_around"],
        board_in=parsed["board_in"],
        board_out=parsed["board_out"],
        staples=facts.staples,
        problems=problems,
        prompt=context,
        model=author,
        generated_at=now_iso(),
        corpus_commit=store.corpus_commit(conn),
        list_hash=store.list_hash(identity.current_cards),
        source="live",
    )
    store.write_brief(conn, brief)
    return brief
