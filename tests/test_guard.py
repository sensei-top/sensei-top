"""Tests for ``api/guard.py``'s ``LoopbackGuard`` — the CSRF/DNS-rebinding
guard that sits outermost on every route (``api/app.py``).

The app here is a fresh, migrated-but-empty database (``open_database`` then
``create_app``), never the ingested fixture ``test_api.py`` uses: every test
below is about the guard stepping aside or refusing, never about match data.
Clients are bare ``TestClient(app, base_url=...)`` with headers set per case
— ``conftest.py``'s ``make_client`` fixture is for *other* modules that want
to look like the dashboard and not think about the guard at all.
"""

import asyncio
import re
from contextlib import asynccontextmanager

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from sensei_top.api import create_app
from sensei_top.api.guard import CLIENT_HEADER, LoopbackGuard, is_loopback_host
from sensei_top.db import open_database


@pytest.fixture(autouse=True)
def _no_claude_calls(monkeypatch):
    """This module deliberately pokes at every non-GET route, including the
    four ``.../narrative`` ones. ``conftest.py``'s ``_no_ambient_config``
    already keeps a real credential out of the environment, but a test here
    must fail loudly — not place a real, billed call — if that isolation
    ever regresses. ``llm/client.py::_run`` is the one place every Claude
    call goes through (``client.messages.stream(...)``)."""

    def _forbidden(*args, **kwargs):
        pytest.fail("a test in test_guard.py tried to call the Claude API")

    monkeypatch.setattr("sensei_top.llm.client._run", _forbidden)


@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "t.db"
    open_database(db_path).close()
    return create_app(db_path)


# --- is_loopback_host --------------------------------------------------------


@pytest.mark.parametrize(
    "host, expected",
    [
        ("localhost", True),
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("::1", True),
        ("LOCALHOST", False),  # no case folding at this layer — callers fold first
        ("localhost.", False),
        ("foo.localhost", False),
        ("rebind.evil.example", False),
        ("10.0.0.1", False),  # private, not loopback
        ("[::1]", False),  # brackets aren't stripped here; the Host parser does that
        ("", False),
    ],
)
def test_is_loopback_host(host, expected):
    assert is_loopback_host(host) is expected


# --- Host header parsing, through the middleware -----------------------------


@pytest.mark.parametrize(
    "host_header", ["127.0.0.1:8000", "LOCALHOST:8000", "[::1]:8000", "localhost"]
)
def test_host_header_naming_loopback_passes(app, host_header):
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.get("/api/health", headers={"host": host_header})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "host_header",
    ["rebind.evil.example", "127.0.0.1:8000:1", "user@127.0.0.1", "::1:8000"],
)
def test_host_header_not_naming_loopback_is_refused(app, host_header):
    """``::1:8000`` is the unbracketed form — a real IPv6-with-port Host must
    bracket the address (``[::1]:8000``), so this is indistinguishable from
    a bare name containing colons, which the parser was never going to
    accept either way."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.get("/api/health", headers={"host": host_header})
    assert response.status_code == 400
    assert response.json() == {"detail": "Host not allowed"}


def test_missing_host_header_is_refused(app):
    """HTTP effectively requires a Host header, so no real client can send a
    request without one — but a raw ASGI scope can, and the guard must
    still refuse it (rather than crash on a ``None`` or fall through)."""
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/health",
        "headers": [],
        "query_string": b"",
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 400


# --- the two 2026-09-26 reproductions -----------------------------------------


def test_2026_09_26_dns_rebinding_get_is_now_refused(app):
    """Verified 2026-09-26: ``GET /api/llm/status`` with
    ``Host: rebind.evil.example`` answered 200 before this guard existed — a
    DNS-rebinding page could have read the whole match history."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.get("/api/llm/status", headers={"host": "rebind.evil.example"})
    assert response.status_code == 400


