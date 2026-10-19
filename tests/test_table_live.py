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
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector.game_state import ZoneCard
from sensei_top.projector.live_state import LiveState, MulliganOffer, replay_live_state
from sensei_top.reader.ingest import ingest_file
from sensei_top.table.keep import build_keep_guide
from sensei_top.table.live import (
    _DECK_MESSAGE_LOOKBACK,
    build_library_remaining,
    find_anchor,
    replay_from_anchor,
)
from sensei_top.table.opening_hand import build_opening_hand_read

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


def test_a_fully_seen_card_stays_at_zero(conn):
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line) VALUES "
        "(?, 'Cheap Bear', '{1}{G}', 'Creature — Bear')", (BEAR_GRP,)
    )
    _insert_deck(conn, "d1", [BEAR_GRP])
    conn.commit()

    state = _state(self_seat=1, zone_cards=[_zone_card("graveyard", 1, 1, BEAR_GRP)])

    cards = build_library_remaining(conn, "d1", state)
    assert [(c.grp_id, c.quantity, c.left) for c in cards] == [(BEAR_GRP, 1, 0)]


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


# --- the boarded deck, from a SubmitDeckResp -----------------------------

INTERMISSION_FIXTURE = Path(__file__).parent / "fixtures" / "intermission_session.log"

# fixture_peek.py entry 39 of intermission_session.log (ClientToGremessage,
# ClientMessageType_SubmitDeckResp): submitDeckResp.deck.deckCards, in file
# order, 60 cards.
_BOARDED_DECK = (
    95638, 95638, 95638, 95638, 68735, 68735, 68735, 68735, 95549, 95549,
    95549, 87145, 87145, 95066, 95066, 95066, 95066, 96722, 96722, 96722,
    96722, 97998, 97998, 97998, 97998, 102474, 102474, 103489, 103489, 103489,
    103489, 96608, 96608, 96608, 96608, 95788, 95788, 95788, 95788, 75864,
    75864, 75864, 75864, 95631, 95631, 95631, 97303, 97303, 97303, 97303,
    70501, 70504, 95520, 95520, 95520, 95520, 87435, 87435, 90479, 90479,
)


def _fixture_payloads(tmp_path, through_entry: int) -> list[str]:
    c = open_database(tmp_path / "f.db")
    try:
        ingest_file(c, INTERMISSION_FIXTURE, locale_hint="mdy")
        c.commit()
        # raw_events.id is the 0-based entry index plus one on an empty
        # table (tests/test_intermission.py::_payloads_through).
        rows = c.execute(
            "SELECT payload FROM raw_events WHERE id <= ? ORDER BY id",
            (through_entry + 1,),
        ).fetchall()
        return [r["payload"] for r in rows]
    finally:
        c.close()


# fixture_peek.py entry 2 of intermission_session.log (the game-1 connectResp):
# connectResp.deckMessage.deckCards, in file order, 60 cards.
_GAME_ONE_DECK = (
    95638, 95638, 95638, 95638, 68735, 68735, 68735, 68735, 95549, 95549,
    95549, 95758, 95758, 95066, 95066, 95066, 95066, 96722, 96722, 96722,
    96722, 97998, 97998, 97998, 97998, 102474, 102474, 103489, 103489, 103489,
    103489, 102793, 102793, 102793, 102793, 95788, 95788, 95788, 95788, 75864,
    75864, 75864, 75864, 95631, 95631, 95631, 97303, 97303, 97303, 97303,
    70501, 70504, 95520, 95520, 95520, 95520, 87435, 87435, 90479, 90479,
)


def _submit_deck_resp_payload(deck_cards) -> str:
    return json.dumps(
        {
            "payload": {
                "type": "ClientMessageType_SubmitDeckResp",
                "submitDeckResp": {"deck": {"deckCards": list(deck_cards)}},
            }
        }
    )


def test_deck_maindeck_is_the_boarded_list_once_a_submitdeckresp_was_seen(tmp_path):
    """Entry 39 is the SubmitDeckResp: before it the replay carries game 1's
    connectResp list, after it the boarded one. deck_id stays game 1's."""
    before = replay_live_state(_fixture_payloads(tmp_path, 38))
    after = replay_live_state(_fixture_payloads(tmp_path, 39))
    assert before.deck_maindeck == _GAME_ONE_DECK
    assert before.deck_maindeck != _BOARDED_DECK
    assert after.deck_maindeck == _BOARDED_DECK
    assert after.deck_id == _expected_deck_id(_GAME_ONE_DECK)


def test_deck_maindeck_is_the_latest_submitdeckresp_of_the_match(tmp_path):
    second = [7] * 60
    payloads = _fixture_payloads(tmp_path, 39)
    payloads.append(_submit_deck_resp_payload(second))
    state = replay_live_state(payloads)
    assert state.deck_maindeck == tuple(second)
    assert state.deck_id == _expected_deck_id(_GAME_ONE_DECK)


