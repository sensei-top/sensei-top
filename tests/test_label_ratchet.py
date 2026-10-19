"""A handler that stops matching must fail a test, not quietly project less.

Arena can rename a label or a message type without notice (docs/arena-log.md).
When it does, the old string still ingests fine and the projector simply
handles nothing: no error, no warning, empty dashboards. ``Projector.handled``
counts the events each handler handled, and this test pins those counts
against every Arena fixture.

The table below was derived from the fixtures, never from the counter
(rule 8): ``fixture_peek.py index`` for the entries and their labels,
``fixture_peek.py grep --type`` to confirm which entries carry
``ConnectResp`` and ``QueuedGameStateMessage``. ``grep`` counts entries and one
entry carries several GRE messages, so the per-message counts come from a
scratch script that reads each entry's JSON through ``segment_lines`` and
counts, per message, those with a ``gameStateMessage`` or a
``connectResp.deckMessage``, under the message's ``type``. It uses no
projector code. ``mtgo_match_session.log`` is MTGO's binary game log, not an Arena
fixture, and is left out. A fixture absent from the table is a failure, so
a new Arena fixture must add its row.

When a fixture changes, re-derive its row the same way; do not paste the
counter's output. ``EventSetDeckV3`` is handled like ``DeckUpsertDeckV3`` but
no fixture carries it, so it is not ratcheted.

Keys are what routed the event to its handler: the payload key
(``authenticateResponse``, ``matchGameRoomStateChangedEvent``) or the label
(``DeckUpsertDeckV3``, ``RankGetCombinedRankInfo``, ``ClientToGremessage``
for a submitted deck). A GRE message routes on its ``gameStateMessage`` or
``connectResp.deckMessage``; its ``type`` is only the key it is counted under.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector import matches
from sensei_top.reader.ingest import ingest_file

FIXTURES = Path(__file__).parent / "fixtures"
GAME_STATE = "GREMessageType_GameStateMessage"
QUEUED = "GREMessageType_QueuedGameStateMessage"
CONNECT = "GREMessageType_ConnectResp"

EXPECTED: dict[str, dict[str, int]] = {
    "bo1_session.log": {
        "authenticateResponse": 1, "matchGameRoomStateChangedEvent": 2,
        CONNECT: 1, GAME_STATE: 4,
    },
    "client_header.log": {},
    "combat_session.log": {
        "authenticateResponse": 1, "matchGameRoomStateChangedEvent": 2,
        "DeckUpsertDeckV3": 1, GAME_STATE: 85,
    },
    "draft_session.log": {},
    "header_languages.log": {},
    "header_relaunch.log": {},
    "human_draft_session.log": {},
    "intermission_session.log": {
        "authenticateResponse": 1, "matchGameRoomStateChangedEvent": 2,
        "ClientToGremessage": 1, CONNECT: 1, GAME_STATE: 94,
    },
    "match_session.log": {
        "authenticateResponse": 2, "matchGameRoomStateChangedEvent": 4,
        "DeckUpsertDeckV3": 4, CONNECT: 2, GAME_STATE: 204, QUEUED: 3,
    },
    "mulligan_session.log": {
        "matchGameRoomStateChangedEvent": 1, CONNECT: 1, GAME_STATE: 5,
    },
    "rank_session.log": {"RankGetCombinedRankInfo": 1},
    "sample_player.log": {"matchGameRoomStateChangedEvent": 2, CONNECT: 1},
    "sideboard_session.log": {"ClientToGremessage": 1, GAME_STATE: 1},
    "undo_session.log": {
        "authenticateResponse": 1, "matchGameRoomStateChangedEvent": 1,
        CONNECT: 1, GAME_STATE: 101, QUEUED: 2,
    },
}


def _handled(tmp_path: Path, name: str, monkeypatch) -> dict[str, int]:
    conn = open_database(tmp_path / "r.db")
    ingest_file(conn, FIXTURES / name, locale_hint="mdy")
    made: list[matches.Projector] = []
    real = matches.Projector

    class Recording(real):
        def __init__(self) -> None:
            super().__init__()
            made.append(self)

    monkeypatch.setattr(matches, "Projector", Recording)
    matches.project(conn)
    conn.close()
    (projector,) = made
    return dict(projector.handled)


def test_every_arena_fixture_is_in_the_table():
    on_disk = {
        p.name for p in FIXTURES.glob("*.log") if not p.name.startswith("mtgo_")
    }
    assert on_disk == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_handler_handles_what_the_fixture_holds(tmp_path, monkeypatch, name):
    expected = EXPECTED[name]
    assert all(count > 0 for count in expected.values())
    assert _handled(tmp_path, name, monkeypatch) == expected
