"""mtgo.com's own decklist pages as a corpus source. The fixtures are an
anonymised event page and fbettega's independent copy of the same event
(handles Player01..., loginids 9000NN), so the expectations come from
fbettega's file, not from this module's output."""

from __future__ import annotations

import dataclasses
import email.message
import io
import json
import logging
import re
import urllib.error
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.formats import FORMATS
from sensei_top.guide.window import format_resets
from sensei_top.metagame import mtgo_site
from sensei_top.metagame.holds import MTGO, Hold, HoldStatus, read_hold
from sensei_top.metagame.source import AnswerKind, TournamentFile, parse_event, store_events

FIX = Path(__file__).parent / "fixtures"

# The run's clock in the tests that set one: a Monday afternoon, UTC.
T = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)
STAMP = "2026-10-05T14:00:00Z"
H = timedelta(hours=1)
# A run completed earlier the same day: the gap is closed, so a run at T reads
# no month page (S4, "The gap"), and the stamp is too old to be fresh.
EARLIER = T - 10 * H
EARLIER_STAMP = "2026-10-05T04:00:00Z"
# A run completed on 2026-09-28: at T the gap starts that day, so the one
# month page a run reads is September's.
LAST_MONTH = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
INDEX = mtgo_site.INDEX_URL
SEPTEMBER = f"{INDEX}/2026/09"
LEAGUE = "standard-league-2026-10-0211129"  # mtgo_site_league.html's own slug
TODAYS_LEAGUE = "standard-league-2026-10-0511129"  # read again on every run at T
YESTERDAYS_LEAGUE = "standard-league-2026-10-0411129"  # read again once after noon at T
CHALLENGE = "standard-challenge-32-2026-10-0212855466"  # mtgo_site_challenge.html's


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _fbettega(name: str) -> dict:
    return json.loads(_read(name))


def _path_of(raw: dict) -> str:
    slug = raw["Tournament"]["Uri"].rsplit("/", 1)[-1]
    y, m, d = raw["Tournament"]["Date"][:10].split("-")
    return f"Tournaments/MTGO/{y}/{m}/{d}/{slug}.json"


def _strip(event) -> dict:
    out = dataclasses.asdict(event)
    out.pop("uri")
    out.pop("blob_sha")
    return out


def test_challenge_page_parses_like_the_mirrors_copy():
    page = mtgo_site.normalize(mtgo_site.extract_data(_read("mtgo_site_challenge.html")))
    twin = _fbettega("mtgo_site_challenge_fbettega.json")
    path = _path_of(twin)
    ours = parse_event(page, TournamentFile(path, "a"))
    theirs = parse_event(twin, TournamentFile(path, "b"))
    assert ours is not None and theirs is not None
    assert _strip(ours) == _strip(theirs)
    assert len(ours.decks) == 32 and len(ours.round_matches) == 7
    assert ours.format == "Standard"
    assert ours.event_date == "2026-10-02"


def test_league_page_is_tier_c_with_five_oh_records():
    page = mtgo_site.normalize(mtgo_site.extract_data(_read("mtgo_site_league.html")))
    twin = _fbettega("mtgo_site_league_fbettega.json")
    path = _path_of(twin)
    ours = parse_event(page, TournamentFile(path, "a"))
    theirs = parse_event(twin, TournamentFile(path, "b"))
    assert ours is not None and theirs is not None
    assert _strip(ours) == _strip(theirs)
    assert ours.tier == "C"
    assert len(ours.decks) == 3
    assert all(d.result == "5-0" and (d.wins, d.losses) == (5, 0) for d in ours.decks)


def test_index_keeps_only_standard_slugs():
    html = _read("mtgo_site_index.html")
    assert mtgo_site.list_event_slugs(html, ("Standard",)) == [
        "standard-league-2026-10-0311129",
        "standard-challenge-32-2026-10-0212855471",
        "standard-challenge-32-2026-10-0212855466",
        "standard-league-2026-10-0211129",
        "standard-challenge-16-2026-10-0112855458",
        "standard-league-2026-10-0111129",
    ]
    repeated = _index_for("standard-a-2026-10-0111", "modern-b-2026-10-0122",
                          "standard-a-2026-10-0111")
    assert mtgo_site.list_event_slugs(repeated, ("Standard",)) == ["standard-a-2026-10-0111"]


def test_extract_data_is_none_without_the_script():
    assert mtgo_site.extract_data("<html>nothing</html>") is None
    assert mtgo_site.extract_data("window.MTGO.decklists.data = {oops") is None


def test_mtgo_site_never_retains_a_player_name(conn):
    events = []
    for name in ("mtgo_site_challenge.html", "mtgo_site_league.html"):
        raw = mtgo_site.normalize(mtgo_site.extract_data(_read(name)))
        events.append(parse_event(raw, TournamentFile(_path_of(raw), "x")))

    store_events(conn, events)
    blob = repr([dataclasses.asdict(e) for e in events])
    dump = "\n".join(
        str(tuple(row)) for t in ("meta_event", "meta_deck")
        for row in conn.execute(f"SELECT * FROM {t}")
    )
    for text in (blob, dump):
        assert "Player0" not in text and "Player1" not in text and "Player2" not in text
        assert "9000" not in text


def _http_error(url: str, code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(url, code, HTTPStatus(code).phrase, headers, io.BytesIO(b""))


def _fake_site(pages: dict[str, str | BaseException], *, missing: int | None = None):
    """A site serving ``pages``; a value that is an exception is raised. A
    page not in ``pages`` is no connection, or the HTTP status ``missing``."""
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        if url not in pages:
            if missing is not None:
                raise _http_error(url, missing)
            raise urllib.error.URLError("down")
        page = pages[url]
        if isinstance(page, BaseException):
            raise page
        return page

    return fetch, calls


def _index_for(*slugs: str) -> str:
    return "".join(f'<a href="/decklist/{s}">{s}</a>' for s in slugs)


def _url(slug: str) -> str:
    return f"{mtgo_site.SITE}/decklist/{slug}"


def _path(slug: str) -> str:
    """The stored path of an event page: the date in its slug, then the slug."""
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", slug)
    assert match is not None, slug
    return "Tournaments/MTGO/{}/{}/{}/{}.json".format(*match.groups(), slug)


def _run(conn, fetch, *, at: datetime = T, **kw):
    return mtgo_site.refresh_mtgo_site(
        conn, pause_s=0, fetch=fetch, sleep=lambda s: None, now=lambda: at, **kw
    )


def _stamped(conn) -> tuple | None:
    row = conn.execute(
        "SELECT fetched_at, events, skipped FROM meta_fetch_source WHERE source = 'mtgo'"
    ).fetchone()
    return tuple(row) if row is not None else None


def _hold(conn, status: str, code: int, *, answers: int = 0, since: datetime,
          not_before: datetime | None) -> Hold:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    conn.execute(
        "INSERT INTO meta_fetch_hold VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (MTGO, status, code, answers, since.strftime(fmt), code, since.strftime(fmt),
         not_before.strftime(fmt) if not_before is not None else None),
    )
    hold = read_hold(conn, MTGO)
    assert hold is not None
    return hold


