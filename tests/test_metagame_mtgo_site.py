"""mtgo.com's own decklist pages as a corpus source. The fixtures are an
anonymised event page and fbettega's independent copy of the same event
(handles Player01..., loginids 9000NN), so the expectations come from
fbettega's file, not from this module's output."""

from __future__ import annotations

import dataclasses
import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.metagame import mtgo_site
from sensei_top.metagame.source import TournamentFile, parse_event

FIX = Path(__file__).parent / "fixtures"


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
    assert mtgo_site.list_event_slugs(html) == [
        "standard-league-2026-10-0311129",
        "standard-challenge-32-2026-10-0212855471",
        "standard-challenge-32-2026-10-0212855466",
        "standard-league-2026-10-0211129",
        "standard-challenge-16-2026-10-0112855458",
        "standard-league-2026-10-0111129",
    ]
    repeated = _index_for("standard-a-2026-10-0111", "modern-b-2026-10-0122",
                          "standard-a-2026-10-0111")
    assert mtgo_site.list_event_slugs(repeated) == ["standard-a-2026-10-0111"]


def test_extract_data_is_none_without_the_script():
    assert mtgo_site.extract_data("<html>nothing</html>") is None
    assert mtgo_site.extract_data("window.MTGO.decklists.data = {oops") is None


def test_mtgo_site_never_retains_a_player_name(conn):
    events = []
    for name in ("mtgo_site_challenge.html", "mtgo_site_league.html"):
        raw = mtgo_site.normalize(mtgo_site.extract_data(_read(name)))
        events.append(parse_event(raw, TournamentFile(_path_of(raw), "x")))
    from sensei_top.metagame.source import store_events

    store_events(conn, events)
    blob = repr([dataclasses.asdict(e) for e in events])
    dump = "\n".join(
        str(tuple(row)) for t in ("meta_event", "meta_deck")
        for row in conn.execute(f"SELECT * FROM {t}")
    )
    for text in (blob, dump):
        assert "Player0" not in text and "Player1" not in text and "Player2" not in text
        assert "9000" not in text


def _fake_site(pages: dict[str, str]):
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        if url not in pages:
            raise urllib.error.URLError("down")
        return pages[url]

    return fetch, calls


def _index_for(*slugs: str) -> str:
    return "".join(f'<a href="/decklist/{s}">{s}</a>' for s in slugs)


def test_refresh_skips_known_paths_and_refetches_recent_ones(conn):
    league = _read("mtgo_site_league.html")
    old = "standard-league-2026-09-2011129"
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    fresh = f"standard-league-{today}11129"
    pages = {
        mtgo_site.INDEX_URL: _index_for(old, fresh),
        f"{mtgo_site.SITE}/decklist/{old}": league,
        f"{mtgo_site.SITE}/decklist/{fresh}": league,
    }
    fetch, _ = _fake_site(pages)
    first = mtgo_site.refresh_mtgo_site(conn, pause_s=0, fetch=fetch, sleep=lambda s: None)
    assert first.status == "updated" and first.events == 2
    stored = {r[0] for r in conn.execute("SELECT event_id FROM meta_event")}
    assert "Tournaments/MTGO/2026/09/20/standard-league-2026-09-2011129.json" in stored
    # the old event is now stored (known); today's event is fetched again
    fetch2, calls2 = _fake_site(pages)
    second = mtgo_site.refresh_mtgo_site(
        conn, pause_s=0, force=True, fetch=fetch2, sleep=lambda s: None
    )
    assert f"{mtgo_site.SITE}/decklist/{old}" not in calls2
    assert f"{mtgo_site.SITE}/decklist/{fresh}" in calls2
    assert second.status == "updated"
    third = mtgo_site.refresh_mtgo_site(conn, fetch=fetch2)
    assert third.status == "fresh"


def test_index_failure_is_failed_and_stores_nothing(conn):
    fetch, _ = _fake_site({})
    result = mtgo_site.refresh_mtgo_site(conn, pause_s=0, fetch=fetch, sleep=lambda s: None)
    assert result.status == "failed"
    assert conn.execute("SELECT COUNT(*) FROM meta_event").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM meta_fetch_source").fetchone()[0] == 0


def test_one_page_failing_is_skipped(conn):
    slug = "standard-league-2026-10-0211129"
    fetch, _ = _fake_site({mtgo_site.INDEX_URL: _index_for(slug)})
    result = mtgo_site.refresh_mtgo_site(conn, pause_s=0, fetch=fetch, sleep=lambda s: None)
    assert (result.status, result.events, result.skipped) == ("updated", 0, 1)


def test_a_malformed_page_is_skipped_not_fatal(conn):
    slug = "standard-challenge-32-2026-09-2012855466"
    page = ('window.MTGO.decklists.data = {"format": "CSTANDARD", "brackets": '
            '[{"matches": [{"players": ["x", "y"]}]}]};')
    fetch, _ = _fake_site({
        mtgo_site.INDEX_URL: _index_for(slug),
        f"{mtgo_site.SITE}/decklist/{slug}": page,
    })
    result = mtgo_site.refresh_mtgo_site(conn, pause_s=0, fetch=fetch, sleep=lambda s: None)
    assert (result.status, result.skipped) == ("updated", 1)


def test_a_league_of_another_format_is_not_standard():
    league = mtgo_site.extract_data(_read("mtgo_site_league.html"))
    league = {**league, "site_name": "modern-league-2026-10-0211129"}
    raw = mtgo_site.normalize(league)
    assert parse_event(raw, TournamentFile(_path_of(raw), "x")) is None


def test_index_with_no_decklist_links_is_failed(conn):
    fetch, _ = _fake_site({mtgo_site.INDEX_URL: "<html>redesigned</html>"})
    result = mtgo_site.refresh_mtgo_site(conn, pause_s=0, fetch=fetch, sleep=lambda s: None)
    assert result.status == "failed"
    assert conn.execute("SELECT COUNT(*) FROM meta_fetch_source").fetchone()[0] == 0


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

    result = mtgo_site.refresh_mtgo_site(conn, pause_s=0, fetch=fetch, sleep=lambda s: None)
    assert attempts == [page_url, page_url]
    assert (result.status, result.events, result.skipped) == ("updated", 1, 0)
