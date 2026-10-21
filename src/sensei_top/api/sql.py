"""Small SQL helpers shared across routers: the "SELECT into plain dicts"
primitive every metric endpoint builds on, the deck filter every metric
endpoint appends, the caches kept on ``app.state`` across requests, and
the one conversion (turn zones) that is itself a database read, not
a pure dataclass-to-model translation — which is what keeps it out of
``convert.py``.
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from fastapi import Request

from sensei_top.archetypes.corpus import CorpusPrior, build_prior
from sensei_top.guide.window import format_resets, window_start
from sensei_top.projector.live_state import LiveState
from sensei_top.review.consensus import ArchetypeConsensus, build_consensus
from sensei_top.review.leaks import ReportCache
from sensei_top.table import live
from sensei_top.table.intermission import BreakRead, build_break_read, opponent_seen_names


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params)]


def _attach_zones(
    conn: sqlite3.Connection, match_id: str, game_number: int, turns: list[dict[str, Any]]
) -> None:
    """Mutate ``turns`` in place, adding each turn's zone contents.

    Turns are still plain dicts here (models are constructed after this
    runs), so the zones list is attached before ``CurrentTurn`` validates the
    dict — pydantic has no hook to reach back into the database.
    """
    zone_rows = _rows(
        conn,
        """
        SELECT turn_number, zone, idx, instance_id, grp_id, card_name, card_types,
               drawn_on_turn, is_tapped, power, toughness, is_self,
               mana_cost, type_line, colors
          FROM v_turn_zones WHERE match_id = ? AND game_number = ?
         ORDER BY turn_number, zone, idx
        """,
        (match_id, game_number),
    )
    by_turn: dict[int, list[dict[str, Any]]] = {}
    for row in zone_rows:
        by_turn.setdefault(row.pop("turn_number"), []).append(row)
    for turn in turns:
        turn["zones"] = by_turn.get(turn["turn_number"], [])


def _filtered(
    sql: str, deck_id: str | None, extra: str = "", source: str = "arena"
) -> tuple[str, tuple[Any, ...]]:
    """Append optional deck and source filters. Views are already aggregated
    per deck and per source (migration 035), so filtering is a WHERE on the
    outer select. A caller whose rows two sources can share (the null
    ``deck_id`` of every deckless match) adds its own ``GROUP BY`` after it,
    so ``'all'`` answers one row per group rather than one per source.

    ``source`` is a literal source name (``'arena'`` by default, or
    ``'mtgo'``), or ``'all'`` for no source filter (``deps.SourceFilter``).
    """
    clauses, params = [], []
    if deck_id:
        clauses.append("v.deck_id = ?")
        params.append(deck_id)
    if source != "all":
        clauses.append("v.source = ?")
        params.append(source)
    if extra:
        clauses.append(extra)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return sql + where, tuple(params)


def _corpus_token(conn: sqlite3.Connection) -> tuple[str, str, int, str]:
    """A single cheap fingerprint for "has the metagame corpus changed",
    shared by every cache below that keys on it: ``meta_fetch``'s own fetch
    stamp (the fbettega cache's single row), ``meta_fetch_source``'s own
    (which also catches a TopDeck.gg-only refresh that never touches
    ``meta_fetch`` at all — see migration 022), and ``meta_deck_archetype``'s
    own count and classification stamp, which is what actually moves when
    ``sensei-top meta`` classifies. Each field is ``COALESCE``d against an
    empty corpus (no fetch yet, nothing classified yet), so a fresh database
    has a defined token rather than a ``NULL`` that would compare unequal to
    itself across calls.

    ``meta_event.duplicate_of`` (migration 043) does not need its own
    component here. ``mark_duplicate_events`` (the dedup pass that sets it)
    has one caller, ``metagame/auto.py::reclassify_corpus``, which follows
    it at once with a full ``classify_meta_decks`` that deletes and
    reinserts every row of ``meta_deck_archetype`` with a fresh, shared
    ``classified_at``. So a dedup pass always moves
    ``MAX(meta_deck_archetype.classified_at)`` too, even one that changed no
    ``COUNT(*)`` (a dedup that only marked an event whose children were
    already gone). The corpus's two live readers gated by this token
    (``review/consensus.py::build_consensus``, ``archetypes/corpus.py::
    build_prior``) both ``JOIN`` through ``meta_deck_archetype`` anyway, so a
    duplicate's deletion is invisible to them regardless of ``duplicate_of``
    itself. The one raw ``meta_deck`` scan unfiltered by classification
    (``guide/window.py::format_resets``, reached via ``_cached_consensus_
    window`` below) is covered the same indirect way: it cannot see a dedup's
    effect without that same reclassification having already moved
    ``classified_at``.
    """
    fetch = conn.execute(
        "SELECT COALESCE(MAX(fetched_at), '') FROM meta_fetch"
    ).fetchone()[0]
    fetch_source = conn.execute(
        "SELECT COALESCE(MAX(fetched_at), '') FROM meta_fetch_source"
    ).fetchone()[0]
    archetype_count, archetype_classified = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(classified_at), '') FROM meta_deck_archetype"
    ).fetchone()
    return (fetch, fetch_source, archetype_count, archetype_classified)


def _cached_mana_source_grp_ids(request: Request, conn: sqlite3.Connection) -> frozenset[int]:
    """``table.live._mana_source_grp_ids``, cached on ``app.state`` and keyed
    on ``cards``' own row count: reference data that only changes on a
    ``cards`` refresh, and a full scan otherwise paid on every
    ``/api/current-match/read`` poll (its cost: docs/current-match.md,
    "Wiring: one route")."""
    cache: dict[int, frozenset[int]] = request.app.state.mana_source_cache
    token = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    if token not in cache:
        cache.clear()  # the token changed; nothing older stays valid anyway
        cache[token] = live._mana_source_grp_ids(conn)
    return cache[token]


def default_format(conn: sqlite3.Connection) -> str:
    """The format a page shows when its address names none: the format
    of the user's most recent match that has one in ``v_match_format`` (the
    log's, else the MTGO pick, else the inference), and Standard when no
    match has one. ``/api/formats`` reports it, and every route whose
    ``format`` query parameter is omitted reads it from here.

    Most recent means latest ``started_at``; a match with none sorts last,
    and ``match_id`` breaks a tie so the answer is the same on every call.
    """
    row = conn.execute(
        """
        SELECT f.format
          FROM v_match_format f
          JOIN matches m ON m.match_id = f.match_id
         WHERE f.format IS NOT NULL
         ORDER BY COALESCE(m.started_at, '') DESC, m.match_id DESC
         LIMIT 1
        """
    ).fetchone()
    return row[0] if row is not None else "Standard"


def match_format(conn: sqlite3.Connection, match_id: str) -> str | None:
    """One match's read-time format (``v_match_format``), or ``None``
    when nothing names one. ``None`` is passed on as it is: a match with no
    format gets no corpus prior and no consensus window, never Standard's."""
    row = conn.execute(
        "SELECT format FROM v_match_format WHERE match_id = ?", (match_id,)
    ).fetchone()
    return row[0] if row is not None else None


def _consensus_window(conn: sqlite3.Connection, fmt: str | None) -> str | None:
    """The format-reset window to pass as ``build_consensus``'s own
    ``since``, computed the same way ``coach/evidence.py::build_coach_evidence``
    does: the latest reset of ``fmt``, as its ``window_start``, or ``None``
    when no reset has been detected (there isn't one yet, or no legality
    data exists to detect one from) or ``fmt`` is ``None`` (a match no
    source names a format for).

    Callers needing an opponent consensus (``_cached_consensus`` below,
    ``api/routes/matches.py``) must call this and pass the result through
    rather than defaulting ``consensus_since`` to ``None`` themselves —
    ``review/snapshot.py::build_snapshot``'s docstring explains why ``None``
    is not a neutral default. This repeats ``coach/evidence.py``'s own
    ``format_resets``/``window_start`` call rather than sharing it: ``review/``
    cannot import ``guide.window`` (a package cycle, ``review/snapshot.py``'s
    docstring), and this layer has no access to the value
    ``coach/evidence.py`` computes. Both query ``guide/window.py``'s
    ``format_resets``, the one source of truth.
    """
    if fmt is None:
        return None
    resets = format_resets(conn, fmt)
    reset = resets[0] if resets else None
    return window_start(reset) if reset is not None else None


# A cache miss, told apart from a cached None: no reset and no prior are
# both real answers worth keeping.
_MISSING = object()


def _per_format(cache: dict[tuple, Any], token: tuple, fmt: str | None) -> tuple:
    """The ``(token, fmt)`` key for a cache holding one entry per format.

    A new corpus token drops every format's entry, since none of them is
    valid any more; a format not seen yet under the current token is only
    added, so switching between formats does not rebuild the others.
    ``list(cache)`` copies the keys before reading them, because a request in
    another thread may add an entry while this one looks.
    """
    if any(key[0] != token for key in list(cache)):
        cache.clear()  # the token changed; nothing older stays valid anyway
    return (token, fmt)


def _cached_consensus_window(
    request: Request, conn: sqlite3.Connection, token: tuple, fmt: str | None
) -> str | None:
    """``_consensus_window`` memoized on ``app.state`` per ``(token, fmt)``,
    ``token`` being the corpus's own ``_corpus_token``. ``format_resets`` is
    a full ``meta_deck JOIN meta_event`` scan, and ``_cached_consensus`` runs
    on every ``/api/current-match/read`` poll, so computing it per call would
    reintroduce exactly the scan that cache exists to avoid.

    Keyed on the corpus token, like the consensus beside it: a ``sensei-top
    meta`` refresh invalidates it for free. A legality-only refresh (``cards
    --scryfall``) does not, so a ban detected purely from new legality data
    waits for the next corpus fetch to take effect here — the same staleness
    the consensus cache already accepts, and a restart clears it either way.
    """
    cache: dict[tuple, str | None] = request.app.state.consensus_window_cache
    key = _per_format(cache, token, fmt)
    cached = cache.get(key, _MISSING)
    if cached is not _MISSING:
        return cached
    window = _consensus_window(conn, fmt)
    cache[key] = window
    return window


def _cached_consensus(
    request: Request,
    conn: sqlite3.Connection,
    opponent_key: str | None,
    fmt: str | None,
) -> ArchetypeConsensus | None:
    """``build_consensus`` for the current match's opponent archetype,
    cached on ``app.state`` under ``(archetype_key, fmt, corpus token,
    window)``, the token being ``_corpus_token``: a ``sensei-top meta``
    refresh invalidates the cache for free. It holds one entry, and any miss
    clears it, a new opponent archetype included. Without this, every
    ``/api/current-match/read`` poll would re-scan ``meta_deck`` while a game
    runs.

    The window is ``_consensus_window(conn, fmt)`` (via
    ``_cached_consensus_window``, itself cached on the same token), so a
    consensus built before a format reset is detected is never handed back
    once one is, without paying a ``format_resets`` scan on every poll —
    only on a token miss.

    ``fmt`` is required: it narrows the consensus to that format's corpus
    decks, and it is the format whose reset windows the consensus. ``None``
    (a match with no format) has no consensus and no window.
    """
    if not opponent_key or not opponent_key.startswith("archetype:"):
        return None
    archetype_key = opponent_key.removeprefix("archetype:")
    token = _corpus_token(conn)
    window = _cached_consensus_window(request, conn, token, fmt)
    cache: dict[tuple[str, str | None, tuple, str | None], ArchetypeConsensus | None] = (
        request.app.state.consensus_cache
    )
    cache_key = (archetype_key, fmt, token, window)
    cached = cache.get(cache_key, _MISSING)
    if cached is not _MISSING:
        return cached  # type: ignore[return-value]
    cache.clear()  # the archetype, token, format or window changed; nothing older stays valid
    consensus = build_consensus(conn, archetype_key, fmt=fmt, board="main", since=window)
    cache[cache_key] = consensus
    return consensus


def _cached_match_opponent(
    request: Request, conn: sqlite3.Connection, match_id: str
) -> dict[str, Any] | None:
    """``v_match_opponent``'s row for one match, cached on ``app.state`` and
    keyed on ``(match_id, projection_state.projections)``: the view's
    ``v_opponent_cards`` CTE can't push a ``match_id`` filter down (it
    materializes every match's opponent-card history to answer a question
    about one), and ``projections`` is a single-row read that moves exactly
    when a rebuild commits, where ``COUNT(*) FROM card_events`` is an
    unindexed scan of a table that grows every game. Both costs:
    docs/current-match.md, "Wiring: one route".

    Known narrow gap: ``projections`` is incremented by ``live.py``'s
    watcher after each rebuild it drives (``LiveIngester.project_if_due``),
    not by ``project()`` itself — a bare ``sensei-top project`` run against a
    database served by a *non*-``--watch`` ``serve`` process would not move
    this token. That combination is already a degenerate one for a *live*
    current-match read (nothing is ingesting in real time either), so it is
    accepted rather than paying for a count on every request."""
    cache: dict[tuple[str, int], dict[str, Any] | None] = request.app.state.opponent_cache
    try:
        token = conn.execute(
            "SELECT projections FROM projection_state WHERE id = 1"
        ).fetchone()
        token = token[0] if token else 0
    except sqlite3.OperationalError:
        # A pre-026 database has no projection_state table (the API never
        # migrates): fall back to the always-available, if pricier, signal
        # rather than crash. One no watcher has touched has the table and no
        # row, and reads 0 above.
        token = conn.execute("SELECT COUNT(*) FROM card_events").fetchone()[0]
    cache_key = (match_id, token)
    if cache_key not in cache:
        cache.clear()  # the token changed; nothing older stays valid anyway
        row = conn.execute(
            """
            SELECT opponent_key, opponent_label, opponent_source,
                   opponent_confidence, opponent_cards_seen, opponent_colors,
                   opponent_signature_cards
              FROM v_match_opponent WHERE match_id = ?
            """,
            (match_id,),
        ).fetchone()
        cache[cache_key] = dict(row) if row is not None else None
    return cache[cache_key]


def _cached_break_read(
    request: Request,
    conn: sqlite3.Connection,
    match_id: str,
    deck_id: str | None,
    live_state: LiveState | None,
) -> BreakRead | None:
    """``table.intermission.build_break_read`` for the current match's Bo3
    break, cached on ``app.state`` and keyed on everything that can change
    its answer, so a 1 Hz poll during a break costs one replay (already paid
    for by the caller to get ``live_state``) plus a dictionary lookup, not a
    second full opponent classification on every beat. What the key holds
    and why: docs/current-match.md, "Wiring: one route".

    ``opponent_deck_override`` and ``matchup_brief`` are in the key because
    a manual pick, or a brief imported from the prompt this card offers, is
    exactly what the user does *during* the break and must show at once —
    and neither moves a projection token. The reference token below is in
    it too: a fresh ``sensei-top meta`` run can change which stored brief
    classifies as the closest alternative.

    ``build_break_read``'s own slower loads live in a second dict this
    function keeps across polls and hands in as ``caches``
    (``table/intermission.py`` says why its per-match entries hold still for
    a whole match). That dict is keyed on the reference data alone (the
    corpus token and the ``archetypes`` and ``cards`` row counts), so a
    reprojection during the break re-runs only the cheap classification,
    while a ``meta``/``archetypes``/``cards`` refresh still takes effect
    without a restart. The costs: docs/current-match.md, "The break read
    (`table/intermission.py`)".

    Returns ``None`` immediately, before touching any cache, when there is
    no live state or the match is not on a break right now — the common
    case on every poll of a game actually in progress.

    Neither cache is pre-registered on ``app.state`` (unlike the others in
    this module); both are created lazily on first use.
    """
    if live_state is None or live_state.intermission is None:
        return None

    reference_token = (
        _corpus_token(conn),
        conn.execute("SELECT COUNT(*) FROM archetypes").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
    )
    held = getattr(request.app.state, "break_classify_caches", None)
    if held is None or held[0] != reference_token:
        held = (reference_token, {})
        request.app.state.break_classify_caches = held
    classify_caches: dict[str, Any] = held[1]

    names = opponent_seen_names(conn, match_id, live_state)
    try:
        projections_row = conn.execute(
            "SELECT projections FROM projection_state WHERE id = 1"
        ).fetchone()
        projections_token: Any = projections_row[0] if projections_row else 0
    except sqlite3.OperationalError:
        # A pre-026 database: the same fallback as _cached_match_opponent.
        projections_token = conn.execute("SELECT COUNT(*) FROM card_events").fetchone()[0]
    override = conn.execute(
        "SELECT label, archetype_key FROM opponent_deck_override WHERE match_id = ?",
        (match_id,),
    ).fetchone()

    briefs = tuple(conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(generated_at), '') FROM matchup_brief"
    ).fetchone())

    cache_key = (
        match_id,
        deck_id,
        live_state.intermission.game_number,
        frozenset(names),
        tuple(override) if override is not None else None,
        briefs,
        projections_token,
        reference_token,
    )
    cache: dict[tuple[Any, ...], BreakRead | None] = getattr(
        request.app.state, "break_cache", None
    )
    if cache is None:
        cache = {}
        request.app.state.break_cache = cache
    if cache_key not in cache:
        cache.clear()  # the key changed; nothing older stays valid anyway
        cache[cache_key] = build_break_read(
            conn, match_id, deck_id, live_state, caches=classify_caches, names=names,
        )
    return cache[cache_key]


