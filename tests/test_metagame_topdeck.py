"""The TopDeck.gg corpus source: credential resolution, and one tournament
shaped exactly like TopDeck's own documented API response, normalized into
the same CacheItem shape metagame/source.py already parses.

No network: refresh_topdeck's own HTTP call (list_tournaments) is
monkeypatched, same as test_metagame.py's fbettega tests never hit GitHub.
The one fixture below is hand-shaped from TopDeck's Tournaments v2 docs
(POST /v2/tournaments query-mode response), not a live capture — this is a
third-party REST API, not an Arena log, so there is nothing for
fixture_peek.py to index.
"""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta

import pytest

from sensei_top.db import open_database
from sensei_top.metagame import topdeck

_T0 = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


def _run(conn, **kw):
    """``refresh_topdeck`` with no real sleep and a fixed clock unless the
    test passes its own; ``fetch`` defaults to the monkeypatched
    ``list_tournaments``."""
    kw.setdefault("sleep", lambda seconds: None)
    kw.setdefault("now", lambda: _T0)
    return topdeck.refresh_topdeck(conn, **kw)


def _http_error(code, *, body=None, retry_after=None, reason=""):
    """An ``HTTPError`` as urlopen raises it: the status, the response
    headers and a readable body. The 429 shape is TopDeck's documented
    "Rate Limited" response, https://topdeck.gg/docs/tournaments-v2."""
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    return urllib.error.HTTPError(
        "https://topdeck.gg/api/v2/tournaments", code, reason, headers, io.BytesIO(payload)
    )


def _answers(by_format):
    """A ``fetch`` that returns a list, or raises the exception, per format,
    and records the formats it was asked."""
    asked = []

    def fetch(**kw):
        asked.append(kw["format"])
        outcome = by_format.get(kw["format"], [])
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    fetch.asked = asked
    return fetch


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def test_no_credential_means_no_call_and_no_error(monkeypatch, conn, tmp_path):
    """The TopDeck key is opt-in exactly like the Claude credential: with
    nothing configured, refresh_topdeck must not even try to reach the
    network, and must report a clean, non-error status."""
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def _boom(*args, **kwargs):
        raise AssertionError("list_tournaments ran with no credential configured")

    monkeypatch.setattr(topdeck, "list_tournaments", _boom)

    result = _run(conn)
    assert result.status == "not_configured"


# One real TopDeck tournament, shaped exactly like the documented
# POST /v2/tournaments query-mode response: two players, a completed round,
# and a deckObj carrying Mainboard/Sideboard as {cardName: count} dicts.
_TOURNAMENT = {
    "TID": "abc123",
    "tournamentName": "Friday Night Standard RCQ",
    "startDate": 1755000000,
    "game": "Magic: The Gathering",
    "format": "Standard",
    "standings": [
        {
            "name": "Real Player One",
            "decklist": None,
            "deckObj": {
                "Mainboard": {"Stock Up": 4, "Negate": 2},
                "Sideboard": {"Rest in Peace": 2},
            },
            "wins": 6,
            "draws": 0,
            "losses": 1,
        },
        {
            "name": "Real Player Two",
            "decklist": None,
            "deckObj": {"Mainboard": {"Lightning Bolt": 4}, "Sideboard": {}},
            "wins": 5,
            "draws": 0,
            "losses": 2,
        },
    ],
    "rounds": [
        {
            "round": i,
            "tables": [
                {
                    "table": 1,
                    "players": [
                        {"name": "Real Player One", "id": "user-aaa"},
                        {"name": "Real Player Two", "id": "user-bbb"},
                    ],
                    "winner": "Real Player One",
                    "winner_id": "user-aaa",
                    "winner_games": 2,
                    "loser_games": 1,
                    "status": "Completed",
                }
            ],
        }
        for i in range(1, 6)  # 5 rounds; round count no longer decides the tier
    ],
}