def test_a_submitdeckresp_before_the_anchor_is_not_read():
    """Before the anchor a SubmitDeckResp is an earlier match's: the lookback
    resolves the connectResp list after it."""
    state = replay_live_state(
        [],
        pre_anchor_payloads=[
            _submit_deck_resp_payload([8] * 60),
            _connect_resp_payload([1, 1, 2]),
        ],
    )
    assert state.deck_maindeck == (1, 1, 2)
    assert state.deck_id == _expected_deck_id([1, 1, 2])


def test_a_lookback_holding_only_a_submitdeckresp_resolves_no_deck():
    state = replay_live_state(
        [], pre_anchor_payloads=[_submit_deck_resp_payload([8] * 60)]
    )
    assert state.deck_maindeck is None
    assert state.deck_id is None


def test_a_connectresp_after_a_submitdeckresp_does_not_replace_the_boarded_list(tmp_path):
    payloads = _fixture_payloads(tmp_path, 39)
    payloads.append(_connect_resp_payload([9] * 60))
    assert replay_live_state(payloads).deck_maindeck == _BOARDED_DECK


# --- the live reads follow the boarded list ------------------------------
#
# In intermission_session.log the game-1 connectResp (entry 2) and the
# SubmitDeckResp (entry 39) differ in four card kinds: 95758 x2 and 102793
# x4 are only in game 1's list, 87145 x2 and 96608 x4 only in the boarded one.
# The three seeded `cards` rows are typed as basic lands only to serve as
# markers: they make the land count tell the two lists apart.


def _seed_game_one_deck(conn, state):
    """The decks row project() would write for game 1's list, under the
    replay's own deck_id, plus the card rows the checks below read."""
    _insert_deck(conn, state.deck_id, list(_GAME_ONE_DECK))
    for grp in (95758, 102793, 87145):
        conn.execute(
            "INSERT INTO cards (grp_id, name, mana_cost, type_line) "
            "VALUES (?, ?, NULL, 'Basic Land — Island')",
            (grp, f"Land {grp}"),
        )
    # One finished game under game 1's deck_id, mulliganed once, so the
    # mulligan record has a row to carry.
    conn.execute("INSERT INTO matches (match_id, deck_id) VALUES ('m1', ?)", (state.deck_id,))
    conn.execute(
        "INSERT INTO games (match_id, game_number, result, self_mulligans) "
        "VALUES ('m1', 1, 'win', 1)"
    )
    conn.commit()


def test_library_panel_counts_the_boarded_list_after_entry_39(tmp_path, conn):
    before = replay_live_state(_fixture_payloads(tmp_path, 38))
    after = replay_live_state(_fixture_payloads(tmp_path, 39))
    _seed_game_one_deck(conn, before)
    assert before.deck_boarded is False and after.deck_boarded is True

    first = {c.grp_id: c for c in build_library_remaining(conn, before.deck_id, before)}
    assert first[95758].quantity == 2
    assert 87145 not in first

    boarded = {c.grp_id: c for c in build_library_remaining(conn, after.deck_id, after)}
    assert boarded[87145].quantity == 2
    assert 95758 not in boarded and 102793 not in boarded


def test_keep_guide_counts_the_boarded_list_after_entry_39(tmp_path, conn):
    before = replay_live_state(_fixture_payloads(tmp_path, 38))
    after = replay_live_state(_fixture_payloads(tmp_path, 39))
    _seed_game_one_deck(conn, before)

    first = build_keep_guide(
        conn, before.deck_id, maindeck=before.deck_maindeck, boarded=before.deck_boarded
    )
    boarded = build_keep_guide(
        conn, after.deck_id, maindeck=after.deck_maindeck, boarded=after.deck_boarded
    )
    assert first is not None and boarded is not None
    assert first.land_count == 6  # 95758 x2 + 102793 x4
    assert boarded.land_count == 2  # 87145 x2
    assert boarded.deck_id == before.deck_id
    # the mulligan record stays game 1's: its one game is still there
    assert [(r.mulligans, r.games, r.wins) for r in boarded.mulligan_record] == [(1, 1, 1)]


def test_opening_hand_read_forwards_boarded_to_the_keep_guide(tmp_path, conn):
    before = replay_live_state(_fixture_payloads(tmp_path, 38))
    after = replay_live_state(_fixture_payloads(tmp_path, 39))
    _seed_game_one_deck(conn, before)
    offer = MulliganOffer(seat=1, cards=(), mulligan_count=0, active_player=None)

    first = build_opening_hand_read(
        conn, deck_id=before.deck_id, offer=offer,
        maindeck=before.deck_maindeck, boarded=before.deck_boarded,
    )
    boarded = build_opening_hand_read(
        conn, deck_id=after.deck_id, offer=offer,
        maindeck=after.deck_maindeck, boarded=after.deck_boarded,
    )
    assert first.keep_guide.land_count == 6
    assert boarded.keep_guide.land_count == 2
