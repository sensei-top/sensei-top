"""M2: synthetic unit tests for ``GameStateTracker`` merge and snapshot rules.

These build minimal ``gameStateMessage``-shaped dicts by hand — the fixture
tests in ``test_projector.py`` cover the real thing end to end. Field shapes
here match what's actually in ``tests/fixtures/match_session.log`` (verified
by direct inspection: ``annotations[].details[]`` entries carry
``valueInt32``, zone entries carry ``objectInstanceIds``, etc.).

The undo rollback is the exception: it is tested against
``tests/fixtures/undo_session.log``, a real game with a cancelled cast, at
the end of this file.
"""

import json
from pathlib import Path

from sensei_top.projector.game_state import GameStateTracker
from sensei_top.reader.segmenter import segment_lines

UNDO_FIXTURE = Path(__file__).parent / "fixtures" / "undo_session.log"


def _id_changed(orig_id: int, new_id: int) -> dict:
    return {
        "type": ["AnnotationType_ObjectIdChanged"],
        "details": [
            {"key": "orig_id", "valueInt32": [orig_id]},
            {"key": "new_id", "valueInt32": [new_id]},
        ],
    }


# --- object/zone merge -------------------------------------------------


def test_diff_merge_is_field_level():
    """A later diff entry updates only the fields it carries."""
    t = GameStateTracker()
    t.apply({"gameObjects": [{"instanceId": 1, "grpId": 100, "zoneId": 10}]})
    t.apply({"gameObjects": [{"instanceId": 1, "zoneId": 11}]})
    assert t.objects[1] == {"instanceId": 1, "grpId": 100, "zoneId": 11}


def test_zone_object_ids_replace_when_present_preserve_when_absent():
    t = GameStateTracker()
    t.apply(
        {"zones": [{"zoneId": 1, "type": "ZoneType_Hand", "ownerSeatId": 2,
                     "objectInstanceIds": [1, 2, 3]}]}
    )
    t.apply({"zones": [{"zoneId": 1, "visibility": "Visibility_Public"}]})
    assert t.zones[1]["objectInstanceIds"] == [1, 2, 3]  # untouched: key absent
    t.apply({"zones": [{"zoneId": 1, "objectInstanceIds": [4]}]})
    assert t.zones[1]["objectInstanceIds"] == [4]  # replaced, not appended


def test_deleted_instance_purges_object_and_zone_lists():
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 5, "controllerSeatId": 1}],
            "zones": [{"zoneId": 1, "type": "ZoneType_Battlefield",
                        "objectInstanceIds": [5, 6]}],
        }
    )
    t.apply({"diffDeletedInstanceIds": [5]})
    assert 5 not in t.objects
    assert t.zones[1]["objectInstanceIds"] == [6]


