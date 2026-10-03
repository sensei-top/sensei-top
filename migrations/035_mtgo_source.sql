-- 035_mtgo_source.sql — MTGO joins the same database as a second `source`.
--
-- `source` ("which client wrote this — 'arena' or 'mtgo'") sits confusingly
-- next to the pre-existing `source_file` ("which filename on disk" — e.g.
-- 'Player.log' vs 'Match_GameLog_<guid>.dat'). They are unrelated columns
-- that happen to share a root word; do not conflate them when reading or
-- extending either table.
--
-- Every view that reads `matches` (directly or transitively) needs `source`
-- threaded through it in the same change that lands the first MTGO row
-- (.claude/handoffs/mtgo-implementation.md): every one of them currently
-- aggregates all of `matches` unconditionally, so a stray MTGO row before
-- this exists would silently change every Arena number on the dashboard.
--
-- One deliberate omission from the 18-view sweep: v_current_match
-- (003_current_match.sql) is `SELECT m.* FROM matches m WHERE ...` — a bare
-- `m.*`. SQLite views store their defining SQL as text and re-expand `.*`
-- against the table's *current* schema on every query (verified directly:
-- ALTER TABLE ADD COLUMN on a table already exposed via `t.*` in a view
-- makes the new column appear with no DROP/CREATE VIEW needed). Recreating
-- it here would be a byte-for-byte no-op, so it is left untouched.
--
-- SQLite has no ALTER VIEW / CREATE OR REPLACE VIEW, so every other
-- affected view is DROP + CREATE, same pattern as 006/016/030/032. Views
-- are dropped before any are recreated, then recreated in dependency order
-- (v_opponent_cards before v_match_opponent before v_matchup_winrate;
-- v_deck_identity before v_deck_identity_winrate) so a CREATE never
-- references a view that has not been rebuilt yet.

ALTER TABLE raw_events ADD COLUMN source TEXT NOT NULL DEFAULT 'arena';
ALTER TABLE matches    ADD COLUMN source TEXT NOT NULL DEFAULT 'arena';
CREATE INDEX idx_raw_events_source ON raw_events(source);
CREATE INDEX idx_matches_source    ON matches(source);

-- ---------------------------------------------------------------------------
-- Drop every view that needs a source-aware body (v_current_match excepted;
-- see header). Dependents dropped before their dependencies, mirroring
-- 032_corpus_naming.sql's own ordering.
-- ---------------------------------------------------------------------------
DROP VIEW v_matchup_winrate;
DROP VIEW v_match_opponent;
DROP VIEW v_opponent_cards;
DROP VIEW v_deck_identity_winrate;
DROP VIEW v_deck_identity;
DROP VIEW v_deck_winrate;
DROP VIEW v_play_draw_winrate;
DROP VIEW v_deck_game_length;
DROP VIEW v_deck_turn_curves;
DROP VIEW v_deck_summary;
DROP VIEW v_card_events;
DROP VIEW v_turn_zones;
DROP VIEW v_self_turns;
DROP VIEW v_self_lands_played;
DROP VIEW v_self_hand_lands;
DROP VIEW v_damage_events;
DROP VIEW v_rank_winrate;

-- ---------------------------------------------------------------------------
-- 8 aggregates: source in both SELECT and GROUP BY, or an outer
-- `WHERE v.source = ?` (api/sql.py::_filtered) cannot reach inside them.
-- ---------------------------------------------------------------------------

-- Recreated from 001_init.sql plus source.
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
JOIN decks d USING (deck_id)
GROUP BY d.deck_id, m.event_id, m.source;

-- Recreated from 001_init.sql plus source.
CREATE VIEW v_play_draw_winrate AS
SELECT
    m.deck_id,
    m.source,
    g.on_play,
    COUNT(*) FILTER (WHERE g.result IN ('win', 'loss', 'draw'))     AS games_completed,
    COUNT(*) FILTER (WHERE g.result = 'win')                        AS games_won
FROM games g
JOIN matches m USING (match_id)
WHERE g.on_play IS NOT NULL
GROUP BY m.deck_id, m.source, g.on_play;

