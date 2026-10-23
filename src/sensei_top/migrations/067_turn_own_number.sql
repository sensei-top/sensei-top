-- 067_turn_own_number.sql — turns.active_turn_number, the active seat's own
-- turn count (Arena's players[].turnNumber), NULL when the game never gave
-- one. v_self_turns.self_turn_index reads it instead of ranking the rows
-- present, which understated the index whenever a capture lacked turns.
-- Rows fill on the next full projection (PROJECTOR_VERSION 4).

ALTER TABLE turns ADD COLUMN active_turn_number INTEGER;

DROP VIEW v_self_turns;

CREATE VIEW v_self_turns AS
SELECT
    t.match_id, t.game_number, t.turn_number,
    m.source,
    t.active_turn_number AS self_turn_index,
    t.self_life, t.opp_life, t.self_hand, t.opp_hand, t.self_lands, t.self_permanents,
    t.opp_permanents, t.self_library, t.self_graveyard, t.self_open_mana,
    LAG(t.self_permanents) OVER (
        PARTITION BY t.match_id, t.game_number ORDER BY t.turn_number
    ) AS prev_self_permanents
FROM turns t
JOIN matches m USING (match_id)
WHERE m.self_seat IS NOT NULL AND t.active_seat = m.self_seat;
