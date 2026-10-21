"""How much of the field this deck's cached briefs actually cover: a read
that stores nothing and writes no brief, only says which briefs are worth
writing next. ``build_coverage``'s docstring holds the row and status
contract. See docs/brief.md,
"`brief/coverage.py` — which of the field this deck's briefs actually cover".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from sensei_top.brief.narrative import _current_window_start
from sensei_top.brief.store import is_stale, list_hash, read_brief
from sensei_top.guide.deck import DeckIdentity, identity_format
from sensei_top.guide.field import faced_archetypes, field_by_key
from sensei_top.review.consensus import build_consensus

TOP_FIELD_ARCHETYPES = 6


@dataclass(frozen=True, slots=True)
class CoverageRow:
    archetype_key: str
    label: str | None
    times_faced: int
    field_share: float | None  # this archetype's windowed share of the field, 0..1
    status: str  # "ok" | "stale" | "missing" | "no_consensus"


@dataclass(frozen=True, slots=True)
class Coverage:
    fmt: str | None  # None: the deck's format is unknown, so there is no field to list
    rows: tuple[CoverageRow, ...]
    matches_covered: float | None  # share of classified matches whose archetype has an ok brief
    matches_covered_numerator: int
    matches_covered_denominator: int
    field_covered: float  # summed windowed field share of every ok row


def _faced_counts(
    conn: sqlite3.Connection, deck_ids: tuple[str, ...]
) -> dict[str, tuple[str | None, int]]:
    """``archetype_key -> (archetype_name, times_faced)``, full history (never
    windowed) — ``guide.field.faced_archetypes``, the one definition of
    "faced" this and the guide's most-faced matchup list share."""
    return faced_archetypes(conn, deck_ids)


def _field_counts(
    conn: sqlite3.Connection, fmt: str, since: str | None
) -> tuple[dict[str, tuple[str | None, int]], int]:
    """``archetype_key -> (label, windowed deck count)`` for every archetype
    in this window's classified field, plus the window's true classified
    total. A thin adapter over ``guide/field.py``'s ``field_by_key`` — the
    one definition of "the field grouped by key" this and
    ``coach/evidence.py``'s ``_build_field`` share (see ``field_by_key``'s
    own docstring for the "two keys can share one name" rationale). The
    label is each key's most common name in the window, ``field_by_key``'s
    own first variant."""
    by_key, total = field_by_key(conn, fmt, since)
    return {
        key: (variants[0][0], sum(n for _, n in variants))
        for key, variants in by_key.items()
    }, total


def build_coverage(
    conn: sqlite3.Connection, identity: DeckIdentity, *, fmt: str | None = None
) -> Coverage:
    """Every archetype worth having a brief for, and how well this deck's
    cached ``matchup_brief`` rows actually cover them.

    Rows are the union of every archetype this deck has actually faced
    (``_faced_counts``, unwindowed, as ``guide/field.py``'s personal rates
    are) and the field's own top ``TOP_FIELD_ARCHETYPES`` archetype keys by
    windowed deck count in the deck's format (``_field_counts``, over the
    denominator ``guide/field.py``'s ``build_field`` uses). A deck with no
    format has no field: ``fmt`` is ``None`` and there are no rows. Every
    row carries its windowed field share,
    whichever source put it there: ``0.0`` when the window has classified
    decks but none of this archetype (measured, not missing), ``None`` only
    when the window has no classified decks at all.

    ``status`` is ``ok`` / ``stale`` for a stored brief, and for a missing
    one either ``missing`` or ``no_consensus`` — the latter when the window
    holds fewer decklists than ``build_consensus`` needs, so no brief *can*
    be written yet (``full_prompt`` would return ``None``). Keeping the two
    apart stops archetypes faced once, long gone from the field, from
    reading as work the user could do today.

    ``matches_covered``'s denominator is every classified (``archetype_key``
    not null), decided (win/loss) match this deck identity has played —
    exactly the sum of every row's own ``times_faced``, since every faced
    archetype is guaranteed a row, ``no_consensus`` rows included (they are
    real matches no brief covers). A match whose opponent never got an
    ``archetype_key`` (a fallback/colours-only or manual-only verdict) is
    outside both numerator and denominator — the same line
    ``guide/field.py`` draws for its own personal rates.
    """
    if fmt is None:
        fmt = identity_format(conn, identity)
    if fmt is None:
        return Coverage(
            fmt=None, rows=(), matches_covered=None, matches_covered_numerator=0,
            matches_covered_denominator=0, field_covered=0.0,
        )
    since = _current_window_start(conn, fmt)
    faced = _faced_counts(conn, identity.deck_ids)
    field, field_total = _field_counts(conn, fmt, since)
    top_field = sorted(field, key=lambda k: (-field[k][1], k))[:TOP_FIELD_ARCHETYPES]

    keys = set(faced) | set(top_field)
    current_list_hash = list_hash(identity.current_cards)

    rows: list[CoverageRow] = []
    numerator = 0
    denominator = 0
    field_covered = 0.0
    for key in keys:
        faced_name, times_faced = faced.get(key, (None, 0))
        field_name, field_n = field.get(key, (None, 0))
        label = field_name or faced_name
        field_share = (field_n / field_total) if field_total else None

        brief = read_brief(conn, identity.key, key)
        if brief is None:
            has_consensus = (
                build_consensus(conn, key, fmt=fmt, board="main", since=since) is not None
            )
            status = "missing" if has_consensus else "no_consensus"
        elif is_stale(conn, brief, current_list_hash=current_list_hash):
            status = "stale"
        else:
            status = "ok"

        rows.append(CoverageRow(
            archetype_key=key, label=label, times_faced=times_faced,
            field_share=field_share, status=status,
        ))
        denominator += times_faced
        if status == "ok":
            numerator += times_faced
            if field_share is not None:
                field_covered += field_share

    rows.sort(key=lambda r: (-r.times_faced, -(r.field_share or 0.0), r.archetype_key))

    return Coverage(
        fmt=fmt,
        rows=tuple(rows),
        matches_covered=(numerator / denominator) if denominator else None,
        matches_covered_numerator=numerator,
        matches_covered_denominator=denominator,
        field_covered=field_covered,
    )