def test_object_id_changed_rekeys_without_duplicating_battlefield_counts():
    """A resolving spell gets a new instanceId; the old one must vanish."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 100, "controllerSeatId": 1,
                              "cardTypes": ["CardType_Creature"]}],
            "zones": [{"zoneId": 1, "type": "ZoneType_Battlefield",
                        "objectInstanceIds": [100]}],
        }
    )
    t.apply(
        {
            "gameObjects": [{"instanceId": 200, "controllerSeatId": 1,
                              "cardTypes": ["CardType_Creature"], "power": 3}],
            "zones": [{"zoneId": 1, "objectInstanceIds": [200]}],
            "annotations": [_id_changed(100, 200)],
        }
    )
    assert 100 not in t.objects
    assert t.objects[200]["power"] == 3
    assert t._battlefield_counts() == {1: 1}


def test_rekey_preserves_fields_already_set_at_new_id():
    """new_id's own gameObjects entry (post-transition truth) wins over stale
    orig_id fields, but fields new_id never had are still carried over."""
    t = GameStateTracker()
    t.apply({"gameObjects": [{"instanceId": 1, "grpId": 55, "zoneId": 10}]})
    t.apply(
        {
            "gameObjects": [{"instanceId": 2, "zoneId": 20}],
            "annotations": [_id_changed(1, 2)],
        }
    )
    assert t.objects[2] == {"instanceId": 2, "grpId": 55, "zoneId": 20}


def test_full_snapshot_resets_accumulated_state():
    t = GameStateTracker()
    t.apply(
        {"gameObjects": [{"instanceId": 1}],
         "zones": [{"zoneId": 1, "objectInstanceIds": [1]}]}
    )
    t.apply({"type": "GameStateType_Full", "gameObjects": [{"instanceId": 2}]})
    assert 1 not in t.objects
    assert t.zones == {}
    assert 2 in t.objects


# --- turn snapshot timing ------------------------------------------------


def test_turn_snapshot_captures_state_at_end_of_turn():
    t = GameStateTracker()
    t.apply({"turnInfo": {"turnNumber": 1, "activePlayer": 1},
              "players": [{"systemSeatNumber": 1, "lifeTotal": 20}]})
    t.apply({"players": [{"systemSeatNumber": 1, "lifeTotal": 15}]})  # still turn 1
    t.apply({"turnInfo": {"turnNumber": 2, "activePlayer": 2}})       # finalizes turn 1
    assert t.turns[1].life == {1: 15}
    assert 2 not in t.turns


def test_final_turn_finalized_on_game_over():
    t = GameStateTracker()
    t.apply({"turnInfo": {"turnNumber": 3, "activePlayer": 1},
              "players": [{"systemSeatNumber": 1, "lifeTotal": 0}]})
    t.finalize_current()
    assert t.turns[3].life == {1: 0}


def test_refinalizing_same_turn_overwrites():
    """Replaying the same events twice must not duplicate or stack state."""
    t = GameStateTracker()
    t.apply({"turnInfo": {"turnNumber": 1},
              "players": [{"systemSeatNumber": 1, "lifeTotal": 20}]})
    t.finalize_current()
    t.apply({"players": [{"systemSeatNumber": 1, "lifeTotal": 18}]})
    t.finalize_current()
    assert t.turns[1].life == {1: 18}


def test_no_turn_observed_means_nothing_finalized():
    t = GameStateTracker()
    t.finalize_current()
    assert t.turns == {}


def test_flush_trailing_records_a_turn_that_outlived_game_over():
    """Arena keeps sending state after GameOver; the turn it advances into
    would otherwise be accumulated and never written."""
    t = GameStateTracker()
    t.apply({"turnInfo": {"turnNumber": 3}, "players": [{"systemSeatNumber": 1,
                                                          "lifeTotal": 12}]})
    t.finalize_current()                                            # GameOver
    t.apply({"turnInfo": {"turnNumber": 24}, "players": [{"systemSeatNumber": 1,
                                                           "lifeTotal": 4}]})
    assert 24 not in t.turns                                        # not yet
    t.flush_trailing()
    assert t.turns[24].life == {1: 4}


def test_flush_trailing_does_not_rewrite_the_game_over_snapshot():
    """Post-game cleanup must not overwrite the state a game ended on."""
    t = GameStateTracker()
    t.apply({"turnInfo": {"turnNumber": 5}, "players": [{"systemSeatNumber": 1,
                                                          "lifeTotal": 3}]})
    t.finalize_current()
    t.apply({"players": [{"systemSeatNumber": 1, "lifeTotal": 0}]})  # cleanup
    t.flush_trailing()
    assert t.turns[5].life == {1: 3}


def test_flush_trailing_covers_a_game_that_never_got_a_game_over():
    """An abandoned game gets no GameOver at all."""
    t = GameStateTracker()
    t.apply({"turnInfo": {"turnNumber": 7}, "players": [{"systemSeatNumber": 2,
                                                          "lifeTotal": 9}]})
    t.flush_trailing()
    assert t.turns[7].life == {2: 9}


# --- derived per-seat columns -------------------------------------------


def test_hidden_hand_still_counted_via_zone_list():
    """Opponent hand cards are hidden instances but the zone list still counts."""
    t = GameStateTracker()
    t.apply(
        {"zones": [{"zoneId": 5, "type": "ZoneType_Hand", "ownerSeatId": 1,
                     "visibility": "Visibility_Private",
                     "objectInstanceIds": [10, 11, 12]}]}
    )
    t.apply({"turnInfo": {"turnNumber": 1}})
    t.finalize_current()
    assert t.turns[1].hand == {1: 3}


def test_unobserved_zones_yield_no_entry_not_zero():
    t = GameStateTracker()
    t.apply({"turnInfo": {"turnNumber": 1}})
    t.finalize_current()
    assert t.turns[1].hand == {}
    assert t.turns[1].permanents == {}
    assert t.turns[1].lands == {}
    assert t.turns[1].life == {}
    assert t.turns[1].graveyard == {}
    assert t.turns[1].open_mana == {}


def test_lands_counted_only_for_land_cardtype():
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [
                {"instanceId": 1, "controllerSeatId": 1, "cardTypes": ["CardType_Land"]},
                {"instanceId": 2, "controllerSeatId": 1, "cardTypes": ["CardType_Creature"]},
            ],
            "zones": [{"zoneId": 1, "type": "ZoneType_Battlefield",
                        "objectInstanceIds": [1, 2]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    assert t.turns[1].lands == {1: 1}
    assert t.turns[1].permanents == {1: 2}


def test_open_mana_counts_untapped_lands_only():
    """Open mana is a bluff/interaction-detection proxy, not a rules-accurate
    mana pool: it is just untapped lands. A tapped land still counts as a
    land, but not as open mana."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [
                {"instanceId": 1, "controllerSeatId": 1, "cardTypes": ["CardType_Land"]},
                {"instanceId": 2, "controllerSeatId": 1, "cardTypes": ["CardType_Land"],
                 "isTapped": True},
            ],
            "zones": [{"zoneId": 1, "type": "ZoneType_Battlefield",
                        "objectInstanceIds": [1, 2]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    assert t.turns[1].lands == {1: 2}
    assert t.turns[1].open_mana == {1: 1}


def test_permanents_grouped_by_controller_not_owner():
    """A stolen permanent counts for its controller, matching the schema's
    self/opp split which is about who currently commands the battlefield."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 1, "ownerSeatId": 1, "controllerSeatId": 2}],
            "zones": [{"zoneId": 1, "type": "ZoneType_Battlefield",
                        "objectInstanceIds": [1]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    assert t.turns[1].permanents == {2: 1}


# --- zone transfers ----------------------------------------------------


def _transfer(
    zone_src: int, zone_dest: int, category: str, affected: list[int], *, id: int | None = None
) -> dict:
    ann = {
        "affectedIds": affected,
        "type": ["AnnotationType_ZoneTransfer"],
        "details": [
            {"key": "zone_src", "valueInt32": [zone_src]},
            {"key": "zone_dest", "valueInt32": [zone_dest]},
            {"key": "category", "valueString": [category]},
        ],
    }
    if id is not None:
        ann["id"] = id
    return ann


LIBRARY = {"zoneId": 1, "type": "ZoneType_Library", "ownerSeatId": 1}
HAND = {"zoneId": 2, "type": "ZoneType_Hand", "ownerSeatId": 1}


def test_zone_transfer_records_card_zones_and_seat():
    t = GameStateTracker()
    t.apply({"turnInfo": {"turnNumber": 3}})
    t.apply(
        {
            "gameObjects": [{"instanceId": 7, "grpId": 86835}],
            "zones": [LIBRARY, HAND],
            "annotations": [_transfer(1, 2, "Draw", [7])],
        }
    )
    (event,) = t.card_events
    assert (event.seq, event.turn_number, event.seat, event.grp_id) == (0, 3, 1, 86835)
    assert (event.category, event.zone_src, event.zone_dest) == (
        "Draw", "ZoneType_Library", "ZoneType_Hand",
    )


def test_hidden_card_transfer_has_no_grp_id():
    """An opponent's draw carries no game object at all, and a face-down card
    reports grpId 0. Neither is a parse failure — we simply cannot see it."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 8, "grpId": 0}],
            "zones": [LIBRARY, HAND],
            "annotations": [_transfer(1, 2, "Draw", [7, 8])],
        }
    )
    assert [e.grp_id for e in t.card_events] == [None, None]
    assert [e.category for e in t.card_events] == ["Draw", "Draw"]