-- Recreated from 001_init.sql plus source.
CREATE VIEW v_deck_game_length AS
SELECT
    m.deck_id,
    m.source,
    g.turn_count,
    COUNT(*)                                                        AS games,
    COUNT(*) FILTER (WHERE g.result = 'win')                        AS games_won
FROM games g
JOIN matches m USING (match_id)
WHERE g.turn_count IS NOT NULL
GROUP BY m.deck_id, m.source, g.turn_count;

-- Recreated from 001_init.sql plus source. games/turns are Arena-only (MTGO
-- writes neither — .claude/handoffs/mtgo-implementation.md's scope decision),
-- so every row here reads source = 'arena' today; the column exists for
-- schema uniformity with every other metric view, not because this one can
-- show a second source yet.
CREATE VIEW v_deck_turn_curves AS
SELECT
    m.deck_id,
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
JOIN matches m USING (match_id)
GROUP BY m.deck_id, m.source, t.turn_number;

-- Recreated from 003_current_match.sql plus source. Structurally this can
-- never show an MTGO row regardless: the LEFT JOIN key is deck_id, and MTGO
-- matches always carry deck_id = NULL (rule 4 — no decklist source exists
-- yet), which never satisfies a USING(deck_id) join. source is added for the
-- same schema-uniformity reason as v_deck_turn_curves above.
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
LEFT JOIN matches m USING (deck_id)
GROUP BY d.deck_id, m.source;

-- Recreated from 023_rank_snapshot.sql plus source. MTGO matches have no
-- rank system to poll, so every MTGO row's rank columns are NULL — the same
-- "not yet observed" grouping this view already gives an Arena match with no
-- prior snapshot, extended to a source that structurally never has one.
CREATE VIEW v_rank_winrate AS
SELECT
    (SELECT r.constructed_class FROM rank_snapshot r
      WHERE r.observed_at <= m.started_at
      ORDER BY r.observed_at DESC LIMIT 1)                      AS constructed_class,
    (SELECT r.constructed_level FROM rank_snapshot r
      WHERE r.observed_at <= m.started_at
      ORDER BY r.observed_at DESC LIMIT 1)                      AS constructed_level,
    m.source,
    COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw')) AS matches_completed,
    COUNT(*) FILTER (WHERE m.result = 'win')                    AS matches_won,
    SUM(COALESCE(m.games_won, 0))                               AS games_won,
    SUM(COALESCE(m.games_lost, 0))                               AS games_lost
FROM matches m
GROUP BY constructed_class, constructed_level, m.source;

-- ---------------------------------------------------------------------------
-- 10 row-level views: source as a passthrough column only, no GROUP BY
-- semantics change beyond carrying it through (v_current_match excepted;
-- see header — SQLite's `m.*` already exposes it with no textual change).
-- ---------------------------------------------------------------------------

-- Recreated from 003_current_match.sql plus source.
CREATE VIEW v_card_events AS
SELECT
    ce.match_id,
    ce.game_number,
    ce.seq,
    ce.turn_number,
    ce.category,
    ce.zone_src,
    ce.zone_dest,
    ce.grp_id,
    c.name AS card_name,
    m.source,
    CASE WHEN m.self_seat IS NULL THEN NULL
         WHEN ce.seat = m.self_seat THEN 1
         ELSE 0 END AS is_self
FROM card_events ce
JOIN matches m USING (match_id)
LEFT JOIN cards c ON c.grp_id = ce.grp_id;

-- Recreated from 010_zone_card_detail.sql plus source. turn_zones is
-- Arena-only (MTGO writes no board state), so every row here reads
-- source = 'arena' today; added for schema uniformity with v_card_events.
CREATE VIEW v_turn_zones AS
SELECT
    tz.match_id, tz.game_number, tz.turn_number, tz.zone, tz.idx,
    tz.instance_id, tz.grp_id, tz.card_types, tz.drawn_on_turn,
    tz.is_tapped, tz.power, tz.toughness,
    c.name AS card_name,
    c.mana_cost, c.type_line, c.colors,
    m.source,
    CASE WHEN m.self_seat IS NULL THEN NULL
         WHEN tz.seat = m.self_seat THEN 1
         ELSE 0 END AS is_self
FROM turn_zones tz
JOIN matches m USING (match_id)
LEFT JOIN cards c ON c.grp_id = tz.grp_id;

-- Recreated from 016_position_view.sql plus source. turns is Arena-only.
CREATE VIEW v_self_turns AS
SELECT
    t.match_id, t.game_number, t.turn_number,
    m.source,
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

-- Recreated from 011_review_views.sql plus source. card_events does carry
-- MTGO rows (Step 4's whole point — the matchups tab), so this one is a real
-- passthrough, not a decorative one: an MTGO PlayLand event would otherwise
-- mix into an Arena-only lands-played read with nothing to filter it back
-- out by.
CREATE VIEW v_self_lands_played AS
SELECT ce.match_id, m.source, ce.game_number, ce.turn_number, COUNT(*) AS lands_played
FROM card_events ce
JOIN matches m ON m.match_id = ce.match_id
WHERE ce.seat = m.self_seat AND ce.category = 'PlayLand' AND ce.turn_number IS NOT NULL
GROUP BY ce.match_id, m.source, ce.game_number, ce.turn_number;

-- Recreated from 011_review_views.sql plus source. turn_zones is Arena-only,
-- so this one stays decorative like v_turn_zones/v_self_turns above.
CREATE VIEW v_self_hand_lands AS
SELECT
    tz.match_id, m.source, tz.game_number, tz.turn_number,
    COUNT(*) FILTER (
        WHERE instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))), 'Land') > 0
    ) AS hand_lands,
    COUNT(*) FILTER (WHERE c.name IS NOT NULL) AS named_cards
