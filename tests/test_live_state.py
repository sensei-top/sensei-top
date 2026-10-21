"""replay_live_state keeps one GameStateTracker per game.

Arena restarts annotation ids every game, so a tracker shared by a whole
match drops a later game's ZoneTransfer whose id an earlier game already
used. Expectations are counted from ``match_session.log`` itself (the
``AnnotationType_ZoneTransfer`` annotations of its two matches (2 and 3
games), one row per ``affectedIds`` entry, de-duplicated on annotation id
within a game), not read off the tracker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector import live_state
from sensei_top.projector.game_state import GameStateTracker
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
INTERMISSION_FIXTURE = Path(__file__).parent / "fixtures" / "intermission_session.log"

# Both matches of match_session.log, as raw_events id ranges (id = entry + 1:
# entries 5-16 and 19-33). Per game: how many transfer rows, and their
# categories in fixture order, counted from the ZoneTransfer annotations
# (one row per affectedIds entry, de-duplicated on annotation id within a
# game). Annotation ids reused across games, which one tracker per match
# would drop: 86 (entries 8 and 13) and 88 (entries 23 and 27).
_MATCHES = [
    (
        6,
        17,
        [
            ["CastSpell", "Put", "Put", "Resolve", "Draw", "Draw"],
            ["Put", "CastSpell", "Put", "Put", "Resolve", "Draw", "PlayLand", "Draw"],
        ],
    ),
    (
        20,
        34,
        [
            ["Put", "PlayLand", "Draw", "Put", "Put", "Resolve", "Draw"],
            ["PlayLand", "Draw", "Put", "Put", "Resolve", "Draw"],
            ["Put", "PlayLand", "Draw", "PlayLand", "Draw"],
        ],
    ),
]


@pytest.mark.parametrize(("low", "high", "games"), _MATCHES)
def test_each_game_of_a_match_gets_its_own_tracker(tmp_path, monkeypatch, low, high, games):
    built: list[GameStateTracker] = []

    class Spy(GameStateTracker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            built.append(self)

    monkeypatch.setattr(live_state, "GameStateTracker", Spy)

    conn = open_database(tmp_path / "f.db")
    try:
        ingest_file(conn, FIXTURE, locale_hint="mdy")
        conn.commit()
        payloads = [
            r["payload"]
            for r in conn.execute(
                "SELECT payload FROM raw_events WHERE id BETWEEN ? AND ? ORDER BY id",
                (low, high),
            )
        ]
    finally:
        conn.close()

    live_state.replay_live_state(payloads)

    assert [e.category for t in built for e in t.card_events] == [c for g in games for c in g]
    assert [[e.category for e in t.card_events] for t in built] == games


def test_a_new_game_starts_with_no_turn_of_the_last(tmp_path):
    """intermission_session.log entry 41 is game 2's opening state; its
    turnInfo holds only decisionPlayer, so no turn or active seat is known yet
    (the base carried game 1's last values over)."""
    conn = open_database(tmp_path / "i.db")
    try:
        ingest_file(conn, INTERMISSION_FIXTURE, locale_hint="mdy")
        conn.commit()
        payloads = [
            r["payload"]
            for r in conn.execute("SELECT payload FROM raw_events WHERE id <= 42 ORDER BY id")
        ]
    finally:
        conn.close()

    state = live_state.replay_live_state(payloads)

    assert state.turn_number is None
    assert state.active_seat is None
