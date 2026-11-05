"""``telemetry``: Sentry starts only with a DSN and the consent, and every
event is scrubbed before it can leave.

Nothing here sends: the gating tests never start a client, the hook tests
call ``before_send`` directly, and the one test that starts the SDK gives it
a transport that only records, with a DSN under ``.invalid`` (RFC 2606),
which resolves nowhere. Expected strings follow ``scrub.py``'s docstring and
``fixtures/scrub_vectors.json``; every identifier is synthetic.
"""

import json
import logging
from importlib.metadata import version

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from sensei_top import telemetry

FAKE_DSN = "https://publickey@sentry.example.invalid/1"
ACCOUNT_ID = "00000000-0000-4000-8000-000000000001"
PLANTED_PATH = "C:\\Users\\zorblax\\AppData\\Local\\sensei-top\\x.db"
SCRUBBED_PATH = "C:\\Users\\<user>\\AppData\\Local\\sensei-top\\x.db"
PLANTED_EMAIL = "zorblax@example.com"


class Recorder(Transport):
    """Keeps every envelope the client hands it; sends nothing."""

    def __init__(self) -> None:
        super().__init__()
        self.envelopes = []

    def capture_envelope(self, envelope) -> None:
        self.envelopes.append(envelope)


@pytest.fixture(autouse=True)
def no_client(monkeypatch):
    for name in (telemetry.DSN_ENV, telemetry.CONSENT_ENV, telemetry.USER_ENV, "SENTRY_DSN"):
        monkeypatch.delenv(name, raising=False)
    sentry_sdk.get_global_scope().set_client(None)
    yield
    client = sentry_sdk.get_client()
    if client.is_active():
        client.close()
    sentry_sdk.get_global_scope().set_client(None)


# --- gating: no DSN or no consent, no client ---


@pytest.mark.parametrize(
    "env",
    [
        {},
        {telemetry.CONSENT_ENV: "1"},
        {telemetry.DSN_ENV: "   ", telemetry.CONSENT_ENV: "1"},
        {telemetry.DSN_ENV: FAKE_DSN},
        {telemetry.DSN_ENV: FAKE_DSN, telemetry.CONSENT_ENV: "0"},
        {telemetry.DSN_ENV: FAKE_DSN, telemetry.CONSENT_ENV: "yes"},
        {telemetry.DSN_ENV: FAKE_DSN, telemetry.CONSENT_ENV: ""},
    ],
    ids=[
        "nothing",
        "consent-without-dsn",
        "blank-dsn",
        "dsn-without-consent",
        "consent-0",
        "consent-not-1",
        "consent-empty",
    ],
)
def test_no_dsn_or_no_consent_never_starts_the_sdk(env, tmp_path, monkeypatch):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert telemetry.options(tmp_path / "x.db") is None
    assert telemetry.init(tmp_path / "x.db") is False
    assert not sentry_sdk.get_client().is_active()


