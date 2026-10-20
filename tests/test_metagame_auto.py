"""The corpus-refresh loop's tick, ``metagame/auto.py``.

No network. fbettega's GitHub calls are monkeypatched as in
``test_metagame.py``; mtgo.com's and TopDeck's refreshes run for real behind
a fetch each test supplies, with no pauses, so their own gates and freshness
rules are the ones exercised. Expectations come from the loop's rules in
docs/metagame.md, "Fetching the corpus", and from what each fake source
serves.

Two clocks: the loop's ``now`` (``_Clock``, starting at ``T``) drives
mtgo.com, TopDeck and the loop's waits; fbettega judges its own freshness on
the wall clock, so its stamps are written from the wall clock too.
"""

from __future__ import annotations

import email.message
import io
import json
import logging
import threading
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sensei_top import cli
from sensei_top.db import open_database
from sensei_top.metagame import auto, mtgo_site, source, topdeck
from sensei_top.metagame.holds import MTGO, TOPDECK, Hold, HoldStatus, read_hold
from sensei_top.metagame.source import AnswerKind, ParsedDeck, ParsedEvent, RefreshResult

FIX = Path(__file__).parent / "fixtures"
T = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)
H = timedelta(hours=1)
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class _Clock:
    """The loop's clock: an aware UTC time the test moves."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "auto.db")
    yield c
    c.close()


def _stamp(conn, name: str, at: datetime) -> None:
    """A completed run of ``name`` at ``at``, as each refresh stamps one."""
    conn.execute(
        "INSERT INTO meta_fetch_source (source, ref, fetched_at, events, skipped) "
        "VALUES (?, 'ref', ?, 0, 0) "
        "ON CONFLICT (source) DO UPDATE SET fetched_at = excluded.fetched_at",
        (name, at.strftime(TIME_FORMAT)),
    )


def _fbettega_fresh(conn) -> None:
    _stamp(conn, "fbettega", datetime.now(UTC))


def _hold(conn, name: str, status: str, code: int, *, since: datetime,
          not_before: datetime | None) -> None:
    conn.execute(
        "INSERT INTO meta_fetch_hold VALUES (?, ?, ?, 0, ?, ?, ?, ?)",
        (name, status, code, since.strftime(TIME_FORMAT), code, since.strftime(TIME_FORMAT),
         not_before.strftime(TIME_FORMAT) if not_before is not None else None),
    )


def _no_github(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        pytest.fail("fbettega must not reach GitHub here")

    monkeypatch.setattr(source, "resolve_commit_sha", refuse)
    monkeypatch.setattr(source, "list_tree", refuse)
    monkeypatch.setattr(source, "fetch_event", refuse)


def _mtgo(monkeypatch, fetch) -> None:
    """mtgo.com behind ``fetch``, with no pauses between requests."""
    real = mtgo_site.refresh_mtgo_site
    monkeypatch.setattr(
        mtgo_site, "refresh_mtgo_site",
        lambda conn, **kw: real(conn, fetch=fetch, sleep=lambda s: None, pause_s=0, **kw),
    )


def _mtgo_down(monkeypatch) -> list[str]:
    """mtgo.com with no connection; returns the URLs it was asked for."""
    asked: list[str] = []

    def fetch(url: str) -> str:
        asked.append(url)
        raise urllib.error.URLError("down")

    _mtgo(monkeypatch, fetch)
    return asked


def _mtgo_must_not_be_asked(monkeypatch) -> None:
    def fetch(url: str) -> str:
        pytest.fail(f"mtgo.com must not be asked for {url} here")

    _mtgo(monkeypatch, fetch)


def _topdeck(monkeypatch, fetch) -> None:
    """TopDeck with a key, behind ``fetch``, with no spacing between formats."""
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    real = topdeck.refresh_topdeck
    monkeypatch.setattr(
        topdeck, "refresh_topdeck",
        lambda conn, **kw: real(conn, fetch=fetch, sleep=lambda s: None, **kw),
    )


def _event(event_id: str, fmt: str, *, decks: int = 0) -> ParsedEvent:
    return ParsedEvent(
        event_id=event_id, source="MTGO", name="League", event_date="2026-09-20",
        format=fmt, tier="C", standings_rows=0, uri=None, blob_sha=f"sha-{event_id}",
        decks=[ParsedDeck(i, "5-0", 5, 0, 0, [{"count": 4, "name": f"Card {i}"}], [])
               for i in range(decks)],
    )


def test_followed_formats_are_the_standing_two_plus_every_stored_one(conn):
    assert auto.followed_formats(conn) == ("Standard", "Modern")

    source.store_events(conn, [
        _event("e-pauper", "Pauper"),
        _event("e-legacy", "legacy"),
        _event("e-commander", "Duel Commander"),
        _event("e-standard", "Standard"),
    ])
    # "Duel Commander" is not one of FORMATS; "legacy" is Legacy in any case.
    assert auto.followed_formats(conn) == ("Standard", "Modern", "Pauper", "Legacy")
    assert auto.followed_formats(conn, ["premodern", "Standard", " pioneer "]) == (
        "Standard", "Pioneer", "Modern", "Pauper", "Legacy", "Premodern"
    )


def test_followed_formats_refuses_a_name_that_is_not_a_format(conn):
    with pytest.raises(ValueError, match="Commander"):
        auto.followed_formats(conn, ["Commander"])


def test_every_source_is_asked_for_the_followed_formats_and_never_by_hand(conn, monkeypatch):
    source.store_events(conn, [_event("e-pauper", "Pauper")])
    calls: dict[str, dict] = {}

    def recorder(name):
        def run(conn, **kw):
            calls[name] = kw
            return RefreshResult(status="fresh")
        return run

    monkeypatch.setattr(source, "refresh_metagame", recorder("fbettega"))
    monkeypatch.setattr(mtgo_site, "refresh_mtgo_site", recorder("mtgo"))
    monkeypatch.setattr(topdeck, "refresh_topdeck", recorder("topdeck"))
    clock = _Clock(T)

    results = auto.refresh_corpus(conn, auto.RefreshState(), now=clock)

    assert list(results) == ["fbettega", "mtgo", "topdeck"]
    assert {name: kw["formats"] for name, kw in calls.items()} == {
        name: ("Standard", "Modern", "Pauper") for name in ("fbettega", "mtgo", "topdeck")
    }
    for name in ("mtgo", "topdeck"):
        assert calls[name]["by_hand"] is False
        assert calls[name]["now"] is clock
        assert "force" not in calls[name]
    assert "force" not in calls["fbettega"]


def test_fresh_sources_make_no_request(conn, monkeypatch):
    # Inside each cadence: fbettega 24 h, mtgo.com 3 h, TopDeck 24 h.
    _fbettega_fresh(conn)
    _stamp(conn, "mtgo", T - 2 * H)
    _stamp(conn, "topdeck", T - 23 * H)
    _no_github(monkeypatch)
    _mtgo_must_not_be_asked(monkeypatch)
    _topdeck(monkeypatch, lambda **kw: pytest.fail("TopDeck must not be asked here"))

    results = auto.refresh_corpus(conn, auto.RefreshState(), now=_Clock(T))

    assert {name: r.status for name, r in results.items()} == {
        "fbettega": "fresh", "mtgo": "fresh", "topdeck": "fresh",
    }


def test_a_run_that_ended_with_no_hold_waits_an_hour(conn, monkeypatch):
    github_calls: list[str] = []

    def unreachable(*args, **kwargs):
        github_calls.append("resolve")
        raise OSError("no route to host")

    monkeypatch.setattr(source, "resolve_commit_sha", unreachable)
    site_calls = _mtgo_down(monkeypatch)
    state, clock = auto.RefreshState(), _Clock(T)

    results = auto.refresh_corpus(conn, state, now=clock)
    assert results["fbettega"].status == "failed"
    assert results["mtgo"].status == "failed"
    assert results["mtgo"].answer is not None
    assert results["mtgo"].answer.kind == AnswerKind.GENERIC
    asked = (len(github_calls), len(site_calls))
    assert asked[0] == 1 and asked[1] >= 1

    clock.at = T + 59 * timedelta(minutes=1)
    results = auto.refresh_corpus(conn, state, now=clock)
    assert "fbettega" not in results
    assert "mtgo" not in results
    assert results["topdeck"].status == "not_configured"
    assert (len(github_calls), len(site_calls)) == asked

    clock.at = T + H
    results = auto.refresh_corpus(conn, state, now=clock)
    assert results["fbettega"].status == "failed"
    assert results["mtgo"].status == "failed"
    assert len(github_calls) == 2
    assert len(site_calls) > asked[1]


def test_a_later_stored_not_before_wins_over_the_hour(conn, monkeypatch):
    _fbettega_fresh(conn)
    site_calls = _mtgo_down(monkeypatch)
    state, clock = auto.RefreshState(), _Clock(T)

    assert auto.refresh_corpus(conn, state, now=clock)["mtgo"].status == "failed"
    asked = len(site_calls)
    # Meanwhile a hand run of `meta` drew a 429 that asked for three hours.
    _hold(conn, "mtgo", "waiting", 429, since=T + 10 * timedelta(minutes=1),
          not_before=T + 3 * H)

    clock.at = T + H
    results = auto.refresh_corpus(conn, state, now=clock)
    assert results["mtgo"].status == "held"
    assert len(site_calls) == asked

    clock.at = T + 3 * H
    results = auto.refresh_corpus(conn, state, now=clock)
    assert results["mtgo"].status == "failed"
    assert len(site_calls) > asked


def test_a_429_stores_topdecks_own_time_and_the_loop_waits_its_hour(conn, monkeypatch):
    """A run a 429 ended did not complete, so the loop leaves TopDeck alone
    for its hour. The hour is the loop's own courtesy and appears in no
    line: what is stored, and what the lines and the Field page show, is
    TopDeck's own time, sixty seconds here."""
    _fbettega_fresh(conn)
    _stamp(conn, "mtgo", T)
    asked: list[str] = []

    def fetch(**kw):
        asked.append(kw["format"])
        if len(asked) == 1:
            headers = email.message.Message()
            answer = {"error": "Rate limit exceeded", "retryAfterSeconds": 60}
            body = json.dumps(answer).encode("utf-8")
            raise urllib.error.HTTPError(
                "https://topdeck.gg/api/v2/tournaments", 429, "Too Many Requests", headers,
                io.BytesIO(body),
            )
        return []

    _topdeck(monkeypatch, fetch)
    state, clock = auto.RefreshState(), _Clock(T)

    first = auto.refresh_corpus(conn, state, now=clock)["topdeck"]
    assert first.status == "failed"
    assert first.answer is not None and first.answer.kind == AnswerKind.RATE
    stored = read_hold(conn, TOPDECK)
    assert stored is not None and stored == first.hold_after
    assert stored.not_before == T + timedelta(seconds=60)

    clock.at = T + 5 * timedelta(minutes=1)
    assert "topdeck" not in auto.refresh_corpus(conn, state, now=clock)
    assert asked == ["Standard"]
    stored = read_hold(conn, TOPDECK)
    assert stored is not None and stored.not_before == T + timedelta(seconds=60)

    clock.at = T + H
    assert auto.refresh_corpus(conn, state, now=clock)["topdeck"].status == "updated"
    assert asked == ["Standard", "Standard", "Modern"]


