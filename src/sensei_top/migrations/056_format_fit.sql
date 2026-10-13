-- 056_format_fit.sql — a match's format, for every format (plan 13, S4).
--
-- MTGO's log never names a format, so an MTGO match's format is read off the
-- cards it revealed. Two derived tables hold that read, both rebuilt in full
-- by archetypes/classify.py::classify_matches for MTGO matches only (an
-- Arena match's format is matches.format, from its own log):
--
--   match_format_fit: one row per format that fits the match, meaning none
--   of the revealed non-token cards, from both seats, is not_legal there
--   (D3). A ban does not rule a format out: Scryfall carries only today's
--   ban list. A match whose legality cannot be read in full (an unresolved
--   card, a card with no legality on file) has no fit rows at all.
--
--   match_format_inference: one row per MTGO match, the single narrowest
--   fitting format under formats.BROADER (D4) and the reason for it. format
--   is set only when reason is 'fit'. Two incomparable narrowest formats
--   give 'ambiguous', so Pauper is never inferred over Standard or Modern.
--
-- Neither table has a foreign key to matches: project() deletes and rewrites
-- every match without knowing these tables exist, and a reference would make
-- that DELETE fail. Between project() committing and classify_matches()
-- committing, the rows still describe the match ids project() writes back.
--
-- opponent_archetype is rebuilt with PRIMARY KEY (match_id, format), because
-- an MTGO match is now named under every fitting format that has
-- definitions, and the read-time format (v_match_format) picks one row.
-- Existing rows are copied across; the next classify run rewrites them all.
-- No ALTER TABLE ... RENAME: a rename re-parses every view in the schema, so
-- the old rows go through a holding table instead.
--
-- v_match_format is the format of every match, in D6's order: the log's
-- (matches.format), else the user's MTGO pick (v_match_deck.format, which
-- applies a pick to MTGO matches only), else the inference. format_source
-- says which one answered: 'log', 'pick', 'inferred', or NULL with format.
--
-- v_match_opponent is recreated from 050_views_follow_mtgo_pick.sql with
-- the classifier's row joined on (match_id, v_match_format.format) and the
-- format exposed as its last column. v_match_format has one row per match
-- and opponent_archetype one row per (match_id, format), so the view still
-- has exactly one row per match. v_matchup_winrate reads v_match_opponent by
-- name and is left alone, as 050 left it.

CREATE TABLE match_format_fit (
    match_id  TEXT NOT NULL,
    format    TEXT NOT NULL CHECK (format IN
                  ('Standard', 'Pioneer', 'Modern', 'Pauper', 'Legacy', 'Vintage', 'Premodern')),
    PRIMARY KEY (match_id, format)
) WITHOUT ROWID;

CREATE TABLE match_format_inference (
    match_id  TEXT PRIMARY KEY,
    format    TEXT CHECK (format IS NULL OR format IN
                  ('Standard', 'Pioneer', 'Modern', 'Pauper', 'Legacy', 'Vintage', 'Premodern')),
    reason    TEXT NOT NULL CHECK (reason IN
                  ('fit', 'ambiguous', 'too_few_cards', 'unresolved_cards',
                   'unknown_legality', 'no_fit')),
    CHECK ((reason = 'fit') = (format IS NOT NULL))
);

DROP VIEW v_match_opponent;

CREATE TABLE opponent_archetype_056 AS SELECT * FROM opponent_archetype;
DROP TABLE opponent_archetype;

CREATE TABLE opponent_archetype (
    match_id            TEXT NOT NULL REFERENCES matches (match_id),
    format              TEXT NOT NULL,
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
    classified_at       TEXT NOT NULL,
    PRIMARY KEY (match_id, format)
);

-- classify_matches only ever wrote a format it had definitions for, so a
-- NULL format here is a row no read could reach; it is not carried over.
INSERT INTO opponent_archetype
     (match_id, format, archetype_key, archetype_name, colors, label, method,
      confidence, cards_seen, conditions_met, conditions_unknown, evidence_json,
      classified_at)
SELECT match_id, format, archetype_key, archetype_name, colors, label, method,
       confidence, cards_seen, conditions_met, conditions_unknown, evidence_json,
       classified_at
  FROM opponent_archetype_056
 WHERE format IS NOT NULL;

DROP TABLE opponent_archetype_056;

CREATE VIEW v_match_format AS
SELECT
    m.match_id,
    COALESCE(m.format, md.format, i.format) AS format,
    CASE WHEN m.format  IS NOT NULL THEN 'log'
         WHEN md.format IS NOT NULL THEN 'pick'
         WHEN i.format  IS NOT NULL THEN 'inferred' END AS format_source
FROM matches m
JOIN v_match_deck md                ON md.match_id = m.match_id
LEFT JOIN match_format_inference i  ON i.match_id = m.match_id AND m.source = 'mtgo';

-- Recreated from 050_views_follow_mtgo_pick.sql: opponent_archetype joined
-- on the match's read-time format, and that format appended.
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
    v.signature_cards AS opponent_signature_cards,
    f.format
FROM matches m
JOIN v_match_deck md               ON md.match_id = m.match_id
JOIN v_match_format f              ON f.match_id = m.match_id
LEFT JOIN opponent_deck_override o ON o.match_id = m.match_id
LEFT JOIN opponent_archetype     a ON a.match_id = m.match_id AND a.format = f.format
LEFT JOIN v_opponent_cards       v ON v.match_id = m.match_id;
