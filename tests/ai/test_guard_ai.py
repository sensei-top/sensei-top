"""The guard's cases that name an AI route (``api/guard.py``). Split from
``tests/test_guard.py``, whose docstring has the setup: the guard refuses
before routing, so these hold without ``ai/`` too, but they name routes it
mounts. Every Claude call is forbidden here (``conftest.py``'s ``no_claude_calls``).
"""

import pytest
from fastapi.testclient import TestClient

from sensei_top.api import create_app
from sensei_top.api.guard import CLIENT_HEADER
from sensei_top.db import open_database

pytestmark = pytest.mark.usefixtures("no_claude_calls")


@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "t.db"
    open_database(db_path).close()
    return create_app(db_path)


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
