-- 016_position_view.sql — v_self_turns gains opp_hand.
--
-- review/position.py's card-advantage term needs both sides' hand size, but
-- 011_review_views.sql's v_self_turns never selected opp_hand from turns
-- even though the column has always been there — no analyzer before this
-- one needed the opponent's hand size specifically. Same drop-and-recreate
-- pattern 006_deck_picker.sql already used for v_matchup_winrate: SQLite
-- views cannot be ALTERed.
DROP VIEW v_self_turns;

CREATE VIEW v_self_turns AS
SELECT
    t.match_id, t.game_number, t.turn_number,
    ROW_NUMBER() OVER (
        PARTITION BY t.match_id, t.game_number ORDER BY t.turn_number
    ) AS self_turn_index,
    t.self_life, t.opp_life, t.self_hand, t.opp_hand, t.self_lands, t.self_permanents,
    t.opp_permanents, t.self_library, t.self_graveyard, t.self_open_mana,
    LAG(t.self_permanents) OVER (
        PARTITION BY t.match_id, t.game_number ORDER BY t.turn_number
    ) AS prev_self_permanents
FROM turns t
JOIN matches m USING (match_id)
WHERE m.self_seat IS NOT NULL AND t.active_seat = m.self_seat;
