"""Tests for projector/mulligan.py's pending-offer replay.

Ground truth comes from tests/fixtures/mulligan_session.log — a real,
anonymized capture of exactly one mulligan-then-keep sequence (10 raw
events), carved from raw_events already sitting in a local database, the
same legitimate-carve precedent migrations/014_combat.sql's own comment
states for combat_session.log. Grp/instance ids below were read directly
from the fixture via fixture_peek.py, never by running this module and
copying its output (AGENTS.md rule 8):

  entry 4 (the first offer, gameStateId 2) — zone 31 (ownerSeatId 1, ours)
  holds objectInstanceIds [169, 168, 167, 166, 165, 164, 163], resolving via
  gameObjects to grpIds [102774, 98389, 98392, 102698, 95062, 91584, 102670]
  in that order. zone 35 (ownerSeatId 2, the opponent) carries its own 7
  ids with no matching gameObjects at all — hidden, as it always is.

  entry 7 (the second offer, after our own Mulligan, gameStateId 3) — zone
  31 now holds [289, 288, 287, 286, 285, 284, 283], resolving to grpIds
  [102774, 68738, 102774, 86835, 102698, 91584, 102578]. gameObjects in
  this same message also lists instanceId 46 (grpId 86836) at zoneId 31 —
  a stale leftover NOT present in zone 31's own objectInstanceIds. Filtering
  gameObjects by zoneId over-counts the hand: docs/arena-log.md, "The
  traps", trap 14. This suite pins it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector.mulligan import replay_pending_offer
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "mulligan_session.log"

FIRST_OFFER_GRP_IDS = (102774, 98389, 98392, 102698, 95062, 91584, 102670)
SECOND_OFFER_GRP_IDS = (102774, 68738, 102774, 86835, 102698, 91584, 102578)


@pytest.fixture
def payloads(tmp_path) -> list[str]:
    conn = open_database(tmp_path / "t.db")
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    rows = [r[0] for r in conn.execute("SELECT payload FROM raw_events ORDER BY id")]
    conn.close()
    return rows


def test_no_offer_before_the_deal(payloads):
    """The room opening and the deck/settings handshake (events 1-4: room
    state, ConnectResp+Full, our SetSettingsReq, its Resp) carry no pending
    mulligan at all."""
    assert replay_pending_offer(payloads[:4]) is None


def test_first_offer_resolves_our_hand_in_zone_order(payloads):
    offer = replay_pending_offer(payloads[:5])
    assert offer is not None
    assert offer.seat == 1
    assert offer.mulligan_count == 0
    assert tuple(c.grp_id for c in offer.cards) == FIRST_OFFER_GRP_IDS


def test_the_opponents_clearing_does_not_affect_our_pending_offer(payloads):
    """Event 6 only mentions seat 2 (whose pendingMessageType key is simply
    absent — Arena never logs the opponent's own decision, only its effect).
    players[] is itself a diff: our own offer from event 5 must still stand,
    not vanish because it wasn't restated."""
    offer = replay_pending_offer(payloads[:6])
    assert offer is not None
    assert offer.seat == 1
    assert tuple(c.grp_id for c in offer.cards) == FIRST_OFFER_GRP_IDS


def test_our_own_decision_clears_the_offer(payloads):
    """Event 7 is our own ClientToGREMessage (Mulligan). Nothing is pending
    again until the next offer arrives."""
    assert replay_pending_offer(payloads[:7]) is None


def test_stale_object_is_excluded_from_the_second_offer(payloads):
    """The regression this file exists for: event 8's gameObjects includes
    instanceId 46 (grpId 86836) tagged zoneId 31, but 46 is absent from
    zone 31's own objectInstanceIds — a leftover from earlier in the game.
    Filtering gameObjects by zoneId (rather than walking the zone's own id
    list) would report an 8-card hand containing a card that was never
    dealt. It must not."""
    offer = replay_pending_offer(payloads[:8])
    assert offer is not None
    assert offer.mulligan_count == 1
    assert len(offer.cards) == 7
    assert tuple(c.grp_id for c in offer.cards) == SECOND_OFFER_GRP_IDS
    assert 86836 not in (c.grp_id for c in offer.cards)


def test_our_second_decision_clears_the_offer_again(payloads):
    assert replay_pending_offer(payloads[:9]) is None


def test_nothing_pending_at_the_end_of_the_fixture(payloads):
    assert replay_pending_offer(payloads) is None


def test_card_types_carry_arenas_own_land_signal(payloads):
    """grpId 68738 (Steam Vents) is the one land in the second offer — its
    cardTypes must say so, since table/opening_hand.py trusts this signal
    over the cards table entirely for land identification."""
    offer = replay_pending_offer(payloads[:8])
    assert offer is not None
    steam_vents = next(c for c in offer.cards if c.grp_id == 68738)
    assert "CardType_Land" in steam_vents.card_types


def test_active_player_is_carried_from_turn_info(payloads):
    """turnInfo.activePlayer is present even before turnNumber exists (see
    docs/arena-log.md); this fixture's opponent (seat 2) is the active
    player, i.e. we are on the draw."""
    offer = replay_pending_offer(payloads[:5])
    assert offer is not None
    assert offer.active_player == 2