def _stamp_at(conn, at: datetime) -> None:
    conn.execute(
        "INSERT INTO meta_fetch_source (source, ref, fetched_at, events, skipped) "
        "VALUES ('mtgo', ?, ?, 0, 0)",
        (mtgo_site.INDEX_URL, at.strftime("%Y-%m-%dT%H:%M:%SZ")),
    )


def _read_row(conn, slug: str) -> tuple:
    row = conn.execute(
        "SELECT lists_read_at, empty_read_at, empty_read_kind, blob_sha FROM meta_event "
        "WHERE event_id = ?", (_path(slug),),
    ).fetchone()
    assert row is not None, slug
    return tuple(row)


def _decks(conn, slug: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM meta_deck WHERE event_id = ?", (_path(slug),)
    ).fetchone()[0]


def _league_as(slug: str) -> str:
    """``mtgo_site_league.html`` as the league ``slug``: its slug, then every
    other date in it, replaced, so the page's own date is the slug's."""
    day = re.search(r"\d{4}-\d{2}-\d{2}", slug)
    assert day is not None, slug
    return _read("mtgo_site_league.html").replace(LEAGUE, slug).replace("2026-10-02", day.group())


def _store(conn, html: str, *, read_at: str) -> None:
    """One page's event stored as read at ``read_at``, under a blob of its
    own, as the mirror's copy of it would be."""
    raw = mtgo_site.normalize(mtgo_site.extract_data(html))
    event = parse_event(raw, TournamentFile(_path_of(raw), "stored"), FORMATS)
    assert event is not None
    store_events(conn, [event], now=read_at)


def _reset_on(conn, fmt: str, day: str, *, source: str = "MTGmelee") -> None:
    """A reset of ``fmt`` that ``guide.window.format_resets`` detects on
    ``day``: a card banned in ``fmt`` whose last appearance is two decks of an
    event that day."""
    event_id = f"Tournaments/{source}/{day.replace('-', '/')}/reset-evidence.json"
    conn.execute("INSERT OR IGNORE INTO cards (grp_id, name) VALUES (1, 'Banned Card')")
    conn.execute(
        "INSERT INTO card_legality (grp_id, format, legality) VALUES (1, ?, 'banned')", (fmt,)
    )
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, format, "
        "tier) VALUES (?, ?, 's', ?, 'e', ?, ?, 'B')",
        (event_id, event_id, source, day, fmt),
    )
    for deck_ord in (0, 1):
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json) "
            "VALUES (?, ?, ?, '[]')",
            (event_id, deck_ord, json.dumps([{"count": 4, "name": "Banned Card"}])),
        )


# --- R3 (D10): the stored leagues read again ----------------------------------


def test_todays_league_is_read_again_on_every_run_and_nothing_else_stored(conn):
    """Of the stored events only today's Standard league is read again: not an
    older league, not today's challenge, not today's league of a format not
    followed, and not today's league marked a duplicate. The index's new slug
    is read as well, once."""
    old = "standard-league-2026-09-2011129"
    twin = "standard-league-2026-10-0511015"
    pauper = "pauper-league-2026-10-0511129"
    challenge = "standard-challenge-32-2026-10-0512855466"
    for slug in (old, TODAYS_LEAGUE, twin, pauper):
        _store(conn, _league_as(slug), read_at=EARLIER_STAMP)
    _store(
        conn,
        _read("mtgo_site_challenge.html").replace(CHALLENGE, challenge).replace(
            "2026-10-02", "2026-10-05"
        ),
        read_at=EARLIER_STAMP,
    )
    conn.execute(
        "UPDATE meta_event SET duplicate_of = ? WHERE event_id = ?",
        (_path(TODAYS_LEAGUE), _path(twin)),
    )
    tiers = dict(conn.execute("SELECT event_id, tier FROM meta_event").fetchall())
    assert tiers[_path(challenge)] != "C" and tiers[_path(pauper)] == "C"
    _stamp_at(conn, EARLIER)
    pages = {
        INDEX: _index_for(old, TODAYS_LEAGUE, twin, pauper, challenge, LEAGUE),
        _url(TODAYS_LEAGUE): _league_as(TODAYS_LEAGUE),
        _url(LEAGUE): _read("mtgo_site_league.html"),
    }

    fetch, calls = _fake_site(pages)
    assert _run(conn, fetch).status == "updated"
    assert calls == [INDEX, _url(TODAYS_LEAGUE), _url(LEAGUE)]

    fetch, calls = _fake_site(pages)
    assert _run(conn, fetch, at=T + 3 * H).status == "updated"
    assert calls == [INDEX, _url(TODAYS_LEAGUE)]

    fetch, calls = _fake_site(pages)
    assert _run(conn, fetch, at=T + 3 * H).status == "fresh"
    assert calls == []


@pytest.mark.parametrize(
    ("at", "lists_at", "empty_at", "read_again"),
    [
        (datetime(2026, 10, 5, 11, 59, tzinfo=UTC), "2026-10-04T20:00:00Z", None, False),
        (datetime(2026, 10, 5, 12, 0, tzinfo=UTC), "2026-10-04T20:00:00Z", None, True),
        (T, "2026-10-05T11:00:00Z", None, True),
        (T, "2026-10-05T12:30:00Z", None, False),
        # The later of the two stamps decides: an empty read after noon.
        (T, "2026-10-04T20:00:00Z", "2026-10-05T13:00:00Z", False),
        (T, None, None, True),
    ],
    ids=["before-noon", "at-noon", "read-this-morning", "read-after-noon",
         "emptied-after-noon", "never-stamped"],
)
def test_yesterdays_league_is_read_again_after_noon_unless_read_since(
    conn, at, lists_at, empty_at, read_again
):
    _store(conn, _league_as(YESTERDAYS_LEAGUE), read_at="2026-10-04T20:00:00Z")
    conn.execute(
        "UPDATE meta_event SET lists_read_at = ?, empty_read_at = ?, empty_read_kind = ? "
        "WHERE event_id = ?",
        (lists_at, empty_at, "empty" if empty_at else None, _path(YESTERDAYS_LEAGUE)),
    )
    _stamp_at(conn, EARLIER)
    fetch, calls = _fake_site({
        INDEX: _index_for(YESTERDAYS_LEAGUE),
        _url(YESTERDAYS_LEAGUE): _league_as(YESTERDAYS_LEAGUE),
    })
    assert _run(conn, fetch, at=at).status == "updated"
    assert calls == ([INDEX, _url(YESTERDAYS_LEAGUE)] if read_again else [INDEX])