def _cached_corpus_prior(
    request: Request, conn: sqlite3.Connection, fmt: str | None
) -> CorpusPrior | None:
    """``archetypes.corpus.build_prior`` for ``fmt``, cached on ``app.state``
    per ``(token, fmt)``, ``token`` being ``_corpus_token`` — the same
    pattern as ``_cached_consensus_window``, for the same reason: building it
    rescans every classified corpus deck of the format, and both
    ``rank_candidates`` (the picker) and, indirectly, ``classify_matches``
    (which builds its own, uncached, since it runs once per full
    reclassification rather than once per request) need the same read of the
    same corpus. ``COUNT(*)`` catches a fresh ``sensei-top meta`` fetch
    adding decks; ``MAX(classified_at)`` catches a format-reset boundary
    changing which archetypes are 'gone' (``guide.window.structural_change``)
    without changing the row count.

    ``fmt`` is the match's ``v_match_format.format``. ``None`` (no source
    names one) is no prior at all, never Standard's, and is not cached.
    """
    if fmt is None:
        return None
    token = _corpus_token(conn)
    cache: dict[tuple, CorpusPrior | None] = request.app.state.corpus_prior_cache
    key = _per_format(cache, token, fmt)
    cached = cache.get(key, _MISSING)
    if cached is not _MISSING:
        return cached
    prior = build_prior(conn, fmt)
    cache[key] = prior
    return prior


