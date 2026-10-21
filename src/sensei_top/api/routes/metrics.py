"""The ``/api/metrics/*`` winrate/curve endpoints — each a thin ``SELECT``
over one metric view. See docs/architecture.md, "Aggregation: views versus
Python".
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from sensei_top.api.deps import Conn, DeckFilter, SourceFilter
from sensei_top.api.models.metrics import (
    DeckWinrate,
    GameLength,
    Matchup,
    PlayDrawWinrate,
    RankWinrate,
    TurnCurve,
)
from sensei_top.api.sql import _filtered, _rows

router = APIRouter()


@router.get("/api/metrics/winrate", response_model=list[DeckWinrate], tags=["metrics"])
def winrate(
    conn: Conn,
    deck_id: DeckFilter = None,
    event_id: Annotated[str | None, Query(description="restrict to one event")] = None,
    source: SourceFilter = "arena",
) -> list[dict[str, Any]]:
    """Winrate by deck, match- and game-level.

    One row per deck (an Arena deck, or an MTGO deck the user picked for a
    match), not per maindeck content hash: a single card swap mints a new
    deck_id, so grouping on the hash splits one deck into a row per version.
    Both filters apply before the rollup, so deck_id still means one
    content hash — matching the deck selector, which emits exactly that.

    Matches with no deck, an MTGO match the user has not picked a deck for
    among them (``v_match_deck``), are one more row with a null ``deck_key``
    rather than missing from the totals. A ``deck_id`` filter leaves that
    row out, since none of those matches has one.
    """
    clauses, params = [], []
    if deck_id:
        clauses.append("v.deck_id = ?")
        params.append(deck_id)
    if event_id:
        clauses.append("v.event_id = ?")
        params.append(event_id)
    if source != "all":
        clauses.append("v.source = ?")
        params.append(source)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT v.deck_key, v.arena_deck_id, v.deck_name,
               COUNT(DISTINCT v.deck_id)  AS versions,
               SUM(v.matches_completed)   AS matches_completed,
               SUM(v.matches_won)         AS matches_won,
               SUM(v.games_won)           AS games_won,
               SUM(v.games_lost)          AS games_lost
          FROM v_deck_identity_winrate v{where}
         GROUP BY v.deck_key
    """
    if not deck_id:
        deckless = ["md.deck_id IS NULL"]
        if event_id:
            deckless.append("m.event_id = ?")
            params.append(event_id)
        if source != "all":
            deckless.append("m.source = ?")
            params.append(source)
        # Grouped on the (always null) deck_id so that no deckless match
        # means no row, where a bare aggregate would answer a row of zeros.
        sql += f"""
         UNION ALL
        SELECT NULL, NULL, NULL, 0,
               COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw')),
               COUNT(*) FILTER (WHERE m.result = 'win'),
               SUM(COALESCE(m.games_won, 0)),
               SUM(COALESCE(m.games_lost, 0))
          FROM matches m
          JOIN v_match_deck md ON md.match_id = m.match_id
         WHERE {' AND '.join(deckless)}
         GROUP BY md.deck_id
        """
    sql = f"""
        SELECT *, CAST(matches_won AS REAL) / NULLIF(matches_completed, 0) AS winrate
          FROM ({sql})
         ORDER BY matches_completed DESC
    """
    return _rows(conn, sql, tuple(params))


@router.get("/api/metrics/winrate-by-rank", response_model=list[RankWinrate], tags=["metrics"])
def winrate_by_rank(conn: Conn, source: SourceFilter = "arena") -> list[dict[str, Any]]:
    """Winrate conditioned on rank tier — every other winrate on this
    dashboard pools every match together regardless of where in the
    ladder it was played. No deck_id filter: rank is a property of the
    account's ladder position, not of one deck, so filtering by deck
    here would just be a smaller, noisier version of the same question
    /api/metrics/winrate already answers. MTGO has no rank ladder at all
    (``rank_snapshot`` is never written for it), so ``source='mtgo'``
    answers one row, the tier with both fields null, rather than a guess
    (migration 046 keeps an Arena snapshot off an MTGO match)."""
    sql = """
        SELECT v.constructed_class, v.constructed_level,
               SUM(v.matches_completed) AS matches_completed,
               SUM(v.matches_won)       AS matches_won,
               SUM(v.games_won)         AS games_won,
               SUM(v.games_lost)        AS games_lost,
               CAST(SUM(v.matches_won) AS REAL)
                   / NULLIF(SUM(v.matches_completed), 0) AS winrate
          FROM v_rank_winrate v
    """
    params: tuple[Any, ...] = ()
    if source != "all":
        sql += " WHERE v.source = ?"
        params = (source,)
    # The view groups per source too, so under 'all' the unranked tier would
    # otherwise come back twice: once for Arena, once for MTGO.
    sql += " GROUP BY v.constructed_class, v.constructed_level ORDER BY matches_completed DESC"
    return _rows(conn, sql, params)