def test_a_rejected_dsn_is_a_warning_not_a_failed_serve(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv(telemetry.DSN_ENV, "not a dsn")
    monkeypatch.setenv(telemetry.CONSENT_ENV, "1")
    with caplog.at_level(logging.WARNING, logger="sensei_top.telemetry"):
        assert telemetry.init(tmp_path / "x.db") is False
    assert not sentry_sdk.get_client().is_active()
    assert "not a dsn" not in caplog.text
    assert "error reports not started" in caplog.text


# --- the options: no sessions, no tracing, no PII, few integrations ---


def test_options_carry_no_sessions_tracing_or_pii(tmp_path):
    env = {telemetry.DSN_ENV: FAKE_DSN, telemetry.CONSENT_ENV: "1"}
    opts = telemetry.options(tmp_path / "x.db", env)
    assert opts is not None
    assert opts["dsn"] == FAKE_DSN
    assert opts["release"] == version("sensei-top")
    assert opts["server_name"] == ""
    assert opts["auto_session_tracking"] is False
    assert opts["traces_sample_rate"] is None
    assert opts["send_client_reports"] is False
    assert opts["include_local_variables"] is False
    assert opts["max_breadcrumbs"] == 0
    assert opts["default_integrations"] is False
    assert {i.identifier for i in opts["integrations"]} == {
        "starlette",
        "fastapi",
        "logging",
        "dedupe",
        "atexit",
    }
    collection = opts["data_collection"]
    assert collection["user_info"] is False
    assert collection["stack_frame_variables"] is False
    assert collection["http_bodies"] == []
    for key in ("cookies", "url_query_params"):
        assert collection[key] == {"mode": "off"}
    assert collection["http_headers"] == {"request": {"mode": "off"}}
    assert "send_default_pii" not in opts
    assert "transport" not in opts


# --- before_send, called directly ---


def _event() -> dict:
    """An event in the shape the SDK hands ``before_send``: an exception with
    a frame, a log message with a parameter, a breadcrumb, a request."""
    return {
        "event_id": "0" * 32,
        "level": "error",
        "server_name": "zorblax-laptop",
        "user": {"id": "someone-else", "ip_address": "{{auto}}"},
        "logentry": {
            "message": "could not open %s",
            "params": [PLANTED_PATH],
            "formatted": f"could not open {PLANTED_PATH}",
        },
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": f"mail {PLANTED_EMAIL} for Wibblesnoot at {PLANTED_PATH}",
                    "stacktrace": {
                        "frames": [
                            {
                                "abs_path": PLANTED_PATH,
                                "function": "open",
                                "lineno": 3,
                            }
                        ]
                    },
                }
            ]
        },
        "breadcrumbs": {"values": [{"message": f"wrote to {PLANTED_EMAIL}"}]},
        "transaction": "/api/x/{who}",
        "transaction_info": {"source": "route"},
        "request": {
            "url": "http://127.0.0.1:8000/api/x/Wibblesnoot?who=Wibblesnoot",
            "method": "GET",
        },
    }


def test_before_send_scrubs_a_planted_path_email_and_name():
    hook = telemetry.make_before_send(ACCOUNT_ID, lambda: ["Wibblesnoot"])
    out = hook(_event(), {})
    text = repr(out)
    for planted in ("zorblax", PLANTED_EMAIL, "Wibblesnoot"):
        assert planted not in text
    exc = out["exception"]["values"][0]
    assert exc["value"] == f"mail <email> for <name> at {SCRUBBED_PATH}"
    assert exc["stacktrace"]["frames"][0]["abs_path"] == SCRUBBED_PATH
    assert exc["stacktrace"]["frames"][0]["lineno"] == 3
    assert out["logentry"]["params"] == [SCRUBBED_PATH]
    assert out["logentry"]["formatted"] == f"could not open {SCRUBBED_PATH}"
    assert out["breadcrumbs"]["values"][0]["message"] == "wrote to <email>"
    assert out["request"]["url"] == "/api/x/{who}"


def test_before_send_sends_the_account_id_alone_and_no_hostname():
    out = telemetry.make_before_send(ACCOUNT_ID, list)(_event(), {})
    assert out["user"] == {"id": ACCOUNT_ID}
    assert "server_name" not in out
    assert set(out["contexts"]["os"]) == {"name", "version"}


def test_before_send_without_an_account_sends_no_user():
    out = telemetry.make_before_send(None, list)(_event(), {})
    assert "user" not in out


def test_before_send_reads_the_names_per_event():
    seen = []
    hook = telemetry.make_before_send(None, lambda: seen)
    hook({"message": "Wibblesnoot"}, {})
    seen.append("Wibblesnoot")
    assert hook({"message": "Wibblesnoot"}, {})["message"] == "<name>"


# --- the SDK started for real, with a transport that records ---


def test_a_captured_error_leaves_scrubbed_with_no_local_variables(tmp_path, monkeypatch):
    # known_names reads the MTGO handle from here; the database does not exist.
    monkeypatch.setenv("MTGO_HANDLE", "Wibblesnoot")
    env = {
        telemetry.DSN_ENV: FAKE_DSN,
        telemetry.CONSENT_ENV: "1",
        telemetry.USER_ENV: ACCOUNT_ID,
    }
    opts = telemetry.options(tmp_path / "absent.db", env)
    recorder = Recorder()
    sentry_sdk.init(transport=recorder, **opts)
    assert sentry_sdk.get_client().is_active()

    def fails(secret_local=PLANTED_EMAIL):
        raise ValueError(f"Wibblesnoot's file {PLANTED_PATH}")

    try:
        fails()
    except ValueError as exc:
        sentry_sdk.capture_exception(exc)
    sentry_sdk.flush()

    events = [e.get_event() for e in recorder.envelopes if e.get_event() is not None]
    assert len(events) == 1
    event = events[0]
    exc = event["exception"]["values"][0]
    assert exc["value"] == f"<name>'s file {SCRUBBED_PATH}"
    for frame in exc["stacktrace"]["frames"]:
        assert "vars" not in frame
        assert "context_line" not in frame
    assert event["user"] == {"id": ACCOUNT_ID}
    assert "server_name" not in event
    assert "modules" not in event
    assert event["release"] == version("sensei-top")
    assert PLANTED_EMAIL not in repr(event)
    assert not [e for e in recorder.envelopes if e.get_event() is None]