def test_yesterdays_league_is_read_again_once(conn):
    """The read after noon stamps the league, so the next run leaves it."""
    _store(conn, _league_as(YESTERDAYS_LEAGUE), read_at="2026-10-04T20:00:00Z")
    _stamp_at(conn, EARLIER)
    pages = {
        INDEX: _index_for(YESTERDAYS_LEAGUE),
        _url(YESTERDAYS_LEAGUE): _league_as(YESTERDAYS_LEAGUE),
    }
    fetch, calls = _fake_site(pages)
    _run(conn, fetch)
    assert calls == [INDEX, _url(YESTERDAYS_LEAGUE)]
    assert _read_row(conn, YESTERDAYS_LEAGUE)[0] == STAMP
    fetch, calls = _fake_site(pages)
    _run(conn, fetch, at=T + 3 * H)
    assert calls == [INDEX]


def test_index_failure_is_failed_and_stores_nothing(conn):
    fetch, _ = _fake_site({})
    result = mtgo_site.refresh_mtgo_site(conn, pause_s=0, fetch=fetch, sleep=lambda s: None)
    assert result.status == "failed"
    assert conn.execute("SELECT COUNT(*) FROM meta_event").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM meta_fetch_source").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("failure", "reason"),
    [(TimeoutError("slow"), "timed out"),
     (urllib.error.URLError("down"), str(urllib.error.URLError("down")))],
)
def test_a_second_timeout_ends_the_run(conn, failure, reason):
    """A timeout or no connection is retried once; the second ends the run
    with a generic answer, which leaves no hold and no new stamp."""
    _stamp_at(conn, EARLIER)
    first, second = LEAGUE, "standard-challenge-32-2026-10-0212855466"
    fetch, calls = _fake_site({
        mtgo_site.INDEX_URL: _index_for(first, second),
        _url(first): failure,
        _url(second): _read("mtgo_site_challenge.html"),
    })
    result = _run(conn, fetch)
    assert calls == [mtgo_site.INDEX_URL, _url(first), _url(first)]
    assert (result.status, result.error, result.events) == ("failed", reason, 0)
    assert result.answer is not None
    assert (result.answer.kind, result.answer.place) == (AnswerKind.GENERIC, f"event:{first}")
    assert result.hold_after is None and read_hold(conn, MTGO) is None
    assert _stamped(conn) == (EARLIER_STAMP, 0, 0)
    assert conn.execute("SELECT COUNT(*) FROM meta_event").fetchone()[0] == 0


def test_an_index_timing_out_twice_is_a_generic_answer(conn):
    fetch, calls = _fake_site({mtgo_site.INDEX_URL: TimeoutError("slow")})
    result = _run(conn, fetch)
    assert calls == [mtgo_site.INDEX_URL, mtgo_site.INDEX_URL]
    assert (result.status, result.error) == ("failed", "timed out")
    assert result.answer is not None and result.answer.kind == AnswerKind.GENERIC
    assert read_hold(conn, MTGO) is None and _stamped(conn) is None


def test_a_malformed_page_is_skipped_not_fatal(conn):
    _stamp_at(conn, EARLIER)
    slug = "standard-challenge-32-2026-09-2012855466"
    page = ('window.MTGO.decklists.data = {"format": "CSTANDARD", "brackets": '
            '[{"matches": [{"players": ["x", "y"]}]}]};')
    fetch, _ = _fake_site({
        mtgo_site.INDEX_URL: _index_for(slug),
        f"{mtgo_site.SITE}/decklist/{slug}": page,
    })
    result = _run(conn, fetch)
    assert (result.status, result.skipped) == ("updated", 1)


def test_a_league_of_a_format_outside_the_list_is_skipped():
    league = mtgo_site.extract_data(_read("mtgo_site_league.html"))
    league = {**league, "site_name": "pauper-league-2026-10-0211129"}
    raw = mtgo_site.normalize(league)
    assert raw["Tournament"]["Formats"] == "Pauper"
    assert parse_event(raw, TournamentFile(_path_of(raw), "x")) is None
    assert parse_event(raw, TournamentFile(_path_of(raw), "x"), ("Pauper",)) is not None


def test_a_modern_league_is_kept_under_modern():
    league = mtgo_site.extract_data(_read("mtgo_site_league.html"))
    league = {**league, "site_name": "modern-league-2026-10-0211129"}
    raw = mtgo_site.normalize(league)
    event = parse_event(raw, TournamentFile(_path_of(raw), "x"))
    assert event is not None and event.format == "Modern"


def test_the_index_selects_only_the_asked_formats_slugs():
    html = _read("mtgo_site_index.html")

    premodern = mtgo_site.list_event_slugs(html, ("Premodern",))
    assert premodern and all(s.startswith("premodern-") for s in premodern)
    modern = mtgo_site.list_event_slugs(html, ("Modern",))
    assert modern and all(s.startswith("modern-") for s in modern)
    both = mtgo_site.list_event_slugs(html, ("Standard", "Premodern"))
    assert {s.split("-")[0] for s in both} == {"standard", "premodern"}


def test_format_codes_become_names_and_an_unknown_code_stays():
    page = {"format": "CPAUPER", "site_name": "pauper-challenge-32-2026-10-0212855466"}
    assert mtgo_site.normalize(page)["Tournament"]["Formats"] == "Pauper"
    page = {"format": "CPREMODERN", "site_name": "premodern-challenge-16-2026-10-0112855458"}
    assert mtgo_site.normalize(page)["Tournament"]["Formats"] == "Premodern"
    page = {"format": "CDUELCOMMANDER", "site_name": "duel-commander-challenge-2026-10-01"}
    assert mtgo_site.normalize(page)["Tournament"]["Formats"] == "CDUELCOMMANDER"