def test_rekey_earlier_in_the_same_message_resolves_the_transferred_card():
    """Arena re-keys a card as it changes zone, emitting ObjectIdChanged just
    before the ZoneTransfer that names the new id (fixture annotations 68/69).
    Both must be handled in array order or the spell loses its identity."""
    t = GameStateTracker()
    t.apply({"gameObjects": [{"instanceId": 257, "grpId": 102774}],
             "zones": [{"zoneId": 3, "type": "ZoneType_Hand", "ownerSeatId": 2},
                       {"zoneId": 4, "type": "ZoneType_Stack"}]})
    t.apply({"annotations": [_id_changed(257, 314),
                             _transfer(3, 4, "CastSpell", [314])]})
    (event,) = t.card_events
    assert (event.grp_id, event.seat, event.zone_dest) == (102774, 2, "ZoneType_Stack")


def test_unseen_zone_ids_leave_the_zone_types_null():
    t = GameStateTracker()
    t.apply({"annotations": [_transfer(90, 91, "Put", [1])]})
    (event,) = t.card_events
    assert (event.zone_src, event.zone_dest, event.seat, event.grp_id) == (None, None, None, None)


def test_transfer_before_the_first_turn_has_no_turn_number():
    """Mulligans happen before turnInfo ever arrives."""
    t = GameStateTracker()
    t.apply({"zones": [HAND, LIBRARY], "annotations": [_transfer(2, 1, "Put", [1])]})
    assert t.card_events[0].turn_number is None


def test_full_snapshot_clears_the_board_but_not_the_history():
    t = GameStateTracker()
    t.apply({"zones": [LIBRARY, HAND], "annotations": [_transfer(1, 2, "Draw", [1])]})
    t.apply({"type": "GameStateType_Full", "zones": [LIBRARY]})
    assert len(t.card_events) == 1
    assert t.objects == {}


