"""Tests for table/live.py's build_library_remaining: the primary panel
once a game is under way — this deck's maindeck minus every copy of our
own cards a live replay has shown outside the library this game.

The replay itself (self/opponent seat resolution, hand/library counts,
the mulligan offer) is exercised end-to-end by test_projector_mulligan.py
and test_table_opening_hand.py against real fixture captures; this file
covers only the subtraction arithmetic build_library_remaining adds on top,
with a synthetic LiveState (the same "edge cases the real log can't easily
show" style test_table_keep.py and test_table_opening_hand.py already use
for pure arithmetic, as opposed to log parsing).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

import pytest

from sensei_top.db import open_database
from sensei_top.projector.game_state import ZoneCard
from sensei_top.projector.live_state import LiveState
from sensei_top.table.live import (
    _DECK_MESSAGE_LOOKBACK,
    build_library_remaining,
    find_anchor,
    replay_from_anchor,
)

ISLAND_GRP = 1
BEAR_GRP = 2
REMOVAL_GRP = 3
COUNTER_GRP = 4
VANILLA_GRP = 5
UNKNOWN_GRP = 6


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_deck(conn, deck_id, maindeck):
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json) VALUES (?, 'Test Deck', ?)",
        (deck_id, json.dumps({"maindeck": maindeck})),
    )


def _zone_card(zone, seat, instance_id, grp_id):
    return ZoneCard(
        zone=zone, seat=seat, idx=0, instance_id=instance_id, grp_id=grp_id,
        card_types=None, drawn_on_turn=None,
    )


def _state(*, self_seat, zone_cards):
    return LiveState(
        self_seat=self_seat, opponent_seat=2 if self_seat == 1 else 1,
        turn_number=3, active_seat=self_seat,
        life={}, hand={}, library={}, graveyard={}, open_mana={}, other_mana_sources={},
        zone_cards=tuple(zone_cards), offer=None,
    )


def test_seen_copies_are_subtracted_once_per_instance(conn):
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line) VALUES "
        "(?, 'Test Island', NULL, 'Basic Land — Island')", (ISLAND_GRP,)
    )
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line) VALUES "
        "(?, 'Cheap Bear', '{1}{G}', 'Creature — Bear')", (BEAR_GRP,)
    )
    _insert_deck(conn, "d1", [ISLAND_GRP] * 17 + [BEAR_GRP] * 4)
    conn.commit()

    # One Island drawn to hand, one Bear cast and later killed (battlefield
    # then graveyard) — the same instance_id in two zones must count once,
    # not twice, matching hand_read.py's own dedup discipline.
    state = _state(
        self_seat=1,
        zone_cards=[
            _zone_card("hand", 1, 501, ISLAND_GRP),
            _zone_card("graveyard", 1, 502, BEAR_GRP),
        ],
    )

    cards = build_library_remaining(conn, "d1", state)
    by_grp = {c.grp_id: c for c in cards}
    assert by_grp[ISLAND_GRP].left == 16
    assert by_grp[ISLAND_GRP].quantity == 17
    assert by_grp[ISLAND_GRP].is_land is True
    assert by_grp[ISLAND_GRP].mana_value is None  # lands never get a mana value
    assert by_grp[BEAR_GRP].left == 3
    assert by_grp[BEAR_GRP].quantity == 4


def test_a_fully_seen_card_drops_out_rather_than_showing_zero(conn):
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line) VALUES "
        "(?, 'Cheap Bear', '{1}{G}', 'Creature — Bear')", (BEAR_GRP,)
    )
    _insert_deck(conn, "d1", [BEAR_GRP])
    conn.commit()

    state = _state(self_seat=1, zone_cards=[_zone_card("graveyard", 1, 1, BEAR_GRP)])

    cards = build_library_remaining(conn, "d1", state)
    assert cards == ()


def test_no_deck_or_no_live_state_yields_nothing(conn):
    _insert_deck(conn, "d1", [BEAR_GRP])
    conn.commit()
    assert build_library_remaining(conn, None, _state(self_seat=1, zone_cards=[])) == ()
    assert build_library_remaining(conn, "d1", None) == ()


def test_is_interaction_classifies_from_oracle_text(conn):
    # Expectations come straight from effects.py's own documented patterns
    # (_SPOT_REMOVAL_RE, _COUNTERSPELL_RE), not from running the classifier
    # and copying its output (AGENTS.md non-negotiable #8).
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) VALUES "
        "(?, 'Test Island', NULL, 'Basic Land — Island', NULL)", (ISLAND_GRP,)
    )
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) VALUES "
        "(?, 'Doom Blade Clone', '{1}{B}', 'Instant', 'Destroy target creature.')",
        (REMOVAL_GRP,),
    )
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) VALUES "
        "(?, 'Counter Clone', '{1}{U}', 'Instant', 'Counter target spell.')",
        (COUNTER_GRP,),
    )
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) VALUES "
        "(?, 'Plain Bear', '{1}{G}', 'Creature — Bear', 'Trample')", (VANILLA_GRP,)
    )
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) VALUES "
        "(?, 'No Text Yet', '{2}{R}', 'Creature — Elemental', NULL)", (UNKNOWN_GRP,)
    )
    _insert_deck(
        conn,
        "d1",
        [ISLAND_GRP] * 2 + [REMOVAL_GRP] + [COUNTER_GRP] + [VANILLA_GRP] + [UNKNOWN_GRP],
    )
    conn.commit()

    cards = build_library_remaining(conn, "d1", _state(self_seat=1, zone_cards=[]))
    by_grp = {c.grp_id: c for c in cards}

    assert by_grp[ISLAND_GRP].is_interaction is False  # a land, never asked to classify
    assert by_grp[REMOVAL_GRP].is_interaction is True  # spot_removal
    assert by_grp[COUNTER_GRP].is_interaction is True  # counterspell
    assert by_grp[VANILLA_GRP].is_interaction is False  # text present, matched nothing
    assert by_grp[UNKNOWN_GRP].is_interaction is None  # no oracle_text — unknown, not False


# --- MTGO rows must never enter an Arena replay ------------------------

_ROOM_PAYLOAD = (
    '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {'
    '"gameRoomConfig": {"matchId": "m1"}, '
    '"stateType": "MatchGameRoomStateType_Playing"}}}'
)


def _gsm_row(digest: str, gsm: dict, *, source: str | None = None) -> tuple:
    payload = json.dumps({"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": gsm}]}})
    if source is None:
        return (
            "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
            "VALUES (?, 'Player.log', 'event', 'GameStateMessage', ?)",
            (digest, payload),
        )
    return (
        "INSERT INTO raw_events (digest, source_file, kind, label, payload, source) "
        "VALUES (?, 'Match_GameLog_x.dat', 'event', 'GameStateMessage', ?, ?)",
        (digest, payload, source),
    )


def test_mtgo_rows_after_the_arena_anchor_are_excluded_from_replay(conn):
    """table/live.py's replay_from_anchor query is ``... AND source =
    'arena'`` deliberately (see its own comment): find_anchor's label
    predicate already excludes MTGO rows (MTGO never writes
    MatchGameRoomStateChangedEvent) so this is the one thing standing
    between an interleaved MTGO row and a real Arena replay. Proven here
    with a *well-formed* gameStateMessage payload under source='mtgo' that
    sets a life total no genuine Arena row in this test ever sets — if the
    SQL filter were missing, this would leak into the replay; it isn't a
    decode-failure accident (replay_live_state's orjson.loads would parse
    this payload without error)."""
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES ('room', 'Player.log', 'event', 'MatchGameRoomStateChangedEvent', ?)",
        (_ROOM_PAYLOAD,),
    )
    conn.execute(
        *_gsm_row(
            "arena-state",
            {
                "type": "GameStateType_Diff",
                "gameStateId": 2,
                "players": [
                    {"systemSeatNumber": 1, "lifeTotal": 20},
                    {"systemSeatNumber": 2, "lifeTotal": 20},
                ],
            },
        )
    )
    # An MTGO row landing after the anchor, indistinguishable from a real
    # Arena gameStateMessage except for its own `source` column.
    conn.execute(
        *_gsm_row(
            "mtgo-imposter",
            {
                "type": "GameStateType_Diff",
                "gameStateId": 3,
                "players": [{"systemSeatNumber": 1, "lifeTotal": 13}],
            },
            source="mtgo",
        )
    )
    conn.commit()

    anchor = find_anchor(conn)
    assert anchor is not None
    state = replay_from_anchor(conn, anchor)
    assert state.life.get(1) == 20


# --- deck_maindeck / deck_id, from the same replay ----------------------


def _connect_resp_payload(deck_cards, sideboard_cards=()):
    return json.dumps(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_ConnectResp",
                        "connectResp": {
                            "deckMessage": {
                                "deckCards": list(deck_cards),
                                "sideboardCards": list(sideboard_cards),
                            }
                        },
                    }
                ]
            }
        }
    )


def _expected_deck_id(maindeck) -> str:
    """Hand-worked against ``deck_identity``'s own documented formula (a
    SHA-256 over ``json.dumps(sorted(Counter(...).items()), separators=(",",
    ":"))``) rather than importing and calling it — an independent
    re-derivation of the same spec, not a run-the-code-and-copy-the-output
    shortcut (AGENTS.md non-negotiable #8)."""
    counts = Counter(maindeck)
    canonical = json.dumps(sorted(counts.items()), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_deck_maindeck_resolves_from_a_connectresp_before_the_anchor(conn):
    """The dominant real shape this was built for: a connectResp landing one
    row *before* the room-opening anchor (measured read-only against a real
    database — see table/live.py's own _DECK_MESSAGE_LOOKBACK comment: 73 of
    288 matches had their nearest connectResp at anchor-1). replay_from_anchor's
    forward window alone (id >= anchor) would never see this row; the
    pre-anchor lookback is what resolves it."""
    maindeck = [1, 1, 2]
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES ('connect', 'Player.log', 'event', 'GreToClientEvent', ?)",
        (_connect_resp_payload(maindeck),),
    )
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES ('room', 'Player.log', 'event', 'MatchGameRoomStateChangedEvent', ?)",
        (_ROOM_PAYLOAD,),
    )
    conn.commit()

    anchor = find_anchor(conn)
    assert anchor is not None
    state = replay_from_anchor(conn, anchor)
    assert state.deck_maindeck == (1, 1, 2)
    assert state.deck_id == _expected_deck_id(maindeck)


