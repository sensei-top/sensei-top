"""The read-only JSON API over the metric views, plus the small allowlist of
routes that write an authored artifact. The dashboard reads here and nowhere
else.

Two rules shape this package, both in docs/conventions.md, "API": aggregation
a ``SELECT`` can express stays in a view (the test for which side a statistic
belongs on is docs/architecture.md, "Aggregation: views versus Python"), and
every connection opens ``PRAGMA query_only=ON`` except the one
``deps.get_writable_conn`` hands to the authored-artifact routes. Which
tables those may write, and why, is AGENTS.md non-negotiable 6;
``tests/test_api.py::test_only_authored_artifact_routes_write`` pins the
exact set of non-GET routes, so an addition is a design change, not a patch.
``GET /api/cards/{grp_id}/image`` and ``/art`` write too, but picture files
beside the database, never rows (docs/architecture.md, "Who owns which
table").

Binding is left to the caller: ``cli.py::_require_loopback`` refuses any
``serve --host`` that isn't loopback. A loopback bind alone isn't enough,
and ``api/guard.py``'s module docstring says why and what ``LoopbackGuard``,
the outermost middleware, refuses.

Package layout: ``deps.py`` the connection dependencies and the deck and
source filters; ``sql.py`` the SQL helpers shared across routers and the
caches kept on ``app.state`` across requests; ``convert.py`` the
dataclass-to-wire-model translation; ``models/`` the response models, grouped
by router, the shared ones in ``common.py``; ``routes/`` one
``APIRouter`` per file (``narrative.py`` is shared plumbing, not a router),
registered in ``create_app`` in an order the schema depends on;
``dashboard.py`` the mount that serves the built dashboard.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as package_version
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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
from sensei_top.i18n import _, use_language

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


async def database_busy(request: Request, exc: Exception) -> JSONResponse:
    """A write that waited out ``deps.WRITE_BUSY_TIMEOUT_MS`` behind the
    watcher's rebuild is answered 503 with a sentence the dashboard shows,
    rather than a 500 and a traceback: nothing was written, and the same
    request succeeds once the rebuild commits. A read can meet the same lock,
    so only a write says nothing was saved. Any other ``OperationalError``
    is re-raised, so it stays the 500 it was."""
    code = getattr(exc, "sqlite_errorcode", None)
    if code is None or code & 0xFF not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        raise exc
    if request.method == "GET":
        detail = _("The database is busy with a rebuild. Try again in a moment.")
    else:
        detail = _(
            "The database is busy with a rebuild, so nothing was saved. "
            "Try again in a moment."
        )
    return JSONResponse(status_code=503, content={"detail": detail})


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
    (docs/architecture.md, "Live mode's two cadences", has the measurements).
    Requests only ever ask it ``is_alive()``, for the /api/live status flag,
    plus ``mtgo_dir`` and ``stopped_unexpectedly()`` (both read with
    ``getattr``) for ``mtgo_watching`` and ``watcher_stopped``; everything
    else that flag reports (``last_projection_at``) is read from the
    database's ``projection_state`` table instead, since a separate process
    can't share in-memory state with this one. The API itself stays read-only
    either way. The app's shutdown calls ``stop()``
    (``_stop_watcher_on_shutdown``).
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
    app.add_exception_handler(sqlite3.OperationalError, database_busy)
    app.state.database = database
    app.state.watcher = watcher
    # The caches api/sql.py keeps across requests. Each one's key, and what
    # clears it, is in the docstring of the api/sql.py function named beside
    # it. `break_cache`/`break_classify_caches` are not registered here:
    # _cached_break_read creates them on first use.
    app.state.consensus_cache = {}         # _cached_consensus
    app.state.consensus_window_cache = {}  # _cached_consensus_window
    app.state.opponent_cache = {}          # _cached_match_opponent
    app.state.corpus_prior_cache = {}      # _cached_corpus_prior
    app.state.mana_source_cache = {}       # _cached_mana_source_grp_ids
    app.state.report_cache = None          # _shared_report_cache, None until built

    # Paths in the generated OpenAPI schema (web/openapi.json) are
    # insertion-ordered, so this order is part of the contract, not tidiness.
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