def test_index_with_no_decklist_links_is_failed(conn):
    fetch, _ = _fake_site({mtgo_site.INDEX_URL: "<html>redesigned</html>"})
    result = mtgo_site.refresh_mtgo_site(conn, pause_s=0, fetch=fetch, sleep=lambda s: None)
    assert result.status == "failed"
    assert result.answer is not None and result.answer.kind == AnswerKind.GENERIC
    assert result.answer.place == "index"
    assert conn.execute("SELECT COUNT(*) FROM meta_fetch_source").fetchone()[0] == 0
    assert read_hold(conn, MTGO) is None


def test_a_page_timing_out_once_is_retried(conn):
    slug = "standard-challenge-32-2026-09-2012855466"
    page_url = f"{mtgo_site.SITE}/decklist/{slug}"
    page = _read("mtgo_site_challenge.html")
    attempts = []

    def fetch(url: str) -> str:
        if url == mtgo_site.INDEX_URL:
            return _index_for(slug)
        attempts.append(url)
        if len(attempts) == 1:
            raise TimeoutError("slow")
        return page

    _stamp_at(conn, EARLIER)
    result = _run(conn, fetch)
    assert attempts == [page_url, page_url]
    assert (result.status, result.events, result.skipped) == ("updated", 1, 0)


def test_refresh_fetches_only_the_asked_formats_pages(conn):
    html = _read("mtgo_site_index.html")
    pauper = mtgo_site.list_event_slugs(html, ("Pauper",))
    assert pauper and all(s.startswith("pauper-") for s in pauper)
    # One Pauper page, built from the league fixture's text.
    league = _read("mtgo_site_league.html")
    slug = "pauper-league-2026-09-2011129"
    page = league.replace("standard-league-", "pauper-league-")
    assert page != league
    pages = {
        mtgo_site.INDEX_URL: html + _index_for(slug),
        f"{mtgo_site.SITE}/decklist/{slug}": page,
    }
    # The index's own Pauper pages are not served: a 404 skips each one,
    # where no connection would end the run.
    fetch, calls = _fake_site(pages, missing=404)
    _stamp_at(conn, EARLIER)
    result = _run(conn, fetch, formats=("Pauper",), max_pages=100)
    page_calls = {c for c in calls if c != mtgo_site.INDEX_URL}
    wanted = {f"{mtgo_site.SITE}/decklist/{s}" for s in (*pauper, slug)}
    assert page_calls == wanted
    assert result.events == 1
    assert [r["format"] for r in conn.execute("SELECT format FROM meta_event")] == ["Pauper"]


# --- The answers (plan 14, S4): the index and an event page ---------------


@pytest.mark.parametrize(
    ("code", "retry_after", "status", "answers", "not_before"),
    [
        (401, None, HoldStatus.PAUSED, 0, None),
        (403, None, HoldStatus.PAUSED, 0, None),
        (451, None, HoldStatus.PAUSED, 0, None),
        # max(Retry-After, now + 3 h)
        (429, "60", HoldStatus.WAITING, 0, T + 3 * H),
        (429, "18000", HoldStatus.WAITING, 0, T + 5 * H),
        # max(now + 1 h, Retry-After); the run's first request, so it counts
        (503, None, HoldStatus.WAITING, 1, T + H),
        (503, "7200", HoldStatus.WAITING, 1, T + 2 * H),
    ],
)
def test_an_answer_at_the_index_ends_the_run_and_holds_the_source(
    conn, code, retry_after, status, answers, not_before
):
    fetch, calls = _fake_site({INDEX: _http_error(INDEX, code, retry_after)})
    result = _run(conn, fetch)
    assert calls == [INDEX]  # an HTTP status is never sent again
    assert result.status == "failed"
    assert result.error == f"HTTP {code} {HTTPStatus(code).phrase}"
    answer = result.answer
    assert answer is not None
    assert (answer.http_status, answer.place, answer.first_request, answer.at) == (
        code, "index", True, T
    )
    expected = Hold(
        source=MTGO, status=status, http_status=code, answers=answers, since=T,
        last_status=code, last_at=T, not_before=not_before,
    )
    assert result.hold_before is None
    assert result.hold_after == expected == read_hold(conn, MTGO)
    assert _stamped(conn) is None


@pytest.mark.parametrize("code", [404, 410, 500, 502])
def test_a_gone_or_failing_index_is_a_generic_answer(conn, code):
    fetch, calls = _fake_site({}, missing=code)
    result = _run(conn, fetch)
    assert calls == [INDEX]
    assert result.status == "failed"
    assert result.error == f"HTTP {code} {HTTPStatus(code).phrase}"
    assert result.answer is not None and result.answer.kind == AnswerKind.GENERIC
    assert result.hold_after is None and read_hold(conn, MTGO) is None
    assert _stamped(conn) is None


@pytest.mark.parametrize(
    ("code", "status", "not_before"),
    [
        (401, HoldStatus.PAUSED, None),
        (403, HoldStatus.PAUSED, None),
        (451, HoldStatus.PAUSED, None),
        (429, HoldStatus.WAITING, T + 3 * H),
        # The index opened first, so this 503 does not count (k1).
        (503, HoldStatus.WAITING, T + H),
        (500, None, None),  # generic: no hold
    ],
)
def test_an_answer_at_an_event_page_ends_the_run_and_keeps_what_it_parsed(
    conn, code, status, not_before
):
    _stamp_at(conn, EARLIER)
    answered = "standard-challenge-32-2026-10-0212855471"
    fetch, calls = _fake_site({
        INDEX: _index_for(LEAGUE, answered, CHALLENGE),
        _url(LEAGUE): _read("mtgo_site_league.html"),
        _url(answered): _http_error(_url(answered), code),
        _url(CHALLENGE): _read("mtgo_site_challenge.html"),
    })
    result = _run(conn, fetch)
    assert calls == [INDEX, _url(LEAGUE), _url(answered)]
    assert (result.status, result.events) == ("failed", 1)
    assert result.error == f"HTTP {code} {HTTPStatus(code).phrase}"
    assert result.answer is not None
    assert (result.answer.place, result.answer.first_request) == (f"event:{answered}", False)
    stored = [r[0] for r in conn.execute("SELECT event_id FROM meta_event")]
    assert stored == [_path(LEAGUE)]
    assert _decks(conn, LEAGUE) == 3
    assert _read_row(conn, LEAGUE)[:3] == (STAMP, None, None)
    expected = None if status is None else Hold(
        source=MTGO, status=status, http_status=code, answers=0, since=T,
        last_status=code, last_at=T, not_before=not_before,
    )
    assert result.hold_after == expected == read_hold(conn, MTGO)
    assert _stamped(conn) == (EARLIER_STAMP, 0, 0)