def test_an_mtgo_run_a_429_cut_short_after_a_store_waits_its_hour_too(conn, monkeypatch):
    """mtgo.com served one league, then answered 429: the run kept what it
    parsed but was not stamped, so it did not complete and the loop waits
    its hour. A first 429's stored wait is at least three hours, later
    than the hour, so once the hour is over the gate holds it instead."""
    _fbettega_fresh(conn)
    # A completed run earlier this month, so no month page is read.
    _stamp(conn, "mtgo", T - 10 * H)
    league = "standard-league-2026-10-0211129"  # mtgo_site_league.html's own slug
    answered = "standard-challenge-32-2026-10-0212855471"
    index = "".join(f'<a href="/decklist/{s}">{s}</a>' for s in (league, answered))
    pages = {
        mtgo_site.INDEX_URL: index,
        f"{mtgo_site.SITE}/decklist/{league}": (FIX / "mtgo_site_league.html").read_text(
            encoding="utf-8"
        ),
    }
    asked: list[str] = []

    def fetch(url: str) -> str:
        asked.append(url)
        if url in pages:
            return pages[url]
        raise urllib.error.HTTPError(
            url, 429, "Too Many Requests", email.message.Message(), io.BytesIO(b"")
        )

    _mtgo(monkeypatch, fetch)
    state, clock = auto.RefreshState(), _Clock(T)

    result = auto.refresh_corpus(conn, state, now=clock)["mtgo"]
    assert (result.status, result.events) == ("failed", 1)
    assert result.answer is not None and result.answer.kind == AnswerKind.RATE
    assert asked[-1] == f"{mtgo_site.SITE}/decklist/{answered}"
    assert state.backoff_until[MTGO] == T + H
    stored = read_hold(conn, MTGO)
    assert stored is not None and stored.not_before == T + 3 * H
    read = len(asked)

    # Inside the hour the loop does not call it at all ...
    clock.at = T + 59 * timedelta(minutes=1)
    assert "mtgo" not in auto.refresh_corpus(conn, state, now=clock)
    # ... and after it, the stored wait holds it at the gate.
    clock.at = T + H
    assert auto.refresh_corpus(conn, state, now=clock)["mtgo"].status == "held"
    assert len(asked) == read


