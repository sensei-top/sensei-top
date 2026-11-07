"""``GET /api/guide/{key}/past-boarding/{archetype_key}`` — the break read's
past boarding (``table/intermission.py::past_boarding_against``) asked for
outside a break, on the projected fixture match.

Ground truth comes from tests/fixtures/intermission_session.log, read via
``fixture_peek.py``'s ``show`` (entries 39 and 43) and, for the two full
card lists that ``show`` truncates, by diffing the raw payloads of entries 2
and 39 as stored verbatim by ``ingest_file`` — never by running the route
and copying its answer (AGENTS.md rule 8):

  entry 2 (17:02:57) — ``connectResp.deckMessage``, the game-1 deck: 60
  main, 15 side.

  entry 39 (17:05:01) — ``ClientMessageType_SubmitDeckResp``, the game-2
  deck: 60 main, 15 side, the same 75 as game 1. Against game 1's main it
  brings in 87145 x2 and 96608 x4 and takes out 95758 x2 and 102793 x4 (the
  first six of its ``sideboardCards``, as ``show`` prints them).

  entry 43 (17:07:10) — ``MatchGameRoomStateType_MatchCompleted`` for match
  fd2d98d2-eac6-459a-8b44-cb1a4eb057dd, eventId ``Traditional_Ladder``:
  both games and the match won by team 1 (our seat 1's team),
  ``ResultReason_Concede`` each.

The opponent's deck is named by a pick (``opponent_deck_override``), the
user's own answer, so the match is found by archetype without the
classifier: the fixture carries no archetype definitions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sensei_top.api.app import create_app
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "intermission_session.log"
MATCH_ID = "fd2d98d2-eac6-459a-8b44-cb1a4eb057dd"
ARCHETYPE = "picked-aggro"


@pytest.fixture
def client(tmp_path, make_client):
    db_path = tmp_path / "pb.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, archetype_key) VALUES (?, ?, ?)",
        (MATCH_ID, "Picked Aggro", ARCHETYPE),
    )
    conn.commit()
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


def _deck_key(client) -> str:
    decks = client.get("/api/guide/decks").json()
    assert len(decks) == 1  # the fixture is one match with one deck
    return decks[0]["key"]


def test_past_boarding_reads_the_finished_match_outside_a_break(client):
    """No break, nothing excluded: the fixture's one finished match against
    the picked archetype, its game 2 diffed against game 1's maindeck. Every
    card swapped is in the deck's current 75 (one deck version, and game 2's
    75 equals game 1's)."""
    response = client.get(f"/api/guide/{_deck_key(client)}/past-boarding/{ARCHETYPE}")
    assert response.status_code == 200
    body = response.json()
    assert [p["match_id"] for p in body] == [MATCH_ID]
    games = body[0]["games"]
    assert [g["game_number"] for g in games] == [2]
    game = games[0]
    assert game["result"] == "win"
    assert game["result_reason"] == "ResultReason_Concede"
    assert sorted((c["grp_id"], c["n"]) for c in game["board_in"]) == [(87145, 2), (96608, 4)]
    assert sorted((c["grp_id"], c["n"]) for c in game["board_out"]) == [(95758, 2), (102793, 4)]
    assert all(c["in_current_75"] for c in game["board_in"] + game["board_out"])


def test_an_archetype_never_faced_is_an_empty_list(client):
    response = client.get(f"/api/guide/{_deck_key(client)}/past-boarding/never-faced")
    assert response.status_code == 200
    assert response.json() == []


def test_an_unknown_deck_key_is_404(client):
    """The route's own 404, not the catch-all one an unmatched path gets."""
    response = client.get(f"/api/guide/deck:nope/past-boarding/{ARCHETYPE}")
    assert response.status_code == 404
    assert "deck:nope" in response.json()["detail"]
