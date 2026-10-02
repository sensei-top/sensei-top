"""M3 API tests, served from the same anonymized fixture as the projector.

Ground truth is inherited from ``test_projector.py``: 2 matches, 5 games,
16 turns, 1 deck named Spellelementals, event Traditional_Ladder, match record
1-1 and game record 2-3.
"""

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient

from sensei_top import card_images
from sensei_top.api import create_app
from sensei_top.api.routes import review as review_routes
from sensei_top.db import open_database
from sensei_top.metagame.classify_meta import classify_meta_decks
from sensei_top.metagame.dedup import mark_duplicate_events
from sensei_top.metagame.source import ParsedDeck, ParsedEvent, ParsedRoundMatch, store_events
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.reader.mtgo_decks import ingest_deck_dir
from sensei_top.review import leaks as leaks_mod
from sensei_top.review import narrative

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
DECK_FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_deck_sample.dek"
MATCH_LOSS = "fd5624a4-d970-40eb-80aa-fba9d2ce17b3"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"


@pytest.fixture
def client(tmp_path, make_client):
    db_path = tmp_path / "api.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


@pytest.fixture
def deck_id(client):
    return client.get("/api/decks").json()[0]["deck_id"]


# --- meta -------------------------------------------------------------------


def test_health_reports_projected_counts(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert (body["decks"], body["matches"], body["games"], body["turns"]) == (1, 2, 5, 16)


def test_missing_database_is_503_not_a_new_empty_file(tmp_path, make_client):
    """sqlite3.connect() would create the file; an empty database renders as
    'no games yet', which is indistinguishable from a wrong --db path."""
    missing = tmp_path / "nope.db"
    with make_client(create_app(missing)) as c:
        assert c.get("/api/health").status_code == 503
    assert not missing.exists()


def test_live_status_reports_counts_without_a_watcher(client):
    """serve (no --watch) still answers /api/live: the dashboard uses it as a
    heartbeat, and an external `ingest --watch --project` may be the writer."""
    body = client.get("/api/live").json()
    assert body["watching"] is False
    assert body["events"] == 34
    assert (body["matches"], body["games"], body["turns"]) == (2, 5, 16)
    assert body["last_ingest_at"] is not None
    assert body["revision"]


def test_live_revision_changes_when_data_changes(tmp_path, make_client):
    """The dashboard refetches on a new revision, so it must move when the
    projection does — and stay put when nothing happened."""
    db_path = tmp_path / "rev.db"
    conn = open_database(db_path)
    with make_client(create_app(db_path)) as c:
        empty = c.get("/api/live").json()["revision"]
        assert c.get("/api/live").json()["revision"] == empty  # stable while idle

        ingest_file(conn, FIXTURE, locale_hint="mdy")
        ingested = c.get("/api/live").json()["revision"]
        assert ingested != empty, "new raw events must move the revision"

        project(conn)
        assert c.get("/api/live").json()["revision"] != ingested, "a rebuild must move it too"
    conn.close()


def test_projection_revision_ignores_ingest_and_moves_on_rebuild(tmp_path, make_client):
    """projection_revision must not move on an ingest-only tick — that is
    exactly the bug it replaces (revision embeds MAX(raw_events.id), which
    moves every second Arena is running, invalidating every dashboard query
    on a 3s heartbeat regardless of whether a rebuild ever happened). It
    should still move once a rebuild actually changes the projected tables."""
    db_path = tmp_path / "prev.db"
    conn = open_database(db_path)
    with make_client(create_app(db_path)) as c:
        empty = c.get("/api/live").json()["projection_revision"]

        ingest_file(conn, FIXTURE, locale_hint="mdy")
        after_ingest = c.get("/api/live").json()["projection_revision"]
        assert after_ingest == empty, "new raw events alone must not move projection_revision"

        project(conn)
        after_rebuild = c.get("/api/live").json()["projection_revision"]
        assert after_rebuild != empty, "a rebuild that changes projected tables must move it"
    conn.close()


def test_live_separates_data_freshness_from_reader_liveness(tmp_path, make_client):
    """A poll that finds nothing must not look like new data.

    ingest_state.updated_at moves on every poll, so using it for "updated N ago"
    would read a few seconds old forever, even with Arena closed.
    """
    db_path = tmp_path / "fresh.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")

    with make_client(create_app(db_path)) as c:
        first = c.get("/api/live").json()
        assert first["last_ingest_at"] is not None

        # Poll again with nothing new: the reader ran, the data did not change.
        ingest_file(conn, FIXTURE, locale_hint="mdy")
        second = c.get("/api/live").json()

    assert second["last_ingest_at"] == first["last_ingest_at"], "no new rows, no new timestamp"
    assert second["last_checked_at"] >= first["last_checked_at"]
    conn.close()


def test_live_last_event_at_ignores_a_deck_file_saved_after_the_last_game(tmp_path, make_client):
    """last_event_at is the newest in-game timestamp. An MTGO deck file's
    logged_at is its mtime, the moment the user saved it, so a deck newer than
    every game row must leave last_event_at where the games put it."""
    db_path = tmp_path / "deck-clock.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    newest_game = conn.execute("SELECT MAX(logged_at) FROM raw_events").fetchone()[0]
    assert newest_game is not None

    decks = tmp_path / "decks"
    decks.mkdir()
    deck = decks / "Alpha.dek"
    shutil.copy(DECK_FIXTURE, deck)
    a_day_later = (datetime.fromisoformat(newest_game) + timedelta(days=1)).timestamp()
    os.utime(deck, (a_day_later, a_day_later))

    with make_client(create_app(db_path)) as c:
        assert c.get("/api/live").json()["last_event_at"] == newest_game

        ingest_deck_dir(conn, decks)
        deck_logged_at = conn.execute(
            "SELECT logged_at FROM raw_events WHERE source = 'mtgo_deck'"
        ).fetchone()[0]
        assert deck_logged_at > newest_game, "the case a bare MAX(logged_at) gets wrong"

        assert c.get("/api/live").json()["last_event_at"] == newest_game
    conn.close()


def test_live_reports_an_attached_watcher(tmp_path, make_client):
    from sensei_top.live import LiveIngester

    db_path = tmp_path / "w.db"
    open_database(db_path).close()
    watcher = LiveIngester(db_path=db_path, log_path=tmp_path / "Player.log")

    with make_client(create_app(db_path, watcher=watcher)) as c:
        assert c.get("/api/live").json()["watching"] is False  # not started yet
        watcher.stats.running = True
        assert c.get("/api/live").json()["watching"] is True


def test_query_only_pragma_actually_blocks_writes(tmp_path):
    """Guards the assumption the read-only claim rests on: if this SQLite build
    ever ignored query_only, every endpoint would silently regain write access."""
    db_path = tmp_path / "ro.db"
    conn = open_database(db_path)
    conn.close()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA query_only=ON")
    with pytest.raises(sqlite3.OperationalError, match=r"readonly|read-only"):
        conn.execute("DELETE FROM matches")
    conn.close()


def test_serving_requests_does_not_mutate_the_database(client, tmp_path):
    """End-to-end: exercising every endpoint leaves the projected data intact."""
    before = client.get("/api/health").json()
    for path in (
        "/api/decks",
        "/api/matches",
        f"/api/matches/{MATCH_WIN}",
        "/api/metrics/winrate",
        "/api/metrics/play-draw",
        "/api/metrics/game-length",
        "/api/metrics/turn-curves",
    ):
        assert client.get(path).status_code == 200
    assert client.get("/api/health").json() == before


# --- decks ------------------------------------------------------------------


def test_decks_lists_the_fixture_deck(client):
    decks = client.get("/api/decks").json()
    assert len(decks) == 1
    assert decks[0]["name"] == "Spellelementals"


# --- metric 1: winrate ------------------------------------------------------


def test_winrate_matches_projected_record(client):
    row = client.get("/api/metrics/winrate").json()[0]
    assert row["deck_key"].startswith("guid:")
    assert row["versions"] == 1
    assert (row["matches_completed"], row["matches_won"]) == (2, 1)
    assert (row["games_won"], row["games_lost"]) == (2, 3)
    assert row["winrate"] == pytest.approx(0.5)


def test_winrate_event_filter(client):
    assert client.get("/api/metrics/winrate", params={"event_id": "Traditional_Ladder"}).json()
    assert client.get("/api/metrics/winrate", params={"event_id": "Nope"}).json() == []


def test_winrate_deck_filter(client, deck_id):
    assert len(client.get("/api/metrics/winrate", params={"deck_id": deck_id}).json()) == 1
    assert client.get("/api/metrics/winrate", params={"deck_id": "beef"}).json() == []