def _tree_entry(path: str, sha: str) -> dict:
    return {"path": path, "type": "blob", "sha": sha}


def _league_path(source_dir: str = "MTGO", days_ago: int = 2) -> str:
    """A Standard league's path inside fbettega's window, which is counted
    back from the wall clock's date."""
    day = datetime.now(UTC).date() - timedelta(days=days_ago)
    return (f"Tournaments/{source_dir}/{day.year}/{day.month:02d}/{day.day:02d}/"
            f"standard-league-{day.isoformat()}.json")


def _github(monkeypatch, tree: list[dict]) -> list[str]:
    """GitHub serving ``tree``, every file a one-deck Standard league;
    returns the paths fetched."""
    fetched: list[str] = []

    def fetch_event(commit_sha, path):
        fetched.append(path)
        return {
            "Tournament": {"Name": "Standard League", "Formats": "Standard"},
            "Decks": [{"Player": "P1", "Result": "5-0", "Mainboard": [], "Sideboard": []}],
            "Rounds": [], "Standings": [],
        }

    monkeypatch.setattr(source, "resolve_commit_sha", lambda *a, **k: "commit1")
    monkeypatch.setattr(source, "list_tree", lambda *a, **k: tree)
    monkeypatch.setattr(source, "fetch_event", fetch_event)
    return fetched


