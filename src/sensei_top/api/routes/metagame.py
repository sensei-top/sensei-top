"""The field's own numbers: real tournament presence, win rates and
matchups, tiered by evidence quality — ``/api/metagame/*``
(``docs/metagame.md``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query

from sensei_top.api.deps import Conn
from sensei_top.api.models.metagame import (
    MetagameStatus,
    MetaMatchup,
    MetaPresence,
    MetaSourceStatus,
    MetaTierCounts,
    MetaWinrate,
    OpponentSourceBreakdown,
)
from sensei_top.api.sql import _consensus_window, _rows
from sensei_top.archetypes import standard_opponent_source_breakdown
from sensei_top.archetypes.source import cache_age_seconds
from sensei_top.metagame import config as topdeck_config
from sensei_top.metagame.source import cache_age_seconds as meta_cache_age_seconds
from sensei_top.metagame.tiers import TIERS

router = APIRouter()


def _since_cutoff(since: date | None, days: int | None) -> str | None:
    """The one place `since`/`days` become an ``event_date >= ?`` cutoff,
    shared by ``presence``, ``winrate`` and ``matchups`` so the format-reset
    window behaves identically across all three. An explicit ``since``
    always wins over ``days`` — this is how the frontend's "Since last
    reset" option overrides the day-count select. With neither given, the
    result is ``None`` — no cutoff at all, i.e. the whole corpus; only
    ``matchups`` relies on that today, since ``presence``/``winrate`` always
    pass a ``days`` default of their own.
    """
    if since is not None:
        return since.isoformat()
    if days is not None:
        return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    return None


@router.get("/api/metagame/status", response_model=MetagameStatus, tags=["metagame"])
def metagame_status(conn: Conn) -> MetagameStatus:
    """Whether the metagame layer has anything worth showing: how stale the
    downloaded archetype definitions are, how often they actually name an
    opponent's deck for the user's own completed Standard matches, and how
    stale and how large the tournament corpus itself is. Read once to
    decide whether either downloaded layer needs attention, never polled
    by the live heartbeat.

    Also carries ``format_reset_start``: the first day of the current
    post-reset window (``api/sql.py::_consensus_window``), or null when no
    reset has been detected. The Field page uses it to offer "Since the last
    reset" as its default window for presence, win rate and matchups.
    """
    age = cache_age_seconds(conn)
    files = conn.execute(
        "SELECT COUNT(*) FROM archetypes WHERE format = 'Standard' AND kind = 'archetype'"
    ).fetchone()[0]
    archetype_url_row = conn.execute("SELECT url FROM archetype_fetch WHERE id = 1").fetchone()
    breakdown = standard_opponent_source_breakdown(conn)

    corpus_age = meta_cache_age_seconds(conn)
    fetch_row = conn.execute(
        "SELECT commit_sha, window_days FROM meta_fetch WHERE id = 1"
    ).fetchone()
    tier_counts = {t.lower(): 0 for t in TIERS}
    for row in conn.execute(
        "SELECT tier, COUNT(*) AS n FROM meta_event WHERE duplicate_of IS NULL GROUP BY tier"
    ):
        tier_counts[row["tier"].lower()] = row["n"]
    duplicate_events = conn.execute(
        "SELECT COUNT(*) FROM meta_event WHERE duplicate_of IS NOT NULL"
    ).fetchone()[0]

    topdeck_configured = topdeck_config.load() is not None
    source_rows = conn.execute(
        "SELECT source, fetched_at, events FROM meta_fetch_source"
    ).fetchall()
    corpus_sources = []
    for row in source_rows:
        source_age = meta_cache_age_seconds(conn, source=row["source"])
        corpus_sources.append(
            MetaSourceStatus(
                source=row["source"],
                age_hours=source_age / 3600 if source_age is not None else None,
                events=row["events"],
                configured=True if row["source"] in ("fbettega", "mtgo") else topdeck_configured,
            )
        )
    # A configured-but-never-fetched topdeck key still deserves a row —
    # otherwise the dashboard has no way to say "configured, first fetch
    # pending" versus "not configured at all".
    if topdeck_configured and not any(s.source == "topdeck" for s in corpus_sources):
        corpus_sources.append(
            MetaSourceStatus(source="topdeck", age_hours=None, events=0, configured=True)
        )

    return MetagameStatus(
        archetype_cache_age_hours=age / 3600 if age is not None else None,
        archetype_files=files,
        archetype_definitions_url=archetype_url_row["url"] if archetype_url_row else None,
        standard_opponent_sources=OpponentSourceBreakdown(**breakdown),
        corpus_commit_sha=fetch_row["commit_sha"] if fetch_row else None,
        corpus_age_hours=corpus_age / 3600 if corpus_age is not None else None,
        corpus_window_days=fetch_row["window_days"] if fetch_row else None,
        corpus_events_by_tier=MetaTierCounts(**tier_counts),
        corpus_duplicate_events=duplicate_events,
        corpus_sources=corpus_sources,
        format_reset_start=_consensus_window(conn),
    )


@router.get("/api/metagame/presence", response_model=list[MetaPresence], tags=["metagame"])
def metagame_presence(
    conn: Conn,
    since: Annotated[
        date | None,
        Query(description="restrict to rounds on/after this date, overriding days"),
    ] = None,
    days: Annotated[
        int, Query(ge=1, le=3650, description="how far back to look when since is not given")
    ] = 90,
    tier: Annotated[str | None, Query(description="restrict to one tier: A, B, C or D")] = None,
) -> list[dict[str, Any]]:
    """Archetype share of the field, from real tournament decklists.

    Every tier appears — presence is the one thing a Tier C league event
    is licensed for (docs/metagame.md) — but never blended across tiers:
    a league's decklists are only ever the undefeated ones, so mixing its
    count into a Tier A share would silently favour whatever archetype
    happens to win leagues. ``share`` is computed within its own tier.

    ``since``, when given, replaces the ``days`` cutoff outright — this is
    how the dashboard's "Since last reset" window avoids pooling results
    from across a Standard ban with the post-ban field (docs/metagame.md's
    "format-reset boundary").

    ``colors`` is the combination most of a row's lists carry, ties to the
    first in text order; a row whose every list has null colours answers
    null.
    """
    cutoff = _since_cutoff(since, days)
    where = "event_date >= ?"
    params: tuple[Any, ...] = (cutoff,)
    if tier:
        where += " AND tier = ?"
        params += (tier,)
    return _rows(
        conn,
        f"""
        WITH filtered AS (
            SELECT archetype_key, label, tier, colors
              FROM v_meta_presence
             WHERE {where}
        ),
        color_rank AS (
            SELECT archetype_key, label, tier, colors,
                   ROW_NUMBER() OVER (
                       PARTITION BY archetype_key, label, tier
                       ORDER BY COUNT(*) DESC, colors ASC
                   ) AS rn
              FROM filtered
             WHERE colors IS NOT NULL
             GROUP BY archetype_key, label, tier, colors
        )
        SELECT f.archetype_key, f.label, f.tier,
               cr.colors AS colors,
               COUNT(*) AS decks,
               CAST(COUNT(*) AS REAL) / SUM(COUNT(*)) OVER (PARTITION BY f.tier) AS share
          FROM filtered f
          LEFT JOIN color_rank cr
            ON cr.archetype_key = f.archetype_key AND cr.label = f.label
           AND cr.tier = f.tier AND cr.rn = 1
         GROUP BY f.archetype_key, f.label, f.tier
         ORDER BY f.tier, decks DESC
        """,
        params,
    )


@router.get("/api/metagame/winrate", response_model=list[MetaWinrate], tags=["metagame"])
def metagame_winrate(
    conn: Conn,
    since: Annotated[
        date | None,
        Query(description="restrict to rounds on/after this date, overriding days"),
    ] = None,
    days: Annotated[
        int, Query(ge=1, le=3650, description="how far back to look when since is not given")
    ] = 90,
    tier: Annotated[str | None, Query(description="restrict to one tier: A, B or D")] = None,
) -> list[dict[str, Any]]:
    """Win rate by archetype, summed from each entry's real ``Standings[]``
    record — Tier A, B and D all carry one. Tier C is excluded by
    ``v_meta_winrate`` itself — a league event publishes no ``Standings`` at
    all, so it cannot contribute a win rate. ``wins``/``losses``/``draws`` here are each
    deck's whole-event match record, not one match's game score — see
    ``MetaWinrate``'s own docstring — so this sums them across every
    entry rather than treating one deck as one match.

    ``since``, when given, replaces the ``days`` cutoff outright, the same
    reset-window override ``presence`` documents above.

    ``colors`` is the combination most of a row's lists carry, ties to the
    first in text order; a row whose every list has null colours answers
    null.
    """
    cutoff = _since_cutoff(since, days)
    where = "event_date >= ?"
    params: tuple[Any, ...] = (cutoff,)
    if tier:
        where += " AND tier = ?"
        params += (tier,)
    return _rows(
        conn,
        f"""
        WITH filtered AS (
            SELECT archetype_key, label, colors, wins, losses, draws
              FROM v_meta_winrate
             WHERE {where}
        ),
        color_rank AS (
            SELECT archetype_key, label, colors,
                   ROW_NUMBER() OVER (
                       PARTITION BY archetype_key, label
                       ORDER BY COUNT(*) DESC, colors ASC
                   ) AS rn
              FROM filtered
             WHERE colors IS NOT NULL
             GROUP BY archetype_key, label, colors
        )
        SELECT f.archetype_key, f.label,
               cr.colors AS colors,
               COUNT(*) AS entries,
               SUM(wins) AS matches_won, SUM(losses) AS matches_lost,
               SUM(draws) AS matches_drawn,
               CAST(SUM(wins) AS REAL)
                   / NULLIF(SUM(wins) + SUM(losses) + SUM(draws), 0) AS winrate
          FROM filtered f
          LEFT JOIN color_rank cr
            ON cr.archetype_key = f.archetype_key AND cr.label = f.label AND cr.rn = 1
         GROUP BY f.archetype_key, f.label
         ORDER BY (SUM(wins) + SUM(losses) + SUM(draws)) DESC
        """,
        params,
    )


@router.get("/api/metagame/matchups", response_model=list[MetaMatchup], tags=["metagame"])
def metagame_matchups(
    conn: Conn,
    tier: Annotated[
        list[str],
        Query(
            description="which tiers' matches to combine — repeat to combine them; the "
            "dashboard counts A, then A and B, then A, B and D"
        ),
    ] = ["A"],  # noqa: B006 — FastAPI reads this as the query default, never mutated
    since: Annotated[
        date | None,
        Query(description="restrict to rounds on/after this date, overriding days"),
    ] = None,
    days: Annotated[
        int | None,
        Query(ge=1, le=3650, description="how far back to look; unset means the whole corpus"),
    ] = None,
) -> list[dict[str, Any]]:
    """Archetype-vs-archetype, from real completed matches. Defaults to
    Tier A alone (paper, 64 or more players) — the highest-ranked tier with
    a genuine round-robin matrix behind it; ``?tier=A&tier=B`` adds Tier B's
    MTGO bracket rounds, usable but tiny, and ``?tier=A&tier=B&tier=D``
    folds in Tier D's own small paper swiss too (see docs/metagame.md).
    Tier C has no rounds at all — see metagame/tiers.py — so it never
    appears here.

    This route pools the tiers asked for. The one matchup number the live
    brief and the match report quote comes from a single tier instead,
    walked A, then B, then D (``metagame/matchup.py``).

    Neither ``since`` nor ``days`` given means the whole corpus, same as
    before this pair existed. ``since`` overrides ``days`` the same way it
    does for ``presence``/``winrate`` — the "Since last reset" window keeps
    a post-ban matchup matrix from pooling with the pre-ban one.
    """
    cutoff = _since_cutoff(since, days)
    placeholders = ",".join("?" for _ in tier)
    where = f"tier IN ({placeholders})"
    params: tuple[Any, ...] = tuple(tier)
    if cutoff is not None:
        where += " AND event_date >= ?"
        params += (cutoff,)
    return _rows(
        conn,
        f"""
        SELECT archetype_key, label, opponent_key, opponent_label,
               GROUP_CONCAT(DISTINCT tier) AS tier,
               SUM(n) AS n,
               SUM(matches_won) AS matches_won, SUM(matches_lost) AS matches_lost,
               SUM(matches_drawn) AS matches_drawn,
               SUM(games_won) AS games_won, SUM(games_lost) AS games_lost,
               CAST(SUM(matches_won) AS REAL) / NULLIF(SUM(n), 0) AS winrate
          FROM v_meta_matchup
         WHERE {where}
         GROUP BY archetype_key, label, opponent_key, opponent_label
         ORDER BY SUM(n) DESC, label
        """,
        params,
    )
