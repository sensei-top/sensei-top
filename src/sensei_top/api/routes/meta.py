"""Diagnostics, the deck picker and the format list: whether the
reader/watcher/database are alive, whether a Claude credential is
configured, every deck with enough context to pick one out of a list, and
every format with what the app holds for it.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Request

from sensei_top.api.deps import Conn
from sensei_top.api.models.common import Deck, Health, LiveStatus, LLMStatus
from sensei_top.api.models.metagame import FormatEntry, FormatMatchCounts, FormatsOut
from sensei_top.api.sql import _rows, default_format
from sensei_top.formats import FORMATS
from sensei_top.llm import config as llm_config

router = APIRouter()


@router.get("/api/health", response_model=Health, tags=["meta"])
def health(request: Request, conn: Conn) -> Health:
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("decks", "matches", "games", "turns")
    }
    return Health(status="ok", database=str(request.app.state.database), **counts)


@router.get("/api/llm/status", response_model=LLMStatus, tags=["meta"])
def llm_status() -> LLMStatus:
    """Whether a Claude credential is resolved right now, and which
    model would be used — never the key itself
    (``sensei_top.llm.config``). The dashboard reads this once to
    decide whether a narrative surface offers a generate button or
    falls back to the copy-prompt path (``docs/llm.md``). No database
    connection needed: this is purely local config, not derived data.
    """
    cfg = llm_config.load()
    return LLMStatus(configured=cfg is not None, model=cfg.model if cfg else None)


@router.get("/api/live", response_model=LiveStatus, tags=["meta"])
def live(request: Request, conn: Conn) -> LiveStatus:
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("matches", "games", "turns", "card_events")
    }
    # raw_events.id is INTEGER PRIMARY KEY (a rowid alias) on a table that is
    # never deleted from (non-negotiable #2) and only ever inserted into with
    # no explicit id — so MAX(id) and COUNT(*) are the same number, verified
    # exactly equal against a real 238,520-row capture (min=1, max=count, no
    # gaps). MAX(id) is an O(1) index lookup; COUNT(*) here was a 300ms+ scan
    # of idx_raw_events_label on every 3s poll for a fact MAX(id) already
    # tells us for free — so raw_events is deliberately absent from the
    # counts dict above, and this one query does both jobs.
    newest_event = conn.execute("SELECT MAX(id) FROM raw_events").fetchone()[0]
    # ingest_state.updated_at moves on every poll, so it answers "is the
    # reader alive", not "is the data fresh". The dashboard needs the
    # latter, which is when a row was last actually written.
    #
    # MAX(ingested_at) used to be a full-table scan (ingested_at carries no
    # index, and never will: it's assigned by DEFAULT at insert time, so it
    # is monotonic with id by construction) — replaced with a tail read in
    # id order, verified against real data to return the identical value at
    # a fraction of the cost (an unindexed full scan of a 1GB+ table taxed
    # every 3s poll, measured 4-7s once raw_events passes a season of play).
    # logged_at is different: it is Arena's own header timestamp, and a
    # Player-prev.log recovery pass can insert an older-logged_at event
    # after a newer one, so it is *not* guaranteed monotonic with id and
    # still needs the index migrations/034 added.
    #
    # last_event_at is the newest in-game timestamp, and an MTGO deck file's
    # logged_at is its mtime, the time the user saved it, so those rows are
    # left out. A bare MAX(logged_at) would return one, so the query below
    # walks the index from its newest end and stops at the first row that is
    # not a deck file, so the walk skips only the deck rows newer than the
    # newest game row. EXPLAIN QUERY PLAN:
    # "SEARCH raw_events USING INDEX idx_raw_events_logged_at (logged_at>?)",
    # no sort step, no scan.
    last_ingest_row = conn.execute(
        "SELECT ingested_at FROM raw_events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    last_ingest = last_ingest_row[0] if last_ingest_row else None
    last_checked = conn.execute("SELECT MAX(updated_at) FROM ingest_state").fetchone()[0]
    last_event_row = conn.execute(
        "SELECT logged_at FROM raw_events "
        "WHERE logged_at IS NOT NULL AND source != 'mtgo_deck' "
        "ORDER BY logged_at DESC LIMIT 1"
    ).fetchone()
    last_event = last_event_row[0] if last_event_row else None
    watcher = getattr(request.app.state, "watcher", None)
    # projection_state (migrations/026) is how this crosses the process
    # boundary now that serve --watch runs the watcher in its own
    # process (live.py's WatcherProcess) rather than a thread sharing
    # this one's GIL. Read defensively: a database that predates 026 and
    # has never been touched by 'ingest'/'project' since (which migrate
    # on open) simply hasn't got the table yet — an ordinary outcome,
    # not a 500.
    try:
        projection_row = conn.execute(
            "SELECT last_projection_at, projections FROM projection_state WHERE id = 1"
        ).fetchone()
    except sqlite3.OperationalError:
        projection_row = None
    last_projection = projection_row[0] if projection_row else None
    projections = projection_row[1] if projection_row else 0
    return LiveStatus(
        watching=bool(watcher and watcher.is_alive()),
        mtgo_watching=bool(watcher and watcher.is_alive() and getattr(watcher, "mtgo_dir", None)),
        watcher_stopped=bool(watcher and getattr(watcher, "stopped_unexpectedly", lambda: False)()),
        last_ingest_at=last_ingest,
        last_checked_at=last_checked,
        last_event_at=last_event,
        last_projection_at=last_projection,
        events=newest_event or 0,
        matches=counts["matches"],
        games=counts["games"],
        turns=counts["turns"],
        # Ingestion moves the row id; projection moves the counts. Both must
        # register, or the dashboard would sit on a stale rebuild. Card
        # events are counted too: a turn in progress accumulates plays and
        # draws without the turn count changing, and the current-match view
        # has to follow that.
        revision=f"{newest_event or 0}:{counts['matches']}:"
        f"{counts['games']}:{counts['turns']}:{counts['card_events']}",
        # A deliberately narrower signal than revision above: revision moves
        # on every ingest tick (roughly once a second while Arena runs),
        # which is why keying the dashboard's query invalidation on it turned
        # "refetch when the data changes" into "refetch everything every 3s
        # forever" (the dashboard's heartbeat keyed on revision). This one
        # leads with projections — the watcher's own rebuild counter,
        # incremented once per completed project() regardless of whether any
        # derived row COUNT actually moved (a match flipping from incomplete
        # to won rewrites its row without changing matches' row count) — so
        # it catches a live rebuild's content-only changes that the counts
        # alone would miss. The counts stay appended for the case nothing
        # increments projections at all: a bare `project(conn)` call with no
        # watcher attached (tests, or `sensei-top project` followed by
        # `serve` without --watch) never touches projection_state, so
        # without the counts this would never move outside a watched
        # session.
        projection_revision=f"{projections}:{counts['matches']}:"
        f"{counts['games']}:{counts['turns']}:{counts['card_events']}",
    )


@router.get("/api/decks", response_model=list[Deck], tags=["decks"])
def decks(conn: Conn) -> list[dict[str, Any]]:
    """Every deck some match was played with, with enough context to pick one
    out of a list.

    A deck no match is picked to is left out: an MTGO deck (from the store or
    an export) no match is picked to yet has a ``v_deck_summary`` row with no
    matches, and a zero-match entry in the deck dropdown or a deck page is a
    dead end.
    The MTGO picker reads its own candidates route, so it still sees them.

    ``first_played`` is the deck's earliest match start, from one grouped
    pass over ``matches JOIN v_match_deck`` (the view's COALESCE has no index,
    so a per-deck filter would rescan it for every deck). ``first_seen`` is
    when the deck was first recorded, which for an MTGO deck is the day the
    file was saved, not the day it was played.
    """
    return _rows(
        conn,
        """
        WITH first_played AS (
            SELECT md.deck_id, MIN(m.started_at) AS first_played
              FROM matches m
              JOIN v_match_deck md ON md.match_id = m.match_id
             GROUP BY md.deck_id
        )
        SELECT s.deck_id, s.name, s.format, s.matches_played, s.matches_won,
               s.last_played, fp.first_played, s.first_seen, s.last_seen
          FROM v_deck_summary s
          LEFT JOIN first_played fp ON fp.deck_id = s.deck_id
         WHERE s.matches_played > 0
         ORDER BY COALESCE(s.last_played, s.last_seen, '') DESC
        """,
    )


@router.get("/api/formats", response_model=FormatsOut, tags=["meta"])
def formats(conn: Conn) -> FormatsOut:
    """Every format, in ``formats.py``'s order, with the user's matches of it
    by ``v_match_format.format_source`` (D6), whether archetype rules are
    stored for it, how many tournament events the corpus holds for it, and
    the default a page shows when its address names no format (D13,
    ``api/sql.py::default_format``). A format with nothing is still listed,
    with zeros: the dashboard decides which ones to offer.
    """
    matches: dict[str, dict[str, int]] = {fmt: {} for fmt in FORMATS}
    for row in conn.execute(
        """
        SELECT format, format_source, COUNT(*) AS n
          FROM v_match_format
         WHERE format IS NOT NULL
         GROUP BY format, format_source
        """
    ):
        if row["format"] in matches:
            matches[row["format"]][row["format_source"]] = row["n"]
    rules = {
        row[0]
        for row in conn.execute("SELECT DISTINCT format FROM archetypes WHERE kind = 'archetype'")
    }
    events = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT format, COUNT(*) FROM meta_event WHERE duplicate_of IS NULL GROUP BY format"
        )
    }
    entries = []
    for fmt in FORMATS:
        by_source = matches[fmt]
        counts = FormatMatchCounts(
            log=by_source.get("log", 0),
            pick=by_source.get("pick", 0),
            inferred=by_source.get("inferred", 0),
            total=sum(by_source.values()),
        )
        entries.append(
            FormatEntry(
                format=fmt, matches=counts, has_rules=fmt in rules,
                corpus_events=events.get(fmt, 0),
            )
        )
    return FormatsOut(formats=entries, default=default_format(conn))