@router.get("/api/metrics/play-draw", response_model=list[PlayDrawWinrate], tags=["metrics"])
def play_draw(
    conn: Conn, deck_id: DeckFilter = None, source: SourceFilter = "arena"
) -> list[dict[str, Any]]:
    """Winrate on the play vs on the draw, per game.

    Matches with no deck, an MTGO match with no picked deck among them, share
    the rows whose ``deck_id`` is null. The view groups per source, and those
    are the only rows two sources can share, so they are added together
    here rather than answered twice under 'all'.
    """
    sql, params = _filtered(
        """
        SELECT v.deck_id, d.name AS deck_name, v.on_play,
               SUM(v.games_completed) AS games_completed,
               SUM(v.games_won)       AS games_won,
               SUM(v.games_lost)      AS games_lost,
               CAST(SUM(v.games_won) AS REAL) / NULLIF(SUM(v.games_completed), 0) AS winrate
          FROM v_play_draw_winrate v
          LEFT JOIN decks d ON d.deck_id = v.deck_id
        """,
        deck_id,
        source=source,
    )
    sql += " GROUP BY v.deck_id, v.on_play ORDER BY deck_name, v.on_play DESC"
    return _rows(conn, sql, params)


@router.get("/api/metrics/game-length", response_model=list[GameLength], tags=["metrics"])
def game_length(
    conn: Conn, deck_id: DeckFilter = None, source: SourceFilter = "arena"
) -> list[dict[str, Any]]:
    """Game length in player-turns, with winrate per bucket.
    Deckless matches are added together across sources, as in play-draw."""
    sql, params = _filtered(
        """
        SELECT v.deck_id, d.name AS deck_name, v.turn_count,
               SUM(v.games)     AS games,
               SUM(v.games_won) AS games_won,
               CAST(SUM(v.games_won) AS REAL) / NULLIF(SUM(v.games), 0) AS winrate
          FROM v_deck_game_length v
          LEFT JOIN decks d ON d.deck_id = v.deck_id
        """,
        deck_id,
        source=source,
    )
    sql += " GROUP BY v.deck_id, v.turn_count ORDER BY deck_name, v.turn_count"
    return _rows(conn, sql, params)


@router.get("/api/metrics/turn-curves", response_model=list[TurnCurve], tags=["metrics"])
def turn_curves(
    conn: Conn, deck_id: DeckFilter = None, source: SourceFilter = "arena"
) -> list[dict[str, Any]]:
    """Per-deck life/hand/board averages by player-turn."""
    sql, params = _filtered(
        """
        SELECT v.deck_id, d.name AS deck_name, v.turn_number, v.samples,
               v.avg_self_life, v.avg_opp_life, v.avg_self_hand, v.avg_opp_hand,
               v.avg_self_lands, v.avg_self_permanents, v.avg_opp_permanents
          FROM v_deck_turn_curves v
          LEFT JOIN decks d ON d.deck_id = v.deck_id
        """,
        deck_id,
        source=source,
    )
    return _rows(conn, sql + " ORDER BY deck_name, v.turn_number", params)


@router.get("/api/metrics/matchups", response_model=list[Matchup], tags=["metrics"])
def matchups(
    conn: Conn, deck_id: DeckFilter = None, source: SourceFilter = "arena"
) -> list[dict[str, Any]]:
    """Winrate against each opponent deck, as inferred from what they showed.

    Two different players on the same archetype land in one row, which is
    the entire reason this is worth grouping. Deckless matches are added
    together across sources, as in play-draw; the view names a key once per
    format across every source, so its label is the same on both rows. One
    row per format too: matches with no resolved format share one row per
    key and deck.
    """
    sql, params = _filtered(
        """
        SELECT v.format, v.opponent_key, MAX(v.opponent_label) AS opponent_label,
               v.deck_id, d.name AS deck_name,
               SUM(v.matches_completed) AS matches_completed,
               SUM(v.matches_won)       AS matches_won,
               SUM(v.games_won)         AS games_won,
               SUM(v.games_lost)        AS games_lost,
               MAX(v.last_played)       AS last_played,
               MAX(v.confidence_rank)   AS confidence_rank,
               NULLIF(
                   (CASE WHEN MAX(v.opponent_colors LIKE '%W%') THEN 'W' ELSE '' END) ||
                   (CASE WHEN MAX(v.opponent_colors LIKE '%U%') THEN 'U' ELSE '' END) ||
                   (CASE WHEN MAX(v.opponent_colors LIKE '%B%') THEN 'B' ELSE '' END) ||
                   (CASE WHEN MAX(v.opponent_colors LIKE '%R%') THEN 'R' ELSE '' END) ||
                   (CASE WHEN MAX(v.opponent_colors LIKE '%G%') THEN 'G' ELSE '' END),
                   ''
               ) AS opponent_colors,
               CAST(SUM(v.matches_won) AS REAL)
                   / NULLIF(SUM(v.matches_completed), 0) AS winrate
          FROM v_matchup_winrate v
          LEFT JOIN decks d ON d.deck_id = v.deck_id
        """,
        deck_id,
        # A matchup you have only ever left unfinished is not a winrate. The
        # view keeps the row so SQL totals still reconcile with v_deck_winrate.
        extra="v.matches_completed > 0",
        source=source,
    )
    sql += (
        " GROUP BY v.format, v.opponent_key, v.deck_id"
        " ORDER BY matches_completed DESC, opponent_label"
    )
    return _rows(conn, sql, params)
