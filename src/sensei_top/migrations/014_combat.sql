-- 014_combat.sql — combat declarations and damage/life attribution.
--
-- Verified against a real capture (tests/fixtures/combat_session.log, carved
-- from raw_events already sitting in the local database when the source log
-- itself had since rotated away — see AGENTS.md rule 2, the whole reason
-- raw_events is kept verbatim). docs/arena-log.md previously called combat
-- "deliberately unparsed" for lack of a fixture; that fixture now exists.
--
-- Projector-owned, deleted and rebuilt by project() like every other derived
-- table (AGENTS.md rule 3).
--
-- Three signals, three tables, each event-sourced off the moment Arena's own
-- diff asserts the fact — never read back from an object's merged, possibly
-- stale field (the way turn_zones.is_tapped safely can, because a dedicated
-- untap annotation exists to correct it — see game_state.py's
-- module docstring). No such correcting signal was found for attackState or
-- blockState in the verified capture, so treating "the object currently
-- reads Attacking" as "attacking this turn" would misattribute every later
-- turn the field simply wasn't re-mentioned in. Instead, each table records
-- an observation at the exact turn the asserting diff arrived, deduped per
-- (turn, instance) so Arena's own repeated re-broadcast of the same
-- assertion across consecutive messages (verified: a real Declared/Attacking
-- pair for one attack repeats across 2-3 messages) does not multiply rows.
--
-- combat_attacks: one row per creature seen with an explicit `attackState`
-- (`AttackState_Declared` or `AttackState_Attacking`) on its own game object,
-- naming `attackInfo.targetId`. In every sample in the verified capture this
-- was a player's systemSeatId (matching the seat already used for
-- affectedIds elsewhere) — never confirmed against a planeswalker or battle
-- target, so target_id is stored as Arena's own raw id, not resolved to a
-- kind. `blocked` is NULL unless a combat_blocks row in the same turn names
-- this attacker: absence of an observed block is not evidence of an
-- unblocked attack (rule 4) — Arena's own `BlockState_Unblocked` value,
-- seen on some attackers, was not used here because it was only ever
-- observed on objects without a matching attackState in the same message,
-- leaving its exact pairing unconfirmed.
CREATE TABLE combat_attacks (
    match_id           TEXT NOT NULL,
    game_number        INTEGER NOT NULL,
    turn_number        INTEGER NOT NULL,
    attacker_seat      INTEGER,
    instance_id        INTEGER NOT NULL,
    grp_id             INTEGER,
    target_id          INTEGER,
    blocked            INTEGER,
    PRIMARY KEY (match_id, game_number, turn_number, instance_id),
    FOREIGN KEY (match_id, game_number) REFERENCES games (match_id, game_number)
);

-- combat_blocks: one row per (blocker, attacker) pair seen with an explicit
-- `blockState = "BlockState_Declared"` and `blockInfo.attackerIds` on the
-- blocking creature's own game object. A double block (one attacker, two
-- blockers) is two rows; a double-blocking creature (rare, some blockers can
-- block more than one attacker) is also two rows, one per attacker id in
-- attackerIds — never collapsed, since which creatures actually traded
-- damage is damage_events' job, not this table's.
CREATE TABLE combat_blocks (
    match_id             TEXT NOT NULL,
    game_number          INTEGER NOT NULL,
    turn_number          INTEGER NOT NULL,
    blocker_seat         INTEGER,
    blocker_instance_id  INTEGER NOT NULL,
    blocker_grp_id       INTEGER,
    attacker_instance_id INTEGER NOT NULL,
    PRIMARY KEY (match_id, game_number, turn_number, blocker_instance_id, attacker_instance_id),
    FOREIGN KEY (match_id, game_number) REFERENCES games (match_id, game_number)
);

-- damage_events: one row per AnnotationType_DamageDealt, Arena's own
-- annotation id kept as the dedup key (same discipline card_events already
-- applies to AnnotationType_ZoneTransfer, for the same reason: a raw event
-- can legitimately reach the projector twice — see game_state.py). A NULL
-- target_instance_id means the target was a player, named by target_seat
-- instead: affectedIds carries a small systemSeatId rather than an instance
-- id whenever the target has no card object of its own. damage_type is
-- Arena's own raw code (values 1, 2 and 3 all observed in a real capture,
-- rarity roughly 63%/37%/<1%) with no confirmed public mapping to "combat"
-- vs. "other" — stored verbatim rather than guessed at (rule 4); one
-- verified example in the fixture shows the same source instance dealing
-- type-1 damage in one event and type-2 damage to the same target on the
-- same turn, so the two are not simply "this creature" vs "a spell".
CREATE TABLE damage_events (
    match_id              TEXT NOT NULL,
    game_number           INTEGER NOT NULL,
    annotation_id         INTEGER NOT NULL,
    turn_number           INTEGER,
    source_instance_id    INTEGER,
    source_grp_id         INTEGER,
    source_seat           INTEGER,
    target_instance_id    INTEGER,
    target_grp_id         INTEGER,
    target_seat           INTEGER,
    amount                INTEGER NOT NULL,
    damage_type           INTEGER,
    PRIMARY KEY (match_id, game_number, annotation_id),
    FOREIGN KEY (match_id, game_number) REFERENCES games (match_id, game_number)
);

