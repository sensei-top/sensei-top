"""The seam between core and ``sensei_top.ai``: ``create_app`` and
``build_parser`` reach ``ai/`` only when ``importlib.util.find_spec`` finds
it, and an app built without it carries ``api/providers.py``'s
``NO_PROVIDERS``.

A core test: it must pass with ``src/sensei_top/ai/`` deleted, so it never
imports ``sensei_top.ai`` statically, and the cases that need ``ai/`` skip
without it. Hiding ``ai/`` is ``find_spec`` answering ``None``; the package
stays in ``sys.modules`` through core's remaining static edges, which is
why the build without it still mounts ``CORE_NARRATIVE_ROUTES``.
"""

import importlib.util

import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from starlette.routing import Mount

from sensei_top.api import create_app
from sensei_top.api.providers import NO_PROVIDERS, Providers, providers_of
from sensei_top.cli import build_parser
from sensei_top.db import open_database

# The ``.../narrative`` routes still mounted by core's own routers
# (``api/routes/``), not by ``sensei_top.ai.routers``. Pinned so that no new
# one joins them; every route leaving for ``ai/routes/`` leaves this set.
CORE_NARRATIVE_ROUTES = {
    "/api/matches/{match_id}/report/narrative",
    "/api/review/leaks/narrative",
    "/api/guide/{key}/narrative",
    "/api/guide/{key}/rcq/narrative",
    "/api/coach/narrative",
    "/api/coach/narrative/{report_id}",
}


def _hide_ai(monkeypatch):
    real = importlib.util.find_spec

    def find_spec(name, package=None):
        if name == "sensei_top.ai" or name.startswith("sensei_top.ai."):
            return None
        return real(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)


@pytest.fixture
def hide_ai(monkeypatch):
    _hide_ai(monkeypatch)


@pytest.fixture
def build(tmp_path, monkeypatch):
    """``create_app`` over an empty database, with a built dashboard so the
    catch-all mount is there to be ordered against."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>t</title>")
    monkeypatch.setattr("sensei_top.api.app.WEB_DIST", dist)
    db_path = tmp_path / "seam.db"
    open_database(db_path).close()
    return lambda: create_app(db_path)


def _paths(app: FastAPI) -> set[str]:
    """Every route's path, through included routers
    (``test_api.py::test_only_authored_artifact_routes_write`` says why)."""
    return {route.path for route in iter_route_contexts(app.routes)}


def _dashboard_is_last(app: FastAPI) -> bool:
    last = app.routes[-1]
    return isinstance(last, Mount) and last.name == "dashboard"


def _subcommands(parser) -> set[str]:
    (action,) = [a for a in parser._actions if a.dest == "command"]
    return set(action.choices)


# --- the app ---------------------------------------------------------------


def test_without_ai_the_app_mounts_no_ai_route(hide_ai, build, make_client):
    app = build()

    paths = _paths(app)
    assert "/api/llm/status" not in paths
    assert {p for p in paths if p.endswith("/narrative") or "/narrative/" in p} == (
        CORE_NARRATIVE_ROUTES
    )
    assert _dashboard_is_last(app)
    with make_client(app) as client:
        assert client.get("/api/health").status_code == 200
        missing = client.get("/api/llm/status")
    # An unknown /api path is the catch-all's JSON 404, never the page.
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")


def test_without_ai_no_seam_is_filled(hide_ai, build):
    assert providers_of(build()) is NO_PROVIDERS


def test_with_ai_its_routers_mount_before_the_dashboard(build, make_client):
    pytest.importorskip("sensei_top.ai")
    app = build()

    assert "/api/llm/status" in _paths(app)
    assert _dashboard_is_last(app)
    with make_client(app) as client:
        status = client.get("/api/llm/status")
    # Answered by its route: mounted after the catch-all, it would be the
    # catch-all's JSON 404.
    assert status.status_code == 200
    assert set(status.json()) == {"configured", "model"}


# --- the providers ---------------------------------------------------------


def test_each_app_keeps_the_providers_it_was_built_with(build, monkeypatch):
    ai = pytest.importorskip("sensei_top.ai")
    lent = Providers()
    monkeypatch.setattr(ai, "providers", lambda: lent)
    with_ai = build()
    _hide_ai(monkeypatch)
    without = build()

    assert providers_of(with_ai) is lent
    assert providers_of(without) is NO_PROVIDERS


def test_an_app_built_elsewhere_provides_nothing():
    assert providers_of(FastAPI()) is NO_PROVIDERS


# --- the CLI ---------------------------------------------------------------


def test_without_ai_the_parser_still_builds(hide_ai):
    commands = _subcommands(build_parser())

    assert {"ingest", "project", "report", "serve", "doctor"} <= commands


def test_with_ai_the_parser_hands_its_subparsers_to_register_cli(monkeypatch):
    ai = pytest.importorskip("sensei_top.ai")
    calls = []
    monkeypatch.setattr(ai, "register_cli", calls.append)

    build_parser()

    (sub,) = calls
    assert "ingest" in sub.choices


def test_register_cli_adds_no_subcommand_yet(monkeypatch):
    with monkeypatch.context() as m:
        _hide_ai(m)
        without = _subcommands(build_parser())
    pytest.importorskip("sensei_top.ai")

    assert _subcommands(build_parser()) == without