def test_winrate_collapses_two_content_hashes_sharing_one_guid(client, deck_id):
    """A single card swap mints a new deck_id but keeps the same Arena
    deck_guids.arena_deck_id — the route must report one row for both
    versions, not split the deck into two."""
    before = client.get("/api/metrics/winrate", params={"deck_id": deck_id}).json()[0]

    conn = sqlite3.connect(client.app.state.database)
    arena_deck_id, cards_json = conn.execute(
        "SELECT g.arena_deck_id, d.cards_json FROM deck_guids g "
        "JOIN decks d ON d.deck_id = g.deck_id WHERE g.deck_id = ?",
        (deck_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('newhash', 'Spellelementals', 'TraditionalStandard', ?, 't', 't')",
        (cards_json,),
    )
    conn.execute(
        "INSERT INTO deck_guids (deck_id, arena_deck_id, version, format, last_seen) "
        "VALUES ('newhash', ?, '2', 'TraditionalStandard', '2099-01-01')",
        (arena_deck_id,),
    )
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES ('m-new', 'Traditional_Ladder', 'newhash', "
        "1, 2, 'u', 'n', '2099-01-01T00:00:00', '2099-01-01T00:10:00', 'win', 2, 0, 'r')"
    )
    conn.commit()
    conn.close()

    rows = client.get("/api/metrics/winrate").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["deck_key"] == f"guid:{arena_deck_id}"
    assert row["versions"] == 2
    assert row["matches_completed"] == before["matches_completed"] + 1
    assert row["matches_won"] == before["matches_won"] + 1
    assert row["games_won"] == before["games_won"] + 2
    assert row["games_lost"] == before["games_lost"]


def test_winrate_by_rank_groups_matches_with_no_snapshot_together(client):
    """match_session.log carries no RankGetCombinedRankInfo events, so both
    fixture matches fall into the one (null, null) "rank never observed"
    bucket — the same overall 2/1 record test_winrate_matches_projected_record
    already pins, reached through the rank-conditioned view instead."""
    rows = client.get("/api/metrics/winrate-by-rank").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["constructed_class"] is None
    assert row["constructed_level"] is None
    assert (row["matches_completed"], row["matches_won"]) == (2, 1)
    assert row["winrate"] == pytest.approx(0.5)


# --- metric 2: play/draw ----------------------------------------------------


def test_play_draw_splits_by_on_play(client):
    rows = {r["on_play"]: r for r in client.get("/api/metrics/play-draw").json()}
    assert rows[True]["games_completed"] == 3
    assert rows[True]["games_won"] == 1
    assert rows[False]["games_completed"] == 2
    assert rows[False]["games_won"] == 1


def test_play_draw_on_play_is_boolean_not_integer(client):
    """SQLite stores 0/1; the schema promises a bool so the UI can branch."""
    assert all(isinstance(r["on_play"], bool) for r in client.get("/api/metrics/play-draw").json())


# --- metric 3: game length + turn curves ------------------------------------


def test_game_length_buckets(client):
    rows = client.get("/api/metrics/game-length").json()
    assert {r["turn_count"] for r in rows} == {3, 24}
    assert sum(r["games"] for r in rows) == 5


def test_turn_curves_start_at_full_life(client):
    rows = client.get("/api/metrics/turn-curves").json()
    first = next(r for r in rows if r["turn_number"] == 1)
    assert first["samples"] == 5
    assert first["avg_self_life"] == pytest.approx(20.0)
    assert first["avg_opp_life"] == pytest.approx(20.0)


def test_turn_curves_cover_every_projected_turn(client):
    rows = client.get("/api/metrics/turn-curves").json()
    assert sum(r["samples"] for r in rows) == 16  # every turns row is sampled once


# --- matches ----------------------------------------------------------------


def test_matches_listed_newest_first(client):
    matches = client.get("/api/matches").json()
    assert len(matches) == 2
    starts = [m["started_at"] for m in matches]
    assert starts == sorted(starts, reverse=True)
    assert {m["result"] for m in matches} == {"win", "loss"}


def test_matches_limit_is_bounded(client):
    assert len(client.get("/api/matches", params={"limit": 1}).json()) == 1
    assert client.get("/api/matches", params={"limit": 0}).status_code == 422
    assert client.get("/api/matches", params={"limit": 10_000}).status_code == 422


# --- match detail -------------------------------------------------------------
# Ground truth is read from test_projector.py, not from running the endpoint:
# MATCH_WIN (fa7a4d16) is self seat 1, games 1, 2, 3; MATCH_LOSS (fd5624a4) is
# self seat 2, games 1, 2.


def test_match_detail_carries_every_game(client):
    body = client.get(f"/api/matches/{MATCH_WIN}").json()
    assert body["result"] == "win"
    assert body["deck_name"] == "Spellelementals"
    assert body["self_seat"] == 1
    assert [g["game_number"] for g in body["games"]] == [1, 2, 3]


def test_match_detail_turns_are_the_projected_turns(client):
    """The fixture is a curated subset: game 2 keeps turns 1, 2, 3 and the
    trailing turn 24 (its final state message reports turnNumber 24)."""
    games = {g["game_number"]: g for g in client.get(f"/api/matches/{MATCH_WIN}").json()["games"]}
    assert {t["turn_number"] for t in games[2]["turns"]} == {1, 2, 3, 24}
    assert games[2]["turn_count"] == 24


def test_match_detail_maps_cards_to_self(client):
    """MATCH_WIN game 3, annotations 51 and 70: we (seat 1) play land 68738,
    the opponent plays 102716."""
    games = {g["game_number"]: g for g in client.get(f"/api/matches/{MATCH_WIN}").json()["games"]}
    lands = [c for c in games[3]["cards"] if c["category"] == "PlayLand"]
    assert {(c["grp_id"], c["is_self"]) for c in lands} == {(68738, True), (102716, False)}


def test_match_detail_turn_zones_include_hand_and_board(client):
    """MATCH_WIN game 3 turn 3: we (seat 1) drew grp_id 102670 into hand this
    turn, and our turn-1 land (grp_id 68738) is still on the battlefield."""
    games = {g["game_number"]: g for g in client.get(f"/api/matches/{MATCH_WIN}").json()["games"]}
    turn3 = next(t for t in games[3]["turns"] if t["turn_number"] == 3)
    hand = [z for z in turn3["zones"] if z["is_self"] and z["zone"] == "hand"]
    assert (102670, 3) in {(z["grp_id"], z["drawn_on_turn"]) for z in hand}
    board = [z for z in turn3["zones"] if z["is_self"] and z["zone"] == "battlefield"]
    assert {z["grp_id"] for z in board} == {68738}


def test_match_detail_turn_zones_carry_tapped_state(client):
    """The board view draws a tapped permanent rotated 90 degrees, so the flag
    has to survive all the way to the API.

    MATCH_WIN game 3, land grp_id 68738 (instance 374): tapped for mana on
    turn 2, then untapped by annotation id 83 in the diff reading
    `turnNumber: 3, step: Step_Upkeep`. Both turns are asserted, so this covers
    the annotation actually reaching the response rather than just the column
    existing.
    """
    games = {g["game_number"]: g for g in client.get(f"/api/matches/{MATCH_WIN}").json()["games"]}
    turns = {t["turn_number"]: t for t in games[3]["turns"]}

    def board(turn: int) -> list[dict]:
        return [z for z in turns[turn]["zones"] if z["is_self"] and z["zone"] == "battlefield"]

    assert [(z["grp_id"], z["is_tapped"]) for z in board(2)] == [(68738, True)]
    assert [(z["grp_id"], z["is_tapped"]) for z in board(3)] == [(68738, False)]
    # A card in hand has no orientation; None says so rather than claiming
    # untapped. Same for power on something that has none.
    hand = [z for z in turns[3]["zones"] if z["zone"] == "hand"]
    assert all(z["is_tapped"] is None for z in hand)
    assert all(z["power"] is None and z["toughness"] is None for z in hand)


def test_match_detail_opponent_hand_zones_are_hidden(client):
    """The opponent's hand is instance ids with no identities: every entry has
    a null grp_id, and is_self correctly marks them as not ours."""
    games = {g["game_number"]: g for g in client.get(f"/api/matches/{MATCH_WIN}").json()["games"]}
    turn3 = next(t for t in games[3]["turns"] if t["turn_number"] == 3)
    opp_hand = [z for z in turn3["zones"] if z["is_self"] is False and z["zone"] == "hand"]
    assert len(opp_hand) == 7
    assert all(z["grp_id"] is None for z in opp_hand)


def test_match_detail_final_life_totals(client):
    """MATCH_LOSS game 2 ends at gameStateId 733 with both lifeTotals == 10,
    read from the fixture's GameComplete messages."""
    games = {g["game_number"]: g for g in client.get(f"/api/matches/{MATCH_LOSS}").json()["games"]}
    final = games[2]["turns"][-1]
    assert (final["self_life"], final["opp_life"]) == (10, 10)


def test_match_detail_turns_carry_graveyard_and_open_mana(client):
    """The turn query used to select 11 of turns' 15 columns, silently
    dropping graveyard and open-mana even though CurrentTurn already declares
    them and /api/current-match already selects them (app.py:657-659).

    Ground truth from test_projector.py's
    test_turns_carry_graveyard_and_open_mana_counts: MATCH_LOSS game 2 turn 3
    has one untapped land in play, so self_open_mana == self_lands == 1."""
    games = {g["game_number"]: g for g in client.get(f"/api/matches/{MATCH_LOSS}").json()["games"]}
    turn3 = next(t for t in games[2]["turns"] if t["turn_number"] == 3)
    assert turn3["self_lands"] == 1
    assert turn3["self_open_mana"] == 1
    assert turn3["self_graveyard"] is not None


def test_match_detail_of_an_unknown_match_is_404(client):
    assert client.get("/api/matches/nope").status_code == 404


def test_sideboarding_of_an_unknown_match_is_404(client):
    assert client.get("/api/matches/nope/sideboarding").status_code == 404


def test_sideboarding_with_no_resubmission_is_an_empty_list_not_an_error(client):
    """match_session.log's two games never resubmit a deck (no
    SubmitDeckResp in the fixture) — a real, common case (Bo1, or a Bo3
    that ended before any boarding), not something to error on."""
    body = client.get(f"/api/matches/{MATCH_WIN}/sideboarding").json()
    assert body["match_id"] == MATCH_WIN
    assert body["games"] == []


# --- card images --------------------------------------------------------------
# The route's network is card_images._download (which itself calls the lower-
# level card_images._get once or twice — see the by-name fallback tests below);
# every test replaces one or the other, so the suite stays offline
# (docs/testing.md: no network in tests).


def test_card_image_serves_a_cached_file_without_touching_the_network(
    client, tmp_path, monkeypatch
):
    def no_network(grp_id, name):
        raise AssertionError("a cache hit must not download")

    monkeypatch.setattr(card_images, "_download", no_network)

    cache = tmp_path / "card_images"
    cache.mkdir()
    (cache / "86835.jpg").write_bytes(b"jpeg-bytes")

    response = client.get("/api/cards/86835/image")
    assert response.status_code == 200
    assert response.content == b"jpeg-bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert "immutable" in response.headers["cache-control"]


def test_card_image_downloads_once_then_serves_from_disk(client, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        card_images, "_download", lambda grp_id, name: (calls.append(grp_id), b"IMG")[1]
    )

    assert client.get("/api/cards/86835/image").status_code == 200
    assert client.get("/api/cards/86835/image").status_code == 200
    assert calls == [86835], "the second request must be a disk hit"
    assert (tmp_path / "card_images" / "86835.jpg").read_bytes() == b"IMG"


def test_card_image_offline_is_404_and_retried_next_time(client, tmp_path, monkeypatch):
    """Being offline is transient, so it must not be remembered as 'no image'."""
    calls = []

    def offline(grp_id, name):
        calls.append(grp_id)
        raise urllib.error.URLError("network unreachable")

    monkeypatch.setattr(card_images, "_download", offline)

    assert client.get("/api/cards/86835/image").status_code == 404
    assert client.get("/api/cards/86835/image").status_code == 404
    assert calls == [86835, 86835], "offline must be retried, not negative-cached"
    assert not (tmp_path / "card_images" / "86835.missing").exists()


def test_a_scryfall_404_is_negative_cached(client, tmp_path, monkeypatch):
    """Tokens and other ids Scryfall cannot map, under any URL tried, 404
    forever; asking again on every render would be rude to a free API."""
    calls = []

    def gone(grp_id, name):
        calls.append(grp_id)
        raise card_images._NotFoundError

    monkeypatch.setattr(card_images, "_download", gone)

    assert client.get("/api/cards/12/image").status_code == 404
    assert client.get("/api/cards/12/image").status_code == 404
    assert calls == [12], "the miss marker must absorb the second request"


def test_card_image_grp_id_must_be_an_integer(client):
    """Also what keeps the cache filename un-spoofable."""
    assert client.get("/api/cards/evil/image").status_code == 422


def test_card_image_falls_back_to_scryfalls_named_lookup(client, tmp_path, monkeypatch):
    """Arena-exclusive printings (full-art basics, etc.) have no Scryfall
    arena_id, so the by-id URL 404s even though Scryfall has the card under a
    different printing. The route already knows the card's name once
    'sensei-top cards' has run, so it retries by name rather than giving up.

    Named after the real bug this covers: grp_id 107494 is 'Swamp' in a set
    Scryfall's arena_id index does not carry.
    """
    conn = sqlite3.connect(client.app.state.database)
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (107494, 'Swamp')")
    conn.commit()
    conn.close()

    urls = []

    def get(url):
        urls.append(url)
        if "arena/107494" in url:
            raise card_images._NotFoundError
        assert "named?exact=Swamp" in url
        return b"SWAMP-ART"

    monkeypatch.setattr(card_images, "_get", get)

    response = client.get("/api/cards/107494/image")
    assert response.status_code == 200
    assert response.content == b"SWAMP-ART"
    assert len(urls) == 2, "by-id must be tried before falling back to by-name"

    # Cached under the grp_id regardless of which URL actually supplied it, so
    # the next request is a disk hit with no further calls.
    assert client.get("/api/cards/107494/image").status_code == 200
    assert len(urls) == 2


def test_card_image_with_no_known_name_does_not_attempt_a_name_fallback(
    client, tmp_path, monkeypatch
):
    """An unnamed grp_id (the card table has not been populated yet) has
    nothing to retry with, so the by-id 404 is final rather than guessed at."""
    calls = []

    def get(url):
        calls.append(url)
        raise card_images._NotFoundError

    monkeypatch.setattr(card_images, "_get", get)

    assert client.get("/api/cards/999999/image").status_code == 404
    assert len(calls) == 1


# --- card art -----------------------------------------------------------------
# The art route is the image route's twin over card_images._download_art; the
# same rule holds: every test replaces the networked function, never the network.


def test_card_art_downloads_once_then_serves_from_its_own_directory(
    client, tmp_path, monkeypatch
):
    """The art is a second picture with its own cache under art/, never the
    whole card's file: cropping that would cut off the artist and copyright."""
    calls = []
    monkeypatch.setattr(
        card_images, "_download_art", lambda grp_id, name: (calls.append(grp_id), b"ART")[1]
    )

    first = client.get("/api/cards/86835/art")
    assert first.status_code == 200
    assert first.content == b"ART"
    assert first.headers["content-type"] == "image/jpeg"
    assert "immutable" in first.headers["cache-control"]
    assert client.get("/api/cards/86835/art").status_code == 200
    assert calls == [86835], "the second request must be a disk hit"
    assert (tmp_path / "card_images" / "art" / "86835.jpg").read_bytes() == b"ART"
    assert not (tmp_path / "card_images" / "86835.jpg").exists()


def test_card_art_offline_is_404_and_retried_next_time(client, tmp_path, monkeypatch):
    """Being offline is transient, so it must not be remembered as 'no art'."""
    calls = []

    def offline(grp_id, name):
        calls.append(grp_id)
        raise urllib.error.URLError("network unreachable")

    monkeypatch.setattr(card_images, "_download_art", offline)

    assert client.get("/api/cards/86835/art").status_code == 404
    assert client.get("/api/cards/86835/art").status_code == 404
    assert calls == [86835, 86835], "offline must be retried, not negative-cached"
    assert not (tmp_path / "card_images" / "art" / "86835.missing").exists()


def test_a_scryfall_404_for_art_is_negative_cached_under_art(client, tmp_path, monkeypatch):
    calls = []

    def gone(grp_id, name):
        calls.append(grp_id)
        raise card_images._NotFoundError

    monkeypatch.setattr(card_images, "_download_art", gone)

    response = client.get("/api/cards/12/art")
    assert response.status_code == 404
    assert response.json()["detail"] == "No art for card 12."
    assert (tmp_path / "card_images" / "art" / "12.missing").exists()
    assert client.get("/api/cards/12/art").status_code == 404
    assert calls == [12], "the miss marker must absorb the second request"


def test_card_art_falls_back_by_name_and_asks_for_art_crop_both_times(
    client, tmp_path, monkeypatch
):
    """The same Arena-exclusive Swamp as the image fallback test: both URLs
    must name Scryfall's art_crop, or the fallback would cache a whole card
    image as art."""
    conn = sqlite3.connect(client.app.state.database)
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (107494, 'Swamp')")
    conn.commit()
    conn.close()

    urls = []

    def get(url):
        urls.append(url)
        if "arena/107494" in url:
            raise card_images._NotFoundError
        assert "named?exact=Swamp" in url
        return b"SWAMP-ART"

    monkeypatch.setattr(card_images, "_get", get)

    response = client.get("/api/cards/107494/art")
    assert response.status_code == 200
    assert response.content == b"SWAMP-ART"
    assert len(urls) == 2, "by-id must be tried before falling back to by-name"
    assert all("version=art_crop" in url for url in urls)


def test_the_art_route_never_answers_with_the_whole_card(client, tmp_path, monkeypatch):
    cache = tmp_path / "card_images"
    cache.mkdir()
    (cache / "86835.jpg").write_bytes(b"WHOLE-CARD")

    def offline(grp_id, name):
        raise urllib.error.URLError("network unreachable")

    monkeypatch.setattr(card_images, "_download_art", offline)

    assert client.get("/api/cards/86835/art").status_code == 404


def test_an_art_miss_marker_does_not_hide_the_whole_card(client, tmp_path, monkeypatch):
    art = tmp_path / "card_images" / "art"
    art.mkdir(parents=True)
    (art / "86835.missing").touch()
    monkeypatch.setattr(card_images, "_download", lambda grp_id, name: b"IMG")

    response = client.get("/api/cards/86835/image")
    assert response.status_code == 200
    assert response.content == b"IMG"


def test_card_art_grp_id_must_be_an_integer(client):
    """Also what keeps the art cache's filename un-spoofable."""
    assert client.get("/api/cards/evil/art").status_code == 422


# --- schema -----------------------------------------------------------------


def test_openapi_schema_is_generated(client):
    """The frontend's types are generated from this schema, so it must exist
    and name every endpoint the dashboard calls."""
    schema = client.get("/openapi.json").json()
    assert {
        "/api/health",
        "/api/decks",
        "/api/metrics/winrate",
        "/api/metrics/play-draw",
        "/api/metrics/game-length",
        "/api/metrics/turn-curves",
        "/api/matches",
        "/api/matches/{match_id}",
        "/api/matches/{match_id}/report",
        "/api/matches/{match_id}/report/narrative",
        "/api/cards/{grp_id}/image",
        "/api/cards/{grp_id}/art",
    } <= set(schema["paths"])


# --- current match ----------------------------------------------------------


@pytest.fixture
def live_client(tmp_path, make_client):
    """The fixture session with its final MatchCompleted cut off, so the last
    match (fa7a4d16, the newest by started_at) is still being played. Line 64
    of the fixture is that event; everything before it is left untouched."""
    lines = FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    trimmed = tmp_path / "in_progress.log"
    trimmed.write_text("".join(lines[:63]), encoding="utf-8")

    db_path = tmp_path / "live.db"
    conn = open_database(db_path)
    ingest_file(conn, trimmed, locale_hint="mdy")
    project(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


def test_current_match_is_null_when_nothing_is_being_played(client):
    """Both fixture matches completed. "No game right now" is an ordinary
    answer, so it is a 200 with a null body rather than a 404."""
    response = client.get("/api/current-match")
    assert response.status_code == 200
    assert response.json() is None


def test_current_match_reports_the_match_in_progress(live_client):
    body = live_client.get("/api/current-match").json()
    assert body["match_id"] == "fa7a4d16-afb7-4094-bae2-111092fc71d2"
    assert body["event_id"] == "Traditional_Ladder"
    assert body["deck_name"] == "Spellelementals"
    assert body["started_at"] is not None
    # live_client (like `client`) never runs `_teach`: `cards` is empty, so
    # every revealed card's colours are unknown and opponent_colors is null,
    # never ''.
    assert body["opponent_colors"] is None


def test_current_match_carries_the_current_game_only(live_client):
    """Game 3 is the one being played; its turns and cards are what a live
    view needs, and earlier games would be noise in it."""
    body = live_client.get("/api/current-match").json()
    assert body["game"]["game_number"] == 3
    assert {t["turn_number"] for t in body["turns"]} == {1, 2, 3}
    assert body["cards"], "game 3 has zone transfers in the fixture"


def test_current_match_turns_include_library_counts(live_client):
    """Counted from the library zone itself. The opponent's library is null on
    turn 1 because game 3 has not shown it yet — never observed stays null
    rather than being guessed at from the deck size."""
    turns = {t["turn_number"]: t for t in live_client.get("/api/current-match").json()["turns"]}
    assert (turns[1]["self_library"], turns[1]["opp_library"]) == (54, None)
    assert (turns[2]["self_library"], turns[2]["opp_library"]) == (54, 52)


def test_current_match_marks_our_own_cards(live_client):
    """self_seat is 1 in this match, so seat 1's plays are ours. The flag is
    what lets the view separate our draws from the opponent's."""
    cards = live_client.get("/api/current-match").json()["cards"]
    lands = [c for c in cards if c["category"] == "PlayLand"]
    assert {(c["grp_id"], c["is_self"]) for c in lands} == {(68738, True), (102716, False)}


def test_current_match_turns_are_empty_during_the_mulligan_phase(tmp_path, make_client):
    """Mulligan decisions happen before turnInfo is ever sent, so
    GameStateTracker's _current_turn stays None the whole time — nothing gets
    finalized, not even by flush_trailing's end-of-replay safety net, which
    only fills in an already-*started* turn. turns must genuinely be empty
    here — not backfilled from the mulligan count, which is a real
    observation on its own."""
    db_path = tmp_path / "mulligan_phase.db"
    conn = open_database(db_path)
    for i, payload in enumerate(
        [
            '{"authenticateResponse": {"clientId": "SELF"}}',
            '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {"gameRoomConfig": {'
            '"matchId": "m1", "reservedPlayers": ['
            '{"userId": "SELF", "systemSeatId": 1, "teamId": 1}, '
            '{"userId": "OPP", "systemSeatId": 2, "teamId": 2}]},'
            '"stateType": "MatchGameRoomStateType_Playing"}}}',
            '{"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {'
            '"gameInfo": {"matchID": "m1", "gameNumber": 1}, '
            '"players": [{"systemSeatNumber": 1, "lifeTotal": 20, "mulliganCount": 1}]}}]}}',
        ]
    ):
        conn.execute(
            "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"d{i}", "Player.log", "event", None, payload),
        )
    project(conn)
    conn.close()

    with make_client(create_app(db_path)) as client:
        body = client.get("/api/current-match").json()
    assert body["match_id"] == "m1"
    assert body["game"]["self_mulligans"] == 1
    assert body["turns"] == []


def test_current_match_read_serves_the_opening_hand_before_any_match_row(tmp_path, make_client):
    """opening_hand reads straight from raw_events (table/opening_hand.py) —
    it must render even when v_current_match has never produced a row,
    which is the whole reason it does not wait on project()."""
    db_path = tmp_path / "opening_hand.db"
    conn = open_database(db_path)
    payloads = [
        '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {"gameRoomConfig": {'
        '"matchId": "m1"}, "stateType": "MatchGameRoomStateType_Playing"}}}',
        '{"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {'
        '"type": "GameStateType_Diff", "gameStateId": 2, '
        '"players": [{"systemSeatNumber": 1, '
        '"pendingMessageType": "ClientMessageType_MulliganResp"}], '
        '"turnInfo": {"activePlayer": 2}, '
        '"zones": [{"zoneId": 31, "type": "ZoneType_Hand", "ownerSeatId": 1, '
        '"objectInstanceIds": [1, 2]}], '
        '"gameObjects": [' + ",".join(
            f'{{"instanceId": {i}, "grpId": {i}, "zoneId": 31, '
            f'"cardTypes": ["CardType_Land"]}}' for i in (1, 2)
        ) + "]}}]}}",
    ]
    labels = ["MatchGameRoomStateChangedEvent", "GreToClientEvent"]
    for i, (payload, label) in enumerate(zip(payloads, labels, strict=True)):
        conn.execute(
            "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"oh{i}", "Player.log", "event", label, payload),
        )
    conn.commit()
    # Deliberately no project() call: no matches/games rows exist at all.
    conn.close()

    with make_client(create_app(db_path)) as client:
        body = client.get("/api/current-match/read").json()

    assert body["status"] == "no_match"
    assert body["opening_hand"] is not None
    assert body["opening_hand"]["seat"] == 1
    assert body["opening_hand"]["mulligan_count"] == 0
    assert body["opening_hand"]["land_count"] == 2
    assert {c["grp_id"] for c in body["opening_hand"]["cards"]} == {1, 2}
    assert body["opening_hand"]["on_the_play"] is False
    assert body["opening_hand"]["verdict"] is None  # no deck_id at all yet
    assert body["keep"] is None
    assert body["hand"] is None
    # This room-start event names no queue, and unknown is ranked
    # (table/ranked.py): the read is built, the page is told to hide it.
    assert body["ranked"] is True
    assert body["advice"] is False


def test_current_match_read_allows_advice_in_a_casual_queue_before_any_match_row(
    tmp_path, make_client
):
    """The queue comes from the live replay's room-start event, so an
    unranked game gets its keep advice at the very first mulligan, before
    project() has written a matches row. Synthetic: no fixture captures a
    casual queue; "Play" is a real event id read off a real database."""
    db_path = tmp_path / "casual.db"
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES ('c0', 'Player.log', 'event', 'MatchGameRoomStateChangedEvent', ?)",
        (
            '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {"gameRoomConfig": {'
            '"matchId": "m1", "reservedPlayers": [{"systemSeatId": 1, "eventId": "Play"}]}, '
            '"stateType": "MatchGameRoomStateType_Playing"}}}',
        ),
    )
    conn.commit()
    conn.close()

    with make_client(create_app(db_path)) as client:
        body = client.get("/api/current-match/read").json()

    assert body["status"] == "no_match"
    assert body["ranked"] is False
    assert body["advice"] is True


# --- current match: MTGO as a second source ---------------------------------

MTGO_FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_match_session.log"
MTGO_FIXTURE_BYTES = MTGO_FIXTURE.read_bytes()
MTGO_SOURCE_FILE = "Match_GameLog_f2244feb-54e1-48ec-b3c5-711b20844adf.dat"


def _insert_mtgo_row(
    conn, *, data: bytes, logged_at: str, source_file: str = MTGO_SOURCE_FILE
) -> None:
    payload = base64.b64encode(data).decode("ascii")
    digest = hashlib.sha256(f"{source_file}:{logged_at}:{len(data)}".encode()).hexdigest()
    conn.execute(
        """
        INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, ?, 'event', 'MtgoGameLog', ?, 'mtgo')
        """,
        (digest, source_file, logged_at, payload),
    )


@pytest.fixture
def mtgo_client(tmp_path, monkeypatch, make_client):
    """The Arena fixture's own two (already-completed) matches, plus a
    still-in-progress MTGO match logged well after both of them. Before
    migration 040 (migrations/040_arena_only_current_match.sql),
    v_current_match had no source filter and resolved to this MTGO match —
    the newest-started incomplete one across every source — proving the
    same ordering test_projector_mtgo.py's own
    test_v_current_match_never_shows_mtgo_however_new now proves at the SQL
    level. Kept as a fixture (rather than deleted along with that
    behaviour) because it now proves the opposite: that an MTGO-only
    database, however recent, never makes the Current match tab non-empty.
    The 222-byte cut is the same mid-mulligan prefix used there:
    matches=1/games=1 exist, but on_play/turn_count/self_mulligans are all
    still NULL and result is 'incomplete' (project_mtgo has not seen a
    game-over line at this cut). project(), not project_mtgo() directly, so
    this exercises the real orchestration path (projector/matches.py calls
    project_mtgo(conn, mtgo_load_handle()) unconditionally) — MTGO_HANDLE is
    set here because conftest.py's autouse fixture deletes it by default.
    """
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    db_path = tmp_path / "mtgo.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    _insert_mtgo_row(conn, data=MTGO_FIXTURE_BYTES[:222], logged_at="2099-01-01T00:00:00")
    conn.commit()
    project(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


def test_current_match_source_defaults_to_arena(live_client):
    """The existing fixture db never touches MTGO at all; source must still
    default to 'arena' rather than becoming null or missing."""
    body = live_client.get("/api/current-match").json()
    assert body["source"] == "arena"


def test_current_match_is_null_for_an_mtgo_only_database(mtgo_client):
    """v_current_match is Arena-only since migration 040
    (migrations/040_arena_only_current_match.sql) — an MTGO match never
    becomes current, even as the sole incomplete match in the database and
    even though both real Arena matches in the fixture are already
    complete. Inverted from this test's pre-040 self (then named
    test_current_match_reports_mtgo_as_the_current_source, which asserted
    body["source"] == "mtgo")."""
    body = mtgo_client.get("/api/current-match").json()
    assert body is None


def test_current_match_read_reports_no_match_for_an_mtgo_only_database(mtgo_client):
    """/read must not 500 with only an MTGO match in the database: since
    v_current_match can never return one (migration 040), the route takes
    its ordinary no-match-row path — status='no_match', deck_id=None, so
    build_live_state and build_opening_hand_read run exactly as they would
    with an empty database. Inverted from this test's pre-040 self (then
    named test_current_match_read_degrades_gracefully_for_an_mtgo_match,
    which asserted body["source"] == "mtgo")."""
    response = mtgo_client.get("/api/current-match/read")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_match"
    assert body["source"] == "arena"
    assert body["opening_hand"] is None
    assert body["library"] == []
    assert body["library_count"] is None


INTERMISSION_FIXTURE = Path(__file__).parent / "fixtures" / "intermission_session.log"


def _intermission_client(tmp_path, cutoff_entry: int, make_client) -> TestClient:
    """A database built from the real Bo3-break fixture
    (tests/test_intermission.py's own ``intermission_session.log``), with
    ``raw_events`` truncated after ``cutoff_entry`` (0-based; that file's
    ``_payloads_through`` documents the same "entry N -> raw_events.id N+1"
    convention this reuses) and reprojected — the same mid-replay state
    /api/current-match/read has to answer from on every poll of a live
    match. Ground truth for entries 34/35/40/41 is
    tests/test_intermission.py's module docstring, read from the fixture via
    fixture_peek.py, never re-derived here."""
    db_path = tmp_path / "intermission_api.db"
    conn = open_database(db_path)
    ingest_file(conn, INTERMISSION_FIXTURE, locale_hint="mdy")
    conn.execute("DELETE FROM raw_events WHERE id > ?", (cutoff_entry + 1,))
    conn.commit()
    project(conn)
    conn.close()
    return make_client(create_app(db_path))


def test_current_match_read_has_no_intermission_mid_game(tmp_path, make_client):
    """entry 34: the last GRE event before game 1 ends, no gameInfo at all —
    S4/S5's field must stay null during ordinary play."""
    with _intermission_client(tmp_path, 34, make_client) as client:
        body = client.get("/api/current-match/read").json()
    assert body["intermission"] is None
    # Traditional_Ladder (the fixture's room-start event): mid-game in a
    # ranked queue, the advice stays off.
    assert body["ranked"] is True
    assert body["advice"] is False


def test_current_match_read_sets_intermission_at_game_over(tmp_path, make_client):
    """entry 35: GameComplete + IntermissionReq, game 1, our team's
    winningTeamId — won by the opponent's concede."""
    with _intermission_client(tmp_path, 35, make_client) as client:
        body = client.get("/api/current-match/read").json()
    intermission = body["intermission"]
    assert intermission is not None
    assert intermission["game_number"] == 1
    assert intermission["next_game"] == 2
    assert intermission["won"] is True
    assert intermission["reason"] == "ResultReason_Concede"
    # Between games the sideboard plan shows even in a ranked queue.
    assert body["ranked"] is True
    assert body["advice"] is True


def test_current_match_read_keeps_intermission_through_submit_deck_confirmation(
    tmp_path, make_client
):
    """entry 40 (SubmitDeckConfirmation) carries no gameInfo of its own and
    does not end the break (trap 11c) — intermission must still be set,
    unchanged from game over."""
    with _intermission_client(tmp_path, 40, make_client) as client:
        body = client.get("/api/current-match/read").json()
    intermission = body["intermission"]
    assert intermission is not None
    assert intermission["game_number"] == 1
    assert intermission["won"] is True
    assert intermission["reason"] == "ResultReason_Concede"


def test_current_match_read_clears_intermission_at_game_2_start(tmp_path, make_client):
    """entry 41's gameInfo (gameNumber 2, GameStage_Start) is the break's
    real end (trap 11c), not the SubmitDeckConfirmation before it."""
    with _intermission_client(tmp_path, 41, make_client) as client:
        body = client.get("/api/current-match/read").json()
    assert body["intermission"] is None
    # Game 2 has begun: the break's allowance ends with it.
    assert body["advice"] is False


def test_card_names_are_null_until_the_card_table_is_populated(live_client):
    """Nothing in an Arena log says what a grpId is called, so the view falls
    back to the number until 'sensei-top cards' has run."""
    cards = live_client.get("/api/current-match").json()["cards"]
    assert cards and all(c["card_name"] is None for c in cards)


def test_card_names_are_joined_once_the_card_table_is_populated(tmp_path, make_client):
    lines = FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    trimmed = tmp_path / "in_progress.log"
    trimmed.write_text("".join(lines[:63]), encoding="utf-8")

    db_path = tmp_path / "named.db"
    conn = open_database(db_path)
    ingest_file(conn, trimmed, locale_hint="mdy")
    project(conn)
    # A stand-in name: this tests the join, not what Scryfall happens to say.
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (68738, 'Test Island')")
    conn.close()

    with make_client(create_app(db_path)) as c:
        cards = c.get("/api/current-match").json()["cards"]
    named = [card for card in cards if card["grp_id"] == 68738]
    assert named and all(card["card_name"] == "Test Island" for card in named)


def test_projection_does_not_discard_downloaded_card_names(tmp_path):
    """cards is reference data, not projector output: a rebuild must not throw
    away a download that costs a few hundred megabytes to repeat."""
    conn = open_database(tmp_path / "keep.db")
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (68738, 'Test Island')")
    project(conn)
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1
    conn.close()


# --- metrics and matches: MTGO as a second source --------------------------

RANK_FIXTURE = Path(__file__).parent / "fixtures" / "rank_session.log"
MTGO_MATCH_ID = "f2244feb-54e1-48ec-b3c5-711b20844adf"


def _mixed_db(tmp_path, monkeypatch) -> Path:
    """The Arena fixture's two matches (August 2026), the rank fixture's one
    snapshot (Platinum 4, observed 2026-09-01T16:17:05, per tests/test_rank.py)
    and the whole MTGO fixture's one match, logged in 2099 — after the
    snapshot, where both Arena matches come before it. The MTGO transcript
    (scripts/mtgo_probe.py) reads: Player1 chooses to play first and wins game
    1; Player2000 chooses to play first, and Player1 wins game 2; "Player1 wins
    the match 2-0". MTGO records no deck, so the match's deck_id is null."""
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    db_path = tmp_path / "mixed.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    ingest_file(conn, RANK_FIXTURE, locale_hint="mdy")
    _insert_mtgo_row(conn, data=MTGO_FIXTURE_BYTES, logged_at="2099-01-01T00:00:00")
    conn.commit()
    project(conn)
    conn.close()
    return db_path


@pytest.fixture
def mixed_client(tmp_path, monkeypatch, make_client):
    with make_client(create_app(_mixed_db(tmp_path, monkeypatch))) as c:
        yield c


def test_winrate_counts_the_matches_with_no_deck(mixed_client):
    assert mixed_client.get("/api/metrics/winrate", params={"source": "mtgo"}).json() == [
        {
            "deck_key": None,
            "arena_deck_id": None,
            "deck_name": None,
            "versions": 0,
            "matches_completed": 1,
            "matches_won": 1,
            "games_won": 2,
            "games_lost": 0,
            "winrate": 1.0,
        }
    ]


def test_winrate_under_all_is_the_arena_decks_and_the_deckless_row(mixed_client):
    arena = mixed_client.get("/api/metrics/winrate").json()
    mtgo = mixed_client.get("/api/metrics/winrate", params={"source": "mtgo"}).json()
    both = mixed_client.get("/api/metrics/winrate", params={"source": "all"}).json()
    key = lambda r: r["deck_key"] or ""  # noqa: E731
    assert sorted(both, key=key) == sorted(arena + mtgo, key=key)
    assert sum(r["matches_completed"] for r in both) == 3


def test_winrate_deck_filter_leaves_the_deckless_row_out(mixed_client):
    deck_id = mixed_client.get("/api/decks").json()[0]["deck_id"]
    rows = mixed_client.get(
        "/api/metrics/winrate", params={"source": "all", "deck_id": deck_id}
    ).json()
    assert rows and all(r["deck_key"] is not None for r in rows)


def test_play_draw_answers_for_mtgo(mixed_client):
    response = mixed_client.get("/api/metrics/play-draw", params={"source": "mtgo"})
    assert response.status_code == 200
    rows = {r["on_play"]: r for r in response.json()}
    assert all(r["deck_id"] is None for r in rows.values())
    assert (rows[True]["games_completed"], rows[True]["games_won"]) == (1, 1)
    assert (rows[False]["games_completed"], rows[False]["games_won"]) == (1, 1)


def test_play_draw_under_all_holds_both_sources(mixed_client):
    """test_play_draw_splits_by_on_play pins Arena's five games (3 on the
    play, 2 on the draw); MTGO adds one of each."""
    response = mixed_client.get("/api/metrics/play-draw", params={"source": "all"})
    assert response.status_code == 200
    totals = {True: 0, False: 0}
    for row in response.json():
        totals[row["on_play"]] += row["games_completed"]
    assert totals == {True: 4, False: 3}


def test_game_length_answers_for_mtgo(mixed_client):
    response = mixed_client.get("/api/metrics/game-length", params={"source": "mtgo"})
    assert response.status_code == 200
    rows = response.json()
    assert all(r["deck_id"] is None for r in rows)
    assert sum(r["games"] for r in rows) == 2


def test_winrate_by_rank_under_all_has_one_row_per_tier(mixed_client):
    """Both Arena matches were played before the only snapshot and the MTGO
    match has no Arena rank, so all three share the unranked tier: one row,
    not one per source, and not a Platinum row borrowed from Arena."""
    rows = mixed_client.get("/api/metrics/winrate-by-rank", params={"source": "all"}).json()
    assert len(rows) == 1
    row = rows[0]
    assert (row["constructed_class"], row["constructed_level"]) == (None, None)
    assert (row["matches_completed"], row["matches_won"]) == (3, 2)


def test_an_mtgo_match_takes_no_arena_rank(mixed_client):
    listed = mixed_client.get("/api/matches", params={"source": "mtgo"}).json()
    assert [(m["match_id"], m["rank_class"], m["rank_level"]) for m in listed] == [
        (MTGO_MATCH_ID, None, None)
    ]
    detail = mixed_client.get(f"/api/matches/{MTGO_MATCH_ID}").json()
    assert (detail["rank_class"], detail["rank_level"]) == (None, None)


def test_an_arena_match_still_takes_the_rank_before_it(tmp_path, monkeypatch, make_client):
    """The same database with one more snapshot, Gold 2, observed before
    either Arena match: both take it, and the MTGO match still takes none."""
    db_path = _mixed_db(tmp_path, monkeypatch)
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO rank_snapshot (observed_at, constructed_class, constructed_level)"
        " VALUES ('2026-01-01T00:00:00', 'Gold', 2)"
    )
    conn.commit()
    conn.close()
    with make_client(create_app(db_path)) as c:
        rows = c.get("/api/matches", params={"source": "all"}).json()
    ranks = {m["source"]: set() for m in rows}
    for m in rows:
        ranks[m["source"]].add((m["rank_class"], m["rank_level"]))
    assert ranks == {"arena": {("Gold", 2)}, "mtgo": {(None, None)}}


def test_match_rows_carry_their_source(mixed_client):
    rows = mixed_client.get("/api/matches", params={"source": "all"}).json()
    assert sorted(m["source"] for m in rows) == ["arena", "arena", "mtgo"]
    assert next(m for m in rows if m["match_id"] == MTGO_MATCH_ID)["source"] == "mtgo"
    assert mixed_client.get(f"/api/matches/{MTGO_MATCH_ID}").json()["source"] == "mtgo"


def _pick_mtgo_deck(db_path, *, pick: bool):
    """Add one MTGO-style ``decks`` row (no Arena match carries it) and, when
    ``pick`` is set, the user's pick of it for the fixture's MTGO match."""
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('mtgodeck', 'Picked MTGO Deck', 'Standard', ?, 't', 't')",
        ('{"maindeck": [100, 100, 200], "sideboard": []}',),
    )
    if pick:
        conn.execute(
            "INSERT INTO mtgo_match_pick (match_id, deck_id) VALUES (?, 'mtgodeck')",
            (MTGO_MATCH_ID,),
        )
    conn.commit()
    conn.close()


