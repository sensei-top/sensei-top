"""The field's own numbers: real tournament presence, win rates and
matchups, tiered by evidence quality — ``/api/metagame/*``
(``docs/metagame.md``).

Every route but the event detail reads one format: the ``format`` query
parameter, else the default ``/api/formats`` reports
(``api/sql.py::default_format``, D13). The detail route takes no format; it
reads one event by its key.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from sensei_top.api.deps import Conn
from sensei_top.api.models.metagame import (
    FormatName,
    MetaCardGroup,
    MetaEventDetail,
    MetaEventRow,
    MetagameStatus,
    MetaMatchup,
    MetaPresence,
    MetaSourceHold,
    MetaSourceStatus,
    MetaTierCounts,
    MetaWinrate,
    OpponentSourceBreakdown,
)
from sensei_top.api.sql import _consensus_window, _rows, default_format
from sensei_top.archetypes import opponent_source_breakdown
from sensei_top.archetypes.source import cache_age_seconds
from sensei_top.metagame import config as topdeck_config
from sensei_top.metagame.holds import SOURCES as HOLD_SOURCES
from sensei_top.metagame.holds import TIME_FORMAT, Hold, read_hold, visible
from sensei_top.metagame.source import cache_age_seconds as meta_cache_age_seconds
from sensei_top.metagame.source import placement_of
from sensei_top.metagame.tiers import TIERS
from sensei_top.review.consensus import _card_rows_by_name

router = APIRouter()

FormatParam = Annotated[
    FormatName | None,
    Query(
        alias="format",
        description="which format's field to read; omitted, the default /api/formats reports",
    ),
]


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


def _hold_out(hold: Hold) -> MetaSourceHold:
    return MetaSourceHold(
        status=hold.status.value,
        http_status=hold.http_status,
        since=hold.since.strftime(TIME_FORMAT),
        not_before=hold.not_before.strftime(TIME_FORMAT) if hold.not_before else None,
    )


@router.get("/api/metagame/status", response_model=MetagameStatus, tags=["metagame"])
def metagame_status(conn: Conn, fmt: FormatParam = None) -> MetagameStatus:
    """Whether the metagame layer has anything worth showing for one format:
    how stale the downloaded archetype definitions are, how many rules the
    format has and how often they actually name an opponent's deck for the
    user's own completed matches of it, and how stale and how large the
    tournament corpus itself is. Read once to decide whether either
    downloaded layer needs attention, never polled by the live heartbeat.

    The rule count, the opponent sources, the tier counts and the reset are
    the format's; the fetch stamps (age, commit, window, per-source rows)
    are the whole download's, since one fetch covers every format it takes.

    Also carries ``format_reset_start``: the first day of the format's
    current post-reset window (``api/sql.py::_consensus_window``), or null
    when no reset has been detected. The Field page uses it to offer "Since
    the last reset" as its default window for presence, win rate and
    matchups.
    """
    fmt = fmt or default_format(conn)
    age = cache_age_seconds(conn)
    files = conn.execute(
        "SELECT COUNT(*) FROM archetypes WHERE format = ? AND kind = 'archetype'", (fmt,)
    ).fetchone()[0]
    archetype_url_row = conn.execute("SELECT url FROM archetype_fetch WHERE id = 1").fetchone()
    breakdown = opponent_source_breakdown(conn, fmt)

    corpus_age = meta_cache_age_seconds(conn)
    fetch_row = conn.execute(
        "SELECT commit_sha, window_days FROM meta_fetch WHERE id = 1"
    ).fetchone()
    tier_counts = {t.lower(): 0 for t in TIERS}
    for row in conn.execute(
        "SELECT tier, COUNT(*) AS n FROM meta_event"
        " WHERE duplicate_of IS NULL AND format = ? GROUP BY tier",
        (fmt,),
    ):
        tier_counts[row["tier"].lower()] = row["n"]
    duplicate_events = conn.execute(
        "SELECT COUNT(*) FROM meta_event WHERE duplicate_of IS NOT NULL AND format = ?", (fmt,)
    ).fetchone()[0]

    # meta_event.source is 'Topdeck', written by metagame/topdeck.py's
    # "Tournaments/Topdeck/<tid>.json" path (parse_event derives the source
    # from it); meta_fetch_source's key for the same download is 'topdeck'.
    topdeck_events = conn.execute(
        "SELECT COUNT(*) FROM meta_event"
        " WHERE source = 'Topdeck' AND duplicate_of IS NULL AND format = ?",
        (fmt,),
    ).fetchone()[0]

    topdeck_configured = topdeck_config.load() is not None
    now = datetime.now(UTC)
    holds: dict[str, MetaSourceHold] = {}
    for held in HOLD_SOURCES:
        hold = read_hold(conn, held)
        if hold is not None and visible(hold, now):
            holds[held] = _hold_out(hold)
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
                hold=holds.get(row["source"]),
            )
        )
    # A configured-but-never-fetched topdeck key still deserves a row —
    # otherwise the dashboard has no way to say "configured, first fetch
    # pending" versus "not configured at all".
    if topdeck_configured and not any(s.source == "topdeck" for s in corpus_sources):
        corpus_sources.append(
            MetaSourceStatus(
                source="topdeck", age_hours=None, events=0, configured=True,
                hold=holds.get("topdeck"),
            )
        )
    # A source held before it ever stored a fetch row still shows its hold.
    for held, shown in holds.items():
        if not any(s.source == held for s in corpus_sources):
            corpus_sources.append(
                MetaSourceStatus(
                    source=held, age_hours=None, events=0,
                    configured=True if held == "mtgo" else topdeck_configured, hold=shown,
                )
            )

    return MetagameStatus(
        archetype_cache_age_hours=age / 3600 if age is not None else None,
        archetype_files=files,
        archetype_definitions_url=archetype_url_row["url"] if archetype_url_row else None,
        format=fmt,
        opponent_sources=OpponentSourceBreakdown(**breakdown),
        corpus_commit_sha=fetch_row["commit_sha"] if fetch_row else None,
        corpus_age_hours=corpus_age / 3600 if corpus_age is not None else None,
        corpus_window_days=fetch_row["window_days"] if fetch_row else None,
        corpus_events_by_tier=MetaTierCounts(**tier_counts),
        corpus_duplicate_events=duplicate_events,
        corpus_topdeck_events=topdeck_events,
        corpus_sources=corpus_sources,
        format_reset_start=_consensus_window(conn, fmt),
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
    fmt: FormatParam = None,
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
    where = "format = ? AND event_date >= ?"
    params: tuple[Any, ...] = (fmt or default_format(conn), cutoff)
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
    fmt: FormatParam = None,
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
    where = "format = ? AND event_date >= ?"
    params: tuple[Any, ...] = (fmt or default_format(conn), cutoff)
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
    fmt: FormatParam = None,
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
    where = f"format = ? AND tier IN ({placeholders})"
    params: tuple[Any, ...] = (fmt or default_format(conn), *tier)
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


_EVENT_PREFIX = "Tournaments/"
_EVENT_SUFFIX = ".json"
# The order a card's group is looked for in; Land is checked first and wins.
_TYPE_ORDER = (
    "Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact", "Enchantment",
)


def _event_key(event_id: str) -> str:
    return event_id.removeprefix(_EVENT_PREFIX).removesuffix(_EVENT_SUFFIX)


def _card_type(type_line: str | None) -> str | None:
    """The group a card sits in, from its front face's type line."""
    if not type_line:
        return None
    types = type_line.split("//")[0].split("\u2014")[0].split()
    if "Land" in types:
        return "Land"
    for t in _TYPE_ORDER:
        if t in types:
            return t
    return None


