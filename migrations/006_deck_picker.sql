-- 006_deck_picker.sql — replace the free-text "name it" override with a pick
-- from the classifier's own ranked candidate list.
--
-- The override table now stores which archetype the user picked, not just
-- text they typed. archetype_key is NULL for "Rogue" (Magic's term for a
-- deck with no established archetype) and set otherwise, so a picked
-- archetype merges into the same matchup as matches the classifier itself
-- named that way, rather than splitting off under its own manual: key.
ALTER TABLE opponent_deck_override ADD COLUMN archetype_key TEXT;

-- The free-text era produced labels typed by hand (e.g. "MonoGreen
-- Landfall") that do not correspond to any archetype_key and cannot be
-- reconciled with the picker's candidate list. There is exactly one such
-- row in practice; wiping the table lets the classifier's own verdict (or a
-- fresh pick) take over instead of leaving stale, unkeyed text behind.
DELETE FROM opponent_deck_override;

DROP VIEW v_matchup_winrate;
DROP VIEW v_match_opponent;

CREATE VIEW v_match_opponent AS
SELECT
    m.match_id,
    m.deck_id,
    COALESCE(
        o.label,
        a.label,
        COALESCE(NULLIF(v.colors, '') || ' ' || char(183) || ' ', '') || v.signature_card,
        'Unknown deck'
    ) AS opponent_label,
    COALESCE(
        'archetype:' || o.archetype_key,
        'manual:' || o.label,
        'archetype:' || a.archetype_key,
        'colors:' || COALESCE(NULLIF(v.colors, '') || ' ' || char(183) || ' ', '')
                  || v.signature_card,
        'unknown'
    ) AS opponent_key,
    CASE WHEN o.match_id IS NOT NULL       THEN 'manual'
         WHEN a.method IS NOT NULL         THEN a.method
         WHEN v.signature_card IS NOT NULL THEN 'colors'
         ELSE 'unknown' END AS opponent_source,
    CASE WHEN o.match_id IS NOT NULL THEN 'high'
         ELSE COALESCE(a.confidence, 'unknown') END AS opponent_confidence,
    CASE WHEN o.match_id IS NOT NULL   THEN 4
         WHEN a.confidence = 'high'    THEN 3
         WHEN a.confidence = 'medium'  THEN 2
         WHEN a.confidence = 'low'     THEN 1
         ELSE 0 END AS confidence_rank,
    COALESCE(v.cards_seen, 0) AS opponent_cards_seen,
    a.archetype_key,
    a.archetype_name,
    a.evidence_json
FROM matches m
LEFT JOIN opponent_deck_override o ON o.match_id = m.match_id
LEFT JOIN opponent_archetype     a ON a.match_id = m.match_id
LEFT JOIN v_opponent_cards       v ON v.match_id = m.match_id;

CREATE VIEW v_matchup_winrate AS
WITH named AS (
    SELECT match_id, deck_id, opponent_key, confidence_rank,
           FIRST_VALUE(opponent_label) OVER (
               PARTITION BY opponent_key
               ORDER BY confidence_rank DESC, opponent_cards_seen DESC, match_id
           ) AS opponent_label
      FROM v_match_opponent
)
SELECT
    n.opponent_key,
    n.opponent_label,
    n.deck_id,
    MAX(n.confidence_rank) AS confidence_rank,
    COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw')) AS matches_completed,
    COUNT(*) FILTER (WHERE m.result = 'win')                    AS matches_won,
    SUM(COALESCE(m.games_won, 0))                               AS games_won,
    SUM(COALESCE(m.games_lost, 0))                              AS games_lost,
    MAX(m.started_at)                                           AS last_played
FROM named n
JOIN matches m USING (match_id)
GROUP BY n.opponent_key, n.deck_id;