def test_deck_maindeck_resolves_from_a_connectresp_after_the_anchor(conn):
    """The other real shape (215 of 288 matches): connectResp landing inside
    the main forward window itself, no lookback needed."""
    maindeck = [7] * 60
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES ('room', 'Player.log', 'event', 'MatchGameRoomStateChangedEvent', ?)",
        (_ROOM_PAYLOAD,),
    )
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES ('connect', 'Player.log', 'event', 'GreToClientEvent', ?)",
        (_connect_resp_payload(maindeck),),
    )
    conn.commit()

    anchor = find_anchor(conn)
    assert anchor is not None
    state = replay_from_anchor(conn, anchor)
    assert state.deck_maindeck == tuple(maindeck)
    assert state.deck_id == _expected_deck_id(maindeck)


def test_deck_maindeck_is_none_with_no_connectresp_anywhere(conn):
    """Rule 4: no connectResp in either window means an honest None, never a
    guess pulled from some other row."""
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
        "VALUES ('room', 'Player.log', 'event', 'MatchGameRoomStateChangedEvent', ?)",
        (_ROOM_PAYLOAD,),
    )
    conn.commit()

    anchor = find_anchor(conn)
    assert anchor is not None
    state = replay_from_anchor(conn, anchor)
    assert state.deck_maindeck is None
    assert state.deck_id is None