def _table_digest(conn: sqlite3.Connection, sql: str) -> str:
    """``blake2b(digest_size=16)`` over every row ``sql`` returns, each row
    turned into ``repr(tuple(row))`` and fed in in the query's own
    ``ORDER BY`` — deterministic across calls the way a bare ``hash()``
    is not, and far cheaper than round-tripping the rows out to Python for a
    caller to compare itself. ``sql`` must carry its own ``ORDER BY``: two
    calls that returned the same rows in a different order must not be
    allowed to hash unequal."""
    hasher = hashlib.blake2b(digest_size=16)
    for row in conn.execute(sql):
        hasher.update(repr(tuple(row)).encode("utf-8"))
    return hasher.hexdigest()


def _report_inputs_token(conn: sqlite3.Connection) -> tuple[Any, ...]:
    """Fingerprints every database input a completed match's ``MatchReport``
    (``review/match_report.py::build_match_report``, via every analyzer in
    ``review/analyzers/`` and ``archetypes/classify.py``'s ``rank_candidates``)
    can read, cheap enough to check on every request where rebuilding every
    completed match's report (``find_leaks``) is not.

    Two things a completed match's report also touches are deliberately left
    out of this token:

    - ``projection_state.projections`` moves on every live rebuild, and the
      watcher rebuilds every few seconds whenever Arena is open — even
      sitting in a menu — so keying on it would invalidate a *completed*
      match's report just as often as an in-progress one's.
    - ``raw_events`` is never read by anything this token covers.

    Neither omission is a gap: a completed match's derived rows are a pure
    function of its own raw events, which are append-only, so a rebuild that
    adds no new match data reproduces a completed match's rows exactly —
    only the fields folded in below can actually move what a completed
    report reads.

    ``opponent_archetype`` is digested on every column *except*
    ``classified_at``: ``classify_matches`` re-stamps that column on every
    rebuild, including ones that changed no verdict, so keying on it would
    empty this cache as often as ``projections`` above would.
    ``matches``/``games``/``decks``/``opponent_deck_override``/
    ``mtgo_match_pick``/``match_format_inference`` are digested on every
    column, since any of them can change what a report says (a
    corrected result, an edited deck list, a manual deck override, an MTGO
    match's picked deck, which ``v_match_deck`` reads in place of
    ``matches.deck_id``) without necessarily changing row counts.

    ``turns``/``card_events``/``turn_zones``/``life_events``/
    ``damage_events``/``combat_attacks``/``combat_blocks`` use
    ``MAX(rowid)`` rather than ``COUNT(*)`` — each an O(log n) index lookup,
    where ``COUNT(*)`` is a full scan (``_cached_match_opponent``). Because
    ``project()`` always deletes and reinserts (non-negotiable #3), an
    unchanged rebuild reproduces the same rowids, so this is not a weaker
    signal than a count would be — just a cheaper one.

    The corpus, cards and archetype-definition fields mirror what
    ``review/consensus.py`` and ``archetypes/classify.py`` actually read:
    ``_corpus_token`` plus ``meta_deck``/``meta_round_match`` counts (the
    field matchup join reads rounds, not just decks), the cards table's own
    stamp (``COUNT(*)``, ``COUNT(*)`` of ``card_legality``, ``COUNT(oracle_id)``,
    ``MAX(updated_at)`` — ``cards.py::_backfill_by_name`` updates legality
    without touching ``updated_at``, which is why the counts are there too),
    and the downloaded archetype definitions' own count and fetch stamp.
    """
    # SELECT *, not a column list: a column a later migration adds must move
    # this token without anyone remembering to add it here.
    matches_digest = _table_digest(conn, "SELECT * FROM matches ORDER BY match_id")
    games_digest = _table_digest(
        conn, "SELECT * FROM games ORDER BY match_id, game_number"
    )
    decks_digest = _table_digest(conn, "SELECT * FROM decks ORDER BY deck_id")
    # Every column but classified_at, read from the schema for the same reason.
    oa_columns = ", ".join(
        row[0]
        for row in conn.execute(
            "SELECT name FROM pragma_table_info('opponent_archetype') "
            "WHERE name <> 'classified_at' ORDER BY cid"
        )
    )
    opponent_archetype_digest = _table_digest(
        conn, f"SELECT {oa_columns} FROM opponent_archetype ORDER BY match_id, format"
    )
    opponent_deck_override_digest = _table_digest(
        conn, "SELECT * FROM opponent_deck_override ORDER BY match_id"
    )

    mtgo_match_pick_digest = _table_digest(
        conn, "SELECT * FROM mtgo_match_pick ORDER BY match_id"
    )

    # What v_match_format reads for an MTGO match: a changed inference moves
    # a report's format, and so its corpus, without touching the tables above.
    format_inference_digest = _table_digest(
        conn, "SELECT * FROM match_format_inference ORDER BY match_id"
    )

    max_rowids = tuple(
        conn.execute(f"SELECT COALESCE(MAX(rowid), 0) FROM {table}").fetchone()[0]
        for table in (
            "turns", "card_events", "turn_zones", "life_events",
            "damage_events", "combat_attacks", "combat_blocks",
        )
    )

    meta_deck_count = conn.execute("SELECT COUNT(*) FROM meta_deck").fetchone()[0]
    meta_round_match_count = conn.execute(
        "SELECT COUNT(*) FROM meta_round_match"
    ).fetchone()[0]

    cards_row = tuple(conn.execute(
        """
        SELECT COUNT(*),
               (SELECT COUNT(*) FROM card_legality),
               COUNT(oracle_id),
               COALESCE(MAX(updated_at), '')
          FROM cards
        """
    ).fetchone())

    archetypes_count = conn.execute("SELECT COUNT(*) FROM archetypes").fetchone()[0]
    archetype_fetch_at = conn.execute(
        "SELECT COALESCE(MAX(fetched_at), '') FROM archetype_fetch"
    ).fetchone()[0]

    return (
        matches_digest,
        games_digest,
        decks_digest,
        opponent_archetype_digest,
        opponent_deck_override_digest,
        mtgo_match_pick_digest,
        format_inference_digest,
        max_rowids,
        _corpus_token(conn),
        meta_deck_count,
        meta_round_match_count,
        cards_row,
        archetypes_count,
        archetype_fetch_at,
    )