@pytest.mark.parametrize(("at_index", "answers"), [(True, 3), (False, 0)])
def test_a_503_counts_only_before_any_page_opened(conn, at_index, answers):
    """Two first-request 503s already counted: a third at the index makes
    three; one after the index opened restarts the count (k1)."""
    _hold(conn, "waiting", 503, answers=2, since=T - 2 * H, not_before=T - H)
    _stamp_at(conn, EARLIER)
    pages: dict[str, str | BaseException] = {INDEX: _http_error(INDEX, 503)}
    if not at_index:
        pages = {INDEX: _index_for(LEAGUE), _url(LEAGUE): _http_error(_url(LEAGUE), 503)}
    fetch, _ = _fake_site(pages)
    result = _run(conn, fetch)
    assert result.status == "failed"
    hold = read_hold(conn, MTGO)
    assert hold is not None and hold == result.hold_after
    assert (hold.status, hold.http_status, hold.answers) == (HoldStatus.WAITING, 503, answers)
    assert (hold.last_at, hold.not_before) == (T, T + H)


def test_a_second_429_pauses_the_source(conn):
    before = _hold(conn, "waiting", 429, since=T - 4 * H, not_before=T - H)
    fetch, _ = _fake_site({INDEX: _http_error(INDEX, 429)})
    result = _run(conn, fetch)
    hold = read_hold(conn, MTGO)
    assert result.hold_before == before
    assert hold is not None and hold == result.hold_after
    assert (hold.status, hold.http_status, hold.since) == (HoldStatus.PAUSED, 429, T)


@pytest.mark.parametrize("code", [404, 410])
def test_a_gone_event_page_is_skipped_and_the_run_completes(conn, code):
    _stamp_at(conn, EARLIER)
    gone = "standard-challenge-32-2026-10-0212855471"
    fetch, calls = _fake_site(
        {INDEX: _index_for(gone, LEAGUE), _url(LEAGUE): _read("mtgo_site_league.html")},
        missing=code,
    )
    result = _run(conn, fetch)
    assert calls == [INDEX, _url(gone), _url(LEAGUE)]
    assert (result.status, result.events, result.skipped) == ("updated", 1, 1)
    assert result.answer is None and result.hold_after is None
    assert _stamped(conn) == (STAMP, 1, 1)


def test_a_redirected_index_is_read_where_it_lands(conn):
    _stamp_at(conn, EARLIER)
    landing = mtgo_site.RedirectedError(
        INDEX, f"{mtgo_site.SITE}/en/decklists", _index_for(LEAGUE).encode()
    )
    fetch, calls = _fake_site({INDEX: landing, _url(LEAGUE): _read("mtgo_site_league.html")})
    result = _run(conn, fetch)
    assert calls == [INDEX, _url(LEAGUE)]
    assert (result.status, result.events) == ("updated", 1)


def _undecodable() -> UnicodeDecodeError:
    return UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


def test_an_undecodable_page_is_unparsable_and_an_undecodable_index_generic(conn, caplog):
    """A page whose bytes are not UTF-8 (3a's review). At an event page it is
    skipped as unparsable and the run goes on; at the index it is a generic
    answer, which holds nothing."""
    _stamp_at(conn, EARLIER)
    fetch, calls = _fake_site({
        INDEX: _index_for(LEAGUE, CHALLENGE),
        _url(LEAGUE): _undecodable(),
        _url(CHALLENGE): _read("mtgo_site_challenge.html"),
    })
    with caplog.at_level(logging.WARNING, logger=mtgo_site.__name__):
        result = _run(conn, fetch)
    assert calls == [INDEX, _url(LEAGUE), _url(CHALLENGE)]
    assert (result.status, result.events, result.skipped) == ("updated", 1, 1)
    assert result.answer is None
    assert any("unparsable" in r.getMessage() and LEAGUE in r.getMessage()
               for r in caplog.records if r.levelno == logging.WARNING)

    fetch, calls = _fake_site({INDEX: _undecodable()})
    result = _run(conn, fetch, at=T + 4 * H)
    assert calls == [INDEX]
    assert result.status == "failed"
    assert result.answer is not None
    assert (result.answer.kind, result.answer.place) == (AnswerKind.GENERIC, "index")
    assert result.hold_after is None and read_hold(conn, MTGO) is None


def test_an_identical_page_stamps_the_read(conn):
    _stamp_at(conn, EARLIER)
    pages = {INDEX: _index_for(TODAYS_LEAGUE), _url(TODAYS_LEAGUE): _read("mtgo_site_league.html")}
    fetch, _ = _fake_site(pages)
    assert _run(conn, fetch, at=T - 6 * H).events == 1
    fetch, calls = _fake_site(pages)
    result = _run(conn, fetch)
    assert calls == [INDEX, _url(TODAYS_LEAGUE)]
    assert (result.status, result.events, result.skipped) == ("updated", 0, 0)
    assert _read_row(conn, TODAYS_LEAGUE)[:3] == (STAMP, None, None)


def test_requests_are_a_second_apart(conn):
    _stamp_at(conn, EARLIER)
    sleeps: list[float] = []
    league = _read("mtgo_site_league.html")
    fetch, calls = _fake_site({
        INDEX: _index_for(LEAGUE, TODAYS_LEAGUE), _url(LEAGUE): league, _url(TODAYS_LEAGUE): league,
    })
    mtgo_site.refresh_mtgo_site(conn, fetch=fetch, sleep=sleeps.append, now=lambda: T)
    assert len(calls) == 3 and sleeps == [1.0, 1.0]


# --- The month pages (plan 14, S4): their answers, and the gap fill -------


@pytest.mark.parametrize(
    ("code", "status", "not_before"),
    [
        (401, HoldStatus.PAUSED, None),
        (403, HoldStatus.PAUSED, None),
        (451, HoldStatus.PAUSED, None),
        (429, HoldStatus.WAITING, T + 3 * H),
        # The index opened first, so this 503 does not count (k1).
        (503, HoldStatus.WAITING, T + H),
        (500, None, None),  # generic: no hold
    ],
)
def test_an_answer_at_a_month_page_ends_the_run_before_any_event_page(
    conn, code, status, not_before
):
    """The last run was in September, so September's page is read after the
    index and before the index's new league; its answer ends the run there,
    and the HTTP status is never sent again."""
    _stamp_at(conn, LAST_MONTH)
    fetch, calls = _fake_site({
        INDEX: _index_for(LEAGUE),
        SEPTEMBER: _http_error(SEPTEMBER, code),
        _url(LEAGUE): _read("mtgo_site_league.html"),
    })
    result = _run(conn, fetch)
    assert calls == [INDEX, SEPTEMBER]
    assert (result.status, result.events) == ("failed", 0)
    assert result.error == f"HTTP {code} {HTTPStatus(code).phrase}"
    answer = result.answer
    assert answer is not None
    assert (answer.http_status, answer.place, answer.first_request) == (
        code, "month:2026-09", False
    )
    expected = None if status is None else Hold(
        source=MTGO, status=status, http_status=code, answers=0, since=T,
        last_status=code, last_at=T, not_before=not_before,
    )
    assert result.hold_after == expected == read_hold(conn, MTGO)
    assert _stamped(conn) == ("2026-09-28T12:00:00Z", 0, 0)
    assert conn.execute("SELECT COUNT(*) FROM meta_event").fetchone()[0] == 0


