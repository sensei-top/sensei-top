"""M2: per-game board-state accumulation, feeding turn-by-turn snapshots.

``GameStateMessage`` entries are full snapshots or partial diffs with **no
flag distinguishing them** (brief §6): fields must be merged in as they
arrive and deletions purged explicitly via ``diffDeletedInstanceIds``. This
module owns that merge and the turn-snapshot rule. ``matches.py`` decides
*when* a fresh tracker is needed (one per game, via ``GameState.tracker``'s
default factory) and *when* to finalize the trailing turn (``GameOver``).

Field paths verified against the same fixture session as M1:

* ``gameStateMessage.gameObjects[]`` — ``instanceId`` keyed, merged field by
  field (a diff entry may carry only the fields that changed).
* ``…zones[]`` — ``zoneId`` keyed; ``objectInstanceIds`` is authoritative
  *per update* (replaces, not merges) when present.
* ``…annotations[]`` with ``type`` containing ``AnnotationType_ObjectIdChanged``
  — re-keys an object (and any zone list referencing it) from ``orig_id`` to
  ``new_id``. ``type`` is an array even when single-valued; annotation data
  lives in a uniform ``details[]`` array of ``{"key": ..., "valueInt32": [...]}``
  entries.
* ``…annotations[]`` with ``AnnotationType_ZoneTransfer`` — one card moving
  between zones: ``zone_src`` / ``zone_dest`` (zone ids, ``valueInt32``),
  ``category`` (``valueString``: ``Draw``, ``CastSpell``, ``PlayLand``,
  ``Put``, ``Resolve``, …) and the moved instances in ``affectedIds``. A card
  transfer is recorded whether or not we can see what the card is.
* ``…annotations[]`` with ``AnnotationType_TappedUntappedPermanent`` — the
  **only** signal that a permanent untapped. ``details[]`` carries
  ``{"key": "tapped", "valueInt32": [1 | 0]}`` and ``affectedIds`` names the
  permanents. See ``_apply_tapped`` for why the game object alone is not enough.
* ``…annotations[].id`` — Arena's own identifier for the annotation instance,
  assigned by the game engine. Verified against 976 real ZoneTransfer
  annotations across two overlapping session logs: never missing, and never
  reused for different content *within one game* (it does reset to a low
  number at the start of each new game, so it is only unique per
  ``(match, game)``, never across a whole session). That makes it the record's
  own identity rather than its position in whatever raw event happened to
  carry it, and is what ``card_events`` dedupes on — see ``_record_transfer``.
* ``…diffDeletedInstanceIds[]`` — purge from objects and every zone list.
* ``…players[]`` — sibling of ``gameInfo``/``turnInfo``; ``systemSeatNumber``
  + ``lifeTotal``.
* ``…turnInfo.turnNumber`` / ``activePlayer`` — turn boundary and active seat.

``turnInfo.turnNumber`` counts **player-turns, not rounds**: a game where each
player took 12 turns reports ``turnNumber: 24``, and the per-seat
``players[].turnNumber`` in that same message reads 12. So a ``turns`` row is
one player's turn, and a game's turn count is roughly twice its round count.

A turn's snapshot is the accumulated state **at the end of that turn**: it is
finalized when ``turnNumber`` next advances, or at ``GameOver`` for the final
turn played. Re-finalizing the same turn number overwrites (last write wins),
so replaying the same events twice is deterministic.

``card_events`` is append-only in ``seq`` order, which makes it the one piece
of state here that is *not* naturally idempotent under replay: two passes over
the same ``AnnotationType_ZoneTransfer`` would otherwise append it twice. So
``_record_transfer`` dedupes on the annotation's own ``id`` before appending —
not a defensive measure against malformed input, but a real necessity: a raw
event can legitimately reach the projector more than once (``ingest.py``
dedupes what it reads, but a source file can itself carry the same message
twice, e.g. a near-total overlap between ``Player.log`` and the
``Player-prev.log`` it rotated from), and every other piece of derived state
here already tolerates that by overwriting. ``card_events`` needed the same
guarantee, just enforced differently because it accumulates instead of
snapshotting.

Exile is a **shared** zone: verified against the real log, ``ZoneType_Exile``
carries no ``ownerSeatId`` (unlike hand, graveyard and library, which all do),
so the seat comes from each exiled object's own ``ownerSeatId``. That makes it
the one owned-looking zone that follows the battlefield's rule instead of the
hand's: an entry whose object we never received is dropped rather than emitted
as a hidden card. The trade-off is deliberate — with no zone owner and no
object there is nothing to attribute the card to, so emitting it would mean
inventing a seat.

Library size is counted from ``ZoneType_Library`` itself, not by subtracting
draws from the decklist: Arena sends the zone's ``objectInstanceIds``, so the
count is observed rather than derived, and a Bo3 sideboard changing the deck
between games needs no special case.

Arena keeps emitting state for a game *after* its ``GameOver`` — and an
abandoned game never gets a ``GameOver`` at all. Either way the last turn can
be left unrecorded, so ``flush_trailing()`` is called once at the end of the
replay to fill that gap. It deliberately does not overwrite a turn already
snapshotted at ``GameOver``, so post-game cleanup messages can never rewrite
the state a game actually ended on.

Combat and damage: ``gameObjects[].attackState``/``attackInfo`` and
``blockState``/``blockInfo``, and annotations ``AnnotationType_DamageDealt``
and ``AnnotationType_ModifiedLife``. All four are handled the same way the
rest of this module handles a diff — merged/observed as they arrive — but the
attack/block pair specifically must be read from the *raw incoming diff*,
never from ``self.objects``' merged state, because nothing was found in a
real capture that ever resets ``attackState``/``blockState`` once set. See
``projector/combat.py`` for the full reasoning and the parsing itself; this
module only decides where in the existing merge passes to call it.

Each annotation type gets its **own** dedup set (``_seen_transfer_ids``,
``_seen_damage_ids``, ``_seen_life_ids``), not one shared set: a real capture
showed Arena reusing the same annotation ``id`` across genuinely different
types within one game (confirmed: a ``ZoneTransfer`` and an unrelated
``PhaseOrStepModified`` sharing an id in the same match). A shared set would
silently drop a real event whenever its id happened to collide with an
unrelated, earlier annotation of a different type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sensei_top.projector import combat


@dataclass
class TurnRow:
    """One finalized turn snapshot. Values are keyed by ``systemSeatNumber``.

    ``matches.py`` maps seat -> self/opp at persistence time (the same
    pattern already used for ``GameState.mulligans``). A seat absent from a
    dict here was simply never observed — callers must not synthesize 0.
    """

    turn_number: int
    active_seat: int | None = None
    life: dict[int, int] = field(default_factory=dict)
    hand: dict[int, int] = field(default_factory=dict)
    permanents: dict[int, int] = field(default_factory=dict)
    lands: dict[int, int] = field(default_factory=dict)
    library: dict[int, int] = field(default_factory=dict)
    graveyard: dict[int, int] = field(default_factory=dict)
    open_mana: dict[int, int] = field(default_factory=dict)
    # Untapped NON-land permanents whose grpId is known to produce mana
    # (cards.produced_mana on file) — mana rocks, dorks, Treasures. A sibling
    # count to open_mana, not a replacement: open_mana's meaning (untapped
    # lands) never changes, since turns.opp_open_mana already has consumers
    # (the post-game report) that must not be silently rewritten. Only
    # populated when the tracker was built with mana_source_grp_ids; empty
    # otherwise, same as any other honestly-unknown count (rule 4).
    other_mana_sources: dict[int, int] = field(default_factory=dict)
    cards: list[ZoneCard] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ZoneCard:
    """One card in one zone at the end of one turn — the identities behind a
    ``TurnRow``'s bare counts.

    ``seat`` stays raw, same contract as ``CardEvent``: ``matches.py`` owns the
    self/opp mapping. ``grp_id`` is NULL for a card hidden from us (an
    opponent's hand) or face-down — same collapsing rule as ``CardEvent``.
    ``idx`` is a position within ``(zone, seat)`` for this turn, assigned by
    ``_zone_cards`` — not the position within Arena's zone list, which is
    shared by both players' graveyards and split across battlefield
    controllers.

    ``is_tapped`` is battlefield-only and ``None`` everywhere else: a card in
    hand or in a graveyard has no orientation, and ``None`` says that rather
    than claiming it is untapped. ``power``/``toughness`` are Arena's *current*
    values, ``None`` for anything that has none.
    """

    zone: str
    seat: int
    idx: int
    instance_id: int
    grp_id: int | None
    card_types: str | None
    drawn_on_turn: int | None
    is_tapped: bool | None = None
    power: int | None = None
    toughness: int | None = None


@dataclass(frozen=True, slots=True)
class CardEvent:
    """One card moving between zones, in the order it was observed.

    ``grp_id`` is NULL whenever the card was hidden from us: Arena simply
    omits the game object for a card we are not allowed to see, so an
    opponent's draw is a transfer with no identity. That is the expected
    shape of hidden information, not a parse failure, so it is not warned
    about. ``seat`` stays raw — ``matches.py`` owns the self/opp mapping.
    """

    seq: int
    turn_number: int | None
    seat: int | None
    grp_id: int | None
    category: str | None
    zone_src: str | None
    zone_dest: str | None


def _detail(annotation: dict[str, Any], key: str) -> int | None:
    for entry in annotation.get("details") or []:
        if entry.get("key") == key:
            values = entry.get("valueInt32")
            if values:
                return values[0]
    return None


def _value(field_value: Any) -> int | None:
    """Unwrap Arena's ``{"value": 3}`` boxing, used for power and toughness.

    Absent on anything without the characteristic, and boxed rather than bare
    because Arena models a characteristic-defining ``*`` as the same shape with
    no ``value`` key. Both collapse to None: unknown, never 0.
    """
    if isinstance(field_value, dict):
        value = field_value.get("value")
        return value if isinstance(value, int) else None
    return None


def _detail_str(annotation: dict[str, Any], key: str) -> str | None:
    """``details[]`` again, for the string-valued keys (``category``)."""
    for entry in annotation.get("details") or []:
        if entry.get("key") == key:
            values = entry.get("valueString")
            if values:
                return values[0]
    return None


class GameStateTracker:
    """Accumulates one game's board state from GameStateMessage snapshots/diffs."""

    def __init__(self, *, mana_source_grp_ids: frozenset[int] = frozenset()) -> None:
        # Non-land grpIds known to produce mana (cards.produced_mana on
        # file) — mana rocks, dorks, Treasures. Empty by default so every
        # existing caller (project()'s per-game tracker included) behaves
        # byte-identically; only a caller that explicitly wants the wider
        # count (table/live.py, for the live opponent-hand read) supplies
        # it. See TurnRow.other_mana_sources.
        self._mana_source_grp_ids = mana_source_grp_ids
        self.objects: dict[int, dict[str, Any]] = {}
        self.zones: dict[int, dict[str, Any]] = {}
        self.life: dict[int, int] = {}
        self.turns: dict[int, TurnRow] = {}
        self.card_events: list[CardEvent] = []
        self.attacks: list[combat.AttackDeclared] = []
        self.blocks: list[combat.BlockDeclared] = []
        self.damage_events: list[combat.DamageEvent] = []
        self.life_events: list[combat.LifeEvent] = []
        self._current_turn: int | None = None
        self._current_active_seat: int | None = None
        # One set per annotation *type*, not one shared set: verified against
        # a real capture that Arena's annotation id is only unique within one
        # type within one game — confirmed collisions exist in real data
        # between, e.g., a ZoneTransfer and an unrelated PhaseOrStepModified
        # reusing the same id in the same game. Within a single type, id was
        # verified unique per (match, game) except for genuine re-broadcasts
        # of the same event, which is exactly what these sets exist to catch.
        self._seen_transfer_ids: set[int] = set()
        self._seen_damage_ids: set[int] = set()
        self._seen_life_ids: set[int] = set()
        # (turn_number, instance_id) pairs already recorded, so Arena's own
        # repeated re-broadcast of the same attack/block assertion across
        # consecutive messages (verified in a real capture) does not multiply
        # rows — see projector/combat.py's module docstring.
        self._seen_attacks: set[tuple[int, int]] = set()
        self._seen_blocks: set[tuple[int, int, int]] = set()
        # instanceId -> turn drawn. History, not board state, so it survives a
        # full-snapshot reset the same way card_events does — see _zone_cards.
        self._drawn_on: dict[int, int] = {}

    def apply(self, gsm: dict[str, Any]) -> None:
        """Merge one GameStateMessage (full or diff) into accumulated state."""
        if gsm.get("type") == "GameStateType_Full":
            # A full snapshot is authoritative on its own; anything accumulated
            # so far (including now-stale hidden objects) must not survive it,
            # since deletions only ever arrive on diffs. card_events is history
            # rather than board state, so it deliberately survives.
            self.objects.clear()
            self.zones.clear()

        for obj in gsm.get("gameObjects") or []:
            instance_id = obj.get("instanceId")
            if instance_id is not None:
                merged = self.objects.setdefault(instance_id, {})
                merged.update(obj)
                # Detection uses obj (this diff's own fields, before merging)
                # so a stale merged value can never be mistaken for a fresh
                # assertion; resolution (seat, grpId) uses the merged entry
                # so fields an earlier message already supplied are not lost
                # — see combat.py's module docstring.
                self._record_attack(obj, instance_id, merged)
                self._record_blocks(obj, instance_id, merged)

        for zone in gsm.get("zones") or []:
            zone_id = zone.get("zoneId")
            if zone_id is None:
                continue
            stored = self.zones.setdefault(zone_id, {})
            for key, value in zone.items():
                stored[key] = list(value) if key == "objectInstanceIds" else value

        # Order matters and is Arena's own: a card entering play is re-keyed by
        # an ObjectIdChanged annotation that sits immediately before the
        # ZoneTransfer naming the new id, in this same array. Handling both in
        # one ordered pass is what lets the transfer find the card's grpId.
        for annotation in gsm.get("annotations") or []:
            types = annotation.get("type") or []
            if "AnnotationType_ObjectIdChanged" in types:
                self._rekey(_detail(annotation, "orig_id"), _detail(annotation, "new_id"))
            if "AnnotationType_ZoneTransfer" in types:
                self._record_transfer(annotation)
            if "AnnotationType_DamageDealt" in types:
                self._record_damage(annotation)
            if "AnnotationType_ModifiedLife" in types:
                self._record_life_change(annotation)

        for instance_id in gsm.get("diffDeletedInstanceIds") or []:
            self._delete(instance_id)

        for player in gsm.get("players") or []:
            seat = player.get("systemSeatNumber")
            life = player.get("lifeTotal")
            if seat is not None and life is not None:
                self.life[seat] = life

        turn = gsm.get("turnInfo")
        if isinstance(turn, dict):
            number = turn.get("turnNumber")
            if isinstance(number, int):
                if self._current_turn is not None and number != self._current_turn:
                    self._finalize(self._current_turn)
                self._current_turn = number
                if (active := turn.get("activePlayer")) is not None:
                    self._current_active_seat = active

        # Tap/untap lands *after* the turn boundary above, unlike every other
        # annotation. Untapping is reported at the new turn's untap step, and
        # Arena puts that annotation in the same message that advances
        # turnInfo — verified in the fixture, where all five untaps ride a
        # message reading `turnNumber: 3, step: Step_Upkeep`. Applied before the
        # boundary they would untap the board of the turn that just *ended*,
        # showing every land upright on the very turn it was tapped for mana.
        # A mid-turn untap effect rides a message that crosses no boundary, so
        # it still lands on the turn it happened in.
        for annotation in gsm.get("annotations") or []:
            if "AnnotationType_TappedUntappedPermanent" in (annotation.get("type") or []):
                self._apply_tapped(annotation)

    @property
    def current_turn(self) -> int | None:
        """The turn number in progress right now, or ``None`` before the
        first ``turnInfo`` (mulligan phase). Public so ``projector/live_state.py``
        can read it without touching a private attribute across modules."""
        return self._current_turn

    @property
    def current_active_seat(self) -> int | None:
        return self._current_active_seat

    def snapshot_now(self) -> TurnRow:
        """The board state exactly as it stands right now, mid-turn — the
        same fields ``_finalize`` produces, but never written to
        ``self.turns`` and never overwritten by a later boundary. This is
        what a request-time live read wants (``projector/live_state.py``):
        it cannot wait for a turn boundary to finalize a row the way
        ``project()`` does, and must never collide with a real finalized
        turn if this same tracker is later asked to finalize one for real.

        ``turn_number`` is forced to 0 when no turn has started yet (still
        in the mulligan phase) since ``TurnRow.turn_number`` is a plain
        ``int`` by contract — callers that care about "no turn yet" as a
        distinct fact should read the ``current_turn`` property instead,
        which stays ``None`` in that case.
        """
        return TurnRow(
            turn_number=self._current_turn or 0,
            active_seat=self._current_active_seat,
            life=dict(self.life),
            hand=self._zone_counts("ZoneType_Hand"),
            permanents=self._battlefield_counts(),
            lands=self._battlefield_counts(land_only=True),
            library=self._zone_counts("ZoneType_Library"),
            graveyard=self._zone_counts("ZoneType_Graveyard"),
            open_mana=self._battlefield_counts(land_only=True, untapped_only=True),
            other_mana_sources=self._battlefield_counts(
                other_mana_sources_only=True, untapped_only=True
            ),
            cards=self._zone_cards(),
        )

    def finalize_current(self) -> None:
        """Snapshot the current turn, overwriting. Call at GameOver."""
        if self._current_turn is not None:
            self._finalize(self._current_turn)

    def flush_trailing(self) -> None:
        """Snapshot the current turn only if nothing recorded it yet.

        The safety net for turns that outlive their GameOver (or never get
        one). Non-overwriting on purpose — see the module docstring.
        """
        if self._current_turn is not None and self._current_turn not in self.turns:
            self._finalize(self._current_turn)

    def _rekey(self, orig_id: int | None, new_id: int | None) -> None:
        if orig_id is None or new_id is None or orig_id == new_id:
            return
        if orig_id in self.objects:
            stale = self.objects.pop(orig_id)
            # Fields already recorded at new_id (e.g. from a gameObjects entry
            # earlier in this same message) are the post-transition truth and
            # must win over the pre-transition fields carried from orig_id.
            self.objects[new_id] = {**stale, **self.objects.get(new_id, {})}
        for zone in self.zones.values():
            ids = zone.get("objectInstanceIds")
            if ids and orig_id in ids:
                zone["objectInstanceIds"] = [new_id if i == orig_id else i for i in ids]
        if orig_id in self._drawn_on:
            self._drawn_on[new_id] = self._drawn_on.pop(orig_id)

    @staticmethod
    def _first_sighting(seen: set[int], annotation_id: int | None) -> bool:
        """True unless ``annotation_id`` was already recorded in ``seen``.

        ``seen`` must be the set for this annotation's own type — see the
        constructor's comment for why one set cannot safely serve every
        type. A missing id is never treated as a guessed duplicate — it is
        always a first sighting, because there is nothing to dedupe it
        against.
        """
        if annotation_id is None:
            return True
        if annotation_id in seen:
            return False
        seen.add(annotation_id)
        return True

    def _record_transfer(self, annotation: dict[str, Any]) -> None:
        """Record one ZoneTransfer: which card went from which zone to which.

        Called from the annotations pass, so the id has already been re-keyed
        if this same message re-keyed it. The turn number is whatever turn is
        current *now*: ``turnInfo`` is merged after annotations, so a transfer
        riding the message that also ends the turn is attributed to the turn it
        happened in rather than the one starting. That ordering is what keeps
        the turn snapshot pre-advance, and must not be swapped.
        """
        if not self._first_sighting(self._seen_transfer_ids, annotation.get("id")):
            return

        src = self.zones.get(_detail(annotation, "zone_src")) or {}
        dest = self.zones.get(_detail(annotation, "zone_dest")) or {}
        # Shared zones (stack, limbo) carry no ownerSeatId, so the owned end of
        # the move is what names the seat; a stack-to-stack move names neither.
        seat = src.get("ownerSeatId") or dest.get("ownerSeatId")
        category = _detail_str(annotation, "category")

        for instance_id in annotation.get("affectedIds") or []:
            obj = self.objects.get(instance_id) or {}
            self.card_events.append(
                CardEvent(
                    seq=len(self.card_events),
                    turn_number=self._current_turn,
                    # A hidden card has no object at all, and a face-down one
                    # reports grpId 0. Both mean "we do not know what this is".
                    seat=seat if seat is not None else obj.get("ownerSeatId"),
                    grp_id=obj.get("grpId") or None,
                    category=category,
                    zone_src=src.get("type"),
                    zone_dest=dest.get("type"),
                )
            )
            # A None turn means an opening-hand transfer (mulligan put-backs
            # included) — deliberately not "drawn" for the UI's purposes.
            if category == "Draw" and self._current_turn is not None:
                self._drawn_on[instance_id] = self._current_turn

    def _record_attack(
        self, raw_obj: dict[str, Any], instance_id: int, resolved: dict[str, Any]
    ) -> None:
        attack = combat.parse_attack(raw_obj, instance_id, self._current_turn, resolved)
        if attack is None:
            return
        key = (attack.turn_number, instance_id)
        if key in self._seen_attacks:
            return
        self._seen_attacks.add(key)
        self.attacks.append(attack)

    def _record_blocks(
        self, raw_obj: dict[str, Any], instance_id: int, resolved: dict[str, Any]
    ) -> None:
        for block in combat.parse_blocks(raw_obj, instance_id, self._current_turn, resolved):
            key = (block.turn_number, instance_id, block.attacker_instance_id)
            if key in self._seen_blocks:
                continue
            self._seen_blocks.add(key)
            self.blocks.append(block)

    def _record_damage(self, annotation: dict[str, Any]) -> None:
        if not self._first_sighting(self._seen_damage_ids, annotation.get("id")):
            return
        event = combat.parse_damage(annotation, self._current_turn, self.objects)
        if event is not None:
            self.damage_events.append(event)

    def _record_life_change(self, annotation: dict[str, Any]) -> None:
        if not self._first_sighting(self._seen_life_ids, annotation.get("id")):
            return
        event = combat.parse_life_change(annotation, self._current_turn, self.objects)
        if event is not None:
            self.life_events.append(event)

    def _apply_tapped(self, annotation: dict[str, Any]) -> None:
        """Write a tap/untap back onto the game object, which is otherwise stale.

        Arena only ever *sets* ``isTapped``. Counted over the full real log:
        149 game objects carry ``isTapped: true`` and **not one** carries
        ``isTapped: false``, while ``AnnotationType_TappedUntappedPermanent``
        appears 166 times, 87 with ``tapped: 1`` and 79 with ``tapped: 0``. So a
        permanent that taps for mana and untaps next upkeep keeps a stale
        ``isTapped: true`` on the merged object forever — field-level diff
        merging (see ``apply``) has nothing to overwrite it with. The annotation
        is the only untap signal there is, and folding it back into the object
        keeps that object the single source of truth for ``_zone_cards``.

        Deliberately **not** deduped on annotation id, unlike
        ``_record_transfer``: this is an idempotent write to a keyed field
        rather than an append, so replaying it is harmless, and skipping a
        repeat could otherwise drop a legitimate re-tap that reuses an id
        across games.

        Runs in its own pass after the turn boundary rather than in the main
        annotation loop — see the call site for why that ordering is
        load-bearing. Rekeys have already been applied by then, so an untap
        naming a permanent that changed id in this message lands on the new id.
        """
        tapped = _detail(annotation, "tapped")
        if tapped is None:
            return
        for instance_id in annotation.get("affectedIds") or []:
            # Only correct objects we actually know about. Creating a bare entry
            # here would invent a battlefield permanent with no controller.
            if (obj := self.objects.get(instance_id)) is not None:
                obj["isTapped"] = bool(tapped)

    def _delete(self, instance_id: int) -> None:
        self.objects.pop(instance_id, None)
        for zone in self.zones.values():
            ids = zone.get("objectInstanceIds")
            if ids and instance_id in ids:
                zone["objectInstanceIds"] = [i for i in ids if i != instance_id]

    def _finalize(self, turn_number: int) -> None:
        self.turns[turn_number] = TurnRow(
            turn_number=turn_number,
            active_seat=self._current_active_seat,
            life=dict(self.life),
            hand=self._zone_counts("ZoneType_Hand"),
            permanents=self._battlefield_counts(),
            lands=self._battlefield_counts(land_only=True),
            library=self._zone_counts("ZoneType_Library"),
            graveyard=self._zone_counts("ZoneType_Graveyard"),
            open_mana=self._battlefield_counts(land_only=True, untapped_only=True),
            cards=self._zone_cards(),
        )

    def _zone_counts(self, zone_type: str) -> dict[int, int]:
        counts: dict[int, int] = {}
        for zone in self.zones.values():
            if zone.get("type") != zone_type:
                continue
            owner = zone.get("ownerSeatId")
            if owner is None:
                continue
            counts[owner] = counts.get(owner, 0) + len(zone.get("objectInstanceIds") or [])
        return counts

    def _battlefield_counts(
        self,
        *,
        land_only: bool = False,
        untapped_only: bool = False,
        other_mana_sources_only: bool = False,
    ) -> dict[int, int]:
        """``other_mana_sources_only`` counts untapped *non-land* permanents
        whose grpId is in ``self._mana_source_grp_ids`` — mana rocks, dorks,
        Treasures. Lands are excluded even when they'd match, so this never
        double-counts anything ``land_only`` already covers; empty whenever
        the tracker was built with no ``mana_source_grp_ids`` at all."""
        counts: dict[int, int] = {}
        for zone in self.zones.values():
            if zone.get("type") != "ZoneType_Battlefield":
                continue
            for instance_id in zone.get("objectInstanceIds") or []:
                obj = self.objects.get(instance_id)
                if obj is None:
                    continue
                controller = obj.get("controllerSeatId")
                if controller is None:
                    continue
                # Arena's own live vocabulary (GameObject.cardTypes), not a
                # `cards.type_line` string -- no em-dash split needed, so
                # this is not a case for review/effects.py::is_land.
                card_types = obj.get("cardTypes") or []
                if land_only and "CardType_Land" not in card_types:
                    continue
                if other_mana_sources_only and (
                    "CardType_Land" in card_types
                    or obj.get("grpId") not in self._mana_source_grp_ids
                ):
                    continue
                # Same idiom _zone_cards uses for is_tapped: Arena only ever
                # *sets* isTapped, so an absent key already means untapped.
                if untapped_only and bool(obj.get("isTapped")):
                    continue
                counts[controller] = counts.get(controller, 0) + 1
        return counts

    def _zone_cards(self) -> list[ZoneCard]:
        """Card identities behind ``_zone_counts``/``_battlefield_counts``,
        using the same seat rules so the two can never disagree: hand and
        graveyard key on the zone's owner, battlefield keys on each object's
        controller. A hand/graveyard instance with no known object is not
        skipped — that is the shape of a hidden card, not missing data, and
        dropping it would make the row count disagree with ``self_hand``.

        Exile is the exception on both counts: it is a shared zone with no
        ``ownerSeatId`` (see the module docstring), so it keys on each object's
        *owner* — who the card belongs to, not who exiled it — and an entry with
        no object is dropped, because nothing would name its seat. It also has
        no matching count on ``TurnRow``, so nothing can disagree with it.
        """
        cards: list[ZoneCard] = []
        next_idx: dict[tuple[str, int], int] = {}

        def _emit(zone_label: str, seat: int, instance_id: int) -> None:
            key = (zone_label, seat)
            idx = next_idx.get(key, 0)
            next_idx[key] = idx + 1
            obj = self.objects.get(instance_id) or {}
            cards.append(
                ZoneCard(
                    zone=zone_label,
                    seat=seat,
                    idx=idx,
                    instance_id=instance_id,
                    # Same collapsing rule as _record_transfer: no object at
                    # all, or a face-down grpId 0, both mean "unknown to us".
                    grp_id=obj.get("grpId") or None,
                    card_types=",".join(obj.get("cardTypes") or []) or None,
                    drawn_on_turn=self._drawn_on.get(instance_id),
                    # Only a permanent has an orientation. Elsewhere None says
                    # "does not apply" rather than claiming untapped, and on the
                    # battlefield an absent isTapped really is untapped: Arena
                    # never sends the false, only _apply_tapped's annotation.
                    is_tapped=bool(obj.get("isTapped")) if zone_label == "battlefield" else None,
                    power=_value(obj.get("power")),
                    toughness=_value(obj.get("toughness")),
                )
            )

        zone_labels = {"ZoneType_Hand": "hand", "ZoneType_Graveyard": "graveyard"}
        for zone in self.zones.values():
            label = zone_labels.get(zone.get("type"))
            if label is None:
                continue
            owner = zone.get("ownerSeatId")
            if owner is None:
                continue
            for instance_id in zone.get("objectInstanceIds") or []:
                _emit(label, owner, instance_id)

        # Battlefield and exile share a shape: one zone list covering both
        # players, so the seat has to come off each object rather than the zone.
        # They differ only in which seat field answers "whose side is this on" —
        # control for a permanent in play, ownership for a card set aside.
        for zone in self.zones.values():
            zone_type = zone.get("type")
            if zone_type == "ZoneType_Battlefield":
                label, seat_key = "battlefield", "controllerSeatId"
            elif zone_type == "ZoneType_Exile":
                label, seat_key = "exile", "ownerSeatId"
            else:
                continue
            for instance_id in zone.get("objectInstanceIds") or []:
                obj = self.objects.get(instance_id)
                if obj is None:
                    continue
                seat = obj.get(seat_key)
                if seat is None:
                    continue
                _emit(label, seat, instance_id)

        return cards
