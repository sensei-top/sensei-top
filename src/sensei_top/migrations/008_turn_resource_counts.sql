-- 008_turn_resource_counts.sql — graveyard size and untapped-land count per
-- turn snapshot, next to the hand/lands/permanents/library counts already in
-- `turns`; plus a view reconstructing each game's *final kept* opening hand.
--
-- Both new turn columns are new SELECTs over state this project has tracked
-- since M2, not a new parsing rule: self_graveyard/opp_graveyard reuse
-- _zone_counts() the same way self_hand/self_library already do (ZoneType_
-- Graveyard is a real per-seat zone Arena names even when empty, so this
-- distinguishes observed-empty (0) from never-observed (NULL) correctly).
-- self_open_mana/opp_open_mana reuse _battlefield_counts(), the same helper
-- self_lands already uses — and inherit the same asymmetry self_lands already
-- has: a seat with zero qualifying battlefield objects gets no entry in that
-- helper's dict at all, so "tapped out" and "never observed your board" both
-- read NULL. That is a pre-existing characteristic of _battlefield_counts,
-- not something introduced here; see game_state.py.
--
-- "Open mana" means untapped lands, a bluff/interaction-detection proxy —
-- NOT a rules-accurate available-mana count. Arena exposes no mana pool (see
-- arena-log.md). It is symmetric across seats because a battlefield, unlike a
-- hand or library, is public information in Magic: both players' lands and
-- tapped state are always known, with no hidden-information caveat the way
-- self_hand/opp_hand have one.
ALTER TABLE turns ADD COLUMN self_graveyard INTEGER;
ALTER TABLE turns ADD COLUMN opp_graveyard  INTEGER;
ALTER TABLE turns ADD COLUMN self_open_mana INTEGER;
ALTER TABLE turns ADD COLUMN opp_open_mana  INTEGER;

-- library_exit_turn: the turn an instance left the library, by *any* transfer
-- category — not just Draw. Projector-internal (see game_state.py's
-- _left_library_on): unlike drawn_on_turn, which stays narrowly scoped to
-- "was actually drawn" for the turn-by-turn view's own purposes, this exists
-- solely so v_opening_hand below can rule out a card that reached its zone by
-- search, mill or surveil-to-graveyard without ever passing through a hand —
-- verified against the real log, where a fetch land's search target arrives
-- as a "Put" (Library -> Battlefield), not a "Draw", and so still carries a
-- NULL drawn_on_turn that would otherwise be indistinguishable from a
-- genuine opening-hand card. Deliberately left off v_turn_zones: it is not
-- part of what a board snapshot means to a general consumer, only to this
-- one reconstruction.
ALTER TABLE turn_zones ADD COLUMN library_exit_turn INTEGER;

-- The final kept opening hand: every card in any zone at the end of turn 1
-- that has never been observed leaving the library during a turn — neither
-- drawn nor searched/milled/surveilled out of it. Both drawn_on_turn and
-- library_exit_turn are NULL for exactly the cards that were already in a
-- zone before any turn began, which a rejected mulligan attempt's cards
-- cannot be, because those are shuffled back into the library (a zone
-- turn_zones does not track) before the next attempt, and library contents
-- never reach turn 1's snapshot. A card cast, discarded or exiled during
-- turn 1 is still included: it was still part of the hand kept at the start
-- of the game, wherever it ended up by the end of the turn. library_exit_turn
-- is a strict superset of drawn_on_turn (every Draw is Library-sourced), so
-- testing it alone is sufficient — drawn_on_turn is still selected below
-- because TurnZoneCard's shape includes it, not because it does any more
-- filtering here.
--
-- Deliberately turn_number = 1, not MIN(turn_number): if turn 1's snapshot
-- is ever missing (a game abandoned before it was written), falling back to
-- a later turn would misattribute a bounced-back or otherwise-returned card
-- — which also carries NULL for both columns — as part of the opening hand.
-- No rows is the honest answer for that case, the same NULL-not-a-guess rule
-- every other view in this schema follows.
--
-- Built directly off turn_zones/matches/cards, the same shape v_turn_zones
-- itself uses, rather than layered on top of v_turn_zones: library_exit_turn
-- is deliberately not part of that view, so the filter has to live where the
-- column does.
CREATE VIEW v_opening_hand AS
SELECT
    tz.match_id, tz.game_number, tz.zone, tz.idx, tz.instance_id, tz.grp_id,
    c.name AS card_name, tz.card_types, tz.drawn_on_turn,
    tz.is_tapped, tz.power, tz.toughness,
    CASE WHEN m.self_seat IS NULL THEN NULL
         WHEN tz.seat = m.self_seat THEN 1
         ELSE 0 END AS is_self
FROM turn_zones tz
JOIN matches m USING (match_id)
LEFT JOIN cards c ON c.grp_id = tz.grp_id
WHERE tz.turn_number = 1
  AND tz.library_exit_turn IS NULL;