def test_a_picked_mtgo_match_counts_under_its_deck(tmp_path, monkeypatch, make_client):
    """The fixture's MTGO match is one match, won 2-0 (see _mixed_db): with a
    pick it is the deck's whole record and no deckless row remains."""
    db_path = _mixed_db(tmp_path, monkeypatch)
    _pick_mtgo_deck(db_path, pick=True)
    with make_client(create_app(db_path)) as c:
        rows = c.get("/api/metrics/winrate", params={"source": "mtgo"}).json()
        assert len(rows) == 1
        assert rows[0]["deck_key"] is not None
        assert rows[0]["deck_name"] == "Picked MTGO Deck"
        assert (rows[0]["matches_completed"], rows[0]["matches_won"]) == (1, 1)
        assert (rows[0]["games_won"], rows[0]["games_lost"]) == (2, 0)

        listed = c.get("/api/matches", params={"source": "all", "deck_id": "mtgodeck"}).json()
        assert [(m["match_id"], m["deck_id"], m["deck_name"]) for m in listed] == [
            (MTGO_MATCH_ID, "mtgodeck", "Picked MTGO Deck")
        ]
        detail = c.get(f"/api/matches/{MTGO_MATCH_ID}").json()
        assert (detail["deck_id"], detail["deck_name"]) == ("mtgodeck", "Picked MTGO Deck")

        # The Arena matches never gain the MTGO deck.
        arena = c.get("/api/matches", params={"source": "arena"}).json()
        assert all(m["deck_id"] != "mtgodeck" for m in arena)