FROM turn_zones tz
JOIN matches m USING (match_id)
LEFT JOIN cards c ON c.grp_id = tz.grp_id
WHERE tz.zone = 'hand' AND tz.seat = m.self_seat
GROUP BY tz.match_id, m.source, tz.game_number, tz.turn_number;

-- Recreated from 014_combat.sql plus source. damage_events is Arena-only.
CREATE VIEW v_damage_events AS
SELECT
    d.match_id, d.game_number, d.turn_number, d.amount, d.damage_type,
    d.source_instance_id, d.source_grp_id, sc.name AS source_card_name,
    d.target_instance_id, tc.name AS target_card_name,
    m.source,
    CASE WHEN m.self_seat IS NULL THEN NULL
         WHEN d.target_instance_id IS NOT NULL THEN NULL
         ELSE d.target_seat = m.self_seat END AS target_is_self,
    CASE WHEN m.self_seat IS NULL OR d.source_seat IS NULL THEN NULL
         ELSE d.source_seat = m.self_seat END AS source_is_self
FROM damage_events d
JOIN matches m ON m.match_id = d.match_id
LEFT JOIN cards sc ON sc.grp_id = d.source_grp_id
LEFT JOIN cards tc ON tc.grp_id = d.target_grp_id;

-- Recreated from 032_corpus_naming.sql plus source, threaded through the
-- `seen` CTE (this is the view that actually unlocks the matchups tab for
-- MTGO — see the module docstring in projector/mtgo/project.py).
CREATE VIEW v_opponent_cards AS
WITH seen AS (
    SELECT m.match_id, m.source, c.name, c.rarity, c.colors, COUNT(*) AS times
      FROM card_events ce
      JOIN matches m ON m.match_id = ce.match_id
      JOIN cards   c ON c.grp_id   = ce.grp_id
     WHERE ce.seat = m.opponent_seat
       AND ce.grp_id IS NOT NULL
       AND instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))),
                 'Land') = 0
       AND instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))),
                 'Token') = 0
     GROUP BY m.match_id, m.source, c.name, c.rarity, c.colors
)
SELECT
    match_id,
    source,
    COUNT(*) AS cards_seen,
    (CASE WHEN MAX(colors LIKE '%W%') THEN 'W' ELSE '' END) ||
    (CASE WHEN MAX(colors LIKE '%U%') THEN 'U' ELSE '' END) ||
    (CASE WHEN MAX(colors LIKE '%B%') THEN 'B' ELSE '' END) ||
    (CASE WHEN MAX(colors LIKE '%R%') THEN 'R' ELSE '' END) ||
    (CASE WHEN MAX(colors LIKE '%G%') THEN 'G' ELSE '' END) AS colors,
    (SELECT s.name FROM seen s
      WHERE s.match_id = seen.match_id
      ORDER BY CASE s.rarity
                   WHEN 'mythic'   THEN 5
                   WHEN 'rare'     THEN 4
                   WHEN 'uncommon' THEN 3
                   WHEN 'common'   THEN 2
                   ELSE 1 END DESC,
               s.times DESC,
               s.name ASC
      LIMIT 1) AS signature_card,
    (SELECT json_group_array(x.name) FROM (
        SELECT s.name FROM seen s
         WHERE s.match_id = seen.match_id
         ORDER BY CASE s.rarity
                      WHEN 'mythic'   THEN 5
                      WHEN 'rare'     THEN 4
                      WHEN 'uncommon' THEN 3
                      WHEN 'common'   THEN 2
                      ELSE 1 END DESC,
                  s.times DESC,
                  s.name ASC
         LIMIT 3
     ) x) AS signature_cards
