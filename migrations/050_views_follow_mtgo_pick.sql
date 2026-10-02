-- 050_views_follow_mtgo_pick.sql — the deck views read the match's deck
-- through v_match_deck (049_mtgo_match_pick.sql), not matches.deck_id.
--
-- matches.deck_id is what the projector wrote, and for an MTGO match that is
-- always NULL: MTGO's game log never names the deck. The user's pick
-- (mtgo_match_pick) is the only source, and v_match_deck already folds it in:
-- the pick for an MTGO match that has one, matches.deck_id for everything
-- else. So an MTGO match with a pick now counts under its deck in every view
-- below, and one without a pick still counts under none, exactly as before.
-- An Arena match reads the same deck_id it always did, since v_match_deck
-- never applies a pick to one.
--
-- Each view is recreated from its current body, 035_mtgo_source.sql for all
-- of them, with the deck source changed: every m.deck_id becomes md.deck_id
-- from a `JOIN v_match_deck md ON md.match_id = m.match_id`. v_match_deck has
-- exactly one row per match (a LEFT JOIN onto a table whose primary key is
-- match_id), so the extra join never adds or drops a match. One body changes
-- beyond that, v_deck_identity's, because its deck_name lookup joined matches
-- on deck_id, which idx_matches_deck serves but v_match_deck's COALESCE
-- cannot. It now reads each deck's last match from a `played` CTE grouped
-- once, so the same name wins on the same rule. Measured on a synthetic
-- database of 150 deck versions under 15 deck GUIDs and 1,200 matches, no
-- ANALYZE (the app runs none), SELECT * FROM v_deck_identity took 146 ms with
-- 035's body, 18,935 ms with v_match_deck swapped into that body as-is, and
-- 20 ms with the CTE, which returned the same rows as 035's body there.
--
-- Two of the ten deck views are deliberately left alone, both byte-for-byte
-- no-ops if recreated (035's reason for leaving v_current_match):
--   - v_matchup_winrate never reads matches.deck_id. Its deck is
--     v_match_opponent's deck_id, and v_match_opponent is recreated here, so
--     it follows the pick through that view. SQLite stores a view as SQL text
--     and resolves the names in it at query time, so v_match_opponent can be
--     dropped and recreated underneath it.
--   - v_deck_land_count (011_review_views.sql) reads decks and cards only,
--     never matches, so it has no match deck to change.
--
-- No ALTER VIEW in SQLite, so DROP + CREATE: dependents dropped before their
-- dependencies, then recreated in dependency order (v_deck_identity before
-- v_deck_identity_winrate). Nothing on project()'s path reads any of these
-- views, so the rebuild still never reads the authored mtgo_match_pick.

DROP VIEW v_match_opponent;
DROP VIEW v_deck_identity_winrate;
DROP VIEW v_deck_identity;
DROP VIEW v_deck_winrate;
DROP VIEW v_play_draw_winrate;
DROP VIEW v_deck_game_length;
DROP VIEW v_deck_turn_curves;
DROP VIEW v_deck_summary;

-- Recreated from 035_mtgo_source.sql, deck from v_match_deck.
CREATE VIEW v_deck_winrate AS
SELECT
    d.deck_id,
    d.name                                                          AS deck_name,
    m.event_id,
    m.source,
    COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw'))     AS matches_completed,
    COUNT(*) FILTER (WHERE m.result = 'win')                        AS matches_won,
    SUM(COALESCE(m.games_won, 0))                                   AS games_won,
    SUM(COALESCE(m.games_lost, 0))                                  AS games_lost
FROM matches m
JOIN v_match_deck md ON md.match_id = m.match_id
JOIN decks d         ON d.deck_id = md.deck_id
GROUP BY d.deck_id, m.event_id, m.source;

-- Recreated from 035_mtgo_source.sql, deck from v_match_deck.
CREATE VIEW v_play_draw_winrate AS
SELECT
    md.deck_id,
    m.source,
    g.on_play,
    COUNT(*) FILTER (WHERE g.result IN ('win', 'loss', 'draw'))     AS games_completed,
    COUNT(*) FILTER (WHERE g.result = 'win')                        AS games_won
FROM games g
JOIN matches m       USING (match_id)
JOIN v_match_deck md ON md.match_id = m.match_id
WHERE g.on_play IS NOT NULL
GROUP BY md.deck_id, m.source, g.on_play;

-- Recreated from 035_mtgo_source.sql, deck from v_match_deck.
CREATE VIEW v_deck_game_length AS
SELECT
    md.deck_id,
    m.source,
    g.turn_count,
    COUNT(*)                                                        AS games,
    COUNT(*) FILTER (WHERE g.result = 'win')                        AS games_won
FROM games g
JOIN matches m       USING (match_id)
JOIN v_match_deck md ON md.match_id = m.match_id
WHERE g.turn_count IS NOT NULL
GROUP BY md.deck_id, m.source, g.turn_count;

-- Recreated from 035_mtgo_source.sql, deck from v_match_deck. turns is still
-- Arena-only, so a pick changes nothing here today.
CREATE VIEW v_deck_turn_curves AS
SELECT
    md.deck_id,
    m.source,
    t.turn_number,
    COUNT(*)                    AS samples,
    AVG(t.self_life)            AS avg_self_life,
    AVG(t.opp_life)             AS avg_opp_life,
    AVG(t.self_hand)            AS avg_self_hand,
    AVG(t.opp_hand)             AS avg_opp_hand,
    AVG(t.self_lands)           AS avg_self_lands,
    AVG(t.self_permanents)      AS avg_self_permanents,
    AVG(t.opp_permanents)       AS avg_opp_permanents
FROM turns t
JOIN matches m       USING (match_id)
JOIN v_match_deck md ON md.match_id = m.match_id
GROUP BY md.deck_id, m.source, t.turn_number;

-- Recreated from 035_mtgo_source.sql, deck from v_match_deck. 035's note that
-- this view can never show an MTGO row no longer holds: a picked MTGO match
-- now reaches its deck through md, and an unpicked one still reaches none.
-- An MTGO deck no match is picked to keeps its one row with a NULL source and
-- no matches.
CREATE VIEW v_deck_summary AS
SELECT
    d.deck_id,
    d.name,
    d.format,
    m.source,
    COUNT(m.match_id)                                  AS matches_played,
    COUNT(m.match_id) FILTER (WHERE m.result = 'win')  AS matches_won,
    MAX(m.started_at)                                  AS last_played,
    d.first_seen,
    d.last_seen
FROM decks d
LEFT JOIN v_match_deck md ON md.deck_id = d.deck_id
LEFT JOIN matches m       ON m.match_id = md.match_id
GROUP BY d.deck_id, m.source;

-- Recreated from 035_mtgo_source.sql, deck from v_match_deck. v_matchup_winrate
-- reads its deck_id from here (see the header).
CREATE VIEW v_match_opponent AS
SELECT
    m.match_id,
    md.deck_id,
    m.source,
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
    NULLIF(v.colors, '') AS opponent_colors,
    v.signature_cards AS opponent_signature_cards
FROM matches m
JOIN v_match_deck md                 ON md.match_id = m.match_id
LEFT JOIN opponent_deck_override o ON o.match_id = m.match_id
LEFT JOIN opponent_archetype     a ON a.match_id = m.match_id
LEFT JOIN v_opponent_cards       v ON v.match_id = m.match_id;

-- Recreated from 035_mtgo_source.sql, deck from v_match_deck through the
-- `played` CTE, which both `owned` and the deck_name lookup read (see the
-- header for why the lookup no longer joins matches itself). An MTGO deck has
-- no deck_guids row (only Arena's log carries a deck GUID), so the LEFT JOIN
-- in `mapped` gives it the 'deck:' || deck_id key, one identity per distinct
-- maindeck.
CREATE VIEW v_deck_identity AS
WITH ranked AS (
    SELECT g.deck_id, g.arena_deck_id,
           ROW_NUMBER() OVER (PARTITION BY g.deck_id
                              ORDER BY g.last_seen DESC, g.arena_deck_id) AS rn
      FROM deck_guids g
),
played AS (
    SELECT md.deck_id, md.source, MAX(m.started_at) AS last_played
      FROM v_match_deck md
      JOIN matches m ON m.match_id = md.match_id
     WHERE md.deck_id IS NOT NULL
     GROUP BY md.deck_id, md.source
),
owned AS (
    SELECT deck_id, source FROM played
),
mapped AS (
    -- LEFT JOIN: a truncated log can leave a played deck_id with no
    -- deck_guids row at all, and it still needs an identity of its own.
    SELECT o.deck_id,
           o.source,
           r.arena_deck_id,
           COALESCE('guid:' || r.arena_deck_id, 'deck:' || o.deck_id) AS deck_key
      FROM owned o
      LEFT JOIN ranked r ON r.deck_id = o.deck_id AND r.rn = 1
)
SELECT p.deck_id,
       p.source,
       p.deck_key,
       p.arena_deck_id,
       -- the name of the most recently played version in the group, so an
       -- Arena rename shows through and the choice is deterministic.
       (SELECT d.name
          FROM mapped q
          JOIN decks d  ON d.deck_id = q.deck_id
          JOIN played l ON l.deck_id = q.deck_id
         WHERE q.deck_key = p.deck_key AND d.name IS NOT NULL
         GROUP BY d.deck_id
         ORDER BY MAX(l.last_played) DESC, d.deck_id
         LIMIT 1) AS deck_name
  FROM mapped p;

-- Recreated from 035_mtgo_source.sql, deck from v_match_deck.
CREATE VIEW v_deck_identity_winrate AS
SELECT i.deck_key,
       i.arena_deck_id,
       i.deck_name,
       d.deck_id,
       m.event_id,
       m.source,
       COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw')) AS matches_completed,
       COUNT(*) FILTER (WHERE m.result = 'win')                    AS matches_won,
       SUM(COALESCE(m.games_won, 0))                               AS games_won,
       SUM(COALESCE(m.games_lost, 0))                               AS games_lost
  FROM matches m
  JOIN v_match_deck md    ON md.match_id = m.match_id
  JOIN decks d            ON d.deck_id = md.deck_id
  JOIN v_deck_identity i  ON i.deck_id = md.deck_id
 GROUP BY i.deck_key, d.deck_id, m.event_id, m.source;
