-- 071_game_length_lost.sql — v_deck_game_length counts games lost.
--
-- games counts every game with a recorded length, a drawn or unfinished one
-- included, so a win rate over it read those as losses. games_lost counts
-- result = 'loss' alone, the way games_won counts 'win', so a rate is won
-- over won plus lost. games stays as it is: the average length counts every
-- game. Recreated from 050_views_follow_mtgo_pick.sql with that one column
-- added; no other view reads this one.
DROP VIEW v_deck_game_length;

CREATE VIEW v_deck_game_length AS
SELECT
    md.deck_id,
    m.source,
    g.turn_count,
    COUNT(*)                                                        AS games,
    COUNT(*) FILTER (WHERE g.result = 'win')                        AS games_won,
    COUNT(*) FILTER (WHERE g.result = 'loss')                       AS games_lost
FROM games g
JOIN matches m       USING (match_id)
JOIN v_match_deck md ON md.match_id = m.match_id
WHERE g.turn_count IS NOT NULL
GROUP BY md.deck_id, m.source, g.turn_count;