def test_a_failing_request_leaves_without_headers_cookies_or_query(tmp_path, monkeypatch):
    monkeypatch.setenv("MTGO_HANDLE", "Wibblesnoot")
    env = {telemetry.DSN_ENV: FAKE_DSN, telemetry.CONSENT_ENV: "1"}
    recorder = Recorder()
    sentry_sdk.init(transport=recorder, **telemetry.options(tmp_path / "absent.db", env))

    app = FastAPI()

    @app.get("/api/boom")
    def boom() -> None:
        raise RuntimeError("the route failed")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/boom",
            params={"opponent": "Wibblesnoot"},
            headers={
                "Cookie": "session=Wibblesnoot",
                "X-Tracker-Client": "Wibblesnoot",
            },
        )
    assert response.status_code == 500
    sentry_sdk.flush()

    events = [e.get_event() for e in recorder.envelopes if e.get_event() is not None]
    assert len(events) == 1
    request = events[0]["request"]
    for key in ("headers", "cookies", "query_string", "env"):
        assert not request.get(key), key
    assert "Wibblesnoot" not in json.dumps(events[0], default=str)


def _request_events(tmp_path, monkeypatch, paths):
    monkeypatch.setenv("MTGO_HANDLE", "Wibblesnoot")
    env = {telemetry.DSN_ENV: FAKE_DSN, telemetry.CONSENT_ENV: "1"}
    recorder = Recorder()
    sentry_sdk.init(transport=recorder, **telemetry.options(tmp_path / "absent.db", env))

    app = FastAPI()

    @app.get("/api/matches/{match_id}")
    def match(match_id: str) -> None:
        raise RuntimeError("the route failed")

    @app.get("/api/guide/{key}")
    def guide(key: str) -> None:
        raise RuntimeError("the route failed")

    with TestClient(app, raise_server_exceptions=False) as client:
        for path in paths:
            client.get(path)
    sentry_sdk.flush()
    return [e.get_event() for e in recorder.envelopes if e.get_event() is not None]


def test_a_failing_request_carries_the_route_template_not_the_ids(tmp_path, monkeypatch):
    events = _request_events(
        tmp_path, monkeypatch, ["/api/matches/m-4711", "/api/guide/guid:9021?x=1"]
    )
    assert len(events) == 2
    by_url = {e["request"]["url"]: e for e in events}
    assert set(by_url) == {"/api/matches/{match_id}", "/api/guide/{key}"}
    for url, event in by_url.items():
        assert event["transaction"] == url
        assert "query_string" not in event["request"]
        dumped = json.dumps(event, default=str)
        for planted in ("m-4711", "9021", "x=1"):
            assert planted not in dumped


def test_an_unmatched_path_sends_no_path_at_all(tmp_path, monkeypatch):
    monkeypatch.setenv("MTGO_HANDLE", "Wibblesnoot")
    env = {telemetry.DSN_ENV: FAKE_DSN, telemetry.CONSENT_ENV: "1"}
    recorder = Recorder()
    sentry_sdk.init(transport=recorder, **telemetry.options(tmp_path / "absent.db", env))

    class RaisesBeforeRouting:
        def __init__(self, app) -> None:
            self.app = app

        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            raise RuntimeError("failed before any route matched")

    app = FastAPI()
    app.add_middleware(RaisesBeforeRouting)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/matches/m-4711?x=1")
    assert response.status_code == 500
    sentry_sdk.flush()

    events = [e.get_event() for e in recorder.envelopes if e.get_event() is not None]
    assert len(events) == 1
    event = events[0]
    assert "url" not in event.get("request", {})
    assert "transaction" not in event
    assert "transaction_info" not in event
    dumped = json.dumps(event, default=str)
    assert "m-4711" not in dumped
    assert "x=1" not in dumped