def _cards(raw: str) -> list[dict[str, Any]]:
    return json.loads(raw)


def _by_count_then_name(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        ({"count": c["count"], "name": c["name"]} for c in cards),
        key=lambda c: (-c["count"], c["name"]),
    )


@router.get("/api/metagame/events", response_model=list[MetaEventRow], tags=["metagame"])
def metagame_events(
    conn: Conn,
    since: Annotated[
        date | None,
        Query(description="restrict to events on/after this date, overriding days"),
    ] = None,
    days: Annotated[
        int, Query(ge=1, le=3650, description="how far back to look when since is not given")
    ] = 90,
    tier: Annotated[str | None, Query(description="restrict to one tier: A, B, C or D")] = None,
    fmt: FormatParam = None,
) -> list[dict[str, Any]]:
    """The format's stored tournament events, newest first. A byte-identical
    twin set aside by dedup and an event with no deck are not listed, and the
    detail route answers 404 for both."""
    cutoff = _since_cutoff(since, days)
    where = "e.format = ? AND e.event_date >= ? AND e.duplicate_of IS NULL"
    params: tuple[Any, ...] = (fmt or default_format(conn), cutoff)
    if tier:
        where += " AND e.tier = ?"
        params += (tier,)
    rows = conn.execute(
        f"""
        SELECT e.event_id, e.name, e.event_date, e.format, e.tier, e.source,
               (SELECT COUNT(*) FROM meta_deck d
                 WHERE d.event_id = e.event_id AND d.mainboard_json != '[]') AS lists
          FROM meta_event e
         WHERE {where}
           AND EXISTS (SELECT 1 FROM meta_deck d WHERE d.event_id = e.event_id)
         ORDER BY e.event_date DESC, e.name, e.event_id
        """,
        params,
    ).fetchall()
    out = []
    for row in rows:
        placed = conn.execute(
            """
            SELECT d.result, a.label FROM meta_deck d
              LEFT JOIN meta_deck_archetype a
                ON a.event_id = d.event_id AND a.deck_ord = d.deck_ord
             WHERE d.event_id = ? ORDER BY d.deck_ord
            """,
            (row["event_id"],),
        )
        winner = next((p["label"] for p in placed if placement_of(p["result"]) == 1), None)
        out.append({
            "key": _event_key(row["event_id"]),
            "name": row["name"],
            "date": row["event_date"][:10] if row["event_date"] else None,
            "format": row["format"],
            "tier": row["tier"],
            "source": row["source"],
            "lists": row["lists"],
            "winner": winner,
        })
    return out