def test_reclassification_follows_only_a_store(conn, monkeypatch):
    _stamp(conn, "mtgo", T)
    _mtgo_must_not_be_asked(monkeypatch)
    reclassified: list[int] = []

    def record(conn):
        reclassified.append(1)
        return 0, {"classified": 0, "unclassified": 0, "skipped_format": 0}

    monkeypatch.setattr(auto, "reclassify_corpus", record)
    state, clock = auto.RefreshState(), _Clock(T)

    # Nothing due.
    _fbettega_fresh(conn)
    _no_github(monkeypatch)
    auto.refresh_corpus(conn, state, now=clock)
    assert reclassified == []

    # fbettega due (its stamp gone, as a day later), and nothing new upstream.
    conn.execute("DELETE FROM meta_fetch_source WHERE source = 'fbettega'")
    _github(monkeypatch, [])
    result = auto.refresh_corpus(conn, state, now=clock)["fbettega"]
    assert (result.status, result.events) == ("updated", 0)
    assert reclassified == []

    # fbettega due again, and one new event upstream.
    conn.execute("DELETE FROM meta_fetch_source WHERE source = 'fbettega'")
    _github(monkeypatch, [_tree_entry(_league_path(), "sha-new")])
    result = auto.refresh_corpus(conn, state, now=clock)["fbettega"]
    assert (result.status, result.events) == ("updated", 1)
    assert reclassified == [1]


def test_a_failed_reclassification_is_owed_to_the_next_tick(conn, monkeypatch, caplog):
    _stamp(conn, "mtgo", T)
    _mtgo_must_not_be_asked(monkeypatch)
    _github(monkeypatch, [_tree_entry(_league_path(), "sha-new")])
    attempts: list[int] = []

    def flaky(conn):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("database is locked")
        return 0, {"classified": 0, "unclassified": 0, "skipped_format": 0}

    monkeypatch.setattr(auto, "reclassify_corpus", flaky)
    state, clock = auto.RefreshState(), _Clock(T)

    with caplog.at_level(logging.WARNING, logger=auto.__name__):
        results = auto.refresh_corpus(conn, state, now=clock)
    assert results["fbettega"].events == 1
    assert "database is locked" in caplog.text
    assert state.reclassify_pending

    # Nothing new is stored, but the failed reclassification is still owed.
    _no_github(monkeypatch)
    auto.refresh_corpus(conn, state, now=clock)
    assert len(attempts) == 2
    assert not state.reclassify_pending

    auto.refresh_corpus(conn, state, now=clock)
    assert len(attempts) == 2


