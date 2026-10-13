"""M3: read-only JSON API over the metric views (brief §3), plus the small
allowlist of routes that write an authored artifact.

The dashboard reads here and nowhere else. Two rules shape this package:

* **Aggregation a ``SELECT`` can express stays in SQL.** Every *metric*
  endpoint is a thin ``SELECT`` over a view (``migrations/001_init.sql`` and
  later); a new metric of that shape owes a view rather than a loop in a
  handler. Endpoints serving a feature package's own analysis (``review/``,
  ``guide/``, ``table/``) call that package and convert its
  dataclasses instead — statistics SQLite cannot express (Wilson intervals,
  hypergeometric odds, medians) legitimately live in Python. See
  "Aggregation: views versus Python" in ``docs/architecture.md`` for the test
  of which side something belongs on.
* **The API writes only authored-artifact tables, never anything the
  projector rebuilds.** Connections are opened with ``PRAGMA query_only=ON``,
  so a bug here cannot corrupt data the reader spent a session collecting.
  Note that ``sqlite3.connect`` *creates* a missing file, which is itself a
  write, so the path is checked before connecting. The allowlist:

  - ``PUT /api/matches/{id}/opponent-deck`` — a manual deck label, the
    user's own words about their own match, with no other source, in the
    one table (``opponent_deck_override``) that has to outlive the full
    rebuild that erases every derived row.
  - ``PUT /api/matches/{id}/mtgo-pick`` — the user's own deck and format
    for an MTGO match, which MTGO's log never names, in the one table
    (``mtgo_match_pick``) that keeps it: the same kind of answer as the
    label above, with no other source, kept through the rebuild for the
    same reason.
  - ``POST /api/matches/{id}/report/narrative``, ``POST
    /api/review/leaks/narrative``, ``POST /api/guide/{key}/narrative``,
    ``POST /api/coach/narrative`` — an opt-in, user-triggered Claude call
    (``sensei_top.llm``, AGENTS.md non-negotiable #5; see
    ``docs/llm.md``) that writes prose into ``match_narrative``,
    ``leaks_narrative``, or ``deck_narrative`` plus ``matchup_brief`` — or,
    for the coach route, ``coach_report``. None of these tables is ever
    read by ``project()``. ``POST /api/guide/{key}/rcq/narrative`` is the
    same kind of call and writes ``rcq_guide``, keeping every row.

  ``tests/test_api.py::test_only_authored_artifact_routes_write`` asserts
  this is still the exact set of non-GET routes — an addition is a design
  change, not a patch. ``GET /api/cards/{grp_id}/image`` reads the database
  like every other route, but also writes to disk outside it — it lazily
  caches Scryfall card images as plain files beside the database, never as
  rows, so the allowlist above stays the whole story for what can write to
  SQLite itself.

Binding is left to the caller (``cli.py serve`` binds 127.0.0.1 only). The
projector owns every table it derives; this layer is disposable for
everything except the authored artifacts above.

Binding loopback-only is necessary but not sufficient: a browser on this
machine is itself a loopback client, so any page it has open can send
requests here. ``api/guard.py``'s ``LoopbackGuard``, the outermost
middleware, refuses three kinds: a ``Host`` that doesn't name loopback (a
DNS-rebinding page, which would otherwise read everything as if
same-origin); a foreign ``Origin`` or cross-site/same-site fetch metadata (a
no-cors ``text/plain`` POST from any web page reaches a metered
``.../narrative`` route without a preflight — the attack this guard was
written for); and a non-GET request without the dashboard's own
``X-Tracker-Client`` header, which a page can't add cross-origin because the
preflight it forces never succeeds here. It also forbids framing, so no
other page can overlay the dashboard and trick a click on a button that
spends a credential (clickjacking).

**Package layout** (the architecture-remediation split): ``deps.py`` holds
the two connection dependencies and the deck filter; ``sql.py`` the small
SQL helpers and request-scoped caches shared across routers; ``convert.py``
the dataclass-to-wire-model translation layer; ``models/`` the ~85 response
models, one file per router; ``routes/`` one ``APIRouter`` per file below,
in the exact order they were once defined inline here — ``paths`` in
``web/openapi.json`` is insertion-ordered, so that order is load-bearing,
not cosmetic. ``dashboard.py`` holds the mount that serves the built
dashboard and answers a page's address with the page. This module is left
as the ~80 lines that actually construct the app.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as package_version
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from sensei_top.api.dashboard import DashboardFiles
from sensei_top.api.guard import LoopbackGuard
from sensei_top.api.routes import (
    cards,
    coach,
    current_match,
    guide,
    matches,
    meta,
    metagame,
    metrics,
    mtgo_picks,
    rcq,
    review,
)
from sensei_top.i18n import use_language

# The built dashboard ships inside the package (``web_dist/``, gitignored,
# written by ``pnpm build``). ``StaticFiles`` needs a real directory, which
# an installed wheel and a source checkout both give.
WEB_DIST = Path(str(files("sensei_top") / "web_dist"))


class RequestLanguage:
    """Translate each request's prose into the language its
    ``Accept-Language`` asks for (``i18n.py``): the dashboard sends the
    user's choice on every request, and the server stores none.

    Pure ASGI, like ``LoopbackGuard``, so the ``ContextVar`` it sets is the
    one the route sees — FastAPI copies the context into the threadpool
    worker that runs a sync route — and is reset when the response is sent.
    A request the guard refuses never gets this far.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        header = Headers(scope=scope).get("accept-language")
        with use_language(header):
            await self.app(scope, receive, send)


