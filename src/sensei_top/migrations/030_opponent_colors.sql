-- 030_opponent_colors.sql — the dashboard's colour identity chrome (real
-- mana pips instead of a 3px colour strip) needs the opponent's revealed
-- colours as a column, not something the client re-derives from a label.
--
-- Semantics: the colours the opponent revealed (v_opponent_cards.colors),
-- never the archetype's assumed colours — a classified match can be all
-- colours the archetype allows while the opponent has only shown one.
-- v_opponent_cards.colors is '' both when only colourless cards were
-- revealed and when revealed cards' colours are simply unknown (no `cards`
-- row for them); those two cannot be told apart, so '' becomes NULL here and
-- the UI renders nothing for it, never the word "Colourless" (AGENTS.md
-- rule 4: unknown means NULL, never a guess).
--
-- SQLite views cannot be ALTERed, so this is the same drop-and-recreate
-- pattern 006_deck_picker.sql and 016_position_view.sql already use.
-- Recreated verbatim from 006 plus the new column on each view. Only 004 and
-- 006 define these two views (verified); every reader (review/snapshot.py,
-- archetypes/classify.py, the API routes) selects named columns rather than
-- `SELECT *`, so an appended column is safe — confirmed with the full
-- pytest suite.
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
    a.evidence_json,
    NULLIF(v.colors, '') AS opponent_colors
FROM matches m
LEFT JOIN opponent_deck_override o ON o.match_id = m.match_id
LEFT JOIN opponent_archetype     a ON a.match_id = m.match_id
LEFT JOIN v_opponent_cards       v ON v.match_id = m.match_id;

-- The matchup group's colours are the union across every match named onto
-- it — one player might reveal only U, another only B, of the same
-- archetype — using the exact idiom 004_archetypes.sql already uses to
-- build v_opponent_cards.colors itself, so the same rule ('' means nothing
-- ever matched MAX(... LIKE ...) truthily) produces the same NULL-vs-empty
-- behaviour here.
CREATE VIEW v_matchup_winrate AS
WITH named AS (
    SELECT match_id, deck_id, opponent_key, confidence_rank, opponent_colors,
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
GROUP BY n.opponent_key, n.deck_id;
