-- 066_play_draw_games_lost.sql — v_play_draw_winrate counts games lost.
--
-- games_completed counts a drawn game, and the view had no losses column, so
-- a reader could only take a side's losses as completed minus won: a draw
-- read as a loss. games_lost counts result = 'loss' alone, the
-- same way games_won counts 'win'. Recreated from 050_views_follow_mtgo_pick.sql
-- with that one column added; no other view reads this one.
DROP VIEW v_play_draw_winrate;

CREATE VIEW v_play_draw_winrate AS
SELECT
    md.deck_id,
    m.source,
    g.on_play,
    COUNT(*) FILTER (WHERE g.result IN ('win', 'loss', 'draw'))     AS games_completed,
    COUNT(*) FILTER (WHERE g.result = 'win')                        AS games_won,
    COUNT(*) FILTER (WHERE g.result = 'loss')                       AS games_lost
FROM games g
JOIN matches m       USING (match_id)
JOIN v_match_deck md ON md.match_id = m.match_id
WHERE g.on_play IS NOT NULL
GROUP BY md.deck_id, m.source, g.on_play;