def test_a_documented_shaped_tournament_lands_as_tier_d_with_no_names_stored(
    monkeypatch, conn, tmp_path
):
    """End to end: normalize -> parse_event -> store_events, then grep every
    text column actually written for the two real player names/ids. This is
    the privacy test AGENTS.md's rule requires, not a separate one — the same
    reuse of parse_event that makes the tier rule uniform also makes the
    name-discarding guarantee automatic rather than something topdeck.py has
    to reimplement."""
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    monkeypatch.setattr(topdeck, "list_tournaments", _only("Standard", [_TOURNAMENT]))

    result = _run(conn, force=True)
    assert result.status == "updated"
    assert result.events == 1

    event_row = conn.execute("SELECT * FROM meta_event WHERE source = 'Topdeck'").fetchone()
    assert event_row is not None
    # Topdeck is tabletop, so it faces the same size test every Melee-sourced
    # event does (classify_tier, reused unchanged): 2 standings rows is well
    # under the 64-player line for A, so this lands as D.
    assert event_row["tier"] == "D"
    assert event_row["event_id"] == "Tournaments/Topdeck/abc123.json"

    decks = conn.execute(
        "SELECT * FROM meta_deck WHERE event_id = ?", (event_row["event_id"],)
    ).fetchall()
    assert len(decks) == 2
    win_loss = {(d["wins"], d["losses"]) for d in decks}
    assert win_loss == {(6, 1), (5, 2)}
    mainboards = {d["deck_ord"]: json.loads(d["mainboard_json"]) for d in decks}
    all_cards = {(c["name"], c["count"]) for cards in mainboards.values() for c in cards}
    assert ("Stock Up", 4) in all_cards
    assert ("Negate", 2) in all_cards
    assert ("Lightning Bolt", 4) in all_cards

    matches = conn.execute(
        "SELECT * FROM meta_round_match WHERE event_id = ?", (event_row["event_id"],)
    ).fetchall()
    assert len(matches) == 5
    assert {(m["wins_a"], m["wins_b"]) for m in matches} == {(2, 1)}

    # The actual privacy check: scan every text value ever written to
    # meta_event/meta_deck/meta_round_match for either real name or id.
    everything = json.dumps(
        {
            "event": dict(event_row),
            "decks": [dict(d) for d in decks],
            "matches": [dict(m) for m in matches],
        }
    )
    for leaked in ("Real Player One", "Real Player Two", "user-aaa", "user-bbb"):
        assert leaked not in everything


def test_list_tournaments_posts_to_the_host_that_resolves(monkeypatch):
    """api.topdeck.gg never resolved; the working base is topdeck.gg/api/v2."""
    from datetime import date

    seen = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"[]"

    def _urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["auth"] = request.get_header("Authorization")
        return _Response()

    monkeypatch.setattr(topdeck.urllib.request, "urlopen", _urlopen)
    result = topdeck.list_tournaments(
        api_key="k-123", start=date(2026, 9, 1), end=date(2026, 9, 2), format="Standard"
    )
    assert result == []
    assert seen == {
        "url": "https://topdeck.gg/api/v2/tournaments",
        "method": "POST",
        "auth": "k-123",
    }


def _only(fmt: str, tournaments: list) -> object:
    """A ``list_tournaments`` stand-in that answers one format's query and
    returns nothing for any other, as the API filters by format."""
    return lambda **kw: tournaments if kw["format"] == fmt else []


def _named(tid: str, name: str) -> dict:
    return {**_TOURNAMENT, "TID": tid, "tournamentName": name}


