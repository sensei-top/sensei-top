-- v_matchup_winrate gains format (D14): one row per
-- (opponent_key, deck_id, source, format), because an archetype key can be
-- faced in two formats and the two are different matchups. Recreated from
-- 035_mtgo_source.sql (050 and 056 left it alone) with v_match_opponent's
-- format (056, v_match_format's answer) carried through the CTE and added to
-- the GROUP BY. Matches with no resolved format have format NULL and share
-- one group per key, deck and source, never merged into a named one. The
-- label is now chosen per (opponent_key, format), so a key faced in two
-- formats carries each format's own name; every other column is unchanged.
-- No other view reads v_matchup_winrate.

DROP VIEW v_matchup_winrate;

CREATE VIEW v_matchup_winrate AS
WITH named AS (
    SELECT match_id, deck_id, opponent_key, confidence_rank, opponent_colors, format,
           FIRST_VALUE(opponent_label) OVER (
               PARTITION BY opponent_key, format
               ORDER BY confidence_rank DESC, opponent_cards_seen DESC, match_id
           ) AS opponent_label
      FROM v_match_opponent
)
SELECT
    n.opponent_key,
    n.opponent_label,
    n.deck_id,
    m.source,
    n.format,
    MAX(n.confidence_rank) AS confidence_rank,
    COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw')) AS matches_completed,
    COUNT(*) FILTER (WHERE m.result = 'win')                    AS matches_won,
    SUM(COALESCE(m.games_won, 0))                               AS games_won,
    SUM(COALESCE(m.games_lost, 0))                              AS games_lost,
    MAX(m.started_at)                                           AS last_played,
    NULLIF(
        (CASE WHEN MAX(n.opponent_colors LIKE '%W%') THEN 'W' ELSE '' END) ||
        (CASE WHEN MAX(n.opponent_colors LIKE '%U%') THEN 'U' ELSE '' END) ||
        (CASE WHEN MAX(n.opponent_colors LIKE '%B%') THEN 'B' ELSE '' END) ||
        (CASE WHEN MAX(n.opponent_colors LIKE '%R%') THEN 'R' ELSE '' END) ||
        (CASE WHEN MAX(n.opponent_colors LIKE '%G%') THEN 'G' ELSE '' END),
        ''
    ) AS opponent_colors
FROM named n
JOIN matches m USING (match_id)
GROUP BY n.opponent_key, n.deck_id, m.source, n.format;