def test_reclassify_corpus_sets_twins_aside_then_classifies(conn):
    """Two copies of one league under two paths: dedup keeps the lower id
    and deletes the other's decks, so one deck is left to classify, and with
    no archetype definitions stored it counts as another format's."""
    twin_a = _event("Tournaments/MTGO/2026/09/20/a.json", "Standard", decks=1)
    twin_b = _event("Tournaments/MTGO/2026/09/21/b.json", "Standard", decks=1)
    source.store_events(conn, [twin_a, twin_b])

    duplicates, counts = auto.reclassify_corpus(conn)

    assert duplicates == 1
    assert counts == {"classified": 0, "unclassified": 0, "skipped_format": 1}
    marked = conn.execute(
        "SELECT event_id, duplicate_of FROM meta_event WHERE duplicate_of IS NOT NULL"
    ).fetchall()
    assert [tuple(r) for r in marked] == [(twin_b.event_id, twin_a.event_id)]


def test_a_refresh_that_raises_does_not_stop_the_others(conn, monkeypatch, caplog):
    _stamp(conn, "mtgo", T)
    _mtgo_must_not_be_asked(monkeypatch)
    raised: list[int] = []

    def broken(conn, **kw):
        raised.append(1)
        raise RuntimeError("malformed tree")

    monkeypatch.setattr(source, "refresh_metagame", broken)
    state, clock = auto.RefreshState(), _Clock(T)

    with caplog.at_level(logging.WARNING, logger=auto.__name__):
        results = auto.refresh_corpus(conn, state, now=clock)
    assert "fbettega" not in results
    assert results["mtgo"].status == "fresh"
    assert results["topdeck"].status == "not_configured"
    assert "malformed tree" in caplog.text

    # It waits its hour like any attempted run that did not complete.
    clock.at = T + 5 * timedelta(minutes=1)
    auto.refresh_corpus(conn, state, now=clock)
    assert raised == [1]


def test_a_stale_topdeck_no_longer_makes_fbettega_run_again(conn, monkeypatch):
    """Defect 1: fbettega judged its freshness by the oldest of every
    source's stamps, so a stale TopDeck sent it to GitHub on every tick."""
    _fbettega_fresh(conn)
    _stamp(conn, "mtgo", T)
    _stamp(conn, "topdeck", datetime(2026, 1, 1, tzinfo=UTC))
    # The unscoped age is TopDeck's, past fbettega's 24 h.
    age = source.cache_age_seconds(conn)
    assert age is not None and age > source.MAX_AGE_SECONDS
    _no_github(monkeypatch)
    _mtgo_must_not_be_asked(monkeypatch)

    results = auto.refresh_corpus(conn, auto.RefreshState(), now=_Clock(T))

    assert results["fbettega"].status == "fresh"


def test_fbettega_still_runs_and_stores_mtgo_paths_while_mtgo_is_paused(conn, monkeypatch):
    """The cache route keeps its cadence and its scope
    while mtgo.com refuses this client, and nothing about it changes."""
    _hold(conn, "mtgo", "paused", 403, since=T - 24 * H, not_before=None)
    _mtgo_must_not_be_asked(monkeypatch)
    league = _league_path("MTGO")
    fetched = _github(monkeypatch, [_tree_entry(league, "sha-league")])
    state, clock = auto.RefreshState(), _Clock(T)

    results = auto.refresh_corpus(conn, state, now=clock)

    assert results["mtgo"].status == "held"
    assert (results["fbettega"].status, results["fbettega"].events) == ("updated", 1)
    assert fetched == [league]
    row = conn.execute(
        "SELECT source FROM meta_event WHERE event_id = ?", (league,)
    ).fetchone()
    assert row is not None and row["source"] == "MTGO"

    # The pause shortens nothing: five minutes on, the cache is fresh.
    _no_github(monkeypatch)
    clock.at = T + 5 * timedelta(minutes=1)
    results = auto.refresh_corpus(conn, state, now=clock)
    assert results["fbettega"].status == "fresh"
    assert results["mtgo"].status == "held"


M = timedelta(minutes=1)