FROM seen
GROUP BY match_id, source;

-- Recreated from 032_corpus_naming.sql plus source.
CREATE VIEW v_match_opponent AS
SELECT
    m.match_id,
    m.deck_id,
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
LEFT JOIN opponent_deck_override o ON o.match_id = m.match_id
LEFT JOIN opponent_archetype     a ON a.match_id = m.match_id
LEFT JOIN v_opponent_cards       v ON v.match_id = m.match_id;

-- Recreated from 032_corpus_naming.sql plus source in both SELECT and
-- GROUP BY — this is the view api/sql.py's _filtered helper's
-- `WHERE v.source = ?` has to reach inside for the matchups tab, and the
-- one Step 8 test (source filter) pins directly.
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
    m.source,
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
GROUP BY n.opponent_key, n.deck_id, m.source;

-- Recreated from 033_deck_identity.sql plus source, threaded through the
-- CTE chain per the plan (not bolted onto the outer select alone) — even
-- though `owned` already excludes every MTGO row (deck_id IS NOT NULL), so
-- source is functionally constant ('arena') on every row this view can ever
-- produce today. Kept for schema uniformity with v_deck_identity_winrate.
CREATE VIEW v_deck_identity AS
WITH ranked AS (
    SELECT g.deck_id, g.arena_deck_id,
           ROW_NUMBER() OVER (PARTITION BY g.deck_id
                              ORDER BY g.last_seen DESC, g.arena_deck_id) AS rn
      FROM deck_guids g
),
owned AS (
    SELECT DISTINCT m.deck_id, m.source FROM matches m WHERE m.deck_id IS NOT NULL
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
          JOIN decks d   ON d.deck_id = q.deck_id
          JOIN matches m2 ON m2.deck_id = q.deck_id
         WHERE q.deck_key = p.deck_key AND d.name IS NOT NULL
         GROUP BY d.deck_id
         ORDER BY MAX(m2.started_at) DESC, d.deck_id
         LIMIT 1) AS deck_name
  FROM mapped p;

-- Recreated from 033_deck_identity.sql plus source. Also structurally
-- Arena-only today (the JOIN decks d ON d.deck_id = m.deck_id excludes every
-- MTGO row, same as v_deck_summary above), kept for the same uniformity
-- reason and so a future deck_id source (.dek import) needs no view change.
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
  JOIN decks d            ON d.deck_id = m.deck_id
  JOIN v_deck_identity i  ON i.deck_id = m.deck_id
 GROUP BY i.deck_key, d.deck_id, m.event_id, m.source;