def test_a_month_page_timing_out_twice_ends_the_run(conn):
    _stamp_at(conn, LAST_MONTH)
    fetch, calls = _fake_site({INDEX: _index_for(LEAGUE), SEPTEMBER: TimeoutError("slow")})
    result = _run(conn, fetch)
    assert calls == [INDEX, SEPTEMBER, SEPTEMBER]
    assert (result.status, result.error) == ("failed", "timed out")
    assert result.answer is not None
    assert (result.answer.kind, result.answer.place) == (AnswerKind.GENERIC, "month:2026-09")
    assert result.hold_after is None and read_hold(conn, MTGO) is None
    assert _stamped(conn) == ("2026-09-28T12:00:00Z", 0, 0)


@pytest.mark.parametrize(
    "page",
    [
        _http_error(SEPTEMBER, 404),
        _http_error(SEPTEMBER, 410),
        mtgo_site.RedirectedError(SEPTEMBER, INDEX, b"<html>the index</html>"),
        "<html>redesigned</html>",
        _undecodable(),
    ],
    ids=["404", "410", "redirect", "no-link", "undecodable"],
)
def test_a_month_page_gone_redirected_unlinked_or_undecodable_is_skipped(conn, caplog, page):
    """Such a month page is skipped with a warning (D19 for the redirect),
    and the run reads the index's league and completes. A month page is not
    an event, so it does not count as a skipped one."""
    _stamp_at(conn, LAST_MONTH)
    fetch, calls = _fake_site({
        INDEX: _index_for(LEAGUE),
        SEPTEMBER: page,
        _url(LEAGUE): _read("mtgo_site_league.html"),
    })
    with caplog.at_level(logging.WARNING, logger=mtgo_site.__name__):
        result = _run(conn, fetch)
    assert calls == [INDEX, SEPTEMBER, _url(LEAGUE)]
    assert (result.status, result.events, result.skipped) == ("updated", 1, 0)
    assert result.answer is None and result.hold_after is None
    assert _stamped(conn) == (STAMP, 1, 0)
    assert any("month:2026-09" in r.getMessage()
               for r in caplog.records if r.levelno == logging.WARNING)


def test_on_the_first_yesterdays_events_come_from_last_months_page(conn):
    """``mtgo_site_month.html`` is every decklist anchor of
    ``https://www.mtgo.com/decklists/2026/09`` (fetched 2026-10-05), verbatim
    and in order, in a minimal document.

    On 2026-10-01, after a run the evening before, the index carries today's
    league and one of yesterday's; September's page carries the rest of
    yesterday's Standard and Modern events, and none of the 29th's. The event
    pages are not served: a 404 skips each, and the requests show the list."""
    first = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
    _stamp_at(conn, datetime(2026, 9, 30, 22, 0, tzinfo=UTC))
    todays = "standard-league-2026-10-0111129"
    fetch, calls = _fake_site(
        {
            INDEX: _index_for(todays, "standard-league-2026-09-3011129"),
            SEPTEMBER: _read("mtgo_site_month.html"),
        },
        missing=404,
    )
    result = _run(conn, fetch, at=first)
    assert calls == [INDEX, SEPTEMBER, *map(_url, [
        todays,
        "standard-league-2026-09-3011129",
        "modern-challenge-96-2026-09-3012855453",
        "modern-challenge-32-2026-09-3012855450",
        "modern-league-2026-09-3011161",
    ])]
    assert (result.status, result.skipped) == ("updated", 5)


def test_after_a_completed_run_this_month_no_month_page_is_read(conn):
    """``mtgo_site_month.html`` is every decklist anchor of
    ``https://www.mtgo.com/decklists/2026/09`` (fetched 2026-10-05), verbatim
    and in order, in a minimal document.

    September's page is served, but the run of 2026-10-01 already reached
    back to it."""
    _stamp_at(conn, datetime(2026, 10, 1, 6, 0, tzinfo=UTC))
    fetch, calls = _fake_site({
        INDEX: _index_for(LEAGUE),
        SEPTEMBER: _read("mtgo_site_month.html"),
        _url(LEAGUE): _read("mtgo_site_league.html"),
    })
    result = _run(conn, fetch)
    assert calls == [INDEX, _url(LEAGUE)]
    assert (result.status, result.events) == ("updated", 1)


def test_with_no_stamp_each_format_reaches_back_to_its_window_or_newest_event(conn):
    """``mtgo_site_month.html`` is every decklist anchor of
    ``https://www.mtgo.com/decklists/2026/09`` (fetched 2026-10-05), verbatim
    and in order, in a minimal document.

    No run has completed. Standard's reset on 2026-09-28 starts its window
    on the 29th; Modern, with no reset, starts at its newest stored MTGO
    event, a league of the 30th. So September's page adds Standard's events
    of the 29th and 30th and Modern's of the 30th, less the league already
    stored. The event pages are not served: a 404 skips each."""
    _reset_on(conn, "Standard", "2026-09-28")
    assert [r.date for r in format_resets(conn, "Standard")] == ["2026-09-28"]
    assert format_resets(conn, "Modern") == []
    _store(conn, _league_as("modern-league-2026-09-3011161"), read_at="2026-09-30T20:00:00Z")
    fetch, calls = _fake_site(
        {
            INDEX: _index_for(LEAGUE),
            SEPTEMBER: _read("mtgo_site_month.html"),
            _url(LEAGUE): _read("mtgo_site_league.html"),
        },
        missing=404,
    )
    result = _run(conn, fetch)
    assert calls == [INDEX, SEPTEMBER, *map(_url, [
        LEAGUE,
        "modern-challenge-96-2026-09-3012855453",
        "modern-challenge-32-2026-09-3012855450",
        "standard-league-2026-09-3011129",
        "standard-challenge-16-2026-09-2912855524",
        "standard-league-2026-09-2911015",
        "standard-league-2026-09-2911129",
    ])]
    assert (result.status, result.events, result.skipped) == ("updated", 1, 6)


