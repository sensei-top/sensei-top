"""AGENTS.md rule 6's full allowlist, with ``ai/`` mounted. Its core half,
``tests/test_api.py::test_core_alone_writes_only_the_picks``, asserts the
picks alone without it.
"""

from fastapi.routing import iter_route_contexts

from sensei_top.api import create_app


def test_only_authored_artifact_routes_write():
    """AGENTS.md rule 6 allows writes only to authored-artifact tables, never
    anything the projector rebuilds. A route outside this allowlist is a
    design change, not a patch — this test is where that conversation
    starts.

    Walks ``iter_route_contexts`` rather than ``app.routes`` directly: since
    the API became a package of routers, every route arrives via
    ``include_router``, and FastAPI resolves those lazily — ``app.routes``
    holds one opaque wrapper per included router, not the routes themselves.
    ``iter_route_contexts`` is what FastAPI's own ``get_openapi`` walks, so
    this sees exactly the set the published schema does.
    """
    app = create_app("unused.db")
    writers = {
        (route.path, method)
        for route in iter_route_contexts(app.routes)
        for method in (route.methods or ())
        if method not in ("GET", "HEAD")
    }
    assert writers == {
        ("/api/matches/{match_id}/opponent-deck", "PUT"),
        ("/api/matches/{match_id}/mtgo-pick", "PUT"),
        ("/api/mtgo/picks", "PUT"),
        ("/api/matches/{match_id}/report/narrative", "POST"),
        ("/api/review/leaks/narrative", "POST"),
        ("/api/guide/{key}/narrative", "POST"),
        ("/api/guide/{key}/rcq/narrative", "POST"),
        ("/api/coach/narrative", "POST"),
        # Pasted answers: no model call, only the same tables.
        ("/api/guide/{key}/narrative", "PUT"),
        ("/api/guide/{key}/rcq/narrative", "PUT"),
        ("/api/guide/{key}/briefs/{archetype_key}", "PUT"),
        ("/api/guide/{key}/coverage", "PUT"),
        ("/api/matches/{match_id}/report/narrative", "PUT"),
        ("/api/review/leaks/narrative", "PUT"),
        ("/api/coach/narrative", "PUT"),
    }


def test_openapi_schema_names_the_narrative_route():
    """The frontend's types are generated from this schema, so it must name
    the match report's narrative endpoint the dashboard calls."""
    schema = create_app("unused.db").openapi()
    assert "/api/matches/{match_id}/report/narrative" in schema["paths"]