-- Verified by reconciliation against the real capture: summing life_events'
-- deltas between two consecutive recorded turns agreed with the observed
-- turns.self_life/opp_life change in 104 of 107 real turn transitions
-- checked. The 3 exceptions all shared one shape: two same-turn
-- ModifiedLife annotations from the same affector summed to a larger loss
-- than the life total actually dropped by (e.g. -11 and -7 recorded, but
-- only -11 actually took effect) — consistent with a damage-prevention or
-- similar rules interaction this reader has no way to see, not a parsing
-- bug (the same 3 mismatches persist with each annotation type deduped
-- into its own set, so it is not a dedup collision either). Reported here
-- rather than guessed at: a caller summing life_events for a turn range
-- should treat the result as what Arena *announced*, not a guaranteed
-- reconciliation with the observed life total.
--
-- life_events: one row per AnnotationType_ModifiedLife, same dedup
-- discipline. affector_instance_id/affector_grp_id name whatever caused the
-- change when it has a game object (a land paying life to enter untapped, a
-- creature, a spell on the stack) — NULL when the cause has none. Verified:
-- one life-modification annotation can aggregate several same-turn
-- damage_events sharing a target (two attackers dealing 3 and 5 to the same
-- player summed into one -8 life change attributed to only the first
-- attacker's instance id) — so life_events must never be assumed to pair
-- 1:1 with damage_events, and a caller wanting "why did life change" should
-- treat this table's affector as *a* cause, not *the complete accounting*.
CREATE TABLE life_events (
    match_id              TEXT NOT NULL,
    game_number           INTEGER NOT NULL,
    annotation_id         INTEGER NOT NULL,
    turn_number           INTEGER,
    seat                  INTEGER NOT NULL,
    delta                 INTEGER NOT NULL,
    affector_instance_id  INTEGER,
    affector_grp_id       INTEGER,
    PRIMARY KEY (match_id, game_number, annotation_id),
    FOREIGN KEY (match_id, game_number) REFERENCES games (match_id, game_number)
);

CREATE INDEX idx_damage_events_target ON damage_events (match_id, game_number, target_seat);
CREATE INDEX idx_life_events_seat ON life_events (match_id, game_number, seat);

-- v_combat / v_damage: raw seat -> is_self, the same split v_card_events
-- already uses (003_current_match.sql), so a truncated session without a
-- resolved self_seat still reads meaningfully (is_self NULL, not absent).
CREATE VIEW v_combat_attacks AS
SELECT
    ca.match_id, ca.game_number, ca.turn_number, ca.instance_id, ca.grp_id,
    ca.target_id, ca.blocked,
    c.name AS card_name,
    CASE WHEN m.self_seat IS NULL THEN NULL
         ELSE ca.attacker_seat = m.self_seat END AS is_self
FROM combat_attacks ca
JOIN matches m ON m.match_id = ca.match_id
LEFT JOIN cards c ON c.grp_id = ca.grp_id;

CREATE VIEW v_damage_events AS
SELECT
    d.match_id, d.game_number, d.turn_number, d.amount, d.damage_type,
    d.source_instance_id, d.source_grp_id, sc.name AS source_card_name,
    d.target_instance_id, tc.name AS target_card_name,
    CASE WHEN m.self_seat IS NULL THEN NULL
         WHEN d.target_instance_id IS NOT NULL THEN NULL
         ELSE d.target_seat = m.self_seat END AS target_is_self,
    CASE WHEN m.self_seat IS NULL OR d.source_seat IS NULL THEN NULL
         ELSE d.source_seat = m.self_seat END AS source_is_self
FROM damage_events d
JOIN matches m ON m.match_id = d.match_id
LEFT JOIN cards sc ON sc.grp_id = d.source_grp_id
LEFT JOIN cards tc ON tc.grp_id = d.target_grp_id;