def test_with_no_stamp_the_reach_is_never_more_than_ninety_days(conn):
    """A reset of Standard on 2026-05-01, and a stored MTGO event that day,
    would each reach back to May; 90 days before 2026-10-05 is 2026-07-07.
    So September's, August's and July's pages are read, and of July's only
    the league of the 7th is kept."""
    _reset_on(conn, "Standard", "2026-05-01", source="MTGO")
    assert [r.date for r in format_resets(conn, "Standard")] == ["2026-05-01"]
    august, july = f"{INDEX}/2026/08", f"{INDEX}/2026/07"
    seventh, sixth = "standard-league-2026-07-0711129", "standard-league-2026-07-0611129"
    fetch, calls = _fake_site(
        {
            INDEX: _index_for(LEAGUE),
            SEPTEMBER: _index_for("pauper-league-2026-09-2011129"),
            august: _index_for("pauper-league-2026-08-2011129"),
            july: _index_for(seventh, sixth),
        },
        missing=404,
    )
    result = _run(conn, fetch, formats=("Standard",))
    assert calls == [INDEX, SEPTEMBER, august, july, _url(LEAGUE), _url(seventh)]
    assert (result.status, result.skipped) == ("updated", 2)


def test_month_pages_stop_once_the_list_holds_forty(conn):
    """``mtgo_site_month.html`` is every decklist anchor of
    ``https://www.mtgo.com/decklists/2026/09`` (fetched 2026-10-05), verbatim
    and in order, in a minimal document.

    With nothing stored and no stamp, both formats start 90 days back, so
    September, August and July are due. September's 152 Standard and Modern
    events fill the list, so August's page is never read, and the event
    pages are the 40 newest: the index's league, then September's from the
    30th down to its 39th, ``modern-league-2026-09-2310983``."""
    fetch, calls = _fake_site(
        {INDEX: _index_for(LEAGUE), SEPTEMBER: _read("mtgo_site_month.html")}, missing=404
    )
    result = _run(conn, fetch)
    assert calls[:4] == [
        INDEX, SEPTEMBER, _url(LEAGUE), _url("modern-challenge-96-2026-09-3012855453")
    ]
    assert len(calls) == 2 + 40
    assert calls[-1] == _url("modern-league-2026-09-2310983")
    assert not any(c.startswith(f"{INDEX}/") for c in calls[2:])
    assert (result.status, result.skipped) == ("updated", 40)
    assert _stamped(conn) == (STAMP, 0, 40)


# --- mtgo_site_league_emptied.html ----------------------------------------


def test_an_emptied_league_never_erases_the_stored_one(conn):
    """``mtgo_site_league_emptied.html`` is ``mtgo_site_league.html`` with its
    ``decklists`` key removed by script, because the league seen emptied had
    its lists again on 2026-10-05.

    G1: the empty copy is declined and not counted, the stored decks stay,
    and the read is stamped 'empty' with the empty copy's blob."""
    noon = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    evening = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)  # the league's own day: read again
    _stamp_at(conn, noon - 10 * H)  # a run earlier that day: no month page
    fetch, _ = _fake_site({INDEX: _index_for(LEAGUE), _url(LEAGUE): _read("mtgo_site_league.html")})
    assert _run(conn, fetch, at=noon).events == 1
    lists_at, _, _, full_sha = _read_row(conn, LEAGUE)
    assert lists_at == "2026-10-02T12:00:00Z" and _decks(conn, LEAGUE) == 3

    fetch, calls = _fake_site(
        {INDEX: _index_for(LEAGUE), _url(LEAGUE): _read("mtgo_site_league_emptied.html")}
    )
    result = _run(conn, fetch, at=evening)
    assert calls == [INDEX, _url(LEAGUE)]
    assert (result.status, result.events, result.skipped) == ("updated", 0, 1)
    assert _decks(conn, LEAGUE) == 3
    lists_at, empty_at, kind, sha = _read_row(conn, LEAGUE)
    assert (lists_at, empty_at, kind) == (
        "2026-10-02T12:00:00Z", "2026-10-02T20:00:00Z", "empty"
    )
    assert sha != full_sha  # nobody downloads the same empty copy again
    assert _stamped(conn) == ("2026-10-02T20:00:00Z", 0, 1)


def test_an_unknown_emptied_league_is_stored_with_no_decks(conn):
    """``mtgo_site_league_emptied.html`` is ``mtgo_site_league.html`` with its
    ``decklists`` key removed by script, because the league seen emptied had
    its lists again on 2026-10-05. Emptied is not unparsable."""
    _stamp_at(conn, EARLIER)
    fetch, _ = _fake_site(
        {INDEX: _index_for(LEAGUE), _url(LEAGUE): _read("mtgo_site_league_emptied.html")}
    )
    result = _run(conn, fetch)
    assert (result.status, result.events, result.skipped) == ("updated", 1, 0)
    assert _decks(conn, LEAGUE) == 0
    assert _read_row(conn, LEAGUE)[:3] == (None, STAMP, "empty")


# --- The end of the run ---------------------------------------------------


def test_a_404_on_a_stored_event_records_it_gone(conn):
    _stamp_at(conn, EARLIER)
    league = _read("mtgo_site_league.html")
    fetch, _ = _fake_site({INDEX: _index_for(TODAYS_LEAGUE), _url(TODAYS_LEAGUE): league})
    _run(conn, fetch, at=T - 6 * H)
    fetch, calls = _fake_site({INDEX: _index_for(TODAYS_LEAGUE)}, missing=404)
    result = _run(conn, fetch)
    assert calls == [INDEX, _url(TODAYS_LEAGUE)]
    assert (result.status, result.events, result.skipped) == ("updated", 0, 1)
    assert _read_row(conn, TODAYS_LEAGUE)[:3] == ("2026-10-05T08:00:00Z", STAMP, "gone")
    assert _decks(conn, TODAYS_LEAGUE) == 3
    assert _stamped(conn) == (STAMP, 0, 1)