def test_an_unpicked_mtgo_match_counts_under_no_deck(tmp_path, monkeypatch, make_client):
    db_path = _mixed_db(tmp_path, monkeypatch)
    _pick_mtgo_deck(db_path, pick=False)
    with make_client(create_app(db_path)) as c:
        rows = c.get("/api/metrics/winrate", params={"source": "mtgo"}).json()
        assert [(r["deck_key"], r["matches_completed"]) for r in rows] == [(None, 1)]
        assert c.get(
            "/api/matches", params={"source": "all", "deck_id": "mtgodeck"}
        ).json() == []
        detail = c.get(f"/api/matches/{MTGO_MATCH_ID}").json()
        assert (detail["deck_id"], detail["deck_name"]) == (None, None)


def test_sideboarding_diffs_against_the_picked_mtgo_deck(tmp_path, monkeypatch, make_client):
    """Maindeck 100 x2 + 200; game 2 played 100 + 200 + 300: one 300 in, one
    100 out. The MTGO projector never writes ``game_decks``, so game 2's row is
    seeded here."""
    db_path = _mixed_db(tmp_path, monkeypatch)
    _pick_mtgo_deck(db_path, pick=True)
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO game_decks (match_id, game_number, deck_cards_json, sideboard_cards_json) "
        "VALUES (?, 2, '[100,200,300]', '[]')",
        (MTGO_MATCH_ID,),
    )
    conn.commit()
    conn.close()
    with make_client(create_app(db_path)) as c:
        game = c.get(f"/api/matches/{MTGO_MATCH_ID}/sideboarding").json()["games"][0]
    assert [(x["grp_id"], x["n"]) for x in game["cards_in"]] == [(300, 1)]
    assert [(x["grp_id"], x["n"]) for x in game["cards_out"]] == [(100, 1)]


# --- match report ------------------------------------------------------------
# The post-game report retires the old live hint (AGENTS.md rule 5's fourth
# outbound call moved from /api/current-match/hint to
# /api/matches/{id}/report/narrative). Every narrative test controls the
# API-key env vars explicitly so a real key in the runner's own environment
# can never make one of these accidentally reach the network, and
# narrative.request_narrative is always monkeypatched rather than called —
# no test in this suite touches the network (docs/testing.md).


def test_match_report_returns_findings_and_gaps_for_a_completed_match(client):
    body = client.get(f"/api/matches/{MATCH_WIN}/report").json()
    assert body["match_id"] == MATCH_WIN
    assert body["findings"]
    assert body["gaps"]


def test_match_report_carries_a_summary_alongside_the_raw_findings(client):
    """review/summary.py's own digest (headline, per-game beats, grouped
    gaps) rides the same route as the raw findings/gaps it is built from —
    the frontend reads both, not a second endpoint."""
    body = client.get(f"/api/matches/{MATCH_WIN}/report").json()
    summary = body["summary"]
    assert summary["headline"]
    assert isinstance(summary["games"], list) and summary["games"]
    assert isinstance(summary["gap_groups"], list) and summary["gap_groups"]


def test_match_report_404s_for_an_unknown_match(client):
    assert client.get("/api/matches/nope/report").status_code == 404


def test_match_report_always_offers_a_narrative_prompt(client):
    """`narrative_available` is kept for wire compatibility and stays
    constant regardless of whether a Claude credential is configured — the
    GET narrative route always has a prompt to hand over either way
    (AGENTS.md non-negotiable #5, `docs/llm.md`)."""
    assert client.get(f"/api/matches/{MATCH_WIN}/report").json()["narrative_available"] is True


# --- leak finder --------------------------------------------------------------


def test_review_leaks_returns_an_empty_list_below_the_sample_gate(client):
    """match_session.log has only 2 matches — leaks.MIN_SAMPLE (10) can
    never be reached on either side of any comparison, so the route must
    answer an empty list, not crash on too little data."""
    body = client.get("/api/review/leaks").json()
    assert body["leaks"] == []
    assert body["narrative_available"] is True


def test_review_leaks_narrative_is_no_report_when_there_is_nothing_to_synthesize(client):
    body = client.get("/api/review/leaks/narrative").json()
    assert body["status"] == "no_report"


def test_review_leaks_routes_pass_the_consensus_window_through(client, monkeypatch):
    """Both `find_leaks` call sites — the GET list route and the narrative
    route's own `build_context` — must forward `consensus_since`, so the
    field record inside `review/analyzers/baseline.py` never pools rounds
    from across a format reset (`docs/metagame.md`'s format-reset boundary).
    `match_session.log` carries no Standard legality data, so
    `_consensus_window` resolves to `None` here; this only pins that the
    kwarg is forwarded on every call, not a particular value."""
    calls = []

    def fake_find_leaks(conn, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(review_routes, "find_leaks", fake_find_leaks)

    client.get("/api/review/leaks")
    client.get("/api/review/leaks/narrative")

    assert len(calls) == 2
    assert all("consensus_since" in call for call in calls)


# --- shared report cache (api/sql.py::_shared_report_cache) -----------------


@pytest.fixture
def counting_build_match_report(monkeypatch):
    """Replaces ``leaks_mod.build_match_report`` with a wrapper that still
    does the real work but records every ``match_id`` it was actually asked
    to build for -- the ``tests/test_leaks.py:514`` pattern, one level up at
    the HTTP layer, so a request that reuses ``_shared_report_cache`` shows
    up here as zero calls rather than zero-cost-but-still-called."""
    calls: list[str] = []
    real_build_match_report = leaks_mod.build_match_report

    def wrapper(conn, match_id, **kwargs):
        calls.append(match_id)
        return real_build_match_report(conn, match_id, **kwargs)

    monkeypatch.setattr(leaks_mod, "build_match_report", wrapper)
    return calls


def test_two_leaks_requests_build_each_report_once(client, counting_build_match_report):
    client.get("/api/review/leaks")
    first_calls = sorted(counting_build_match_report)
    assert first_calls == sorted([MATCH_LOSS, MATCH_WIN])  # both fixture matches built

    counting_build_match_report.clear()
    client.get("/api/review/leaks")
    assert counting_build_match_report == []  # second request reused the shared cache


def test_new_completed_match_invalidates_the_shared_report_cache(
    client, counting_build_match_report
):
    client.get("/api/review/leaks")
    counting_build_match_report.clear()

    conn = sqlite3.connect(client.app.state.database)
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES ('m-new', 'e', NULL, 1, 2, 'u', 'n', "
        "'t0', 't1', 'win', 1, 0, 'r')"
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES ('m-new', 1, 1, 'win', NULL, 6, 0, 0)"
    )
    conn.commit()
    conn.close()

    client.get("/api/review/leaks")
    assert "m-new" in counting_build_match_report


def test_changed_match_result_invalidates_the_shared_report_cache(
    client, counting_build_match_report
):
    client.get("/api/review/leaks")
    counting_build_match_report.clear()

    conn = sqlite3.connect(client.app.state.database)
    conn.execute("UPDATE matches SET result = 'loss' WHERE match_id = ?", (MATCH_WIN,))
    conn.commit()
    conn.close()

    client.get("/api/review/leaks")
    assert counting_build_match_report  # at least the edited match was rebuilt


def test_opponent_archetype_classified_at_alone_rebuilds_nothing(
    client, counting_build_match_report
):
    """classify_matches restamps classified_at on every rebuild, including
    ones that changed no verdict, and the watcher does this every few
    seconds while Arena is open -- the shared cache must not treat that as
    a reason to rebuild every report on the next request."""
    conn = sqlite3.connect(client.app.state.database)
    conn.execute(
        "INSERT INTO opponent_archetype (match_id, format, archetype_key, archetype_name, "
        "colors, label, method, confidence, cards_seen, conditions_met, conditions_unknown, "
        "evidence_json, classified_at) VALUES (?, 'Standard', 'boros', 'Boros Aggro', 'RW', "
        "'Boros Aggro', 'archetype', 'high', 5, 3, 0, NULL, '2026-01-01T00:00:00Z')",
        (MATCH_WIN,),
    )
    conn.commit()
    conn.close()

    client.get("/api/review/leaks")
    counting_build_match_report.clear()

    conn = sqlite3.connect(client.app.state.database)
    conn.execute(
        "UPDATE opponent_archetype SET classified_at = '2026-02-02T00:00:00Z' WHERE match_id = ?",
        (MATCH_WIN,),
    )
    conn.commit()
    conn.close()

    client.get("/api/review/leaks")
    assert counting_build_match_report == []


def test_opponent_deck_override_write_invalidates_the_shared_report_cache(
    client, counting_build_match_report
):
    client.get("/api/review/leaks")
    counting_build_match_report.clear()

    resp = client.put(f"/api/matches/{MATCH_WIN}/opponent-deck", json={"label": "Rogue"})
    assert resp.status_code == 200

    client.get("/api/review/leaks")
    assert MATCH_WIN in counting_build_match_report


def test_mtgo_pick_write_invalidates_the_shared_report_cache(
    mtgo_pick_client, counting_build_match_report
):
    """A pick moves ``v_match_deck``, which a cached report reads in place of
    ``matches.deck_id``, so ``_report_inputs_token`` digests ``mtgo_match_pick``."""
    mtgo_pick_client.get("/api/review/leaks")
    counting_build_match_report.clear()

    resp = mtgo_pick_client.put(
        f"/api/matches/{MTGO_PICK_A}/mtgo-pick", json={"format": "Modern"}
    )
    assert resp.status_code == 200

    mtgo_pick_client.get("/api/review/leaks")
    assert counting_build_match_report


def test_guide_request_after_leaks_request_reuses_its_reports(
    client, guide_key, counting_build_match_report
):
    """Cross-route share: build_deck_guide's own find_leaks calls
    (guide/bundle.py) must see the same shared cache api/routes/review.py
    already populated, for the same consensus_since -- a guide page load
    right after a leaks page load should build no report the leaks request
    already built."""
    client.get("/api/review/leaks")
    counting_build_match_report.clear()

    client.get(f"/api/guide/{guide_key}")
    assert counting_build_match_report == []


def test_narrative_route_hands_over_a_prompt_with_no_key_anywhere(client, monkeypatch):
    """The GET route never checks for a credential at all — only the POST
    generate route does — so it hands over the prompt the same way whether
    or not one is configured (AGENTS.md #5, `docs/llm.md`)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    body = client.get(f"/api/matches/{MATCH_WIN}/report/narrative").json()
    assert body["status"] == "prompt"
    assert body["narrative"] is None
    assert narrative.SYSTEM_PROMPT in body["prompt"]


def test_narrative_404s_for_an_unknown_match(client):
    assert client.get("/api/matches/nope/report/narrative").status_code == 404


def test_narrative_prompt_carries_the_evidence_and_the_framing(client):
    body = client.get(
        f"/api/matches/{MATCH_WIN}/report/narrative", params={"preview": "1"}
    ).json()
    assert body["status"] == "prompt"
    assert body["narrative"] is None
    assert "Findings:" in body["prompt"]
    assert "Not tracked by this reader at all, for any match" in body["prompt"]


def test_narrative_prompt_carries_no_local_paths(client, monkeypatch):
    """AGENTS.md rule 5 was rewritten to drop the enumerated-calls model in
    favor of a standard (opt-in, inspectable, fail-soft, no more than the
    feature needs) — this prompt now deliberately carries the game's own
    shape (review/narrative.py's module docstring), so the old "no board
    state at all" check no longer matches the design. What would still be
    wrong to leak regardless is a filesystem path, which would reveal the
    machine and buy the coaching nothing."""
    body = client.get(
        f"/api/matches/{MATCH_WIN}/report/narrative", params={"preview": "1"}
    ).json()
    prompt = body["prompt"].lower()
    for leaked in ("/home/", "c:\\users", "/users/", "appdata"):
        assert leaked not in prompt


def test_narrative_prompt_includes_field_context_for_a_classified_opponent(
    named_client, monkeypatch
):
    """MATCH_WIN resolves to the 'Test' archetype in named_client — with
    metagame data stored for that same archetype_key, the prompt must carry
    the field figure. The vocabulary is shared on purpose (Phase 1/3): the
    same archetype_key names both a personal match and a corpus decklist."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    conn = sqlite3.connect(named_client.app.state.database)
    event = ParsedEvent(
        event_id="e1", source="MTGmelee", name="Champs", event_date="2026-08-01",
        format="Standard", tier="A", standings_rows=1, uri=None, blob_sha="s1",
    )
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, format, "
        "tier, standings_rows, uri) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event.event_id, event.event_id, event.blob_sha, event.source, event.name,
         event.event_date, event.format, event.tier, event.standings_rows, event.uri),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, result, wins, losses, draws, "
        "mainboard_json, sideboard_json) VALUES (?, 0, '2-1-0', 2, 1, 0, '[]', '[]')",
        (event.event_id,),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "colors, label, method, classified_at) "
        "VALUES (?, 0, 'Test', 'Test Deck', '', 'Test Deck', 'archetype', '2026-08-01T00:00:00Z')",
        (event.event_id,),
    )
    conn.commit()
    conn.close()

    body = named_client.get(
        f"/api/matches/{MATCH_WIN}/report/narrative", params={"preview": "1"}
    ).json()
    assert "Field context" in body["prompt"]
    assert "Test Deck has won" in body["prompt"]