def test_serve_prints_only_the_transitions(conn, tmp_path, monkeypatch, capsys):
    """serve's console prints a line only after its own attempt moved a hold:
    into mtgo.com's wait, with the ending serve's console gives it, and out
    of it. Every tick between, inside the loop's hour, held, or fresh, prints
    nothing, and neither does fbettega fresh or TopDeck with no key."""
    _fbettega_fresh(conn)
    _no_github(monkeypatch)
    _stamp(conn, "mtgo", T - 5 * H)  # the stored copy, 5h old at T
    league = "standard-league-2026-10-0211129"  # mtgo_site_league.html's own slug
    pages = {
        mtgo_site.INDEX_URL: f'<a href="/decklist/{league}">{league}</a>',
        f"{mtgo_site.SITE}/decklist/{league}": (FIX / "mtgo_site_league.html").read_text(
            encoding="utf-8"
        ),
    }
    pausing = [True]
    asked: list[str] = []

    def fetch(url: str) -> str:
        asked.append(url)
        if pausing[0]:
            raise urllib.error.HTTPError(
                url, 429, "Too Many Requests", email.message.Message(), io.BytesIO(b"")
            )
        if url not in pages:
            pytest.fail(f"mtgo.com must not be asked for {url} here")
        return pages[url]

    _mtgo(monkeypatch, fetch)
    state, clock = auto.RefreshState(), _Clock(T)

    def tick(at: datetime) -> str:
        clock.at = at
        cli._corpus_refresh_tick(tmp_path / "auto.db", state, now=clock)
        return capsys.readouterr().out

    # A first 429 with no Retry-After waits three hours: 14:00 to 17:00.
    assert tick(T) == (
        "mtgo: asked for a pause (HTTP 429) at the index; keeping what is stored "
        "(5h old); the next fetch is after 17:00 UTC.\n"
    )
    assert asked == [mtgo_site.INDEX_URL]

    assert tick(T + 5 * M) == ""  # inside the loop's hour
    assert tick(T + H) == ""      # held by the stored wait
    assert asked == [mtgo_site.INDEX_URL]

    pausing[0] = False
    assert tick(T + 3 * H) == "mtgo: 1 tournament events stored; the wait is over.\n"
    assert tick(T + 3 * H + 5 * M) == ""  # fresh for its three hours
    assert asked == [mtgo_site.INDEX_URL, *pages]


def test_an_exception_is_logged_and_the_thread_survives(tmp_path, monkeypatch, capsys, caplog):
    """A tick that raises (here the database, locked past the wait) is logged
    and the next tick runs, with the same ``RefreshState``; a result
    ``render`` refuses is logged while the other source's line still prints."""
    db_path = tmp_path / "auto.db"
    open_database(db_path).close()
    calls: list[tuple[auto.RefreshState, int]] = []
    answered = threading.Event()
    waiting = Hold(
        source=TOPDECK, status=HoldStatus.WAITING, http_status=429, answers=0,
        since=T, last_status=429, last_at=T, not_before=T + 60 * M,
    )

    def refresh_corpus(conn, state, *, now):
        calls.append((state, conn.execute("PRAGMA busy_timeout").fetchone()[0]))
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        if len(calls) > 2:
            return {}
        answered.set()
        return {
            # A failed run carries the answer that ended it; this one does not.
            MTGO: RefreshResult(status="failed", hold_after=Hold(
                source=MTGO, status=HoldStatus.WAITING, http_status=429, answers=0,
                since=T, last_status=429, last_at=T, not_before=T + 3 * H,
            )),
            TOPDECK: RefreshResult(status="updated", events=3, hold_before=waiting),
        }

    monkeypatch.setattr(auto, "refresh_corpus", refresh_corpus)
    stop = threading.Event()

    with caplog.at_level(logging.WARNING, logger=cli.__name__):
        thread = cli._start_corpus_refresh(db_path, interval=0.01, stop=stop)
        assert answered.wait(5)
        stop.set()
        thread.join(5)

    assert not thread.is_alive()
    assert (thread.name, thread.daemon) == ("corpus-refresh", True)
    assert "database is locked" in caplog.text
    assert "no line for mtgo's failed run" in caplog.text
    assert capsys.readouterr().out == "topdeck: 3 tournament events stored; the wait is over.\n"
    states = {id(state) for state, _ in calls}
    assert len(states) == 1 and isinstance(calls[0][0], auto.RefreshState)
    assert {timeout for _, timeout in calls} == {60_000}