def test_2026_09_26_cross_site_coach_post_is_now_refused(app):
    """Verified 2026-09-26: ``POST /api/coach/narrative`` with
    ``Origin: https://evil.example`` and ``Content-Type: text/plain`` reached
    the handler (503 only for lack of a credential) — any web page's no-cors
    ``fetch()`` could have spent a configured Claude credential."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.post(
        "/api/coach/narrative",
        headers={"origin": "https://evil.example", "content-type": "text/plain"},
    )
    assert response.status_code == 403


# --- every non-GET route needs the header ------------------------------------

# Route introspection only, on a path that is never opened (mirrors
# test_api.py::test_only_authored_artifact_routes_write's own
# create_app("unused.db")) — this exists purely to build the parametrize
# list at collection time, before the `app` fixture (which needs `tmp_path`)
# is available.
_ROUTE_SWEEP_APP = create_app("unused.db")


def _non_get_routes() -> list:
    """``(method, concrete_path)`` for every non-GET/HEAD route the app
    serves, substituting a dummy value for every ``{param}`` — there is
    ``{key}`` (the guide route) as well as ``{match_id}``, so this replaces
    generically rather than naming either one.

    Walks ``iter_route_contexts`` rather than ``app.routes`` directly, for
    the same reason ``test_api.py::test_only_authored_artifact_routes_write``
    does: every route arrives via ``include_router``, and plain ``app.routes``
    holds one opaque wrapper per included router, not the routes themselves.
    """
    params = []
    for route in iter_route_contexts(_ROUTE_SWEEP_APP.routes):
        methods = route.methods or ()
        concrete_path = re.sub(r"\{[^}]+\}", "dummy", route.path)
        for method in sorted(methods):
            if method not in ("GET", "HEAD"):
                params.append(pytest.param(method, concrete_path, id=f"{method}_{concrete_path}"))
    return params


@pytest.mark.parametrize("method, path", _non_get_routes())
def test_non_get_route_without_client_header_is_refused(app, method, path):
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.request(method, path)
    assert response.status_code == 403
    assert response.json() == {"detail": f"Missing {CLIENT_HEADER} header"}


@pytest.mark.parametrize("method, path", _non_get_routes())
def test_non_get_route_with_client_header_reaches_the_route(app, method, path):
    """Whatever comes back is this route's own business (404/422/503 have
    all been seen here) — the only claim is that the guard stepped aside."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.request(method, path, headers={CLIENT_HEADER: "dashboard"})
    assert response.status_code not in (400, 403)


# --- Origin -------------------------------------------------------------------


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:8000", "http://[::1]:8000"])
def test_loopback_origin_passes_a_put(app, origin):
    """``localhost:5173`` is the Vite dev port talking to the API on 8000 —
    a different port than Host, on purpose (docs/frontend.md "Ports")."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.put(
        "/api/matches/dummy/opponent-deck",
        headers={"origin": origin, CLIENT_HEADER: "dashboard"},
        json={"label": "Rogue"},
    )
    assert response.status_code not in (400, 403)


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "null",
        "http://[::1",  # malformed IPv6 netloc — urlsplit itself raises
        "http://127.0.0.1:99999",  # port out of range — .port raises
        "http://user@127.0.0.1:8000",  # userinfo present
        "ftp://127.0.0.1",  # non-http(s) scheme
    ],
)
def test_foreign_or_null_origin_is_refused_even_on_get(app, origin):
    """The four new cases each exercise a distinct failure branch of
    ``_origin_is_loopback`` that the first two cases don't reach: a
    ``urlsplit`` exception, a ``.port`` exception, rejected userinfo, and a
    rejected scheme. All are refused the same way as an ordinary foreign
    origin — a parse failure is exactly as foreign as a parse success naming
    another host."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.get("/api/health", headers={"origin": origin})
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-origin request refused"}


# --- fetch metadata -------------------------------------------------------


def test_cross_site_no_cors_image_get_is_refused(app):
    """The shape of a cross-site ``<img src>`` load, which sends no Origin
    at all — fetch metadata is what catches this, not the Origin check."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.get(
        "/api/health",
        headers={
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "no-cors",
            "sec-fetch-dest": "image",
        },
    )
    assert response.status_code == 403


def test_cross_site_top_level_navigation_passes(app):
    """A link to the dashboard from another page must still open."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.get(
        "/api/health",
        headers={
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
        },
    )
    assert response.status_code == 200


