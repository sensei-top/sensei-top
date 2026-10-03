"""The dashboard mount (``api/dashboard.py``): a page's address answers
``index.html``, a file answers the file, and ``api`` and ``assets`` keep
their 404.

Every case runs against a ``web/dist`` the test writes itself in
``tmp_path``, with ``sensei_top.api.app.WEB_DIST`` pointed at it, so no
case depends on whether the real dashboard has been built. Each file's
content is a string the test chose, and the assertions compare against
that string: what a response should hold is known before the app
answers.
"""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from sensei_top.api import create_app
from sensei_top.db import open_database

INDEX_HTML = "<!doctype html><title>dashboard</title>"
APP_JS = "console.log('dashboard');"
FAVICON = "<svg>favicon</svg>"


def _write_dist(dist: Path) -> None:
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML)
    (dist / "assets" / "app.js").write_text(APP_JS)
    (dist / "favicon.svg").write_text(FAVICON)


@pytest.fixture
def app(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    _write_dist(dist)
    monkeypatch.setattr("sensei_top.api.app.WEB_DIST", dist)

    db_path = tmp_path / "api.db"
    open_database(db_path).close()
    return create_app(db_path)


@pytest.fixture
def client(app, make_client):
    with make_client(app) as c:
        yield c


def test_root_answers_index_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == INDEX_HTML


@pytest.mark.parametrize("path", ["/matches/abc", "/decks/x/guide"])
def test_a_page_address_answers_index_html(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX_HTML
    assert response.headers["content-type"].startswith("text/html")


def test_a_real_file_answers_the_file(client):
    assert client.get("/assets/app.js").text == APP_JS
    assert client.get("/favicon.svg").text == FAVICON


def test_a_missing_asset_keeps_its_404(client):
    response = client.get("/assets/missing.js")
    assert response.status_code == 404
    assert response.text != INDEX_HTML


def test_an_unknown_api_path_is_a_json_404_not_the_page(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.text != INDEX_HTML


@pytest.mark.parametrize(
    "path",
    [
        "/assets%5Cmissing.js",
        "/api%5Cnope",
        "/%5Capi%5Cnope",
        "/%5Cassets%5Cmissing.js",
    ],
)
def test_a_windows_style_path_also_keeps_its_404(client, path):
    """``%5C`` decodes to a literal backslash within one path segment, the
    same string ``StaticFiles.get_path`` would build on Windows by joining
    ``assets``/``api`` with a file name using the OS separator. A leading
    ``%5C`` is Windows' own leading separator, the same shape a leading
    ``/`` takes on this system."""
    response = client.get(path)
    assert response.status_code == 404
    assert response.text != INDEX_HTML


def test_head_of_a_page_address_has_no_body(client):
    response = client.head("/matches/abc")
    assert response.status_code == 200
    assert response.content == b""


def test_health_route_still_answers_from_its_route(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_post_to_a_page_address_never_answers_the_page(client, app):
    with_header = client.post("/matches/abc")
    assert with_header.status_code != 200
    assert with_header.text != INDEX_HTML
    # Starlette's own get_response (named in dashboard.py's module
    # docstring) raises 405 for a method other than GET/HEAD.
    assert with_header.status_code == 405

    bare = TestClient(app, base_url="http://127.0.0.1:8000")
    without_header = bare.post("/matches/abc")
    assert without_header.status_code != 200
    assert without_header.text != INDEX_HTML
    # api/guard.py rejects a non-GET request with no X-Tracker-Client header.
    assert without_header.status_code == 403


def test_a_climbing_path_never_escapes_the_directory(client, tmp_path):
    """The client library rewrites a literal ``/../x`` before it ever leaves
    this process, so the case that actually reaches the server is the
    encoded form, ``/%2e%2e/x``."""
    secret = tmp_path / "secret.txt"
    secret.write_text("outside the dist directory")

    response = client.get("/%2e%2e/secret.txt")
    assert response.status_code in (200, 404)
    assert "outside the dist directory" not in response.text


def test_with_no_web_dist_a_page_address_is_404(tmp_path, monkeypatch, make_client):
    monkeypatch.setattr("sensei_top.api.app.WEB_DIST", tmp_path / "nowhere")
    db_path = tmp_path / "api2.db"
    open_database(db_path).close()
    with make_client(create_app(db_path)) as c:
        response = c.get("/matches/abc")
    assert response.status_code == 404