def _shared_report_cache(
    request: Request, conn: sqlite3.Connection
) -> ReportCache:
    """The cross-request ``MatchReport`` cache that every ``find_leaks`` call
    (``api/routes/review.py``), ``build_deck_guide`` (``guide/bundle.py``,
    via ``api/routes/guide.py``; via ``guide/rcq.py::build_rcq`` from
    ``api/routes/rcq.py``; and directly from
    ``api/routes/rcq.py::rcq_markdown``) and ``build_coach_evidence``
    (``coach/evidence.py``, via ``api/routes/coach.py``) share, keyed by
    ``_report_inputs_token``. A ``MatchReport`` depends only on the database
    and ``consensus_since``
    (``review/leaks.py::find_leaks``'s own docstring) — and on the language
    its findings were written in, which is why its key
    (``review/leaks.py::report_cache_key``, read inside ``find_leaks`` and
    ``coach/evidence.py``, never here) carries the language: a page loaded
    in Portuguese and a prompt, always English, share this dict without
    sharing a report. So it is safe to reuse across requests and across
    these callers as long as the token has not moved: the first request
    after something actually changed pays for every report, and every
    request after that until the next change is a dict lookup.

    Only completed matches ever enter the inner dict: every current consumer
    already filters to them before calling ``build_match_report``
    (``find_leaks`` scans ``result IN ('win', 'loss')``; the coach's
    population is completed matches too), so an in-progress match's report —
    which *can* change from one poll to the next — never gets the chance to
    be cached stale. ``api/routes/matches.py``'s single-match report route
    deliberately does not use this cache: one report is cheap, and it may be
    exactly the in-progress match this cache must never see.

    Held as ``(token, dict)`` on ``app.state.report_cache`` rather than a
    bare dict keyed by token, and *replaced* rather than cleared on a miss:
    FastAPI runs handlers in a threadpool, so a concurrent request may still
    be iterating the old dict between its own ``in`` check and its read of
    it — ``.clear()``-ing that dict out from under it would turn that read
    into a ``KeyError`` instead of an ordinary cache miss. Replacing the
    tuple leaves every reference already holding the old dict intact; the
    same pattern ``_cached_break_read``'s ``held`` tuple already uses above.
    """
    token = _report_inputs_token(conn)
    held = request.app.state.report_cache
    if held is None or held[0] != token:
        held = (token, {})
        request.app.state.report_cache = held
    return held[1]
