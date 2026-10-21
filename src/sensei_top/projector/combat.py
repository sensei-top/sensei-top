"""Combat and damage: attack/block declarations, damage and life attribution.

Verified against ``tests/fixtures/combat_session.log`` (see
``migrations/014_combat.sql`` for the full provenance and the traps this
module exists to avoid) and cross-checked against the full real capture that
fixture was carved from: across 1,082 ``AnnotationType_DamageDealt`` and 1,602
``AnnotationType_ModifiedLife`` annotations, ``affectedIds`` was length 1 in
every single case — so a damage or life event never needs to fan out to more
than one target, and the schema does not provide for it.

Arena reports an attack or block as a field directly on the acting creature's
own game object (``attackState``/``attackInfo``, ``blockState``/``blockInfo``),
not as a standalone event, and repeats the same assertion across 2-3
consecutive ``GameStateMessage`` entries for one real attack. Nothing in the
verified capture ever resets ``attackState`` once set (no third value was
ever observed alongside ``AttackState_Declared``/``AttackState_Attacking``),
so treating "the object currently reads Attacking" as "attacking this turn"
would misattribute every later turn the field simply was not re-mentioned in.
So this module is driven from the *raw incoming diff* — the object's own
fields exactly as they arrived in one ``GameStateMessage``, before
``game_state.py`` merges them — and ``GameStateTracker._record_attack`` and
``_record_blocks`` dedupe the repeats, keyed on turn and instance.

``AnnotationType_DamageDealt`` and ``AnnotationType_ModifiedLife`` are deduped
on Arena's annotation id like ``AnnotationType_ZoneTransfer``, but each type in
its own set, never a shared one: ids collide across types within one game (see
``GameStateTracker.__init__``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ATTACK_STATES = ("AttackState_Declared", "AttackState_Attacking")
BLOCK_DECLARED = "BlockState_Declared"


def _detail_int(annotation: dict[str, Any], key: str) -> int | None:
    for entry in annotation.get("details") or []:
        if entry.get("key") == key:
            values = entry.get("valueInt32")
            if values:
                return values[0]
    return None


@dataclass(frozen=True, slots=True)
class AttackDeclared:
    """One creature observed attacking, at the turn the diff asserted it.

    ``target_id`` is Arena's raw ``attackInfo.targetId``: in every sample
    verified this matched a player's ``systemSeatId``, never a planeswalker
    or battle's instance id, but that was never directly confirmed either
    way, so it is stored unresolved rather than assumed to be one or the
    other (rule 4).
    """

    turn_number: int
    seat: int | None
    instance_id: int
    grp_id: int | None
    target_id: int | None


@dataclass(frozen=True, slots=True)
class BlockDeclared:
    """One blocker's own declared block, naming one attacker it blocks.

    A blocker declared against two attackers reports two of these — each
    ``blockInfo.attackerIds`` entry is this blocker's own decision, not a
    guess about how damage will actually be assigned.
    """

    turn_number: int
    seat: int | None
    blocker_instance_id: int
    blocker_grp_id: int | None
    attacker_instance_id: int


@dataclass(frozen=True, slots=True)
class DamageEvent:
    """One ``AnnotationType_DamageDealt``.

    ``target_instance_id``/``target_seat`` are mutually exclusive: Arena
    gives a player no game object, so ``affectedIds`` carries their raw
    ``systemSeatId`` directly in that case, named by ``target_seat`` with
    ``target_instance_id`` left ``None``; a creature target sets
    ``target_instance_id``/``target_grp_id`` and leaves ``target_seat`` `None`
    — its controller lives on ``turn_zones`` already, and filling both would
    give two disagreeing answers to "whose is this" (``v_damage_events``'
    ``target_is_self`` assumes exactly one). ``damage_type`` is
    Arena's own raw code (values 1, 2 and 3 all observed; no confirmed public
    mapping to "combat" vs. "other" — see migrations/014_combat.sql), stored
    verbatim rather than labelled.
    """

    annotation_id: int
    turn_number: int | None
    source_instance_id: int | None
    source_grp_id: int | None
    source_seat: int | None
    target_instance_id: int | None
    target_grp_id: int | None
    target_seat: int | None
    amount: int
    damage_type: int | None


@dataclass(frozen=True, slots=True)
class LifeEvent:
    """One ``AnnotationType_ModifiedLife``.

    ``affector_instance_id``/``affector_grp_id`` name whatever caused the
    change when it has a game object — ``None`` when it does not. Verified:
    one life-modification annotation can aggregate several same-turn damage
    events sharing a target (two attackers dealing 3 and 5 to the same
    player summed into one -8 life change, attributed to only one of the two
    attackers' instance ids) — so this must never be assumed to pair 1:1
    with a single ``DamageEvent``.
    """

    annotation_id: int
    turn_number: int | None
    seat: int
    delta: int
    affector_instance_id: int | None
    affector_grp_id: int | None


def parse_attack(
    raw_obj: dict[str, Any],
    instance_id: int,
    turn_number: int | None,
    resolved: dict[str, Any],
) -> AttackDeclared | None:
    """One attack observation, if this diff entry itself asserts ``attackState``.

    ``raw_obj`` must be the diff's own fields for this instance — containing
    the key is what counts as an assertion, not a merged/possibly-stale read
    (see module docstring). ``resolved`` is the tracker's merged object
    *after* this diff was applied, used only to fill in fields (seat, grpId)
    the diff itself may have omitted because an earlier message already
    supplied them.
    """
    if raw_obj.get("attackState") not in ATTACK_STATES or turn_number is None:
        return None
    info = raw_obj.get("attackInfo") or resolved.get("attackInfo") or {}
    return AttackDeclared(
        turn_number=turn_number,
        seat=resolved.get("controllerSeatId"),
        instance_id=instance_id,
        grp_id=resolved.get("grpId") or None,
        target_id=info.get("targetId"),
    )


def parse_blocks(
    raw_obj: dict[str, Any],
    instance_id: int,
    turn_number: int | None,
    resolved: dict[str, Any],
) -> list[BlockDeclared]:
    """Zero or more block observations, if this diff entry declares a block.

    One entry per attacker in ``blockInfo.attackerIds`` — see ``BlockDeclared``.
    """
    if raw_obj.get("blockState") != BLOCK_DECLARED or turn_number is None:
        return []
    info = raw_obj.get("blockInfo") or resolved.get("blockInfo") or {}
    return [
        BlockDeclared(
            turn_number=turn_number,
            seat=resolved.get("controllerSeatId"),
            blocker_instance_id=instance_id,
            blocker_grp_id=resolved.get("grpId") or None,
            attacker_instance_id=attacker_id,
        )
        for attacker_id in info.get("attackerIds") or []
    ]


def parse_damage(
    annotation: dict[str, Any],
    turn_number: int | None,
    objects: dict[int, dict[str, Any]],
) -> DamageEvent | None:
    """One ``DamageDealt`` annotation. ``objects`` resolves source/target
    identity when either end is a creature; see ``DamageEvent`` for the
    player case.
    """
    annotation_id = annotation.get("id")
    amount = _detail_int(annotation, "damage")
    affected = annotation.get("affectedIds") or []
    if annotation_id is None or amount is None or not affected:
        return None
    source_id = annotation.get("affectorId")
    source_obj = objects.get(source_id) if source_id is not None else None
    target_id = affected[0]
    target_obj = objects.get(target_id)
    return DamageEvent(
        annotation_id=annotation_id,
        turn_number=turn_number,
        source_instance_id=source_id,
        source_grp_id=(source_obj or {}).get("grpId") or None,
        source_seat=(source_obj or {}).get("controllerSeatId"),
        target_instance_id=target_id if target_obj is not None else None,
        target_grp_id=(target_obj or {}).get("grpId") or None,
        # Mutually exclusive with target_instance_id: see DamageEvent.
        target_seat=target_id if target_obj is None else None,
        amount=amount,
        damage_type=_detail_int(annotation, "type"),
    )


def parse_life_change(
    annotation: dict[str, Any],
    turn_number: int | None,
    objects: dict[int, dict[str, Any]],
) -> LifeEvent | None:
    """One ``ModifiedLife`` annotation. ``affectedIds`` names a player's own
    seat directly here — life belongs to a player, never a card, and every
    sample verified was a known seat, never a stray instance id.
    """
    annotation_id = annotation.get("id")
    delta = _detail_int(annotation, "life")
    affected = annotation.get("affectedIds") or []
    if annotation_id is None or delta is None or not affected:
        return None
    affector_id = annotation.get("affectorId")
    affector_obj = objects.get(affector_id) if affector_id is not None else None
    return LifeEvent(
        annotation_id=annotation_id,
        turn_number=turn_number,
        seat=affected[0],
        delta=delta,
        affector_instance_id=affector_id,
        affector_grp_id=(affector_obj or {}).get("grpId") or None,
    )