@asynccontextmanager
async def _stop_watcher_on_shutdown(app: FastAPI) -> AsyncIterator[None]:
    """The server's shutdown stops the watcher. It is the one hook that runs
    on a SIGTERM as well as on Ctrl+C: uvicorn turns either signal into this
    shutdown, then re-raises it, and a re-raised SIGTERM ends the process
    before ``cmd_serve``'s own ``finally`` runs (``procs.py``)."""
    yield
    if app.state.watcher is not None:
        app.state.watcher.stop()


def create_app(db_path: str | Path, watcher: object | None = None) -> FastAPI:
    """Build the app around one database file.

    ``watcher`` is an optional object with ``is_alive()`` and ``stop()`` — a
    ``live.WatcherProcess`` in practice, running the rebuild in a separate OS
    process so it stops contending with every request for this process's GIL
    (see ``WatcherProcess``'s own docstring for the measurements). Requests
    only ever ask it ``is_alive()``, for the /api/live status flag, plus
    ``mtgo_dir`` and ``stopped_unexpectedly()`` (both read with ``getattr``)
    for ``mtgo_watching`` and ``watcher_stopped``; everything
    else that flag reports (``last_projection_at``) is read from the database's
    ``projection_state`` table instead, since a separate process can't share
    in-memory state with this one. The API itself stays read-only either way.
    The app's shutdown calls ``stop()``: ``cmd_serve`` starts the watcher, but
    its own ``finally`` never runs on a SIGTERM.
    """
    database = Path(db_path)
    app = FastAPI(
        title="Sensei Top",
        description="Local, read-only analytics over a Magic: The Gathering Arena log.",
        version=package_version("sensei-top"),
        lifespan=_stop_watcher_on_shutdown,
    )
    # The last middleware added runs first, so the guard stays outermost and
    # the language is only set for a request it lets through.
    app.add_middleware(RequestLanguage)
    app.add_middleware(LoopbackGuard)
    app.state.database = database
    app.state.watcher = watcher
    # Cache for the current-match hand read's archetype consensus (see
    # api/sql.py::_cached_consensus). It holds exactly one entry: it clears
    # on any key miss, so switching to a new opponent archetype mid-session
    # clears it just as a `sensei-top meta` refresh does (the key is
    # (archetype_key, corpus token, format-reset window) — any one of the
    # three changing counts as a miss).
    app.state.consensus_cache = {}
    # Cache for the format-reset window that consensus is scoped to (see
    # api/sql.py::_cached_consensus_window), one entry per (corpus token,
    # format): every format's entry is cleared when the corpus token
    # (api/sql.py::_corpus_token) changes, never when only the format
    # differs. format_resets is a full meta_deck JOIN meta_event scan and
    # _cached_consensus runs on the current-match heartbeat.
    app.state.consensus_window_cache = {}
    # One-entry cache for the current match's v_match_opponent row (see
    # api/sql.py::_cached_match_opponent) — cleared whenever card_events
    # grows, since that is the only thing that can move what the view says
    # mid-match.
    app.state.opponent_cache = {}
    # Cache for the corpus naming source's CorpusPrior (see
    # api/sql.py::_cached_corpus_prior), one entry per (corpus token,
    # format): every format's entry is cleared when the corpus token
    # (api/sql.py::_corpus_token) changes, since that is the whole corpus
    # each prior is built from, and never when only the format differs.
    app.state.corpus_prior_cache = {}
    # One-entry cache for the mana-source grpId set the live replay needs
    # (see api/sql.py::_cached_mana_source_grp_ids) — cleared whenever
    # `cards` is refreshed, since that is the only thing that can change it.
    app.state.mana_source_cache = {}
    # Cross-request MatchReport cache shared by the Leaks/Guide/Coach routes
    # (see api/sql.py::_shared_report_cache) — held as `None` until the first
    # request builds it, then as a `(token, dict)` pair keyed on
    # api/sql.py::_report_inputs_token. A token change replaces the pair
    # rather than clearing the dict in place, the same held-tuple pattern
    # `break_cache`/`break_classify_caches` use (those two stay lazily
    # created instead of pre-registered here, since they only exist at all
    # once a match reaches a break).
    app.state.report_cache = None

    # Registered in the same order these routes were once defined inline in
    # this file — paths in the generated OpenAPI schema are insertion-ordered,
    # so this order is part of the contract, not just tidiness.
    app.include_router(meta.router)
    app.include_router(current_match.router)
    app.include_router(metrics.router)
    app.include_router(metagame.router)
    app.include_router(matches.router)
    app.include_router(mtgo_picks.router)
    app.include_router(review.router)
    app.include_router(guide.router)
    app.include_router(rcq.router)
    app.include_router(coach.router)
    app.include_router(cards.router)

    # Serve the built dashboard when it exists, so a single command gives the
    # whole tool. In development Vite serves the UI and proxies /api here.
    # Mounted last, at "/", so it takes every path no route above took,
    # an unknown /api path among them (api/dashboard.py).
    if WEB_DIST.is_dir():
        app.mount("/", DashboardFiles(directory=WEB_DIST, html=True), name="dashboard")

    return app