def test_a_redirect_off_an_event_page_is_gone_and_never_unparsable(conn):
    """D19. Two unparsable pages, the redirect, then a good page: were the
    redirect the third unparsable page in a row, the run would end before
    the good one."""
    _stamp_at(conn, EARLIER)
    league = _read("mtgo_site_league.html")
    fetch, _ = _fake_site({INDEX: _index_for(TODAYS_LEAGUE), _url(TODAYS_LEAGUE): league})
    _run(conn, fetch, at=T - 6 * H)

    # Dated today, like the league R3 reads again, so they come before it:
    # a day's pages keep their order, the index's before R3's.
    u1 = "standard-challenge-32-2026-10-0512855501"
    u2 = "standard-challenge-32-2026-10-0512855502"
    redirect = mtgo_site.RedirectedError(_url(TODAYS_LEAGUE), INDEX, b"<html>the index</html>")
    fetch, calls = _fake_site({
        INDEX: _index_for(u1, u2, TODAYS_LEAGUE, CHALLENGE),
        _url(u1): "<html>no data script</html>",
        _url(u2): "window.MTGO.decklists.data = {oops",
        _url(TODAYS_LEAGUE): redirect,
        _url(CHALLENGE): _read("mtgo_site_challenge.html"),
    })
    result = _run(conn, fetch)
    assert calls == [INDEX, _url(u1), _url(u2), _url(TODAYS_LEAGUE), _url(CHALLENGE)]
    assert (result.status, result.events, result.skipped) == ("updated", 1, 3)
    assert _read_row(conn, TODAYS_LEAGUE)[1:3] == (STAMP, "gone")
    assert _decks(conn, TODAYS_LEAGUE) == 3
    assert _decks(conn, CHALLENGE) == 32


def test_three_unparsable_pages_in_a_row_complete_the_run(conn, caplog):
    unparsable = [f"standard-challenge-32-2026-10-04128555{n:02d}" for n in range(3)]
    _hold(conn, "waiting", 503, since=T - 2 * H, not_before=T - H)
    _stamp_at(conn, EARLIER)
    fetch, calls = _fake_site({
        INDEX: _index_for(*unparsable, CHALLENGE),
        **{_url(s): "<html>redesigned</html>" for s in unparsable},
        _url(CHALLENGE): _read("mtgo_site_challenge.html"),
    })
    with caplog.at_level(logging.WARNING, logger=mtgo_site.__name__):
        result = _run(conn, fetch)
    assert calls == [INDEX, *map(_url, unparsable)]
    assert (result.status, result.events, result.skipped) == ("updated", 0, 3)
    assert result.answer is None
    # Completed: stamped, and the hold lifted.
    assert _stamped(conn) == (STAMP, 0, 3)
    assert result.hold_after is None and read_hold(conn, MTGO) is None
    assert any("unparsable" in r.getMessage() and "run" in r.getMessage()
               for r in caplog.records if r.levelno == logging.WARNING)


def test_a_run_cut_at_forty_pages_completes(conn):
    slugs = [f"standard-league-2026-09-01{n:05d}" for n in range(41)]
    league = _read("mtgo_site_league.html")
    fetch, calls = _fake_site({INDEX: _index_for(*slugs), **{_url(s): league for s in slugs}})
    result = _run(conn, fetch)
    assert calls == [INDEX, *(_url(s) for s in slugs[:40])]
    assert (result.status, result.events, result.skipped) == ("updated", 40, 0)
    assert _stamped(conn) == (STAMP, 40, 0)


# --- The run's frame: the gate, and what every result carries -------------


@pytest.mark.parametrize("by_hand", [False, True])
def test_a_wait_still_ahead_holds_every_run_even_forced(conn, by_hand):
    hold = _hold(conn, "waiting", 429, since=T - H, not_before=T + 2 * H)
    fetch, calls = _fake_site({})
    result = _run(conn, fetch, by_hand=by_hand, force=True)
    assert calls == []
    assert (result.status, result.events, result.by_hand) == ("held", 0, by_hand)
    assert result.hold_before == hold and result.hold_after == hold
    assert read_hold(conn, MTGO) == hold


def test_a_pause_holds_the_loop_and_lets_one_hand_run_through(conn):
    hold = _hold(conn, "paused", 403, since=T - 24 * H, not_before=None)
    _stamp_at(conn, T - H)  # fresh, which a hand run through a pause ignores
    fetch, calls = _fake_site({INDEX: _index_for("pauper-league-2026-10-0511129")})
    loop = _run(conn, fetch)
    assert (loop.status, calls, loop.age_seconds) == ("held", [], 3600.0)

    hand = _run(conn, fetch, by_hand=True)
    assert calls == [INDEX]
    assert (hand.status, hand.events, hand.by_hand) == ("updated", 0, True)
    assert hand.hold_before == hold and hand.hold_after is None
    assert read_hold(conn, MTGO) is None
    assert hand.age_seconds == 0.0
    assert _stamped(conn) == (STAMP, 0, 0)


@pytest.mark.parametrize("by_hand", [False, True])
def test_a_passed_wait_leaves_the_freshness_rule_to_decide(conn, by_hand):
    hold = _hold(conn, "waiting", 503, answers=1, since=T - 2 * H, not_before=T - H)
    _stamp_at(conn, T - 150 * timedelta(minutes=1))
    fetch, calls = _fake_site({})
    result = _run(conn, fetch, by_hand=by_hand)
    assert (result.status, calls, result.age_seconds) == ("fresh", [], 9000.0)
    assert result.hold_before == hold and result.hold_after == hold


def test_an_answered_run_reports_the_stored_copys_age(conn):
    _stamp_at(conn, T - 5 * H)
    fetch, _ = _fake_site({INDEX: _http_error(INDEX, 403)})
    result = _run(conn, fetch)
    assert (result.status, result.age_seconds) == ("failed", 18000.0)
    assert _stamped(conn) == ("2026-10-05T09:00:00Z", 0, 0)


# --- fetch_page -------------------------------------------------------------


class _Response:
    def __init__(self, body: bytes, final_url: str) -> None:
        self._body, self._final_url = body, final_url

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._final_url


def test_fetch_page_reports_a_redirect_and_reads_a_page(monkeypatch):
    sent = []

    def landing(request, timeout):
        sent.append(request)
        return _Response(b"<html>the index</html>", INDEX)

    monkeypatch.setattr(mtgo_site.urllib.request, "urlopen", landing)
    with pytest.raises(mtgo_site.RedirectedError) as info:
        mtgo_site.fetch_page(_url(LEAGUE))
    assert (info.value.final_url, info.value.body) == (INDEX, b"<html>the index</html>")
    assert sent[0].get_header("User-agent") == mtgo_site.USER_AGENT

    monkeypatch.setattr(
        mtgo_site.urllib.request, "urlopen",
        lambda request, timeout: _Response("<html>Æther</html>".encode(), request.full_url),
    )
    assert mtgo_site.fetch_page(_url(LEAGUE)) == "<html>Æther</html>"