@router.get("/api/metagame/events/{key:path}", response_model=MetaEventDetail, tags=["metagame"])
def metagame_event(conn: Conn, key: str) -> dict[str, Any]:
    """One stored event with its decks, by placement, each mainboard grouped
    by card type (a card's front face decides; Land wins, then the first of
    Creature, Planeswalker, Battle, Instant, Sorcery, Artifact, Enchantment;
    an unknown card is the null group, last). An unknown key, a twin and an
    event with no deck are all 404 — the set the list hides."""
    event = conn.execute(
        "SELECT * FROM meta_event WHERE event_id = ? AND duplicate_of IS NULL"
        " AND EXISTS (SELECT 1 FROM meta_deck d WHERE d.event_id = meta_event.event_id)",
        (_EVENT_PREFIX + key + _EVENT_SUFFIX,),
    ).fetchone()
    if event is None:
        raise HTTPException(status_code=404, detail=f"No event for key {key!r}.")
    deck_rows = conn.execute(
        """
        SELECT d.deck_ord, d.result, d.wins, d.losses, d.draws, d.mainboard_json,
               d.sideboard_json, a.archetype_key, a.label, a.colors
          FROM meta_deck d
          LEFT JOIN meta_deck_archetype a
            ON a.event_id = d.event_id AND a.deck_ord = d.deck_ord
         WHERE d.event_id = ?
        """,
        (event["event_id"],),
    ).fetchall()
    mains = {r["deck_ord"]: _cards(r["mainboard_json"]) for r in deck_rows}
    names = sorted({c["name"] for cards in mains.values() for c in cards})
    types = {
        n: _card_type(row["type_line"]) for n, row in _card_rows_by_name(conn, names).items()
    }
    rank = {t: i for i, t in enumerate((*_TYPE_ORDER, "Land"))}
    decks = []
    for r in deck_rows:
        groups: dict[str | None, list[dict[str, Any]]] = {}
        for card in mains[r["deck_ord"]]:
            groups.setdefault(types.get(card["name"]), []).append(card)
        main = [
            MetaCardGroup(
                type=t,
                count=sum(c["count"] for c in cards),
                cards=_by_count_then_name(cards),
            )
            for t, cards in sorted(
                groups.items(), key=lambda kv: (kv[0] is None, rank.get(kv[0] or '', 0))
            )
        ]
        placement = placement_of(r["result"])
        decks.append({
            "_sort": (placement is None, placement or 0, r["deck_ord"]),
            "placement": placement,
            "record": (
                {"wins": r["wins"], "losses": r["losses"], "draws": r["draws"]}
                if r["wins"] or r["losses"] or r["draws"]
                else None
            ),
            "archetype": (
                {"key": r["archetype_key"], "label": r["label"], "colors": r["colors"]}
                if r["archetype_key"] is not None
                else None
            ),
            "main": main,
            "side": _by_count_then_name(_cards(r["sideboard_json"])),
        })
    decks.sort(key=lambda d: d["_sort"])
    for d in decks:
        del d["_sort"]
    return {
        "key": key,
        "name": event["name"],
        "date": event["event_date"][:10] if event["event_date"] else None,
        "format": event["format"],
        "tier": event["tier"],
        "source": event["source"],
        "uri": event["uri"],
        "lists_read_at": event["lists_read_at"],
        "empty_read_at": event["empty_read_at"],
        "empty_read_kind": event["empty_read_kind"],
        "decks": decks,
    }