def test_non_constructed_names_are_skipped_and_std_is_kept(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    monkeypatch.setattr(
        topdeck,
        "list_tournaments",
        _only("Standard", [
            _named("t1", "Commander night"),
            _named("t2", "Pre release"),
            _named("t3", "Torneo magic std"),
        ]),
    )
    result = _run(conn, force=True)
    assert (result.events, result.skipped) == (1, 2)
    ids = [r["event_id"] for r in conn.execute("SELECT event_id FROM meta_event")]
    assert ids == ["Tournaments/Topdeck/t3.json"]


def test_a_stored_non_constructed_event_is_purged_with_its_rows(monkeypatch, conn):
    from sensei_top.metagame.source import TournamentFile, parse_event, store_events

    raw = topdeck._normalize(_named("old", "fractured pre release"))
    store_events(
        conn, [parse_event(raw, TournamentFile("Tournaments/Topdeck/old.json", "x"))]
    )
    assert conn.execute("SELECT COUNT(*) FROM meta_deck").fetchone()[0] > 0
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    monkeypatch.setattr(topdeck, "list_tournaments", lambda **kw: [])
    _run(conn, force=True)
    for table in ("meta_event", "meta_deck", "meta_round_match", "meta_deck_archetype"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_each_fetch_format_is_queried_and_stored_under_its_own_format(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    asked = []
    modern = {**_named("m1", "Modern RCQ"), "format": "Modern"}
    standard = _named("s1", "Standard RCQ")

    def _list(**kw):
        asked.append(kw["format"])
        return {"Standard": [standard], "Modern": [modern]}.get(kw["format"], [])

    monkeypatch.setattr(topdeck, "list_tournaments", _list)
    result = _run(conn, force=True)
    assert asked == ["Standard", "Modern"]
    assert result.events == 2
    rows = {
        r["event_id"]: r["format"]
        for r in conn.execute("SELECT event_id, format FROM meta_event")
    }
    assert rows == {"Tournaments/Topdeck/s1.json": "Standard",
                    "Tournaments/Topdeck/m1.json": "Modern"}


def test_an_extra_format_is_queried_and_kept(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    pauper = {**_named("p1", "Pauper RCQ"), "format": "Pauper"}
    monkeypatch.setattr(topdeck, "list_tournaments", _only("Pauper", [pauper]))
    result = _run(conn, force=True, formats=("Standard", "Pauper"))
    assert result.events == 1
    fmt = conn.execute("SELECT format FROM meta_event").fetchone()["format"]
    assert fmt == "Pauper"


def test_an_object_that_omits_its_format_takes_the_queried_one(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    bare = {k: v for k, v in _named("m2", "Modern RCQ").items() if k != "format"}
    monkeypatch.setattr(topdeck, "list_tournaments", _only("Modern", [bare]))
    _run(conn, force=True)
    assert conn.execute("SELECT format FROM meta_event").fetchone()["format"] == "Modern"


def test_one_format_failing_keeps_the_other_and_all_failing_is_failed(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")

    def _half(**kw):
        if kw["format"] == "Modern":
            raise OSError("down")
        return [_named("s1", "Standard RCQ")]

    monkeypatch.setattr(topdeck, "list_tournaments", _half)
    partial = _run(conn, force=True)
    assert partial.events == 1
    assert partial.error == "Modern"

    def _down(**kw):
        raise OSError("down")

    monkeypatch.setattr(topdeck, "list_tournaments", _down)
    assert _run(conn, force=True).status == "failed"


def test_the_non_constructed_rule_applies_to_every_format(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    bad = {**_named("m3", "Modern Draft Night"), "format": "Modern"}
    monkeypatch.setattr(topdeck, "list_tournaments", _only("Modern", [bad]))
    result = _run(conn, force=True)
    assert (result.events, result.skipped) == (0, 1)


_RATE_BODY = {"error": "Rate limit exceeded", "retryAfterSeconds": 90}


def _hold_row(conn):
    return conn.execute("SELECT * FROM meta_fetch_hold WHERE source = 'topdeck'").fetchone()


def _stamped(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM meta_fetch_source WHERE source = 'topdeck'"
    ).fetchone()[0]


def test_a_429_takes_the_bodys_seconds_before_the_header(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    fetch = _answers({"Standard": _http_error(
        429, body=_RATE_BODY, retry_after="3600", reason="Too Many Requests")})
    result = _run(conn, fetch=fetch)
    assert result.status == "failed"
    assert result.error == "HTTP 429 Too Many Requests"
    assert result.answer.place == "Standard"
    assert result.answer.first_request is True
    assert result.hold_before is None
    assert result.hold_after.status == "waiting"
    assert result.hold_after.http_status == 429
    assert result.hold_after.not_before == _T0 + timedelta(seconds=90)
    assert (result.answered, result.unfetched, result.unanswered) == ((), ("Modern",), ())
    assert fetch.asked == ["Standard"]
    assert _stamped(conn) == 0


def test_a_429_without_a_body_time_takes_the_header(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    fetch = _answers({"Standard": _http_error(429, body={"error": "x"}, retry_after="600")})
    result = _run(conn, fetch=fetch)
    assert result.hold_after.not_before == _T0 + timedelta(seconds=600)


def test_a_429_with_neither_waits_an_hour(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    result = _run(conn, fetch=_answers({"Standard": _http_error(429)}))
    assert result.hold_after.not_before == _T0 + timedelta(hours=1)


def test_a_second_429_pauses_and_the_wait_is_not_shortened(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    first = _run(conn, fetch=_answers({"Standard": _http_error(429, body=_RATE_BODY)}))
    # Inside the wait: no request, forced or not.
    fetch = _answers({})
    inside = _T0 + timedelta(seconds=30)
    held = _run(conn, fetch=fetch, force=True, by_hand=True, now=lambda: inside)
    assert held.status == "held"
    assert fetch.asked == []
    assert held.hold_after == first.hold_after
    # After it, a second 429 in a row pauses.
    later = _T0 + timedelta(minutes=5)
    second = _run(conn, fetch=_answers({"Standard": _http_error(429, body=_RATE_BODY)}),
                  now=lambda: later)
    assert second.hold_before == first.hold_after
    assert second.hold_after.status == "paused"
    assert second.hold_after.since == later


@pytest.mark.parametrize("code", [401, 403, 451])
def test_a_refusal_at_the_first_format_pauses_and_leaves_the_rest_unfetched(
    monkeypatch, conn, code
):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    fetch = _answers({"Standard": _http_error(code)})
    result = _run(conn, fetch=fetch)
    assert result.status == "failed"
    assert result.answer.kind == "refused"
    assert result.answer.http_status == code
    assert result.hold_after.status == "paused"
    assert result.hold_after.http_status == code
    assert result.hold_after.not_before is None
    assert result.unfetched == ("Modern",)
    assert fetch.asked == ["Standard"]
    assert _stamped(conn) == 0


@pytest.mark.parametrize("code", [401, 403, 451])
def test_a_refusal_after_one_format_keeps_what_the_first_returned(monkeypatch, conn, code):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    fetch = _answers({"Standard": [_named("s1", "Standard RCQ")], "Modern": _http_error(code)})
    result = _run(conn, fetch=fetch, formats=("Standard", "Modern", "Pauper"))
    assert result.status == "failed"
    assert result.answer.place == "Modern"
    assert result.answer.first_request is False
    assert result.answered == ("Standard",)
    assert result.unfetched == ("Pauper",)
    assert result.events == 1
    assert result.hold_after.status == "paused"
    assert fetch.asked == ["Standard", "Modern"]
    assert conn.execute("SELECT COUNT(*) FROM meta_event").fetchone()[0] == 1
    assert _stamped(conn) == 0


def test_a_paused_source_is_tried_by_hand_only_and_completing_lifts_it(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    _run(conn, fetch=_answers({"Standard": _http_error(403)}))
    fetch = _answers({"Standard": [_named("s1", "Standard RCQ")]})
    loop = _run(conn, fetch=fetch)
    assert loop.status == "held"
    assert fetch.asked == []
    by_hand = _run(conn, fetch=fetch, by_hand=True)
    assert by_hand.status == "updated"
    assert by_hand.hold_before.status == "paused"
    assert by_hand.hold_after is None
    assert _hold_row(conn) is None
    assert _stamped(conn) == 1


@pytest.mark.parametrize("code", [500, 503])
def test_a_5xx_at_one_format_is_no_answer_for_it_and_the_run_goes_on(
    monkeypatch, conn, code
):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    fetch = _answers({"Standard": _http_error(code), "Modern": [_named("m1", "Modern RCQ")]})
    result = _run(conn, fetch=fetch)
    assert result.status == "updated"
    assert result.answer is None
    assert result.answered == ("Modern",)
    assert result.unanswered == ("Standard",)
    assert result.error == "Standard"
    assert result.events == 1
    assert fetch.asked == ["Standard", "Modern"]
    assert _hold_row(conn) is None
    assert _stamped(conn) == 1


def test_every_format_unanswered_is_a_generic_failure_and_changes_no_hold(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    first = _run(conn, fetch=_answers({"Standard": _http_error(429, body=_RATE_BODY)}))
    later = _T0 + timedelta(minutes=5)
    fetch = _answers({"Standard": _http_error(503, reason="Service Unavailable"),
                      "Modern": TimeoutError()})
    result = _run(conn, fetch=fetch, now=lambda: later)
    assert result.status == "failed"
    assert result.answer.kind == "generic"
    assert result.error == "HTTP 503 Service Unavailable"
    assert result.unanswered == ("Standard", "Modern")
    assert result.hold_after == first.hold_after
    assert _hold_row(conn)["last_at"] == "2026-10-05T12:00:00Z"
    assert _stamped(conn) == 0


def test_an_identical_copy_records_its_read(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    fetch = _answers({"Standard": [_TOURNAMENT]})
    first = _run(conn, fetch=fetch, now=lambda: _T0)
    assert first.events == 1
    event_id = "Tournaments/Topdeck/abc123.json"

    def read_at():
        return conn.execute(
            "SELECT lists_read_at FROM meta_event WHERE event_id = ?", (event_id,)
        ).fetchone()["lists_read_at"]

    assert read_at() == "2026-10-05T12:00:00Z"
    later = _T0 + timedelta(days=2)
    second = _run(conn, fetch=fetch, force=True, now=lambda: later)
    assert (second.events, second.skipped) == (0, 0)
    assert read_at() == "2026-10-07T12:00:00Z"


def test_formats_are_spaced_fifteen_seconds_apart_and_never_before_the_first(
    monkeypatch, conn
):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    log = []

    def fetch(**kw):
        log.append(("fetch", kw["format"]))
        return []

    _run(conn, fetch=fetch, formats=("Standard", "Modern", "Pauper"),
         sleep=lambda seconds: log.append(("sleep", seconds)))
    assert log == [
        ("fetch", "Standard"), ("sleep", 15.0),
        ("fetch", "Modern"), ("sleep", 15.0),
        ("fetch", "Pauper"),
    ]


def test_a_fresh_copy_makes_no_request_unless_forced(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    _run(conn, fetch=_answers({}))
    fetch = _answers({})
    soon = _T0 + timedelta(hours=1)
    fresh = _run(conn, fetch=fetch, now=lambda: soon)
    assert fresh.status == "fresh"
    assert fresh.age_seconds == 3600
    assert fetch.asked == []
    assert _run(conn, fetch=fetch, force=True, now=lambda: soon).status == "updated"


def test_the_not_before_counts_from_when_the_answer_arrived(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    times = iter([_T0, _T0 + timedelta(seconds=20), _T0 + timedelta(seconds=40)])
    fetch = _answers({"Standard": _http_error(429, body=_RATE_BODY)})
    result = _run(conn, fetch=fetch, now=lambda: next(times))
    assert result.answer.at == _T0 + timedelta(seconds=20)
    assert result.hold_after.not_before == _T0 + timedelta(seconds=20 + 90)


def test_an_unusable_body_time_is_logged_and_the_header_is_used(monkeypatch, conn, caplog):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    err = _http_error(429, body={"retryAfterSeconds": "42"}, retry_after="600")
    with caplog.at_level("WARNING"):
        result = _run(conn, fetch=_answers({"Standard": err}))
    assert result.hold_after.not_before == _T0 + timedelta(seconds=600)
    assert "unusable retryAfterSeconds" in caplog.text