def test_narrative_prompt_omits_field_context_for_a_colours_only_opponent(
    named_client, monkeypatch
):
    """MATCH_LOSS falls back to a colours-only label in named_client — its
    opponent_key never starts with 'archetype:', so there is no shared
    vocabulary to join field data on, and the prompt must not claim one."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    body = named_client.get(
        f"/api/matches/{MATCH_LOSS}/report/narrative", params={"preview": "1"}
    ).json()
    if body["prompt"] is not None:
        assert "Field context" not in body["prompt"]


# --- deck selector ----------------------------------------------------------


def test_decks_carry_the_context_the_selector_shows(client):
    """The selector labels decks with their format and record, so a deck that
    reported neither would render as a bare hash."""
    (deck,) = client.get("/api/decks").json()
    assert deck["name"] == "Spellelementals"
    assert deck["format"] == "TraditionalStandard"
    assert (deck["matches_played"], deck["matches_won"]) == (2, 1)
    assert deck["last_played"] == "2026-08-13T15:18:39"


def test_a_decks_first_played_is_its_earliest_match_start(client):
    """The fixture's first match starts at entry 5 (its MatchGameRoomStateChangedEvent,
    logged 2026-08-13T14:49:19, per fixture_peek.py), the second at 15:18:39, so
    first_played is the older of the two."""
    (deck,) = client.get("/api/decks").json()
    assert deck["first_played"] == "2026-08-13T14:49:19"
    assert deck["first_played"] < deck["last_played"]


def test_decks_leave_out_one_no_match_is_picked_to(mtgo_pick_client):
    """Three exported MTGO decks and two unpicked MTGO matches: the dropdown
    still lists only the Arena deck, which has matches."""
    assert mtgo_pick_client.get("/api/health").json()["decks"] == 4
    (deck,) = mtgo_pick_client.get("/api/decks").json()
    assert deck["name"] == "Spellelementals"
    assert deck["matches_played"] > 0


def test_a_picked_mtgo_deck_appears_and_its_range_starts_at_its_first_match(
    mtgo_pick_db, make_client
):
    """mtgo_pick_db logs match A at 2099-01-01T00:00:00 and match B a day later,
    and those are their started_at. The deck file's save time is first_seen, a
    different moment: first_played is the older picked match's start."""
    with make_client(create_app(mtgo_pick_db)) as client:
        deck_id = _pick_decks(client)["Sample"]
        for match_id in (MTGO_PICK_A, MTGO_PICK_B):
            client.put(f"/api/matches/{match_id}/mtgo-pick", json={"deck_id": deck_id})
        picked = {d["deck_id"]: d for d in client.get("/api/decks").json()}
    assert len(picked) == 2  # the Arena deck and the one picked deck
    row = picked[deck_id]
    assert row["matches_played"] == 2
    assert row["first_played"] == "2099-01-01T00:00:00"
    assert row["last_played"] == "2099-01-02T00:00:00"
    assert row["first_seen"] is not None and row["first_seen"] != row["first_played"]


def test_deck_counts_include_a_match_still_being_played(live_client):
    """v_deck_winrate counts completed matches only. The selector must not
    drop a deck, or shrink its count, in the middle of a game."""
    (deck,) = live_client.get("/api/decks").json()
    assert deck["matches_played"] == 2


# --- opponent decks ---------------------------------------------------------
# Arena never sends the opponent's decklist, so the label is inferred from the
# cards they revealed. Definitions here are synthetic, so what is asserted is
# the plumbing and the precedence, not upstream's metagame.


