-- 073_cloud_match_views.sql — restored matches (cloud_match, 072) count in the
-- match list and in the match-level win-rate views.
--
-- v_cloud_match is the one place a cloud payload is read into the columns the
-- match list and the views want. A row is hidden when matches has the same
-- match_id: a match read from this install's own log always wins. What the
-- payload does not carry stays NULL (rule 4): there is no ended_at, no
-- opponent_colors, no rank and no deck_id, since the cloud names a deck by its
-- name and cards only, and a local deck_id is a hash of a local list. So a
-- restored match counts under a deck_key of 'cloud:' || the deck's name, with
-- a NULL deck_id, and is absent from every view keyed on deck_id (play/draw,
-- game length, turn curves, the deck summary): those stay local-only.
--
-- started_at is played_at (UTC) converted to this machine's local time, the
-- clock matches.started_at is written in, so both sort together.
--
-- opponent_source is 'manual' when the payload carries the user's own
-- opponent pick; otherwise it follows the prefix of the opponent key, the
-- one v_match_opponent writes: colors: is 'colors' (a read of colours and a
-- card, not a named deck), manual: 'manual', archetype: 'archetype', and
-- anything else, or no key, 'unknown'. The payload does not say how sure the
-- app was, so only a manual one is 'high' (rank 4), as locally; every other
-- is 'unknown', rank 0.
--
-- The three views are recreated from 050_views_follow_mtgo_pick.sql
-- (v_deck_winrate, v_deck_identity_winrate) and 058_matchup_format.sql
-- (v_matchup_winrate) with a restored branch UNIONed in; the local branch is
-- unchanged. Nothing on project()'s path reads any of them.

CREATE VIEW v_cloud_match AS
SELECT
    c.match_id,
    c.source,
    json_extract(c.payload, '$.event')                          AS event_id,
    CAST(NULL AS TEXT)                                          AS deck_id,
    json_extract(c.payload, '$.deck.name')                      AS deck_name,
    strftime('%Y-%m-%dT%H:%M:%S', c.played_at, 'localtime')     AS started_at,
    json_extract(c.payload, '$.result')                         AS result,
    json_extract(c.payload, '$.won')                            AS games_won,
    json_extract(c.payload, '$.lost')                           AS games_lost,
    json_extract(c.payload, '$.best_of')                        AS best_of,
    json_extract(c.payload, '$.format')                         AS format,
    COALESCE(json_extract(c.payload, '$.opp.label'), 'Unknown deck') AS opponent_label,
    COALESCE(json_extract(c.payload, '$.opp.key'), 'unknown')   AS opponent_key,
    CASE WHEN json_extract(c.payload, '$.picks.opp') IS NOT NULL THEN 'manual'
         WHEN json_extract(c.payload, '$.opp.key') LIKE 'colors:%'    THEN 'colors'
         WHEN json_extract(c.payload, '$.opp.key') LIKE 'manual:%'    THEN 'manual'
         WHEN json_extract(c.payload, '$.opp.key') LIKE 'archetype:%' THEN 'archetype'
         ELSE 'unknown' END                                     AS opponent_source,
    CASE WHEN json_extract(c.payload, '$.picks.opp') IS NOT NULL
           OR json_extract(c.payload, '$.opp.key') LIKE 'manual:%' THEN 'high'
         ELSE 'unknown' END                                     AS opponent_confidence,
    CASE WHEN json_extract(c.payload, '$.picks.opp') IS NOT NULL
           OR json_extract(c.payload, '$.opp.key') LIKE 'manual:%' THEN 4
         ELSE 0 END                                             AS confidence_rank,
    COALESCE(json_array_length(c.payload, '$.opp_cards'), 0)    AS opponent_cards_seen,
    CAST(NULL AS TEXT)                                          AS opponent_colors,
    1                                                           AS restored
FROM cloud_match c
WHERE NOT EXISTS (SELECT 1 FROM matches m WHERE m.match_id = c.match_id);

