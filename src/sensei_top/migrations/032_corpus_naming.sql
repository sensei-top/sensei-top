-- 032_corpus_naming.sql — a second evidence source for naming the
-- opponent's deck: archetypes/corpus.py's naive-Bayes read over the
-- metagame corpus's own classified decklists, combined with (never
-- replacing) the rule engine's verdict in classify.py's classify_matches().
-- See that module's docstring and docs/architecture.md's "Naming the
-- opponent's deck" section for why a second source exists at all: the rule
-- engine is silent on any archetype nobody has written a definition for yet
-- (a brand-new set, until archetypes/source.py's downloaded corpus catches
-- up), and its own fit saturates fast even when a definition does exist.
--
-- Two independent changes bundled into one migration because both are pure
-- schema-widening with no data to preserve:
--
-- 1. opponent_archetype.method's CHECK constraint needs a third value,
--    'corpus', for a row classify_matches() wrote from the corpus source
--    rather than choose()'s rule engine. SQLite cannot ALTER a CHECK
--    constraint, so this is DROP + CREATE — safe here specifically because
--    opponent_archetype is entirely derived (004_archetypes.sql's own
--    comment: "Between project() committing and classify_matches()
--    committing this table is empty" — nothing else ever writes to it, and
--    classify_matches() always does a full DELETE+INSERT). Losing the old
--    rows costs nothing; the very next classify run repopulates every one
--    of them, corpus-aware.
--
-- 2. v_opponent_cards gets a signature_cards column (JSON array of up to
--    three revealed nonland cards, rarity-then-frequency order — same
--    ordering as the existing singular signature_card, just not cut off at
--    one) so the "genuinely unclear" case can show more than a single
--    card once real corpus naming makes a lone signature card an obviously
--    thin substitute for a name. JSON array text, like `cards.colors`/
--    `produced_mana` (031_card_body.sql's own comment on that convention) —
--    parsed with json.loads at the API layer, same as any other JSON
--    column here. opponent_signature_cards then surfaces that same value on
--    v_match_opponent so a caller never has to join v_opponent_cards itself
--    just for this.
--
-- opponent_source needs no view change at all: it already reads straight
-- from a.method (CASE WHEN a.method IS NOT NULL THEN a.method), so once
-- opponent_archetype.method can hold 'corpus' this column reports it for
-- free.
--
-- SQLite views cannot be ALTERed either, so this is the same
-- drop-and-recreate pattern 006_deck_picker.sql, 016_position_view.sql and
-- 030_opponent_colors.sql already use — dependents dropped first
-- (v_matchup_winrate depends on v_match_opponent; v_match_opponent depends
-- on opponent_archetype and v_opponent_cards), then everything recreated in
-- dependency order. Every reader selects named columns rather than
-- `SELECT *` (verified for the same reason 030 records), so an appended
-- column is safe.
DROP VIEW v_matchup_winrate;
DROP VIEW v_match_opponent;
DROP VIEW v_opponent_cards;

DROP TABLE opponent_archetype;
CREATE TABLE opponent_archetype (
    match_id            TEXT PRIMARY KEY REFERENCES matches (match_id),
    format              TEXT,
    archetype_key       TEXT,
    archetype_name      TEXT,
    colors              TEXT,
    label               TEXT NOT NULL,
    method              TEXT NOT NULL CHECK (method IN ('archetype', 'fallback', 'corpus')),
    confidence          TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    cards_seen          INTEGER NOT NULL,
    conditions_met      INTEGER NOT NULL,
    conditions_unknown  INTEGER NOT NULL,
    evidence_json       TEXT,
    classified_at       TEXT NOT NULL
);

-- Recreated verbatim from 004_archetypes.sql plus the new signature_cards
-- column, sharing the `seen` CTE and the exact rarity-then-frequency
-- ordering the existing signature_card subquery already uses.
CREATE VIEW v_opponent_cards AS
WITH seen AS (
    SELECT m.match_id, c.name, c.rarity, c.colors, COUNT(*) AS times
      FROM card_events ce
      JOIN matches m ON m.match_id = ce.match_id
      JOIN cards   c ON c.grp_id   = ce.grp_id
     WHERE ce.seat = m.opponent_seat
       AND ce.grp_id IS NOT NULL
       AND instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))),
                 'Land') = 0
       AND instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))),
                 'Token') = 0
     GROUP BY m.match_id, c.name, c.rarity, c.colors
)
SELECT
    match_id,
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
GROUP BY match_id;

-- Recreated verbatim from 030_opponent_colors.sql plus opponent_signature_cards.
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
    NULLIF(v.colors, '') AS opponent_colors,
    v.signature_cards AS opponent_signature_cards
FROM matches m
LEFT JOIN opponent_deck_override o ON o.match_id = m.match_id
LEFT JOIN opponent_archetype     a ON a.match_id = m.match_id
LEFT JOIN v_opponent_cards       v ON v.match_id = m.match_id;

-- Recreated verbatim from 030_opponent_colors.sql — no change needed here,
-- only rebuilt because it depends on v_match_opponent.
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
