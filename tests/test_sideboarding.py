"""Sideboard projection: migrations/024_game_decks.sql and
Projector._handle_submit_deck / the flush logic in _handle_gre_message
(projector/matches.py).

``tests/fixtures/sideboard_session.log`` is two real entries, reconstructed
in the exact shapes ``reader/segmenter.py``'s module docstring documents for
a "prefixed event with header" (shapes 1 and 3): a ClientMessageType_
SubmitDeckResp (a client-outbound message — carries no matchID or gameNumber
of its own, discovered by tracing raw_events ids 581->583 and 1897->1899 in
the user's own database during planning), and the GameStateMessage that
follows it, carrying gameInfo.matchID and gameInfo.gameNumber=2. Both
payloads are real field shapes read via fixture_peek.py against the user's
own Player.log on 2026-09-01; the grpId lists are a small real subset (not
the full 60+15) since the parsing rule under test — sort, store, attach to
whichever game starts next — does not depend on deck size. The match id is
a session GUID, not personal data, so nothing needed scrubbing (same
judgment test_combat.py already makes about its own match id).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "sideboard_session.log"
MATCH_ID = "d3d8e7a3-564b-4a13-ae59-bcc3e9734784"


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "s.db")
    ingest_file(c, FIXTURE, locale_hint="mdy")
    yield c
    c.close()


def test_a_submitted_deck_attaches_to_the_game_that_starts_next(conn):
    project(conn)
    rows = conn.execute("SELECT * FROM game_decks").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["match_id"] == MATCH_ID
    # The submission carries no game number of its own — this is the whole
    # point under test: it lands on game 2 because that is the game whose
    # GameStateMessage arrived next, not because anything counted games.
    assert row["game_number"] == 2
    assert json.loads(row["deck_cards_json"]) == [68738, 68738, 75876, 79089]
    assert json.loads(row["sideboard_cards_json"]) == [98392, 98475]


def test_a_rebuild_does_not_duplicate_game_decks(conn):
    """project() is always a full rebuild (AGENTS.md rule 3), and game_decks
    has a foreign key to matches — a wrong delete order would break the
    rebuild outright rather than merely duplicate rows, so this also guards
    against that FK-ordering regression."""
    project(conn)
    project(conn)
    assert conn.execute("SELECT COUNT(*) FROM game_decks").fetchone()[0] == 1
