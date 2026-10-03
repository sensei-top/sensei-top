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

import json

import pytest

from sensei_top.db import open_database
from sensei_top.metagame import topdeck


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

    result = topdeck.refresh_topdeck(conn)
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
    monkeypatch.setattr(
        topdeck, "list_tournaments", lambda **kwargs: [_TOURNAMENT]
    )

    result = topdeck.refresh_topdeck(conn, force=True)
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
        api_key="k-123", start=date(2026, 9, 1), end=date(2026, 9, 2)
    )
    assert result == []
    assert seen == {
        "url": "https://topdeck.gg/api/v2/tournaments",
        "method": "POST",
        "auth": "k-123",
    }


def _named(tid: str, name: str) -> dict:
    return {**_TOURNAMENT, "TID": tid, "tournamentName": name}


def test_non_constructed_names_are_skipped_and_std_is_kept(monkeypatch, conn):
    monkeypatch.setenv("TOPDECK_API_KEY", "test-key")
    monkeypatch.setattr(
        topdeck,
        "list_tournaments",
        lambda **kw: [
            _named("t1", "Commander night"),
            _named("t2", "Pre release"),
            _named("t3", "Torneo magic std"),
        ],
    )
    result = topdeck.refresh_topdeck(conn, force=True)
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
    topdeck.refresh_topdeck(conn, force=True)
    for table in ("meta_event", "meta_deck", "meta_round_match", "meta_deck_archetype"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