def test_same_site_iframe_is_refused(app):
    """Same-site is refused too: another port on 127.0.0.1 is same-site to a
    browser, which is exactly the ``python -m http.server`` attacker."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.get(
        "/api/health",
        headers={
            "sec-fetch-site": "same-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "iframe",
        },
    )
    assert response.status_code == 403


@pytest.mark.parametrize("site", ["same-origin", "none"])
def test_same_origin_or_absent_fetch_site_passes(app, site):
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.get("/api/health", headers={"sec-fetch-site": site})
    assert response.status_code == 200


def test_same_origin_post_without_client_header_is_still_refused(app):
    """Fetch metadata alone doesn't satisfy check 4 — a same-origin POST
    still needs the dashboard's own header."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.post("/api/coach/narrative", headers={"sec-fetch-site": "same-origin"})
    assert response.status_code == 403


def test_post_claiming_navigation_fetch_metadata_is_still_refused(app):
    """The navigation exception in check 3 is GET/HEAD-only (``_evaluate``'s
    own docstring) — a POST cannot claim it just by sending the same
    ``sec-fetch-mode: navigate``/``sec-fetch-dest: document`` pair a real
    link click would send. The client header is present here, so check 4
    cannot be what refuses this request: this is the only test that fails
    if ``method in ("GET", "HEAD")`` were dropped from check 3's exception."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.post(
        "/api/coach/narrative",
        headers={
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
            CLIENT_HEADER: "dashboard",
        },
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-origin request refused"}


# --- OPTIONS preflight ---------------------------------------------------


def test_options_preflight_with_foreign_origin_is_refused_and_carries_no_cors_header(app):
    """There is no CORS middleware and never was: nothing here ever sends
    ``Access-Control-Allow-Origin``, so a preflight can never succeed even if
    this 403 didn't exist — but it does, so the browser never gets far
    enough to notice that on its own."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.request(
        "OPTIONS",
        "/api/coach/narrative",
        headers={"origin": "https://evil.example", "access-control-request-method": "POST"},
    )
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


# --- frame headers ---------------------------------------------------------


def test_frame_headers_present_on_success_404_and_guard_rejection(app):
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    ok = client.get("/api/health")
    not_found = client.get("/api/does-not-exist")
    refused = client.get("/api/health", headers={"origin": "https://evil.example"})

    assert (ok.status_code, not_found.status_code, refused.status_code) == (200, 404, 403)
    for response in (ok, not_found, refused):
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["content-security-policy"] == "frame-ancestors 'none'"


# --- lifespan ---------------------------------------------------------------


def test_lifespan_passes_through_the_guard():
    """``lifespan`` is neither ``http`` nor ``websocket`` — the guard must
    step aside unconditionally rather than needing its own opinion about
    process startup."""
    started = {"value": False}

    @asynccontextmanager
    async def lifespan(app):
        started["value"] = True
        yield

    guarded = LoopbackGuard(Starlette(lifespan=lifespan))

    with TestClient(guarded):
        assert started["value"] is True


# --- websocket ---------------------------------------------------------------


async def _echo(websocket):
    await websocket.accept()
    await websocket.send_text("hello")
    await websocket.close()


def _websocket_app():
    return LoopbackGuard(Starlette(routes=[WebSocketRoute("/ws", _echo)]))


def test_websocket_with_loopback_host_connects():
    client = TestClient(_websocket_app(), base_url="http://127.0.0.1:8000")
    with client.websocket_connect("/ws", headers={"host": "127.0.0.1"}) as websocket:
        assert websocket.receive_text() == "hello"


def test_websocket_with_foreign_host_is_refused():
    """Confirmed by direct experiment against the installed Starlette
    (1.6.0): sending ``websocket.close`` before ``accept`` surfaces from
    ``websocket_connect()`` as a ``WebSocketDisconnect`` carrying the close
    code — not a handshake-level HTTP 403 — for this version's TestClient."""
    client = TestClient(_websocket_app(), base_url="http://127.0.0.1:8000")
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws", headers={"host": "evil.example"}),
    ):
        pass
    assert exc_info.value.code == 1008


# --- logging -----------------------------------------------------------------


def test_a_refusal_logs_one_warning_naming_method_path_and_value(app, caplog):
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    with caplog.at_level("WARNING", logger="sensei_top.api.guard"):
        response = client.get("/api/health", headers={"host": "rebind.evil.example"})
    assert response.status_code == 400

    records = [r for r in caplog.records if r.name == "sensei_top.api.guard"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "GET" in message
    assert "/api/health" in message
    assert repr("rebind.evil.example") in message
