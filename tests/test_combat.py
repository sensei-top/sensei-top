"""Tests for combat/damage projection: migrations/014_combat.sql,
projector/combat.py and the new pieces of projector/game_state.py.

``tests/fixtures/combat_session.log`` is carved from a real capture — see
migrations/014_combat.sql for its provenance (the source session had already
rotated off disk; the raw JSON survived verbatim in the local database, which
is the entire reason raw_events is kept that way, AGENTS.md rule 2). Ground
truth for every annotation-level fact below (annotation id, amount, delta,
instance/grp ids) was read directly from that JSON with an independent
script before this module was written, never from running the projector and
copying its output (rule 8). Turn-number attribution follows the same
"annotations land on whatever turn is current when they arrive" rule
``_record_transfer`` already uses and is already tested elsewhere in this
suite — this module does not re-litigate that rule, only reuses it.

The match is ``17c8bb71-ce69-46b5-bc7c-ba43788a76ff``, game 2. Self is
seat 1 here — the opposite of ``match_session.log``'s convention, so do not
carry that assumption over from ``test_review.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector import combat
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent / "fixtures" / "combat_session.log"
MATCH_ID = "17c8bb71-ce69-46b5-bc7c-ba43788a76ff"


@pytest.fixture
def db(tmp_path):
    conn = open_database(tmp_path / "t.db")
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    yield conn
    conn.close()


# --- fixture-backed: the full pipeline against a real capture ---------------


def test_match_and_seats_resolve(db):
    row = db.execute(
        "SELECT self_seat, opponent_seat, result FROM matches WHERE match_id = ?", (MATCH_ID,)
    ).fetchone()
    assert (row["self_seat"], row["opponent_seat"], row["result"]) == (1, 2, "win")


def test_combat_attacks_match_the_real_capture(db):
    """Six attacks, each seen exactly once despite Arena re-broadcasting the
    same attackState assertion across consecutive messages (verified in the
    raw capture for instance 419's turn-4 declaration, which appears twice)."""
    rows = db.execute(
        """SELECT turn_number, attacker_seat, instance_id, grp_id, target_id, blocked
             FROM combat_attacks WHERE match_id = ? AND game_number = 2
            ORDER BY turn_number, instance_id""",
        (MATCH_ID,),
    ).fetchall()
    got = [tuple(r) for r in rows]
    assert got == [
        (3, 2, 415, 87254, 1, None),
        (4, 1, 419, 86940, 2, None),
        (8, 1, 438, 90492, 2, 1),
        (10, 1, 419, 86940, 2, None),
        (10, 1, 438, 90492, 2, None),
        (10, 1, 464, 91668, 2, 1),
    ]


def test_combat_blocks_match_the_real_capture(db):
    rows = db.execute(
        """SELECT turn_number, blocker_seat, blocker_instance_id, blocker_grp_id,
                  attacker_instance_id
             FROM combat_blocks WHERE match_id = ? AND game_number = 2
            ORDER BY turn_number""",
        (MATCH_ID,),
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        (8, 2, 424, 86783, 438),
        (10, 2, 458, 87258, 464),
    ]


def test_an_attack_with_no_observed_block_is_unknown_not_unblocked(db):
    """rule 4: absence of a combat_blocks row is not evidence of an unblocked
    attack. Three of the six attacks (turn 3's 415, turn 4's 419, and one of
    turn 10's two unblocked attackers) have no matching block anywhere in
    this game, and all three must read NULL, never 0."""
    rows = db.execute(
        "SELECT blocked FROM combat_attacks WHERE match_id = ? AND game_number = 2",
        (MATCH_ID,),
    ).fetchall()
    blocked_values = [r["blocked"] for r in rows]
    assert blocked_values.count(None) == 4
    assert blocked_values.count(1) == 2
    assert 0 not in blocked_values


def test_damage_events_match_the_real_capture(db):
    """Includes one creature-vs-creature trade (turn 8: 438 <-> 424), a
    double creature trade plus two hits on the same player in one turn
    (turn 10), and the one verified damage_type discriminator in this
    capture: the same source instance (438) deals type-1 damage to the
    player earlier in turn 10 and type-2 damage to the same player later
    the same turn — two distinct annotation ids, never conflated into one."""
    rows = db.execute(
        """SELECT annotation_id, turn_number, source_instance_id, source_grp_id,
                  target_instance_id, target_grp_id, target_seat, amount, damage_type
             FROM damage_events WHERE match_id = ? AND game_number = 2
            ORDER BY annotation_id""",
        (MATCH_ID,),
    ).fetchall()
    got = [tuple(r) for r in rows]
    assert got == [
        (209, 3, 415, 87254, None, None, 1, 1, 1),
        (554, 8, 438, 90492, 424, 86783, None, 3, 1),
        (555, 8, 424, 86783, 438, 90492, None, 1, 1),
        (789, 10, 464, 91668, 458, 87258, None, 7, 1),
        (790, 10, 458, 87258, 464, 91668, None, 2, 1),
        (791, 10, 419, 86940, None, None, 2, 3, 1),
        (792, 10, 438, 90492, None, None, 2, 5, 1),
        (837, 10, 438, 90492, None, None, 2, 7, 2),
    ]


def test_life_events_match_the_real_capture(db):
    """Row 1 (annotation 145) is the non-combat case this table exists for:
    a -2 life change from instance 9002 with no matching DamageDealt
    anywhere nearby — a payment (a shockland-style "enter untapped" cost is
    the only mechanic in Standard that recurs at exactly -2 with no combat
    signal), not a hit. Rows 3-4 are the turn-10 lethal sequence, each
    aggregating damage from what the raw annotations show as a single
    named attacker even where two attackers contributed (rule 4: this
    table's affector is *a* cause, not the complete accounting — see
    migrations/014_combat.sql)."""
    rows = db.execute(
        """SELECT annotation_id, turn_number, seat, delta, affector_instance_id, affector_grp_id
             FROM life_events WHERE match_id = ? AND game_number = 2
            ORDER BY annotation_id""",
        (MATCH_ID,),
    ).fetchall()
    got = [tuple(r) for r in rows]
    assert got[1:] == [
        (213, 3, 1, -1, 415, 87254),
        (794, 10, 2, -8, 419, 86940),
        (838, 10, 2, -7, 438, 90492),
    ]
    # Row 1 (annotation 145) separately: no DamageDealt annotation in this
    # capture ever names instance 9002, confirming it is not a combat source.
    assert got[0][:1] + got[0][2:] == (145, 1, -2, 9002, None)
    damage_sources = {
        r["source_instance_id"]
        for r in db.execute(
            "SELECT source_instance_id FROM damage_events WHERE match_id = ?", (MATCH_ID,)
        )
    }
    assert 9002 not in damage_sources


def test_repeated_raw_events_do_not_multiply_combat_or_damage_rows(db):
    """Re-running ingest on the same file (simulating the Player.log /
    Player-prev.log overlap AGENTS.md documents) must not double anything:
    ingest_file's own digest dedup should refuse the duplicates, and even if
    it did not, this tracker's own (turn, instance) and annotation-id dedup
    would still hold the line."""
    before = {
        table: db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in ("combat_attacks", "combat_blocks", "damage_events", "life_events")
    }
    ingest_file(db, FIXTURE, locale_hint="mdy")
    project(db)
    after = {
        table: db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in ("combat_attacks", "combat_blocks", "damage_events", "life_events")
    }
    assert after == before


def test_projection_is_deterministic(db):
    """project() twice must produce byte-identical combat/damage rows —
    AGENTS.md rule 3: projection is always a full rebuild, never incremental."""
    first = db.execute(
        "SELECT * FROM combat_attacks ORDER BY turn_number, instance_id"
    ).fetchall()
    project(db)
    second = db.execute(
        "SELECT * FROM combat_attacks ORDER BY turn_number, instance_id"
    ).fetchall()
    assert [tuple(r) for r in first] == [tuple(r) for r in second]


# --- pure-function unit tests: dedup and shape edge cases -------------------
# Synthetic minimal inputs for edge cases the fixture cannot cleanly isolate
# (docs/testing.md's established pattern for this project) — each shape
# below was verified against the real capture before being used here, never
# invented; see projector/combat.py's module docstring for where.


def test_parse_attack_ignores_a_diff_with_no_attack_state():
    assert combat.parse_attack({"instanceId": 1}, 1, 4, {"controllerSeatId": 1}) is None


def test_parse_attack_returns_none_without_a_current_turn():
    """A creature cannot attack before any turnInfo has ever been seen;
    guards the (turn, instance) dedup key against a None turn_number."""
    raw = {"attackState": "AttackState_Declared", "attackInfo": {"targetId": 2}}
    assert combat.parse_attack(raw, 419, None, {"controllerSeatId": 1}) is None


def test_parse_attack_reads_target_from_the_raw_diff():
    raw = {"attackState": "AttackState_Declared", "attackInfo": {"targetId": 2}}
    resolved = {"controllerSeatId": 1, "grpId": 86940}
    attack = combat.parse_attack(raw, 419, 4, resolved)
    assert attack == combat.AttackDeclared(
        turn_number=4, seat=1, instance_id=419, grp_id=86940, target_id=2
    )


def test_parse_blocks_returns_one_entry_per_attacker():
    """Verified shape (data/sensei-top.db): {'blockState': 'BlockState_Declared',
    'blockInfo': {'attackerIds': [367]}} — extended here to two attackers to
    prove the fan-out, since a real double-block was not captured but the
    field shape (a plain list) makes the fan-out unambiguous."""
    raw = {"blockState": "BlockState_Declared", "blockInfo": {"attackerIds": [367, 368]}}
    resolved = {"controllerSeatId": 2, "grpId": 86783}
    blocks = combat.parse_blocks(raw, 424, 8, resolved)
    assert blocks == [
        combat.BlockDeclared(
            turn_number=8, seat=2, blocker_instance_id=424,
            blocker_grp_id=86783, attacker_instance_id=367,
        ),
        combat.BlockDeclared(
            turn_number=8, seat=2, blocker_instance_id=424,
            blocker_grp_id=86783, attacker_instance_id=368,
        ),
    ]


def test_parse_damage_names_a_player_target_by_seat_not_instance():
    """affectedIds carrying a bare seat number (no matching object) is a
    player target — verified in every one of 1,082 real DamageDealt
    annotations, affectedIds was length 1, and a target with no object was
    always a small, known seat number."""
    annotation = {
        "id": 791, "affectorId": 419, "affectedIds": [2],
        "details": [
            {"key": "damage", "type": "KeyValuePairValueType_int32", "valueInt32": [3]},
            {"key": "type", "type": "KeyValuePairValueType_int32", "valueInt32": [1]},
        ],
    }
    objects = {419: {"grpId": 86940, "controllerSeatId": 1}}
    event = combat.parse_damage(annotation, 10, objects)
    assert event == combat.DamageEvent(
        annotation_id=791, turn_number=10, source_instance_id=419, source_grp_id=86940,
        source_seat=1, target_instance_id=None, target_grp_id=None, target_seat=2,
        amount=3, damage_type=1,
    )


def test_parse_damage_names_a_creature_target_by_instance():
    annotation = {
        "id": 554, "affectorId": 438, "affectedIds": [424],
        "details": [
            {"key": "damage", "type": "KeyValuePairValueType_int32", "valueInt32": [3]},
            {"key": "type", "type": "KeyValuePairValueType_int32", "valueInt32": [1]},
        ],
    }
    objects = {
        438: {"grpId": 90492, "controllerSeatId": 1},
        424: {"grpId": 86783, "controllerSeatId": 2},
    }
    event = combat.parse_damage(annotation, 8, objects)
    assert event.target_instance_id == 424
    assert event.target_grp_id == 86783
    assert event.target_seat is None


def test_parse_damage_without_an_id_or_amount_is_not_recorded():
    assert combat.parse_damage({"affectorId": 1, "affectedIds": [2]}, 1, {}) is None
    assert combat.parse_damage({"id": 1, "affectedIds": [2]}, 1, {}) is None
    assert combat.parse_damage({"id": 1, "affectorId": 1}, 1, {}) is None


def test_parse_life_change_without_an_affected_seat_is_not_recorded():
    annotation = {
        "id": 145, "affectorId": 9002,
        "details": [{"key": "life", "type": "KeyValuePairValueType_int32", "valueInt32": [-2]}],
    }
    assert combat.parse_life_change(annotation, 1, {}) is None