DROP VIEW v_deck_identity_winrate;
DROP VIEW v_deck_winrate;
DROP VIEW v_matchup_winrate;

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
GROUP BY d.deck_id, m.event_id, m.source
UNION ALL
SELECT
    NULL,
    r.deck_name,
    r.event_id,
    r.source,
    COUNT(*) FILTER (WHERE r.result IN ('win', 'loss', 'draw')),
    COUNT(*) FILTER (WHERE r.result = 'win'),
    SUM(COALESCE(r.games_won, 0)),
    SUM(COALESCE(r.games_lost, 0))
FROM v_cloud_match r
WHERE r.deck_name IS NOT NULL
GROUP BY r.deck_name, r.event_id, r.source;

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
       SUM(COALESCE(m.games_lost, 0))                              AS games_lost
  FROM matches m
  JOIN v_match_deck md    ON md.match_id = m.match_id
  JOIN decks d            ON d.deck_id = md.deck_id
  JOIN v_deck_identity i  ON i.deck_id = md.deck_id
 GROUP BY i.deck_key, d.deck_id, m.event_id, m.source
UNION ALL
SELECT 'cloud:' || r.deck_name,
       NULL,
       r.deck_name,
       NULL,
       r.event_id,
       r.source,
       COUNT(*) FILTER (WHERE r.result IN ('win', 'loss', 'draw')),
       COUNT(*) FILTER (WHERE r.result = 'win'),
       SUM(COALESCE(r.games_won, 0)),
       SUM(COALESCE(r.games_lost, 0))
  FROM v_cloud_match r
 WHERE r.deck_name IS NOT NULL
 GROUP BY r.deck_name, r.event_id, r.source;

CREATE VIEW v_matchup_winrate AS
WITH joined AS (
    SELECT n.match_id, n.deck_id, n.opponent_key, n.confidence_rank, n.opponent_colors,
           n.format, n.opponent_label, n.opponent_cards_seen,
           m.source, m.result, m.games_won, m.games_lost, m.started_at
      FROM v_match_opponent n
      JOIN matches m USING (match_id)
    UNION ALL
    SELECT r.match_id, r.deck_id, r.opponent_key, r.confidence_rank, r.opponent_colors,
           r.format, r.opponent_label, r.opponent_cards_seen,
           r.source, r.result, r.games_won, r.games_lost, r.started_at
      FROM v_cloud_match r
),
named AS (
    SELECT *,
           FIRST_VALUE(opponent_label) OVER (
               PARTITION BY opponent_key, format
               ORDER BY confidence_rank DESC, opponent_cards_seen DESC, match_id
           ) AS named_label
      FROM joined
)
SELECT
    n.opponent_key,
    n.named_label AS opponent_label,
    n.deck_id,
    n.source,
    n.format,
    MAX(n.confidence_rank) AS confidence_rank,
    COUNT(*) FILTER (WHERE n.result IN ('win', 'loss', 'draw')) AS matches_completed,
    COUNT(*) FILTER (WHERE n.result = 'win')                    AS matches_won,
    SUM(COALESCE(n.games_won, 0))                               AS games_won,
    SUM(COALESCE(n.games_lost, 0))                              AS games_lost,
    MAX(n.started_at)                                           AS last_played,
    NULLIF(
        (CASE WHEN MAX(n.opponent_colors LIKE '%W%') THEN 'W' ELSE '' END) ||
        (CASE WHEN MAX(n.opponent_colors LIKE '%U%') THEN 'U' ELSE '' END) ||
        (CASE WHEN MAX(n.opponent_colors LIKE '%B%') THEN 'B' ELSE '' END) ||
        (CASE WHEN MAX(n.opponent_colors LIKE '%R%') THEN 'R' ELSE '' END) ||
        (CASE WHEN MAX(n.opponent_colors LIKE '%G%') THEN 'G' ELSE '' END),
        ''
    ) AS opponent_colors
FROM named n
GROUP BY n.opponent_key, n.deck_id, n.source, n.format;
