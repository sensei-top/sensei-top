-- 007_board_detail.sql — the board fields Arena has always sent and the
-- projector has always dropped.
--
-- The turn-by-turn view draws a Magic table: two halves mirrored across a
-- center line, hand outermost, then lands, then nonlands. Three things were
-- missing to make that table readable, and all three were already sitting in
-- `GameStateTracker.objects` verbatim, discarded only at the ZoneCard boundary.
--
-- * is_tapped — a 90-degree rotation is Magic's only rules-sanctioned
--   orientation signal (MTR 4.7) and the fastest read on a real board. Verified
--   against the real log: Arena sends `isTapped: true` on the game object and
--   *never* sends `isTapped: false` (149 true, 0 false). Untapping arrives only
--   as AnnotationType_TappedUntappedPermanent with `tapped: 0` (87 taps, 79
--   untaps), so the merged object goes stale without that annotation — see
--   `_apply_tapped` in game_state.py. Battlefield only; NULL in every other
--   zone, because only a permanent can be tapped.
-- * power / toughness — the *current* values Arena reports, not the printed
--   ones, which is what a snapshot of the board should show. NULL for anything
--   that has no power, and NULL whenever Arena did not send it.
-- * exile joins hand, battlefield and graveyard as a fourth `zone` value. It is
--   a zone the table has, and until now it was visible only as a card_events
--   endpoint.
--
-- NULL keeps its usual meaning here (AGENTS.md rule 4): "does not apply, or was
-- never observed". It is never a stand-in for 0 or for false.
--
-- `zone` has no CHECK constraint, so admitting a fourth value needs no table
-- rebuild. The view is dropped and recreated because SQLite views are frozen at
-- creation and would not otherwise see the new columns.
ALTER TABLE turn_zones ADD COLUMN is_tapped INTEGER;  -- battlefield only; NULL elsewhere
ALTER TABLE turn_zones ADD COLUMN power     INTEGER;  -- current, not printed
ALTER TABLE turn_zones ADD COLUMN toughness INTEGER;

DROP VIEW v_turn_zones;

-- Unchanged from 005 apart from the three new columns: still mirrors
-- v_card_events, mapping the raw seat to self/opp and joining the downloaded
-- card names, reporting NULL when it cannot.
CREATE VIEW v_turn_zones AS
SELECT
    tz.match_id, tz.game_number, tz.turn_number, tz.zone, tz.idx,
    tz.instance_id, tz.grp_id, tz.card_types, tz.drawn_on_turn,
    tz.is_tapped, tz.power, tz.toughness,
    c.name AS card_name,
    CASE WHEN m.self_seat IS NULL THEN NULL
         WHEN tz.seat = m.self_seat THEN 1
         ELSE 0 END AS is_self
FROM turn_zones tz
JOIN matches m USING (match_id)
LEFT JOIN cards c ON c.grp_id = tz.grp_id;