def _teach(db_path, *, grp_id, name, archetype="Test Deck"):
    """Set up one match to classify and one to fall back on colours.

    ``grp_id`` gets a name and a rule that matches it, so its match resolves to
    an archetype. The other match's opponent card (69399, a card seat 1 played
    in MATCH_LOSS, read from the fixture) gets a name but no rule, so it
    exercises the colours-and-signature layer underneath. A second archetype,
    ``NeverSeen``, requires a card neither match ever reveals — it never wins
    a classification, but it makes every candidates-endpoint call exercise the
    "offered anyway, ranked last" tier.
    """
    from sensei_top.archetypes import classify_matches

    conn = open_database(db_path)
    conn.executemany(
        "INSERT OR REPLACE INTO cards (grp_id, name, type_line, rarity, colors) VALUES (?,?,?,?,?)",
        [
            (grp_id, name, "Creature — Test", "rare", '["U"]'),
            (69399, "Unruled Card", "Creature — Test", "rare", '["G"]'),
        ],
    )
    conn.execute(
        """
        INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)
             VALUES ('Standard', 'archetype', 'Test', ?, 0, ?, '2026-01-01T00:00:00Z')
        """,
        (archetype,
         json.dumps({"Name": archetype,
                     "Conditions": [{"Type": "InMainboard", "Cards": [name]}]})),
    )
    conn.execute(
        """
        INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)
             VALUES ('Standard', 'archetype', 'NeverSeen', 'Never Seen Deck', 0, ?,
                     '2026-01-01T00:00:00Z')
        """,
        (json.dumps({"Name": "Never Seen Deck",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Nonexistent Card"]}]}),),
    )
    classify_matches(conn)
    conn.close()


@pytest.fixture
def named_client(tmp_path, make_client):
    """The fixture session with one opponent card named and one rule to match it.

    grpId 98589 is a card the opponent played in MATCH_WIN, read from the
    fixture's ZoneTransfer annotations.
    """
    db_path = tmp_path / "named.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    _teach(db_path, grp_id=98589, name="Test Signature")
    with make_client(create_app(db_path)) as c:
        yield c


def test_matches_carry_the_inferred_opponent_deck(named_client):
    rows = named_client.get("/api/matches").json()
    matched = [m for m in rows if m["opponent_source"] == "archetype"]
    assert [m["opponent_label"] for m in matched] == ["Test Deck"]
    assert matched[0]["opponent_cards_seen"] >= 1


def test_the_player_name_is_still_returned_even_though_it_is_not_shown(named_client):
    """The dashboard stopped rendering it; removing it from the contract to
    enforce that would put a display decision in the wrong layer."""
    assert any(m["opponent_name"] for m in named_client.get("/api/matches").json())


def test_an_unidentified_opponent_falls_back_to_colours_and_a_signature_card(named_client):
    """No rule matched, so the label describes rather than classifies — and
    says so, in raw WUBRG letters instead of a guild name."""
    rows = named_client.get("/api/matches").json()
    described = [m for m in rows if m["opponent_source"] == "colors"]
    assert [m["opponent_label"] for m in described] == ["G · Unruled Card"]
    assert described[0]["opponent_confidence"] == "unknown"


def test_matches_carry_the_opponents_revealed_colours(named_client):
    """opponent_colors is the colours the opponent actually revealed
    (v_opponent_cards.colors), not the archetype's assumed colours. `_teach`
    gives the classified match's signature card (grpId 98589, "Test
    Signature") colours ["U"], and the fallback match's own card (grpId
    69399, "Unruled Card", read from the fixture) colours ["G"] — the test
    DB's `cards` table holds only those two taught rows, so those are the
    only colours either match could possibly report."""
    rows = named_client.get("/api/matches").json()
    matched = [m for m in rows if m["opponent_source"] == "archetype"]
    described = [m for m in rows if m["opponent_source"] == "colors"]
    assert [m["opponent_colors"] for m in matched] == ["U"]
    assert [m["opponent_colors"] for m in described] == ["G"]


def test_an_untaught_client_never_reports_opponent_colors(client):
    """`client` never runs `_teach`, so `cards` is empty and every revealed
    card's colours are unknown — v_opponent_cards.colors is '' for every
    match, which becomes NULL here, never the empty string."""
    rows = client.get("/api/matches").json()
    assert rows
    assert all(m["opponent_colors"] is None for m in rows)


def test_matchups_group_two_opponents_onto_one_deck(named_client):
    """The whole point: different players on the same archetype are one row."""
    rows = named_client.get("/api/metrics/matchups").json()
    assert rows
    assert all(r["matches_completed"] > 0 for r in rows)
    assert sum(r["matches_completed"] for r in rows) == sum(
        r["matches_completed"] for r in named_client.get("/api/metrics/winrate").json()
    )


def test_matchups_deck_filter(named_client, deck_id):
    assert named_client.get("/api/metrics/matchups", params={"deck_id": deck_id}).json()
    assert named_client.get("/api/metrics/matchups", params={"deck_id": "beef"}).json() == []


def test_metagame_status_counts_the_named_clients_opponent_sources(named_client):
    """named_client resolves one match to 'archetype' and one to 'colors', and
    stores one 'Standard' archetype file — this route must report exactly that,
    not silently miscount or drop a bucket."""
    body = named_client.get("/api/metagame/status").json()
    assert body["archetype_files"] == 2  # 'Test' and 'NeverSeen', both Standard
    breakdown = body["standard_opponent_sources"]
    assert breakdown["archetype"] == 1
    assert breakdown["colors"] == 1
    assert breakdown["total"] == breakdown["archetype"] + breakdown["colors"] + breakdown[
        "fallback"
    ] + breakdown["manual"] + breakdown["unknown"]


def test_metagame_status_with_no_data(tmp_path, make_client):
    """A freshly migrated, empty database — no archetypes fetched, no matches
    played — must answer with zeros and a null age, never an error."""
    db_path = tmp_path / "empty.db"
    open_database(db_path).close()
    with make_client(create_app(db_path)) as c:
        body = c.get("/api/metagame/status").json()
    assert body["archetype_cache_age_hours"] is None
    assert body["archetype_files"] == 0
    assert body["standard_opponent_sources"]["total"] == 0


# --- metagame: presence, winrate, matchups -----------------------------------
# One archetype (needs Momo), one fallback family, a Tier C league (presence
# only) and a Tier A paper swiss with a real head-to-head match — the same
# shape test_metagame.py's _teach_meta uses, wired through the API this time.


@pytest.fixture
def meta_client(tmp_path, make_client):
    db_path = tmp_path / "meta.db"
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'UWMomo', 'Momo', 0, ?, '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Momo",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Momo, Friendly Flier"]}]}),),
    )
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'Aristocrats', 'Aristocrats', 0, ?,"
        " '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Aristocrats",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Infestation Sage"]}]}),),
    )
    today = datetime.now(UTC)
    league_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    swiss_date = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    league = ParsedEvent(
        event_id="league1", source="MTGO", name="League", event_date=league_date,
        format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="s1",
        decks=[
            ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
            ParsedDeck(1, "5-0", 5, 0, 0, [{"count": 4, "name": "Something Unmatched"}], []),
        ],
    )
    swiss = ParsedEvent(
        event_id="swiss1", source="MTGmelee", name="Champs", event_date=swiss_date,
        format="Standard", tier="A", standings_rows=2, uri=None, blob_sha="s2",
        decks=[
            ParsedDeck(0, "2-1-0", 2, 1, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
            ParsedDeck(1, "1-2-0", 1, 2, 0, [{"count": 4, "name": "Infestation Sage"}], []),
        ],
        round_matches=[ParsedRoundMatch("Round 1", 0, 1, 2, 1, 0)],
    )
    store_events(conn, [league, swiss])
    classify_meta_decks(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


def test_metagame_presence_covers_every_tier_without_blending_them(meta_client):
    rows = meta_client.get("/api/metagame/presence").json()
    by_tier_key = {(r["tier"], r["archetype_key"]): r for r in rows}
    assert set(by_tier_key) == {("A", "UWMomo"), ("A", "Aristocrats"), ("C", "UWMomo")}
    # Tier C's one classified deck is the whole Tier C pool, so its own share
    # is 1.0 — never diluted by Tier A's decks, which must never be blended in.
    assert by_tier_key[("C", "UWMomo")]["share"] == 1.0
    assert by_tier_key[("A", "UWMomo")]["share"] == 0.5


def test_metagame_presence_tier_filter(meta_client):
    rows = meta_client.get("/api/metagame/presence", params={"tier": "C"}).json()
    assert {r["archetype_key"] for r in rows} == {"UWMomo"}


def test_metagame_presence_days_window_excludes_older_events(meta_client):
    rows = meta_client.get("/api/metagame/presence", params={"days": 1}).json()
    assert rows == []


def test_metagame_winrate_excludes_the_tier_c_league(meta_client):
    """The load-bearing constraint from the caller's side: a Tier C-only
    archetype must never appear in the winrate endpoint at all."""
    rows = meta_client.get("/api/metagame/winrate").json()
    keys = {r["archetype_key"] for r in rows}
    assert keys == {"UWMomo", "Aristocrats"}
    momo = next(r for r in rows if r["archetype_key"] == "UWMomo")
    assert momo["entries"] == 1  # only the Tier A deck, not the Tier C one
    # ParsedDeck(0, "2-1-0", 2, 1, 0, ...) in _teach_meta: 2 match wins, 1 loss.
    assert (momo["matches_won"], momo["matches_lost"], momo["matches_drawn"]) == (2, 1, 0)
    assert momo["winrate"] == pytest.approx(2 / 3)


def test_metagame_matchups_default_to_tier_a_with_sample_size(meta_client):
    rows = meta_client.get("/api/metagame/matchups").json()
    momo_vs_aristo = next(r for r in rows if r["archetype_key"] == "UWMomo")
    assert momo_vs_aristo["tier"] == "A"
    assert momo_vs_aristo["n"] == 1
    assert momo_vs_aristo["matches_won"] == 1
    assert momo_vs_aristo["winrate"] == 1.0


def test_metagame_matchups_tier_c_has_no_rounds_at_all(meta_client):
    """A league event never populates meta_round_match — see tiers.py — so
    asking for Tier C matchups must come back empty, not an error."""
    assert meta_client.get("/api/metagame/matchups", params={"tier": "C"}).json() == []


def test_metagame_matchups_combines_repeated_tier_params(meta_client):
    """`?tier=A&tier=C` must equal Tier A alone here (C has no rounds to
    contribute), proving tiers are summed rather than one silently winning."""
    a_only = meta_client.get("/api/metagame/matchups", params={"tier": "A"}).json()
    combined = meta_client.get(
        "/api/metagame/matchups", params=[("tier", "A"), ("tier", "C")]
    ).json()
    assert [(r["archetype_key"], r["n"], r["matches_won"]) for r in a_only] == [
        (r["archetype_key"], r["n"], r["matches_won"]) for r in combined
    ]


# --- metagame: since/days windowing (format-reset boundary) -----------------
# Two dated Tier A swiss events for the same UWMomo-vs-Aristocrats pairing —
# the same shape test_metagame.py's _teach_meta_two_dated_swiss_events uses
# for v_meta_matchup's own date grain (044), wired through the API here.


@pytest.fixture
def windowed_meta_client(tmp_path, make_client):
    db_path = tmp_path / "meta_window.db"
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'UWMomo', 'Momo', 0, ?, '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Momo",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Momo, Friendly Flier"]}]}),),
    )
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'Aristocrats', 'Aristocrats', 0, ?,"
        " '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Aristocrats",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Infestation Sage"]}]}),),
    )
    early = ParsedEvent(
        event_id="early", source="MTGmelee", name="Champs", event_date="2026-07-01",
        format="Standard", tier="A", standings_rows=2, uri=None, blob_sha="s1",
        decks=[
            ParsedDeck(0, "1-0-0", 1, 0, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
            ParsedDeck(1, "0-1-0", 0, 1, 0, [{"count": 4, "name": "Infestation Sage"}], []),
        ],
        round_matches=[ParsedRoundMatch("Round 1", 0, 1, 1, 0, 0)],
    )
    late = ParsedEvent(
        event_id="late", source="MTGmelee", name="Champs", event_date="2026-08-10",
        format="Standard", tier="A", standings_rows=2, uri=None, blob_sha="s2",
        decks=[
            ParsedDeck(0, "1-0-0", 1, 0, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
            ParsedDeck(1, "0-1-0", 0, 1, 0, [{"count": 4, "name": "Infestation Sage"}], []),
        ],
        round_matches=[ParsedRoundMatch("Round 1", 0, 1, 1, 0, 0)],
    )
    store_events(conn, [early, late])
    classify_meta_decks(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


def test_metagame_presence_since_excludes_the_earlier_event(windowed_meta_client):
    rows = windowed_meta_client.get(
        "/api/metagame/presence", params={"since": "2026-08-01"}
    ).json()
    assert sum(r["decks"] for r in rows) == 2  # only the late event's two decks


def test_metagame_presence_since_overrides_days(windowed_meta_client):
    """A wide days window would include both events on its own — since must
    still win when both are given."""
    rows = windowed_meta_client.get(
        "/api/metagame/presence", params={"since": "2026-08-01", "days": 3650}
    ).json()
    assert sum(r["decks"] for r in rows) == 2


def test_metagame_winrate_since_excludes_the_earlier_event(windowed_meta_client):
    rows = windowed_meta_client.get(
        "/api/metagame/winrate", params={"since": "2026-08-01"}
    ).json()
    momo = next(r for r in rows if r["archetype_key"] == "UWMomo")
    assert momo["entries"] == 1  # only the late event's deck


def test_metagame_matchups_since_excludes_the_earlier_event(windowed_meta_client):
    rows = windowed_meta_client.get(
        "/api/metagame/matchups", params={"since": "2026-08-01"}
    ).json()
    momo_vs_aristo = next(r for r in rows if r["archetype_key"] == "UWMomo")
    assert momo_vs_aristo["n"] == 1  # only the late round, not both pooled


def test_metagame_matchups_with_no_window_returns_the_whole_corpus(windowed_meta_client):
    """Neither since nor days given — today's behaviour, unchanged."""
    rows = windowed_meta_client.get("/api/metagame/matchups").json()
    momo_vs_aristo = next(r for r in rows if r["archetype_key"] == "UWMomo")
    assert momo_vs_aristo["n"] == 2


# Every list inserted directly into meta_event/meta_deck/meta_deck_archetype
# (test_consensus.py's own pattern), one event per list, so a known count of
# each combination drives a by-hand expectation rather than the classifier's
# own output (AGENTS.md non-negotiable 8).


def _meta_colored_deck(conn, event_id, *, tier, event_date, colors, archetype_key,
                        wins=0, losses=0, draws=0):
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
        "format, tier) VALUES (?, 'p', ?, 'mtgo', 'e', ?, 'Standard', ?)",
        (event_id, event_id, event_date, tier),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, wins, losses, draws, mainboard_json, "
        "sideboard_json) VALUES (?, 0, ?, ?, ?, '[]', '[]')",
        (event_id, wins, losses, draws),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "colors, label, method, classified_at) VALUES (?, 0, ?, ?, ?, ?, 'archetype', 'now')",
        (event_id, archetype_key, archetype_key, colors, archetype_key),
    )


@pytest.fixture
def field_colors_client(tmp_path, make_client):
    db_path = tmp_path / "field_colors.db"
    conn = open_database(db_path)

    # Lifegain: 3 of 4 lists are WB, but MAX(colors) would pick the lexically
    # largest combination, "WBG", though it is the minority.
    for i, colors in enumerate(["WB", "WB", "WB", "WBG"]):
        _meta_colored_deck(conn, f"lg-{i}", tier="B", event_date="2026-08-15",
                            colors=colors, archetype_key="Lifegain")

    # TieDeck: 2 UB, 2 WU — a tie must answer the combination first in text
    # order ("UB" < "WU").
    for i, colors in enumerate(["UB", "UB", "WU", "WU"]):
        _meta_colored_deck(conn, f"td-{i}", tier="B", event_date="2026-08-15",
                            colors=colors, archetype_key="TieDeck")

    # TierDeck: the same archetype, two tiers, two different majorities.
    for i, colors in enumerate(["WUR", "WUR", "WUBR"]):
        _meta_colored_deck(conn, f"tdb-{i}", tier="B", event_date="2026-08-15",
                            colors=colors, archetype_key="TierDeck")
    for i, colors in enumerate(["UBG", "UBG", "WUR"]):
        _meta_colored_deck(conn, f"tdc-{i}", tier="C", event_date="2026-08-15",
                            colors=colors, archetype_key="TierDeck")

    # WindowDeck: in-window majority is UB (2 of 3); five more "U" lists sit
    # before the window and would flip the majority to "U" if they counted.
    for i, colors in enumerate(["UB", "UB", "U"]):
        _meta_colored_deck(conn, f"wd-in-{i}", tier="B", event_date="2026-08-15",
                            colors=colors, archetype_key="WindowDeck")
    for i in range(5):
        _meta_colored_deck(conn, f"wd-out-{i}", tier="B", event_date="2026-07-01",
                            colors="U", archetype_key="WindowDeck")

    # WinDeck: win rate pools tiers A and B — UB (3 of 5) only becomes the
    # majority once both tiers are combined; Tier B alone would answer WR (2
    # of 3). A Tier C list ("G") must not be counted at all.
    for i in range(2):
        _meta_colored_deck(conn, f"win-a-{i}", tier="A", event_date="2026-08-15",
                            colors="UB", archetype_key="WinDeck")
    _meta_colored_deck(conn, "win-b-ub", tier="B", event_date="2026-08-15",
                        colors="UB", archetype_key="WinDeck")
    for i in range(2):
        _meta_colored_deck(conn, f"win-b-wr-{i}", tier="B", event_date="2026-08-15",
                            colors="WR", archetype_key="WinDeck")
    _meta_colored_deck(conn, "win-c", tier="C", event_date="2026-08-15",
                        colors="G", archetype_key="WinDeck")

    # NullDeck: every list's colours are unknown — the row must answer null,
    # exactly like today.
    for i in range(2):
        _meta_colored_deck(conn, f"null-{i}", tier="B", event_date="2026-08-15",
                            colors=None, archetype_key="NullDeck")

    conn.commit()
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


def test_metagame_presence_colors_is_the_majority_not_max(field_colors_client):
    rows = field_colors_client.get(
        "/api/metagame/presence", params={"since": "2026-08-01"}
    ).json()
    lifegain = next(r for r in rows if r["archetype_key"] == "Lifegain")
    assert lifegain["colors"] == "WB"  # MAX(colors) would answer "WBG"


def test_metagame_presence_colors_tie_goes_to_text_order(field_colors_client):
    rows = field_colors_client.get(
        "/api/metagame/presence", params={"since": "2026-08-01"}
    ).json()
    tie = next(r for r in rows if r["archetype_key"] == "TieDeck")
    assert tie["colors"] == "UB"


def test_metagame_presence_colors_are_computed_per_tier(field_colors_client):
    rows = field_colors_client.get(
        "/api/metagame/presence", params={"since": "2026-08-01"}
    ).json()
    by_tier = {r["tier"]: r for r in rows if r["archetype_key"] == "TierDeck"}
    assert by_tier["B"]["colors"] == "WUR"
    assert by_tier["C"]["colors"] == "UBG"


def test_metagame_presence_colors_ignore_lists_outside_the_window(field_colors_client):
    rows = field_colors_client.get(
        "/api/metagame/presence", params={"since": "2026-08-01"}
    ).json()
    window_deck = next(r for r in rows if r["archetype_key"] == "WindowDeck")
    assert window_deck["colors"] == "UB"  # "U" would win if the older event counted


def test_metagame_presence_colors_null_when_every_list_has_none(field_colors_client):
    rows = field_colors_client.get(
        "/api/metagame/presence", params={"since": "2026-08-01"}
    ).json()
    null_deck = next(r for r in rows if r["archetype_key"] == "NullDeck")
    assert null_deck["colors"] is None


def test_metagame_winrate_colors_combine_tiers_a_and_b(field_colors_client):
    rows = field_colors_client.get(
        "/api/metagame/winrate", params={"since": "2026-08-01"}
    ).json()
    win_deck = next(r for r in rows if r["archetype_key"] == "WinDeck")
    assert win_deck["colors"] == "UB"  # Tier B alone would answer "WR" (2 of 3)
    assert win_deck["entries"] == 5  # the Tier C list is not counted


def _store_meta_deck(conn, event_id, deck_ord, mainboard, *, event_date, fmt="Standard"):
    """Minimal meta_event/meta_deck rows — no archetype classification
    needed, since format_resets (guide/window.py) reads mainboard_json
    directly. Mirrors test_guide_window.py's own _store_deck helper."""
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES (?, 'p', ?, 'mtgo', 'e', ?, ?, 'B')",
        (event_id, event_id, event_date, fmt),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json) "
        "VALUES (?, ?, ?, '[]')",
        (event_id, deck_ord, json.dumps(mainboard)),
    )


def test_metagame_status_format_reset_start_is_null_with_no_legality_data(tmp_path, make_client):
    db_path = tmp_path / "no_legality.db"
    conn = open_database(db_path)
    _store_meta_deck(
        conn, "e1", 0, [{"count": 4, "name": "Lightning Bolt"}], event_date="2026-08-01"
    )
    conn.commit()
    conn.close()
    with make_client(create_app(db_path)) as c:
        body = c.get("/api/metagame/status").json()
    assert body["format_reset_start"] is None


def test_metagame_status_format_reset_start_equals_window_start_once_detected(
    tmp_path, make_client
):
    """Same shape as test_guide_window.py's
    test_reset_detected_from_a_banned_card_disappearing: the banned card's
    last-seen date is 2026-08-09, so window_start (the day after) is
    2026-08-10 — computed by hand from guide/window.py's own +1-day rule,
    not by running the code and pasting its output."""
    db_path = tmp_path / "reset.db"
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO cards (grp_id, name, standard_legality) VALUES (900001, 'Badgermole Cub', "
        "'banned')"
    )
    for i in range(3):
        _store_meta_deck(
            conn, f"pre{i}", 0, [{"count": 4, "name": "Badgermole Cub"}], event_date="2026-08-09"
        )
    for i in range(3):
        _store_meta_deck(
            conn, f"post{i}", 0, [{"count": 4, "name": "Forest"}], event_date="2026-08-15"
        )
    conn.commit()
    conn.close()
    with make_client(create_app(db_path)) as c:
        body = c.get("/api/metagame/status").json()
    assert body["format_reset_start"] == "2026-08-10"


def test_metagame_status_reports_the_pinned_corpus_commit(meta_client):
    body = meta_client.get("/api/metagame/status").json()
    assert body["corpus_events_by_tier"] == {"a": 1, "b": 0, "c": 1, "d": 0}
    # No refresh_metagame() call happened in this fixture (only store_events +
    # classify), so meta_fetch has no row — commit_sha stays null, honestly.
    assert body["corpus_commit_sha"] is None
    # No duplicate events in this fixture's corpus.
    assert body["corpus_duplicate_events"] == 0


def test_metagame_status_excludes_duplicate_events_from_tier_counts(tmp_path, make_client):
    """A twin (metagame/dedup.py) must not inflate corpus_events_by_tier —
    it is reported separately, via corpus_duplicate_events instead."""
    db_path = tmp_path / "meta_dup.db"
    conn = open_database(db_path)
    decks = [ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "X"}], [])]
    survivor = ParsedEvent(
        event_id="Tournaments/MTGO/2026/06/08/standard-league-2026-06-0810660.json",
        source="MTGO", name="League", event_date="2026-06-08", format="Standard", tier="C",
        standings_rows=0, uri=None, blob_sha="sa", decks=decks,
    )
    twin = ParsedEvent(
        event_id="Tournaments/MTGO/2026/06/10/standard-league-2026-06-0810660.json",
        source="MTGO", name="League", event_date="2026-06-10", format="Standard", tier="C",
        standings_rows=0, uri=None, blob_sha="sb", decks=decks,
    )
    store_events(conn, [survivor, twin])
    assert mark_duplicate_events(conn) == 1
    conn.close()
    with make_client(create_app(db_path)) as c:
        body = c.get("/api/metagame/status").json()
    assert body["corpus_events_by_tier"] == {"a": 0, "b": 0, "c": 1, "d": 0}
    assert body["corpus_duplicate_events"] == 1


# --- metagame: the fourth tier (small paper) ---------------------------------
# Same shape as meta_client (one Tier C league, one paper swiss with a real
# head-to-head match) but the swiss is under 64 players, so it lands in D
# rather than A — a separate fixture so meta_client's own assertions, which
# pin an exact tier set, are untouched.