def test_turn_snapshot_counts_the_library_from_the_zone():
    """Library size is observed, not decklist minus draws, so a Bo3 sideboard
    changing the deck between games needs no special case."""
    t = GameStateTracker()
    t.apply(
        {
            "zones": [
                {"zoneId": 1, "type": "ZoneType_Library", "ownerSeatId": 1,
                 "objectInstanceIds": list(range(54))},
                {"zoneId": 2, "type": "ZoneType_Library", "ownerSeatId": 2,
                 "objectInstanceIds": list(range(100, 160))},
            ],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    assert t.turns[1].library == {1: 54, 2: 60}


def test_graveyard_counted_from_the_zone():
    """Graveyard size is observed the same way library size is: a real
    per-seat zone Arena names even when empty, so an empty graveyard reads 0,
    not the NULL an unobserved seat would get."""
    t = GameStateTracker()
    t.apply(
        {
            "zones": [
                {"zoneId": 1, "type": "ZoneType_Graveyard", "ownerSeatId": 1,
                 "objectInstanceIds": [1, 2]},
                {"zoneId": 2, "type": "ZoneType_Graveyard", "ownerSeatId": 2,
                 "objectInstanceIds": []},
            ],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    assert t.turns[1].graveyard == {1: 2, 2: 0}


def test_transfer_is_attributed_to_the_turn_it_happened_in():
    """turnInfo is merged after annotations on purpose: a card played on the
    last message of a turn belongs to that turn, not the one starting. The
    same ordering keeps the turn snapshot pre-advance, so it must not swap."""
    t = GameStateTracker()
    t.apply({"turnInfo": {"turnNumber": 1}})
    t.apply(
        {
            "zones": [LIBRARY, HAND],
            "annotations": [_transfer(2, 1, "Put", [1])],
            "turnInfo": {"turnNumber": 2},
        }
    )
    assert t.card_events[0].turn_number == 1


# --- zone card contents (identities behind the counts) -------------------


def test_turn_snapshot_captures_hand_contents_with_identities():
    """A hand instance with a matching gameObjects entry carries its grpId; one
    with none is a card hidden from us, not a card the snapshot forgot."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 10, "grpId": 1000}],
            "zones": [{"zoneId": 5, "type": "ZoneType_Hand", "ownerSeatId": 1,
                        "objectInstanceIds": [10, 11]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    cards = {c.instance_id: c for c in t.turns[1].cards}
    assert (cards[10].zone, cards[10].seat, cards[10].grp_id) == ("hand", 1, 1000)
    assert cards[11].grp_id is None


def test_battlefield_card_contents_grouped_by_controller_not_owner():
    """Mirrors test_permanents_grouped_by_controller_not_owner, but for the
    card identities rather than the bare count."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 1, "grpId": 500, "ownerSeatId": 1,
                              "controllerSeatId": 2}],
            "zones": [{"zoneId": 1, "type": "ZoneType_Battlefield", "objectInstanceIds": [1]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    (card,) = t.turns[1].cards
    assert (card.zone, card.seat, card.grp_id) == ("battlefield", 2, 500)


def test_graveyard_card_contents_snapshot():
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 20, "grpId": 700}],
            "zones": [{"zoneId": 6, "type": "ZoneType_Graveyard", "ownerSeatId": 2,
                        "objectInstanceIds": [20]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    (card,) = t.turns[1].cards
    assert (card.zone, card.seat, card.grp_id) == ("graveyard", 2, 700)


def test_zone_card_idx_is_scoped_per_zone_and_seat():
    """Two graveyards of the same type must not collide on idx: the storage
    key is (zone, seat, idx), not the position in Arena's own zone list, which
    both players' graveyards would otherwise restart from independently."""
    t = GameStateTracker()
    t.apply(
        {
            "zones": [
                {"zoneId": 6, "type": "ZoneType_Graveyard", "ownerSeatId": 1,
                 "objectInstanceIds": [1, 2]},
                {"zoneId": 7, "type": "ZoneType_Graveyard", "ownerSeatId": 2,
                 "objectInstanceIds": [3]},
            ],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    by_seat: dict[int, list[int]] = {}
    for c in t.turns[1].cards:
        by_seat.setdefault(c.seat, []).append(c.idx)
    assert sorted(by_seat[1]) == [0, 1]
    assert sorted(by_seat[2]) == [0]


def test_drawn_on_turn_set_for_a_draw_but_not_the_opening_hand():
    t = GameStateTracker()
    # Opening hand: a Put transfer recorded before any turnInfo ever arrives.
    t.apply({"zones": [LIBRARY, {**HAND, "objectInstanceIds": [1]}],
             "annotations": [_transfer(1, 2, "Put", [1])]})
    t.apply({"turnInfo": {"turnNumber": 1}})
    t.apply(
        {
            "gameObjects": [{"instanceId": 2, "grpId": 100}],
            "zones": [LIBRARY, {"zoneId": 2, "objectInstanceIds": [1, 2]}],
            "annotations": [_transfer(1, 2, "Draw", [2])],
        }
    )
    t.finalize_current()
    cards = {c.instance_id: c for c in t.turns[1].cards}
    assert cards[1].drawn_on_turn is None
    assert cards[2].drawn_on_turn == 1


def test_drawn_on_turn_survives_a_rekey():
    """A drawn card re-keyed later (e.g. cast, then countered back to hand
    under a new id) must keep its drawn-turn marker at the new id."""
    t = GameStateTracker()
    t.apply({"turnInfo": {"turnNumber": 1}})
    t.apply(
        {
            "gameObjects": [{"instanceId": 1, "grpId": 100}],
            "zones": [LIBRARY, {**HAND, "objectInstanceIds": [1]}],
            "annotations": [_transfer(1, 2, "Draw", [1])],
        }
    )
    t.apply(
        {
            "gameObjects": [{"instanceId": 2, "grpId": 100}],
            "zones": [{"zoneId": 2, "objectInstanceIds": [2]}],
            "annotations": [_id_changed(1, 2)],
        }
    )
    t.finalize_current()
    (card,) = t.turns[1].cards
    assert (card.instance_id, card.drawn_on_turn) == (2, 1)


def test_refinalizing_same_turn_overwrites_zone_cards():
    """Replaying the same events twice must not duplicate zone contents,
    matching test_refinalizing_same_turn_overwrites for the bare counts."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 1, "grpId": 100}],
            "zones": [{"zoneId": 2, "type": "ZoneType_Hand", "ownerSeatId": 1,
                        "objectInstanceIds": [1]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    t.apply({"gameObjects": [{"instanceId": 2, "grpId": 200}],
              "zones": [{"zoneId": 2, "objectInstanceIds": [1, 2]}]})
    t.finalize_current()
    assert len(t.turns[1].cards) == 2


def test_full_snapshot_clears_zone_card_contents():
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 1, "grpId": 100}],
            "zones": [{"zoneId": 2, "type": "ZoneType_Hand", "ownerSeatId": 1,
                        "objectInstanceIds": [1]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.apply({"type": "GameStateType_Full", "zones": []})
    t.finalize_current()
    assert t.turns[1].cards == []


# --- board detail: tapped, power/toughness, exile -------------------------
# Field shapes verified by direct inspection of the real log: game objects
# carry `"isTapped": true` and a boxed `"power": {"value": 3}`, and
# ZoneType_Exile is a single shared zone (zoneId 29) with no ownerSeatId.


def _tapped(instance_id: int, tapped: int) -> dict:
    return {
        "type": ["AnnotationType_TappedUntappedPermanent"],
        "affectedIds": [instance_id],
        "details": [{"key": "tapped", "valueInt32": [tapped]}],
    }


def _land_in_play(instance_id: int, seat: int = 1, **extra) -> dict:
    return {
        "gameObjects": [
            {"instanceId": instance_id, "grpId": 900, "controllerSeatId": seat,
             "ownerSeatId": seat, "cardTypes": ["CardType_Land"], **extra}
        ],
        "zones": [
            {"zoneId": 1, "type": "ZoneType_Battlefield", "objectInstanceIds": [instance_id]}
        ],
    }


def test_tapped_permanent_is_recorded_as_tapped():
    t = GameStateTracker()
    t.apply({**_land_in_play(1, isTapped=True), "turnInfo": {"turnNumber": 1}})
    t.finalize_current()
    (card,) = t.turns[1].cards
    assert card.is_tapped is True


def test_absent_is_tapped_means_untapped_on_the_battlefield():
    """Arena never sends `isTapped: false` — 149 objects carry the true and not
    one carries the false across the whole real log. So on the battlefield the
    field's absence is the untapped state, not missing data."""
    t = GameStateTracker()
    t.apply({**_land_in_play(1), "turnInfo": {"turnNumber": 1}})
    t.finalize_current()
    (card,) = t.turns[1].cards
    assert card.is_tapped is False


def test_tapped_is_null_outside_the_battlefield():
    """A card in hand has no orientation. None says that; False would claim it
    is untapped, which is a different statement."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 1, "grpId": 100}],
            "zones": [{"zoneId": 2, "type": "ZoneType_Hand", "ownerSeatId": 1,
                        "objectInstanceIds": [1]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    (card,) = t.turns[1].cards
    assert card.is_tapped is None


def test_untap_annotation_corrects_the_stale_object():
    """The whole reason _apply_tapped exists: Arena only ever *sets* isTapped
    on the game object, so field-level diff merging leaves a land that untapped
    reading tapped forever. The annotation is the only untap signal there is."""
    t = GameStateTracker()
    t.apply({**_land_in_play(1, isTapped=True), "turnInfo": {"turnNumber": 1}})
    # Note the diff carries no gameObjects entry at all — exactly as the real
    # log does it. Nothing here could overwrite isTapped except the annotation.
    t.apply({"annotations": [_tapped(1, 0)], "turnInfo": {"turnNumber": 2}})
    t.finalize_current()
    assert t.turns[1].cards[0].is_tapped is True   # still tapped when turn 1 ended
    assert t.turns[2].cards[0].is_tapped is False  # untapped during turn 2


def test_untap_at_the_new_turns_upkeep_does_not_untap_the_ending_turn():
    """Ordering guard. Every untap in the fixture rides the message that also
    advances turnInfo, reading `turnNumber: 3, step: Step_Upkeep` — it is the
    new turn's untap step. Applying it before the turn boundary would show the
    ending turn's lands upright on the very turn they were tapped for mana, so
    _apply_tapped deliberately runs after the boundary.
    """
    t = GameStateTracker()
    t.apply({**_land_in_play(1, isTapped=True), "turnInfo": {"turnNumber": 1}})
    # One message, both facts: turn 2 begins, and the land untaps in its upkeep.
    t.apply({"annotations": [_tapped(1, 0)], "turnInfo": {"turnNumber": 2}})
    assert t.turns[1].cards[0].is_tapped is True


def test_tap_annotation_applies_within_the_turn_it_arrives_in():
    t = GameStateTracker()
    t.apply({**_land_in_play(1), "turnInfo": {"turnNumber": 1}})
    t.apply({"annotations": [_tapped(1, 1)]})
    t.finalize_current()
    assert t.turns[1].cards[0].is_tapped is True


def test_untap_of_an_unknown_instance_invents_nothing():
    """Creating an object here would conjure a battlefield permanent with no
    controller, which _battlefield_counts would then disagree about."""
    t = GameStateTracker()
    t.apply({"annotations": [_tapped(999, 0)], "turnInfo": {"turnNumber": 1}})
    t.finalize_current()
    assert 999 not in t.objects
    assert t.turns[1].cards == []


def test_power_and_toughness_unwrap_arenas_boxed_values():
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 1, "grpId": 500, "controllerSeatId": 1,
                              "cardTypes": ["CardType_Creature"],
                              "power": {"value": 3}, "toughness": {"value": 4}}],
            "zones": [{"zoneId": 1, "type": "ZoneType_Battlefield",
                        "objectInstanceIds": [1]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    (card,) = t.turns[1].cards
    assert (card.power, card.toughness) == (3, 4)


def test_a_noncreature_has_no_power_rather_than_zero():
    t = GameStateTracker()
    t.apply({**_land_in_play(1), "turnInfo": {"turnNumber": 1}})
    t.finalize_current()
    (card,) = t.turns[1].cards
    assert (card.power, card.toughness) == (None, None)


def test_a_characteristic_defining_power_is_unknown_not_zero():
    """Arena boxes power as {"value": n}; a `*` power arrives as the same box
    with no value. Unknown is None — never 0, which would be a real number we
    did not observe (AGENTS.md rule 4)."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 1, "grpId": 500, "controllerSeatId": 1,
                              "power": {}, "toughness": {}}],
            "zones": [{"zoneId": 1, "type": "ZoneType_Battlefield",
                        "objectInstanceIds": [1]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    (card,) = t.turns[1].cards
    assert (card.power, card.toughness) == (None, None)


def test_exile_contents_keyed_on_the_objects_owner():
    """Exile is shared: verified against the real log, ZoneType_Exile carries no
    ownerSeatId (unlike hand, graveyard and library), so the seat has to come
    off each exiled object. Ownership, not control — the card belongs to whoever
    owns it, not whoever exiled it."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [
                {"instanceId": 295, "grpId": 96722, "ownerSeatId": 2,
                 "controllerSeatId": 1, "cardTypes": ["CardType_Creature"]},
            ],
            "zones": [{"zoneId": 29, "type": "ZoneType_Exile",
                        "visibility": "Visibility_Public", "objectInstanceIds": [295]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    (card,) = t.turns[1].cards
    assert (card.zone, card.seat, card.grp_id) == ("exile", 2, 96722)
    assert card.is_tapped is None  # exile is not the battlefield


def test_exiled_instance_with_no_object_is_dropped_not_guessed():
    """The hand emits hidden instances as card backs because the *zone* names
    their owner. Exile has no owner, so an objectless entry has nothing to
    attribute it to — emitting one would mean inventing a seat."""
    t = GameStateTracker()
    t.apply(
        {
            "zones": [{"zoneId": 29, "type": "ZoneType_Exile", "objectInstanceIds": [77]}],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    assert t.turns[1].cards == []


def test_exile_does_not_leak_into_the_battlefield_counts():
    """Both zones key their seat off the object rather than the zone, so the
    shared loop must still keep them apart: an exiled creature is not a
    permanent in play."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [
                {"instanceId": 1, "grpId": 500, "ownerSeatId": 1, "controllerSeatId": 1,
                 "cardTypes": ["CardType_Creature"]},
                {"instanceId": 2, "grpId": 501, "ownerSeatId": 1, "controllerSeatId": 1,
                 "cardTypes": ["CardType_Creature"]},
            ],
            "zones": [
                {"zoneId": 1, "type": "ZoneType_Battlefield", "objectInstanceIds": [1]},
                {"zoneId": 29, "type": "ZoneType_Exile", "objectInstanceIds": [2]},
            ],
            "turnInfo": {"turnNumber": 1},
        }
    )
    t.finalize_current()
    assert t.turns[1].permanents == {1: 1}
    assert sorted(c.zone for c in t.turns[1].cards) == ["battlefield", "exile"]


# --- replayed annotations ------------------------------------------------
# A raw event can legitimately reach the tracker more than once: ingest.py
# dedupes what it reads, but a source file can itself carry the same message
# twice (observed for real: Player-prev.log's content reappearing almost
# wholesale inside the Player.log it rotated from). card_events is the one
# piece of state here that accumulates instead of snapshotting, so unlike
# turns it needs its own defence — see _record_transfer.


def test_replaying_the_same_annotation_does_not_double_the_card_event():
    t = GameStateTracker()
    gsm = {
        "gameObjects": [{"instanceId": 7, "grpId": 86835}],
        "zones": [LIBRARY, HAND],
        "annotations": [_transfer(1, 2, "Draw", [7], id=42)],
    }
    t.apply(gsm)
    t.apply(gsm)  # the exact same message, reaching the tracker twice
    (event,) = t.card_events
    assert event.grp_id == 86835


def test_two_genuinely_different_annotations_both_record():
    """Distinct ids must not be conflated just because they share a category
    and card — a double-cast of the same spell is two events, not one."""
    t = GameStateTracker()
    t.apply(
        {
            "gameObjects": [{"instanceId": 7, "grpId": 86835}],
            "zones": [LIBRARY, HAND],
            "annotations": [_transfer(1, 2, "Draw", [7], id=1)],
        }
    )
    t.apply(
        {
            "gameObjects": [{"instanceId": 8, "grpId": 86835}],
            "zones": [LIBRARY, HAND],
            "annotations": [_transfer(1, 2, "Draw", [8], id=2)],
        }
    )
    assert len(t.card_events) == 2


def test_an_annotation_with_no_id_is_never_treated_as_a_replay():
    """No id means no identity to dedupe on — recorded as-is, same as before
    this existed, rather than guessed to be a repeat."""
    t = GameStateTracker()
    gsm = {"zones": [LIBRARY, HAND], "annotations": [_transfer(1, 2, "Draw", [1])]}
    t.apply(gsm)
    t.apply(gsm)
    assert len(t.card_events) == 2


# --- undo (tests/fixtures/undo_session.log) ----------------------------
#
# Every expected value below was read from the fixture with fixture_peek.py
# and an independent script over its JSON, never from a run (rule 8). The
# receiving seat is 2. State 100 is seat 2's CastSpell of instance 176 (re-
# keyed to 272, grpId 106256); state 101 is a Full state with update
# GameStateUpdate_Undo and prevGameStateId 99; state 102 casts instance 214
# instead (grpId 106273, drawn at state 24), re-keyed to the same 272 under
# the same annotation id 267. Zones: 27 stack, 28 battlefield, 31/32/33
# seat 1's hand/library/graveyard, 35/36 seat 2's hand/library.

_CANCELLED_CAST = (5, 2, 106256, "CastSpell", "ZoneType_Hand", "ZoneType_Stack")  # 100

# (turn_number, seat, grp_id, category, zone_src, zone_dest), state by state.
# The turn is the one current before the carrying message's own turnInfo.
_ROWS_BEFORE_THE_UNDO = [
    (1, 1, 101039, "PlayLand", "ZoneType_Hand", "ZoneType_Battlefield"),  # 7
    (1, 1, 106358, "CastSpell", "ZoneType_Hand", "ZoneType_Stack"),  # 8
    (1, 1, 106358, "Resolve", "ZoneType_Stack", "ZoneType_Battlefield"),  # 10
    (2, 2, 106273, "Draw", "ZoneType_Library", "ZoneType_Hand"),  # 24
    (2, 2, 97169, "PlayLand", "ZoneType_Hand", "ZoneType_Battlefield"),  # 27
    (2, 2, 106415, "CastSpell", "ZoneType_Hand", "ZoneType_Stack"),  # 28
    (2, 2, 106415, "Resolve", "ZoneType_Stack", "ZoneType_Battlefield"),  # 30
    (3, 1, None, "Draw", "ZoneType_Library", "ZoneType_Hand"),  # 44, hidden
    (3, 1, 101039, "PlayLand", "ZoneType_Hand", "ZoneType_Battlefield"),  # 47
    (3, 1, 106276, "Discard", "ZoneType_Hand", "ZoneType_Graveyard"),  # 48
    # 51: the object rides the message under its old id 163, re-keyed to 225.
    (3, 1, 101041, "Put", "ZoneType_Library", "ZoneType_Hand"),  # 51
    (4, 2, 106491, "Draw", "ZoneType_Library", "ZoneType_Hand"),  # 75
    (4, 2, 70504, "PlayLand", "ZoneType_Hand", "ZoneType_Battlefield"),  # 78
    (5, 1, None, "Draw", "ZoneType_Library", "ZoneType_Hand"),  # 92, hidden
    (5, 1, 101041, "PlayLand", "ZoneType_Hand", "ZoneType_Battlefield"),  # 95
    # 96 reaches the log only as a QueuedGameStateMessage.
    (5, 1, 106296, "CastSpell", "ZoneType_Hand", "ZoneType_Stack"),  # 96
]


def _undo_fixture_states() -> list[dict]:
    """Every gameStateMessage in the fixture, queued ones included, in log
    order: the same messages the projector hands the tracker."""
    lines = UNDO_FIXTURE.read_text(encoding="utf-8").splitlines()
    states = []
    for entry in segment_lines(lines, locale_hint="mdy"):
        event = json.loads(entry.payload).get("greToClientEvent") or {}
        for message in event.get("greToClientMessages") or []:
            if isinstance(message.get("gameStateMessage"), dict):
                states.append(message["gameStateMessage"])
    return states


def _rows(tracker: GameStateTracker) -> list[tuple]:
    return [
        (e.turn_number, e.seat, e.grp_id, e.category, e.zone_src, e.zone_dest)
        for e in tracker.card_events
    ]


def test_an_undo_drops_the_cancelled_cast_and_keeps_the_rest():
    t = GameStateTracker()
    for gsm in _undo_fixture_states():
        t.apply(gsm)

    rows = _rows(t)
    # The cancelled cast never happened.
    assert _CANCELLED_CAST not in rows
    # The cast before the undo window (state 96) survives.
    assert (5, 1, 106296, "CastSpell", "ZoneType_Hand", "ZoneType_Stack") in rows
    # Every other row is unchanged, and the cast made after the undo is kept
    # although Arena gave it the cancelled one's annotation id.
    assert rows == [
        *_ROWS_BEFORE_THE_UNDO,
        (5, 2, 106273, "CastSpell", "ZoneType_Hand", "ZoneType_Stack"),  # 102
    ]
    assert [e.seq for e in t.card_events] == list(range(len(rows)))


def test_an_undo_to_a_state_never_applied_warns_and_drops_nothing():
    """State 99 left out, as if its message had been lost: the undo names a
    state this tracker never saw, so there is nothing to return to, and
    guessing a point would invent history (rule 4)."""
    states = [s for s in _undo_fixture_states() if s.get("gameStateId") != 99]
    t = GameStateTracker()
    for gsm in states:
        if gsm.get("gameStateId") == 101:
            break
        t.apply(gsm)
    before = list(t.card_events)
    assert _rows(t)[-1] == _CANCELLED_CAST
    assert t.warnings == []

    t.apply(next(s for s in states if s.get("gameStateId") == 101))

    assert t.card_events == before
    (warning,) = t.warnings
    assert "99" in warning


# Synthetic undo cases: shapes the one real fixture game cannot show.

STACK = {"zoneId": 3, "type": "ZoneType_Stack"}


def _undo(state_id: int, prev_state_id: int, **extra) -> dict:
    return {
        "type": "GameStateType_Full",
        "update": "GameStateUpdate_Undo",
        "gameStateId": state_id,
        "prevGameStateId": prev_state_id,
        **extra,
    }


def _cast(state_id: int, instance_id: int, grp_id: int, annotation_id: int, **extra) -> dict:
    return {
        "gameStateId": state_id,
        "gameObjects": [{"instanceId": instance_id, "grpId": grp_id}],
        "zones": [HAND, STACK],
        "annotations": [_transfer(2, 3, "CastSpell", [instance_id], id=annotation_id)],
        **extra,
    }


def test_an_undo_never_returns_to_a_state_of_an_earlier_game():
    """Synthetic. live_state.py replays a whole match through one tracker, and
    state ids start over each game, so a game-2 undo can name an id only game
    1 applied. Rolling back to game 1's point would truncate game 2's real
    rows."""
    t = GameStateTracker()
    t.apply(_cast(5, 7, 100, 1, gameInfo={"gameNumber": 1}))
    t.apply(_cast(1, 8, 200, 2, gameInfo={"gameNumber": 2}))
    t.apply(_cast(2, 9, 300, 3))
    before = list(t.card_events)

    t.apply(_undo(9, 5, gameInfo={"gameNumber": 2}))

    assert t.card_events == before
    assert len(t.warnings) == 1


def test_an_undo_rolls_back_by_apply_order_not_by_state_id():
    """Synthetic. 16 of 923 real games carry state ids that are not monotonic
    in the order they arrive, so "the states after prevGameStateId" means the
    states applied after it, never the ones with a larger id."""
    t = GameStateTracker()
    t.apply(_cast(10, 7, 100, 1))  # A
    t.apply(_cast(5, 8, 200, 2))  # B
    t.apply(_cast(7, 9, 300, 3))  # C
    t.apply(_undo(12, 10))

    assert [(e.seq, e.grp_id) for e in t.card_events] == [(0, 100)]
    assert t.warnings == []


def test_an_undo_forgets_exactly_the_annotation_ids_it_drops():
    """Synthetic. Arena rewinds annotation ids with the game, so an id the
    undone window used can return on a real action and must not read as a
    re-broadcast. An id first seen before the restored state is still a
    re-broadcast when it comes again, even if the window repeated it, and
    the undo state's own transfers happened after the undo and stay."""
    t = GameStateTracker()
    x = _transfer(1, 2, "Draw", [7], id=10)
    t.apply(
        {
            "gameStateId": 1,
            "gameObjects": [{"instanceId": 7, "grpId": 100}],
            "zones": [LIBRARY, HAND],
            "annotations": [x],
        }
    )
    t.apply(
        {
            "gameStateId": 2,
            "gameObjects": [{"instanceId": 8, "grpId": 200}],
            "zones": [LIBRARY, HAND],
            "annotations": [_transfer(1, 2, "Draw", [8], id=11), x],  # Y, then X again
        }
    )
    t.apply(
        _undo(
            3,
            1,
            gameObjects=[{"instanceId": 9, "grpId": 300}],
            zones=[LIBRARY, HAND],
            annotations=[_transfer(1, 2, "Draw", [9], id=12)],  # Z
        )
    )
    assert [e.grp_id for e in t.card_events] == [100, 300]  # Y gone, Z kept

    t.apply(
        {
            "gameStateId": 4,
            "gameObjects": [{"instanceId": 11, "grpId": 400}],
            "zones": [LIBRARY, HAND],
            "annotations": [x, _transfer(1, 2, "Draw", [11], id=11)],  # X, a new card as 11
        }
    )

    assert [(e.seq, e.grp_id) for e in t.card_events] == [(0, 100), (1, 300), (2, 400)]
