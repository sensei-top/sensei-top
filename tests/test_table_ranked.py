"""Tests for the ranked-play rule (table/ranked.py) and the event id the live
replay hands it (projector/live_state.py).

The event ids below were read off a real database's ``matches.event_id``
(2026-10-01), which ``projector/matches.py`` fills from the same
``reservedPlayers[].eventId`` path the replay reads. The fixture-backed
cases read ``mulligan_session.log`` entry 0, whose two reserved players both
carry ``"eventId": "Traditional_Ladder"`` (read with fixture_peek.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector.live_state import replay_live_state
from sensei_top.reader.ingest import ingest_file
from sensei_top.table.live import build_live_state
from sensei_top.table.ranked import is_ranked

FIXTURE = Path(__file__).parent / "fixtures" / "mulligan_session.log"


# --- the rule -----------------------------------------------------------


@pytest.mark.parametrize(
    "event_id",
    [
        "Traditional_Ladder",
        "Traditional_Cons_Event_2026",
        "PremierDraft_FRA_20260929",
        "PickTwoDraft_FRA_20260929",
        "QuickDraft_SOS_20260831",
        "CubeDraft_Powered_20260908",
    ],
)
def test_ladder_and_events_are_ranked(event_id):
    """The ladder and every event with a prize structure: advice stays off."""
    assert is_ranked(event_id)


@pytest.mark.parametrize(
    "event_id", ["Play", "Constructed_BestOf3", "AIBotMatch", "DualColorPrecons"]
)
def test_the_casual_queues_are_unranked(event_id):
    assert not is_ranked(event_id)


def test_direct_challenge_counts_as_ranked():
    """Community tournaments on Arena are played by Direct Challenge, and the
    log cannot tell one from a friendly game — the user chose the
    conservative reading."""
    assert is_ranked("DirectGame")


@pytest.mark.parametrize("event_id", [None, "", "SomeQueueArenaAddsLater"])
def test_an_unknown_or_missing_queue_counts_as_ranked(event_id):
    """Rule 4: unknown is never read as the permissive answer. A real
    database holds two Arena matches with no event id, and every MTGO match
    has none."""
    assert is_ranked(event_id)


# --- the event id, from the live replay ---------------------------------


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "ranked.db")
    ingest_file(c, FIXTURE, locale_hint="mdy")
    yield c
    c.close()


def test_the_replay_reads_the_queue_from_the_room_start_event(conn):
    """No project() call: the rule has to hold at the first mulligan, before
    any matches row exists, so the event id comes from the replay itself."""
    state = build_live_state(conn)
    assert state is not None
    assert state.event_id == "Traditional_Ladder"
    assert is_ranked(state.event_id)


def test_a_room_start_event_without_an_event_id_leaves_the_queue_unknown():
    """Synthetic: a room-start event whose reserved players name no queue.
    The replay reports None rather than a guess, and None is ranked."""
    payload = (
        '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {"gameRoomConfig": {'
        '"matchId": "m1", "reservedPlayers": [{"systemSeatId": 1}]}, '
        '"stateType": "MatchGameRoomStateType_Playing"}}}'
    )
    state = replay_live_state([payload])
    assert state.event_id is None
    assert is_ranked(state.event_id)