@pytest.fixture
def tier_d_client(tmp_path, make_client):
    db_path = tmp_path / "meta_d.db"
    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'UWMomo', 'Momo', 0, ?, '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Momo",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Momo, Friendly Flier"]}]}),),
    )
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'Aristocrats', 'Aristocrats', 0, ?,"
        " '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Aristocrats",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Infestation Sage"]}]}),),
    )
    today = datetime.now(UTC)
    league_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    swiss_date = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    league = ParsedEvent(
        event_id="league-d", source="MTGO", name="League", event_date=league_date,
        format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="ld1",
        decks=[
            ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
            ParsedDeck(1, "5-0", 5, 0, 0, [{"count": 4, "name": "Something Unmatched"}], []),
        ],
    )
    small_swiss = ParsedEvent(
        event_id="swiss-d", source="MTGmelee", name="Local RCQ", event_date=swiss_date,
        format="Standard", tier="D", standings_rows=10, uri=None, blob_sha="sd1",
        decks=[
            ParsedDeck(0, "2-1-0", 2, 1, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
            ParsedDeck(1, "1-2-0", 1, 2, 0, [{"count": 4, "name": "Infestation Sage"}], []),
        ],
        round_matches=[ParsedRoundMatch("Round 1", 0, 1, 2, 1, 0)],
    )
    store_events(conn, [league, small_swiss])
    classify_meta_decks(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


def test_metagame_status_counts_a_tier_d_event(tier_d_client):
    body = tier_d_client.get("/api/metagame/status").json()
    assert body["corpus_events_by_tier"] == {"a": 0, "b": 0, "c": 1, "d": 1}


def test_metagame_presence_accepts_tier_d(tier_d_client):
    rows = tier_d_client.get("/api/metagame/presence", params={"tier": "D"}).json()
    assert {r["archetype_key"] for r in rows} == {"UWMomo", "Aristocrats"}


def test_metagame_winrate_includes_tier_d_and_excludes_tier_c(tier_d_client):
    rows = tier_d_client.get("/api/metagame/winrate").json()
    assert {r["archetype_key"] for r in rows} == {"UWMomo", "Aristocrats"}
    momo = next(r for r in rows if r["archetype_key"] == "UWMomo")
    assert momo["entries"] == 1  # only the Tier D deck, not the Tier C one
    assert (momo["matches_won"], momo["matches_lost"], momo["matches_drawn"]) == (2, 1, 0)


# --- candidates for the picker -----------------------------------------------


def _match_id_by_source(client, source: str) -> str:
    rows = client.get("/api/matches").json()
    return next(m["match_id"] for m in rows if m["opponent_source"] == source)


def test_candidates_rank_the_matched_archetype_first(named_client):
    match_id = _match_id_by_source(named_client, "archetype")
    candidates = named_client.get(f"/api/matches/{match_id}/opponent-deck/candidates").json()
    # fit: one condition, fully met (proof 1, support 1-0.5=0.5), and the
    # opponent's only card in the `cards` table (Test Signature, U) matches
    # the definition's own colour, so the colour factor is 1 — 0.5 total.
    # No differently-labelled rival (NeverSeen never matches), so margin is
    # infinite; cards_seen is 1, under the 'high' floor of 6, so confidence
    # settles at 'medium' rather than 'high'.
    assert candidates[0] == {
        "archetype_key": "Test",
        "label": "Test Deck",
        "kind": "archetype",
        "confidence": "medium",
        "fit": 0.5,
        "evidence": ["Test Signature"],
        "reasons": ["matched Test Signature"],
        "signature_cards": [{"name": "Test Signature", "seen": True}],
        "picked": False,
    }


def test_candidates_include_unmatched_definitions_ranked_last(named_client):
    """`NeverSeen` (see `_teach`) never wins a classification, but the player
    watched the match and may know better than the heuristic — so it is still
    offered, just last and unscored."""
    match_id = _match_id_by_source(named_client, "archetype")
    candidates = named_client.get(f"/api/matches/{match_id}/opponent-deck/candidates").json()
    assert candidates[-1] == {
        "archetype_key": "NeverSeen",
        "label": "Never Seen Deck",
        "kind": "archetype",
        "confidence": "none",
        "fit": 0.0,
        "evidence": [],
        "reasons": [],
        "signature_cards": [],
        "picked": False,
    }


def test_candidates_show_seen_and_unseen_signature_cards(tmp_path, make_client):
    """The hints panel's 'play around' section reads signature_cards, not just
    evidence — it needs the archetype's other defining cards too, flagged by
    whether the opponent has shown them yet.

    grpId 98589 is a card the opponent played in MATCH_WIN (see
    ``named_client``'s docstring); 'Unseen Threat' names no real card, so
    Standard's real Test Deck definition can never see it played."""
    db_path = tmp_path / "sig.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, rarity, colors) VALUES (?,?,?,?,?)",
        (98589, "Test Signature", "Creature — Test", "rare", '["U"]'),
    )
    conn.execute(
        """
        INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)
             VALUES ('Standard', 'archetype', 'Test', 'Test Deck', 0, ?, '2026-01-01T00:00:00Z')
        """,
        (json.dumps({
            "Name": "Test Deck",
            "Conditions": [
                {"Type": "InMainboard", "Cards": ["Test Signature"]},
                {"Type": "InMainboard", "Cards": ["Unseen Threat"]},
            ],
        }),),
    )
    from sensei_top.archetypes import classify_matches

    classify_matches(conn)
    conn.close()

    with make_client(create_app(db_path)) as c:
        match_id = _match_id_by_source(c, "archetype")
        candidates = c.get(f"/api/matches/{match_id}/opponent-deck/candidates").json()
    signatures = {s["name"]: s["seen"] for s in candidates[0]["signature_cards"]}
    assert signatures == {"Test Signature": True, "Unseen Threat": False}


def test_candidates_are_empty_when_no_archetypes_are_loaded(client):
    """`client` never runs `_teach`, so the `archetypes` table is empty and
    there is nothing to rank — an empty list, not an error."""
    match_id = client.get("/api/matches").json()[0]["match_id"]
    assert client.get(f"/api/matches/{match_id}/opponent-deck/candidates").json() == []


def test_candidates_for_a_match_that_does_not_exist_is_a_404(named_client):
    response = named_client.get("/api/matches/nope/opponent-deck/candidates")
    assert response.status_code == 404


def _add_a_second_test_deck(db_path) -> None:
    """A second definition under the name "Test Deck" (see ``_teach``), the
    shape of one archetype defined twice in two colours. It needs a card no
    match reveals, so it ranks last at confidence 'none'."""
    conn = open_database(db_path)
    conn.execute(
        """
        INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)
             VALUES ('Standard', 'archetype', 'TestTwin', 'Test Deck', 0, ?,
                     '2026-01-01T00:00:00Z')
        """,
        (json.dumps({"Name": "Test Deck",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Nonexistent Card"]}]}),),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def twin_client(tmp_path, make_client):
    db_path = tmp_path / "twin.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    _teach(db_path, grp_id=98589, name="Test Signature")
    _add_a_second_test_deck(db_path)
    with make_client(create_app(db_path)) as c:
        yield c


def test_candidates_offer_one_name_once_keeping_the_better_fit(twin_client):
    match_id = _match_id_by_source(twin_client, "archetype")
    candidates = twin_client.get(f"/api/matches/{match_id}/opponent-deck/candidates").json()
    assert [(c["label"], c["archetype_key"]) for c in candidates] == [
        ("Test Deck", "Test"),
        ("Never Seen Deck", "NeverSeen"),
    ]


def test_a_picked_twin_keeps_the_name_in_the_better_fits_place(twin_client):
    match_id = _match_id_by_source(twin_client, "archetype")
    twin_client.put(
        f"/api/matches/{match_id}/opponent-deck",
        json={"label": "Test Deck", "archetype_key": "TestTwin"},
    )
    candidates = twin_client.get(f"/api/matches/{match_id}/opponent-deck/candidates").json()
    assert [(c["label"], c["archetype_key"], c["picked"]) for c in candidates] == [
        ("Test Deck", "TestTwin", True),
        ("Never Seen Deck", "NeverSeen", False),
    ]


# --- the one write ----------------------------------------------------------


def match_id_of(client) -> str:
    return client.get("/api/matches").json()[0]["match_id"]


def test_picking_a_candidate_wins_over_the_inferred_one(named_client):
    match_id = _match_id_by_source(named_client, "colors")
    body = named_client.put(
        f"/api/matches/{match_id}/opponent-deck",
        json={"label": "Test Deck", "archetype_key": "Test"},
    ).json()
    assert body["opponent_label"] == "Test Deck"
    assert body["opponent_source"] == "manual"
    assert body["opponent_confidence"] == "high"


def test_picking_a_candidate_flags_it_picked_in_the_candidate_list(named_client):
    """The advisor's hint context and the 'play around' card both need to
    know which candidate the player chose, not just that some pick was made —
    `rank_candidates` flags the matching candidate itself rather than making
    each caller re-look-up `opponent_deck_override`."""
    match_id = _match_id_by_source(named_client, "colors")
    named_client.put(
        f"/api/matches/{match_id}/opponent-deck",
        json={"label": "Test Deck", "archetype_key": "Test"},
    )
    candidates = named_client.get(f"/api/matches/{match_id}/opponent-deck/candidates").json()
    picked = [c for c in candidates if c["picked"]]
    assert [c["archetype_key"] for c in picked] == ["Test"]


def test_a_picked_archetype_merges_into_the_classifiers_own_matchup(named_client):
    """The whole point of storing `archetype_key`: two matches on the same
    archetype are one matchup row, whether the classifier found it or the
    player picked it."""
    archetype_match = _match_id_by_source(named_client, "archetype")
    colors_match = _match_id_by_source(named_client, "colors")
    named_client.put(
        f"/api/matches/{colors_match}/opponent-deck",
        json={"label": "Test Deck", "archetype_key": "Test"},
    )

    matchups = named_client.get("/api/metrics/matchups").json()
    merged = [m for m in matchups if m["opponent_key"] == "archetype:Test"]
    assert len(merged) == 1
    assert merged[0]["matches_completed"] == 2
    assert archetype_match  # both matches feed the same row; nothing left unmerged
    # Both matches' revealed colours (U from the archetype match, G from the
    # one just picked onto it) union onto the merged row, WUBRG order.
    assert merged[0]["opponent_colors"] == "UG"


def test_rogue_is_accepted_without_an_archetype_key(named_client):
    """Rogue — Magic's term for a deck with no established archetype — is not
    one of the candidates the API offers, but it is always a valid pick."""
    match_id = match_id_of(named_client)
    response = named_client.put(f"/api/matches/{match_id}/opponent-deck", json={"label": "Rogue"})
    body = response.json()
    assert body["opponent_label"] == "Rogue"
    assert body["opponent_key"] == "manual:Rogue"
    assert body["opponent_source"] == "manual"


def test_free_text_without_an_archetype_key_is_refused(named_client):
    """The free-text 'name it' path is gone: a label must either name a real
    candidate via `archetype_key`, or be exactly 'Rogue'."""
    match_id = match_id_of(named_client)
    response = named_client.put(
        f"/api/matches/{match_id}/opponent-deck", json={"label": "Azorius Momo"}
    )
    assert response.status_code == 422


def test_an_unknown_archetype_key_is_refused(named_client):
    match_id = match_id_of(named_client)
    response = named_client.put(
        f"/api/matches/{match_id}/opponent-deck",
        json={"label": "Made Up", "archetype_key": "NoSuchKey"},
    )
    assert response.status_code == 422


def test_surrounding_whitespace_is_normalised(named_client):
    body = named_client.put(
        f"/api/matches/{match_id_of(named_client)}/opponent-deck",
        json={"label": "  Test   Deck  ", "archetype_key": "Test"},
    ).json()
    assert body["opponent_label"] == "Test Deck"


def test_an_empty_label_clears_the_override_and_the_guess_returns(named_client):
    """Clearing is the same verb, so the response shows what comes back."""
    match_id = match_id_of(named_client)
    named_client.put(f"/api/matches/{match_id}/opponent-deck", json={"label": "Rogue"})
    body = named_client.put(f"/api/matches/{match_id}/opponent-deck", json={"label": ""}).json()
    assert body["opponent_source"] != "manual"


def test_labelling_a_match_that_does_not_exist_is_a_404(named_client):
    response = named_client.put("/api/matches/nope/opponent-deck", json={"label": "Rogue"})
    assert response.status_code == 404


def test_an_overlong_label_is_refused(named_client):
    match_id = match_id_of(named_client)
    assert named_client.put(
        f"/api/matches/{match_id}/opponent-deck", json={"label": "x" * 81}
    ).status_code == 422


def test_a_pasted_newline_is_folded_into_a_space_not_rejected(named_client):
    """Pasting a deck name off a website brings a line break with it. Folding
    it is what the user meant; refusing would be pedantry."""
    body = named_client.put(
        f"/api/matches/{match_id_of(named_client)}/opponent-deck",
        json={"label": "Test\nDeck", "archetype_key": "Test"},
    ).json()
    assert body["opponent_label"] == "Test Deck"


def test_a_control_character_is_refused(named_client):
    """Whitespace normalises away; anything else non-printing is not a name."""
    assert named_client.put(
        f"/api/matches/{match_id_of(named_client)}/opponent-deck",
        json={"label": "Azorius\x00Momo"},
    ).status_code == 422


def test_a_manual_pick_survives_a_full_rebuild(tmp_path, make_client):
    """The override table deliberately has no foreign key to matches: a rebuild
    deletes every derived row, and the user's own pick must outlive it."""
    db_path = tmp_path / "survive.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()

    with make_client(create_app(db_path)) as client:
        match_id = match_id_of(client)
        client.put(f"/api/matches/{match_id}/opponent-deck", json={"label": "Rogue"})

    conn = open_database(db_path)
    project(conn)
    conn.close()

    with make_client(create_app(db_path)) as client:
        after = [m for m in client.get("/api/matches").json() if m["match_id"] == match_id]
        assert after[0]["opponent_label"] == "Rogue"


# --- the MTGO deck pick ------------------------------------------------------

DECK_FIXTURES = Path(__file__).parent / "fixtures"
MTGO_PICK_A = "f2244feb-54e1-48ec-b3c5-711b20844adf"
# A second MTGO match, made by swapping the fixture's GUID for another of the
# same length, so the length-prefixed strings around it stay valid.
MTGO_PICK_B = "0a1b2c3d-1111-4222-8333-444455556666"
MTGO_PICK_B_FILE = f"Match_GameLog_{MTGO_PICK_B}.dat"
# The cards the user (Player1) plays in the fixture that Arena has, per
# `mtgo_probe.py --force --lines 400` and tests/fixtures/mtgo_deck_cards.json:
# Plains, Cavern of Souls, Voice of Victory, Sacred Foundry, Sunbillow Verge,
# Inspiring Vantage and Multiversal Passage. All seven are in the sample deck.
# The opponent plays an Island, which is in the adventure deck only, so a deck
# score that counted their seat would put the adventure deck above zero.
MTGO_PICK_SELF_CARDS = 7


@pytest.fixture
def mtgo_pick_db(tmp_path, monkeypatch):
    """The Arena fixture's two matches, two MTGO matches, and the three MTGO
    deck fixtures, projected. Returns the database path."""
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    db_path = tmp_path / "pick.db"
    conn = open_database(db_path)
    conn.executemany(
        "INSERT INTO cards (grp_id, name, type_line) VALUES (:grp_id, :name, :type_line)",
        json.loads((DECK_FIXTURES / "mtgo_deck_cards.json").read_text(encoding="utf-8")),
    )
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    second = MTGO_FIXTURE_BYTES.replace(MTGO_PICK_A.encode(), MTGO_PICK_B.encode())
    assert second != MTGO_FIXTURE_BYTES
    _insert_mtgo_row(conn, data=MTGO_FIXTURE_BYTES, logged_at="2099-01-01T00:00:00")
    _insert_mtgo_row(
        conn, data=second, logged_at="2099-01-02T00:00:00", source_file=MTGO_PICK_B_FILE
    )
    conn.commit()
    decks = tmp_path / "decks"
    decks.mkdir()
    for name, minute in (("Sample", 0), ("Faced", 1), ("Adventure", 2)):
        source = {"Sample": "sample", "Faced": "double_faced", "Adventure": "adventure"}[name]
        shutil.copy(DECK_FIXTURES / f"mtgo_deck_{source}.dek", decks / f"{name}.dek")
        stamp = 1_790_000_000 + 60 * minute
        os.utime(decks / f"{name}.dek", (stamp, stamp))
    ingest_deck_dir(conn, decks)
    project(conn)
    conn.close()
    return db_path


@pytest.fixture
def mtgo_pick_client(mtgo_pick_db, make_client):
    with make_client(create_app(mtgo_pick_db)) as c:
        yield c


def _pick_decks(client, match_id=MTGO_PICK_A) -> dict[str, str]:
    """``{deck name: deck_id}`` from the candidates route."""
    body = client.get(f"/api/matches/{match_id}/mtgo-pick/candidates").json()
    return {c["name"]: c["deck_id"] for c in body["candidates"]}


def test_candidates_rank_by_the_cards_the_user_played(mtgo_pick_client):
    body = mtgo_pick_client.get(f"/api/matches/{MTGO_PICK_A}/mtgo-pick/candidates").json()
    assert body["cards_seen"] == MTGO_PICK_SELF_CARDS
    assert [(c["name"], c["cards_matched"]) for c in body["candidates"]] == [
        ("Sample", MTGO_PICK_SELF_CARDS),
        ("Adventure", 0),  # newer than Faced, so first among the zeros
        ("Faced", 0),
    ]
    assert body["current"] is None
    assert all(c["format_prefill"] is None for c in body["candidates"])


def test_candidates_carry_a_few_card_names_spells_first(mtgo_pick_client):
    """Read off the fixtures, not the route. Order is (front face is a land,
    not played in this match, -maindeck copies, name). Sample: Voice of
    Victory is its one played spell, so it leads; the 4-copy spells follow by
    name (Burst Lightning, Clarion Conqueror, Magmatic Hellkite, Momo), ahead
    of every land and of Plains, which is a basic and never listed. Adventure
    matches nothing, so its 4-copy spells come first by name.

    Faced is the deck that pins the front-face rule and the zero-copy
    sideboard rule. Its maindeck 4-ofs include spell//land double-faced cards
    (Suppression Ray, Sink into Stupor, Hydroelectric Specimen, Sea Gate
    Restoration, Jwari Disruption), spells by their front faces, so they sit
    among Goblin Charbelcher, Preordain, Tameshi and Whir of Invention and
    the first five by name are Goblin Charbelcher, Hydroelectric Specimen,
    Jwari Disruption, Preordain and Sea Gate Restoration. Read as lands they
    would drop out of those five. Consign to Memory is a sideboard 4-of: with
    its copies counted it would lead the list by name, so its absence shows
    a sideboard-only card ranks as zero copies."""
    body = mtgo_pick_client.get(f"/api/matches/{MTGO_PICK_A}/mtgo-pick/candidates").json()
    names = {c["name"]: c["card_names"] for c in body["candidates"]}
    assert names["Sample"] == [
        "Voice of Victory",
        "Burst Lightning",
        "Clarion Conqueror",
        "Magmatic Hellkite",
        "Momo, Friendly Flier",
    ]
    assert names["Adventure"] == [
        "Eddymurk Crab",
        "Hearth Elemental // Stoke Genius",
        "Opt",
        "Prismari Charm",
        "Sleight of Hand",
    ]
    assert names["Faced"] == [
        "Goblin Charbelcher",
        "Hydroelectric Specimen // Hydroelectric Laboratory",
        "Jwari Disruption // Jwari Ruins",
        "Preordain",
        "Sea Gate Restoration // Sea Gate, Reborn",
    ]
    assert all(len(c["card_names"]) <= 5 for c in body["candidates"])


def test_a_basic_land_is_never_a_candidate_card_name(mtgo_pick_db, tmp_path, make_client):
    """Twenty Plains (one of the cards the user played) and four Smaug the
    Magnificent, CatIDs as in the sample export: Plains would be the next name
    after the one spell, and is left out."""
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "Plains Heavy.dek").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Deck xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        "  <NetDeckID>0</NetDeckID>\n"
        "  <PreconstructedDeckID>0</PreconstructedDeckID>\n"
        '  <Cards CatID="15758" Quantity="20" Sideboard="false" Name="Plains" />\n'
        '  <Cards CatID="154156" Quantity="4" Sideboard="false" Name="Smaug the Magnificent" />\n'
        "</Deck>\n",
        encoding="utf-8",
    )
    conn = open_database(mtgo_pick_db)
    ingest_deck_dir(conn, extra)
    project(conn)
    conn.close()
    with make_client(create_app(mtgo_pick_db)) as client:
        body = client.get(f"/api/matches/{MTGO_PICK_A}/mtgo-pick/candidates").json()
    by_name = {c["name"]: c for c in body["candidates"]}
    assert by_name["Plains Heavy"]["cards_matched"] == 1  # Plains: the deck does hold it
    assert by_name["Plains Heavy"]["card_names"] == ["Smaug the Magnificent"]


# Six CatIds chosen from test_mtgo_decks_projector.py's _DEK_NAMES, all of them
# in tests/fixtures/mtgo_grouping_deck.xml. Every other CatId in the grouping
# stays out of mtgo_card, so the store deck keeps only these six cards.
_STORE_CAT_IDS = {
    61855: "Inspiring Vantage",
    144288: "Multiversal Passage",
    139189: "Sarkhan, Dragon Ascendant",
    142909: "Nova Hellkite",
    139489: "Maelstrom of the Spirit Dragon",
    144536: "Momo, Friendly Flier",
}


@pytest.fixture
def mtgo_store_db(mtgo_pick_db, tmp_path):
    """``mtgo_pick_db`` plus the fixture's deck-store grouping (FormatCode
    CSTANDARD), projected as a fourth MTGO deck."""
    conn = open_database(mtgo_pick_db)
    conn.executemany(
        "INSERT INTO mtgo_card (mtgo_id, name) VALUES (?, ?)", _STORE_CAT_IDS.items()
    )
    store = tmp_path / "store"
    store.mkdir()
    shutil.copy(DECK_FIXTURES / "mtgo_grouping_deck.xml", store / "grouping 0001.xml")
    stamp = 1_790_000_000 + 60 * 3
    os.utime(store / "grouping 0001.xml", (stamp, stamp))
    ingest_deck_dir(conn, store)
    project(conn)
    conn.close()
    return mtgo_pick_db


def test_a_store_decks_format_prefills_the_candidate(mtgo_store_db, make_client):
    """Only the grouping names a format; the three exports carry none. The
    grouping holds Inspiring Vantage and Multiversal Passage (both played in
    the fixture match) and, among what resolves, Momo, Nova Hellkite, Sarkhan
    and Maelstrom, 4 copies each: spells before lands, so Momo, Nova Hellkite
    and Sarkhan by name, then the two played lands (Maelstrom is cut)."""
    with make_client(create_app(mtgo_store_db)) as client:
        body = client.get(f"/api/matches/{MTGO_PICK_A}/mtgo-pick/candidates").json()
    by_name = {c["name"]: c for c in body["candidates"]}
    assert {n: c["format_prefill"] for n, c in by_name.items()} == {
        "Fixture Deck": "Standard",
        "Sample": None,
        "Adventure": None,
        "Faced": None,
    }
    store_deck = by_name["Fixture Deck"]
    assert store_deck["cards_matched"] == 2
    assert store_deck["card_names"] == [
        "Momo, Friendly Flier",
        "Nova Hellkite",
        "Sarkhan, Dragon Ascendant",
        "Inspiring Vantage",
        "Multiversal Passage",
    ]
    assert [c["name"] for c in body["candidates"]][:2] == ["Sample", "Fixture Deck"]


def test_a_store_decks_format_wins_over_the_last_confirmed_one(mtgo_store_db, make_client):
    """The user confirms the store deck as Modern on one match; the next
    match is still offered the store's Standard (D16 ahead of D10)."""
    with make_client(create_app(mtgo_store_db)) as client:
        deck = _pick_decks(client)["Fixture Deck"]
        response = client.put(
            f"/api/matches/{MTGO_PICK_A}/mtgo-pick", json={"deck_id": deck, "format": "Modern"}
        )
        assert response.status_code == 200
        assert response.json()["format"] == "Modern"
        body = client.get(f"/api/matches/{MTGO_PICK_B}/mtgo-pick/candidates").json()
    assert {c["name"]: c["format_prefill"] for c in body["candidates"]}["Fixture Deck"] == (
        "Standard"
    )


def test_candidates_leave_out_arena_decks(mtgo_pick_client):
    arena_deck = mtgo_pick_client.get(f"/api/matches/{MATCH_WIN}").json()["deck_id"]
    assert arena_deck is not None
    assert arena_deck not in _pick_decks(mtgo_pick_client).values()


def test_pick_answers_400_for_an_arena_match(mtgo_pick_client):
    deck = _pick_decks(mtgo_pick_client)["Sample"]
    url = f"/api/matches/{MATCH_WIN}/mtgo-pick"
    assert mtgo_pick_client.get(f"{url}/candidates").status_code == 400
    assert mtgo_pick_client.put(url, json={"deck_id": deck, "format": "Modern"}).status_code == 400


def test_pick_answers_404_for_no_such_match(mtgo_pick_client):
    assert mtgo_pick_client.get("/api/matches/nope/mtgo-pick/candidates").status_code == 404
    assert (
        mtgo_pick_client.put("/api/matches/nope/mtgo-pick", json={"format": "Modern"}).status_code
        == 404
    )


def test_pick_answers_400_for_an_unknown_deck_or_an_empty_body(mtgo_pick_client):
    url = f"/api/matches/{MTGO_PICK_A}/mtgo-pick"
    arena_deck = mtgo_pick_client.get(f"/api/matches/{MATCH_WIN}").json()["deck_id"]
    assert arena_deck is not None
    assert mtgo_pick_client.put(url, json={"deck_id": "nope"}).status_code == 400
    assert mtgo_pick_client.put(url, json={"deck_id": arena_deck}).status_code == 400
    assert mtgo_pick_client.put(url, json={}).status_code == 400
    assert mtgo_pick_client.put(url, json={"deck_id": None, "format": None}).status_code == 400
    # The seven formats are the whole list.
    deck = _pick_decks(mtgo_pick_client)["Sample"]
    response = mtgo_pick_client.put(url, json={"deck_id": deck, "format": "Commander"})
    assert response.status_code == 422
    # Nothing above wrote a row.
    needs = mtgo_pick_client.get("/api/mtgo/needs-pick").json()
    assert MTGO_PICK_A in [m["match_id"] for m in needs]


def test_a_pick_shows_in_v_match_deck_and_survives_a_rebuild(mtgo_pick_db, make_client):
    with make_client(create_app(mtgo_pick_db)) as client:
        deck = _pick_decks(client)["Sample"]
        response = client.put(
            f"/api/matches/{MTGO_PICK_A}/mtgo-pick", json={"deck_id": deck, "format": "Modern"}
        )
        assert response.status_code == 200
        assert response.json() == {"deck_id": deck, "format": "Modern", "deck_confirmed": True}

    conn = open_database(mtgo_pick_db)
    project(conn)
    row = conn.execute(
        "SELECT deck_id, format, deck_confirmed FROM v_match_deck WHERE match_id = ?",
        (MTGO_PICK_A,),
    ).fetchone()
    # matches.deck_id is what the projector wrote: still nothing.
    raw = conn.execute(
        "SELECT deck_id FROM matches WHERE match_id = ?", (MTGO_PICK_A,)
    ).fetchone()
    conn.close()
    assert tuple(row) == (deck, "Modern", 1)
    assert raw[0] is None

    with make_client(create_app(mtgo_pick_db)) as client:
        current = client.get(f"/api/matches/{MTGO_PICK_A}/mtgo-pick/candidates").json()["current"]
        assert current == {"deck_id": deck, "format": "Modern", "deck_confirmed": True}


def test_v_match_deck_for_matches_with_no_pick(mtgo_pick_db):
    """An Arena match is confirmed by its log and keeps its deck; an MTGO match
    without a pick has no deck and is not confirmed."""
    conn = open_database(mtgo_pick_db)
    rows = {
        r["match_id"]: tuple(r)[1:]
        for r in conn.execute("SELECT match_id, deck_id, format, deck_confirmed FROM v_match_deck")
    }
    arena_deck = conn.execute(
        "SELECT deck_id FROM matches WHERE match_id = ?", (MATCH_WIN,)
    ).fetchone()[0]
    conn.close()
    assert arena_deck is not None
    assert rows[MATCH_WIN] == (arena_deck, None, 1)
    assert rows[MTGO_PICK_A] == (None, None, 0)
    assert rows[MTGO_PICK_B] == (None, None, 0)


def test_a_format_can_be_confirmed_without_a_deck(mtgo_pick_client):
    url = f"/api/matches/{MTGO_PICK_A}/mtgo-pick"
    response = mtgo_pick_client.put(url, json={"format": "Pauper"})
    assert response.json() == {"deck_id": None, "format": "Pauper", "deck_confirmed": True}
    needs = [m["match_id"] for m in mtgo_pick_client.get("/api/mtgo/needs-pick").json()]
    assert needs == [MTGO_PICK_B]


def test_a_second_pick_replaces_the_first_whole(mtgo_pick_client):
    url = f"/api/matches/{MTGO_PICK_A}/mtgo-pick"
    deck = _pick_decks(mtgo_pick_client)["Sample"]
    mtgo_pick_client.put(url, json={"deck_id": deck, "format": "Modern"})
    body = mtgo_pick_client.put(url, json={"format": "Legacy"}).json()
    assert body == {"deck_id": None, "format": "Legacy", "deck_confirmed": True}


def test_the_needs_pick_queue_empties_as_picks_land(mtgo_pick_client):
    queue = mtgo_pick_client.get("/api/mtgo/needs-pick").json()
    # Newest first: B was logged a day after A.
    assert [m["match_id"] for m in queue] == [MTGO_PICK_B, MTGO_PICK_A]
    assert queue[0]["opponent_name"] == "Player2000"
    assert queue[0]["result"] == "win"
    assert (queue[0]["games_won"], queue[0]["games_lost"]) == (2, 0)

    deck = _pick_decks(mtgo_pick_client)["Sample"]
    mtgo_pick_client.put(
        f"/api/matches/{MTGO_PICK_B}/mtgo-pick", json={"deck_id": deck, "format": "Modern"}
    )
    queue = mtgo_pick_client.get("/api/mtgo/needs-pick").json()
    assert [m["match_id"] for m in queue] == [MTGO_PICK_A]

    mtgo_pick_client.put(f"/api/matches/{MTGO_PICK_A}/mtgo-pick", json={"deck_id": deck})
    assert mtgo_pick_client.get("/api/mtgo/needs-pick").json() == []


def test_the_format_last_confirmed_for_a_deck_prefills_the_next_match(
    mtgo_pick_client, mtgo_pick_db
):
    """Two matches confirm the same deck in different formats. The PUTs land in
    the same second, so updated_at is set by hand: the match whose id sorts
    later is the newer one, and its format is the pre-fill."""
    deck = _pick_decks(mtgo_pick_client)["Sample"]
    older, newer = sorted((MTGO_PICK_A, MTGO_PICK_B))
    for match_id, fmt in ((older, "Pioneer"), (newer, "Legacy")):
        mtgo_pick_client.put(
            f"/api/matches/{match_id}/mtgo-pick", json={"deck_id": deck, "format": fmt}
        )
    conn = sqlite3.connect(mtgo_pick_db)
    conn.execute(
        "UPDATE mtgo_match_pick SET updated_at = '2099-02-01T00:00:00Z' WHERE match_id = ?",
        (older,),
    )
    conn.execute(
        "UPDATE mtgo_match_pick SET updated_at = '2099-02-02T00:00:00Z' WHERE match_id = ?",
        (newer,),
    )
    conn.commit()
    conn.close()

    # Pre-fill is per deck, not per match, so either match sees the newest.
    body = mtgo_pick_client.get(f"/api/matches/{older}/mtgo-pick/candidates").json()
    prefill = {c["name"]: c["format_prefill"] for c in body["candidates"]}
    assert prefill == {"Sample": "Legacy", "Adventure": None, "Faced": None}


def test_a_pick_row_for_an_arena_match_never_overrides_its_deck(mtgo_pick_db):
    conn = open_database(mtgo_pick_db)
    arena_deck = conn.execute(
        "SELECT deck_id FROM matches WHERE match_id = ?", (MATCH_WIN,)
    ).fetchone()[0]
    assert arena_deck is not None
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) VALUES (?, ?, 'Modern')",
        (MATCH_WIN, "some-other-deck"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT deck_id, format, deck_confirmed FROM v_match_deck WHERE match_id = ?",
        (MATCH_WIN,),
    ).fetchone()
    conn.close()
    assert tuple(row) == (arena_deck, None, 1)


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
        ("/api/matches/{match_id}/report/narrative", "POST"),
        ("/api/review/leaks/narrative", "POST"),
        ("/api/guide/{key}/narrative", "POST"),
        ("/api/coach/narrative", "POST"),
    }


def test_classification_is_idempotent(tmp_path):
    from sensei_top.archetypes import classify_matches

    db_path = tmp_path / "idem.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    _teach(db_path, grp_id=98589, name="Test Signature")

    conn = open_database(db_path)
    before = [dict(r) for r in conn.execute("SELECT * FROM opponent_archetype ORDER BY match_id")]
    project(conn)
    classify_matches(conn)
    after = [dict(r) for r in conn.execute("SELECT * FROM opponent_archetype ORDER BY match_id")]
    conn.close()
    assert [{k: v for k, v in r.items() if k != "classified_at"} for r in before] == \
           [{k: v for k, v in r.items() if k != "classified_at"} for r in after]


# --- brief coverage -----------------------------------------------------------


@pytest.fixture
def guide_key(client):
    return client.get("/api/guide/decks").json()[0]["key"]


def test_guide_coverage_200_shape(client, guide_key):
    body = client.get(f"/api/guide/{guide_key}/coverage").json()
    assert body["fmt"] == "Standard"
    assert isinstance(body["rows"], list)
    assert "matches_covered_numerator" in body
    assert "matches_covered_denominator" in body
    assert "field_covered" in body
    for row in body["rows"]:
        assert row["status"] in ("ok", "stale", "missing")


def test_guide_coverage_404_for_unknown_deck(client):
    resp = client.get("/api/guide/nope/coverage")
    assert resp.status_code == 404


def test_guide_brief_prompt_no_consensus_with_no_corpus_loaded(client, guide_key):
    """The fixture-backed client has no metagame corpus at all, so any
    archetype key asked about here has no field consensus to anchor a
    brief to -- the ordinary 'not yet' outcome, not a server error."""
    resp = client.get(f"/api/guide/{guide_key}/briefs/some_archetype/prompt")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_consensus"
    assert body["archetype_key"] == "some_archetype"
    assert body["prompt"] is None


def test_guide_brief_prompt_404_for_unknown_deck(client):
    resp = client.get("/api/guide/nope/briefs/some_archetype/prompt")
    assert resp.status_code == 404


def test_guide_coverage_prompt_200_with_no_gaps_or_consensus(client, guide_key):
    """No metagame corpus means build_coverage names no archetypes at all
    (nothing faced resolves to a classified archetype_key in this fixture,
    and the field has no top archetypes to report), so there is nothing
    missing to prompt for."""
    resp = client.get(f"/api/guide/{guide_key}/coverage/prompt")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("nothing_missing", "no_consensus")
    assert body["included"] == []
    assert body["deferred"] == []


def test_guide_coverage_prompt_404_for_unknown_deck(client):
    resp = client.get("/api/guide/nope/coverage/prompt")
    assert resp.status_code == 404