def test_deck_maindeck_lookback_reaches_exactly_the_configured_bound(conn):
    """The pre-anchor lookback is bounded, not unbounded: table/live.py's own
    query is ``id >= anchor - _DECK_MESSAGE_LOOKBACK``, so a connectResp
    exactly that many rows back is the farthest one still found, and one row
    farther is missed — an honest None past the measured margin, never a
    wider guess than what step 1 actually measured."""
    maindeck = [3, 3, 3]

    def _build(gap_rows: int) -> int:
        conn.execute("DELETE FROM raw_events")
        conn.execute(
            "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
            "VALUES ('connect', 'Player.log', 'event', 'GreToClientEvent', ?)",
            (_connect_resp_payload(maindeck),),
        )
        if gap_rows:
            conn.executemany(
                "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
                "VALUES (?, 'Player.log', 'event', 'Filler', '{}')",
                [(f"filler-{i}",) for i in range(gap_rows)],
            )
        conn.execute(
            "INSERT INTO raw_events (digest, source_file, kind, label, payload) "
            "VALUES ('room', 'Player.log', 'event', 'MatchGameRoomStateChangedEvent', ?)",
            (_ROOM_PAYLOAD,),
        )
        conn.commit()
        anchor = find_anchor(conn)
        assert anchor is not None
        return anchor

    # gap_rows filler rows between connect and room put the room id at
    # connect_id + gap_rows + 1, so connect_id == anchor - (gap_rows + 1).
    # At gap_rows = _DECK_MESSAGE_LOOKBACK - 1, connect_id == anchor -
    # _DECK_MESSAGE_LOOKBACK exactly — the query's own inclusive >= bound.
    anchor = _build(_DECK_MESSAGE_LOOKBACK - 1)
    assert replay_from_anchor(conn, anchor).deck_maindeck == (3, 3, 3)

    # One row farther back (gap_rows = _DECK_MESSAGE_LOOKBACK) puts
    # connect_id one past the bound — excluded.
    anchor = _build(_DECK_MESSAGE_LOOKBACK)
    assert replay_from_anchor(conn, anchor).deck_maindeck is None
