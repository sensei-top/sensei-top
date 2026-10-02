-- 047_meta_event_tier_rank.sql — re-tier the corpus by the user's ranking
-- (2026-09-29/30): tabletop 64+ players, then MTGO challenges, then MTGO
-- leagues, then every other tabletop event.
--
-- `metagame/tiers.py::classify_tier` used to tag an event from shape alone —
-- standings presence and round count — because that was all the schema
-- carried. `standings_rows` (012) and `source` (already on every row) are
-- enough to redo the call without a re-fetch: no upstream file changes, so
-- this migration only recomputes `tier` from columns already stored.
--
-- A column swap, not a table rebuild: `meta_event` is referenced by
-- `meta_deck`, `meta_round_match` and `meta_deck_archetype` (all
-- `REFERENCES meta_event (event_id)`) plus its own self-reference
-- `duplicate_of`, and `db.migrate` runs with `foreign_keys=ON` — a rebuild
-- (new table, copy, drop, rename) would have to touch every child row's FK
-- or disable enforcement mid-migration. `ADD COLUMN` / `DROP COLUMN` /
-- `RENAME COLUMN` touch only this table.
--
-- The three views naming `e.tier` are dropped and recreated rather than left
-- in place: SQLite view bodies are frozen text, so `v_meta_winrate`'s old
-- `WHERE e.tier IN ('A', 'B')` would keep excluding Tier D's real swiss data
-- until dropped and rewritten.
--
-- Every stored event is re-tagged, including a twin already marked
-- `duplicate_of` another event — the dedup rows aren't read by any of these
-- views today, but this migration doesn't special-case them, matching
-- `metagame/dedup.py`'s own rule that a twin keeps its own `meta_event` row.

DROP VIEW v_meta_presence;
DROP VIEW v_meta_winrate;
DROP VIEW v_meta_matchup;

-- The DEFAULT exists only to satisfy ADD COLUMN on existing rows; every row
-- gets a real value from the UPDATE below immediately after, and
-- `store_events` always writes a real tier for every row inserted from now
-- on, so no row is ever left holding this default in practice.
ALTER TABLE meta_event ADD COLUMN tier_rank TEXT NOT NULL DEFAULT 'D'
    CHECK (tier_rank IN ('A', 'B', 'C', 'D'));

-- Mirrors `metagame/tiers.py::classify_tier`'s new order exactly: no
-- standings at all is the conservative Tier C regardless of source; an MTGO
-- event with standings is a challenge (B), since MTGO never publishes a
-- challenge's full swiss, only its top-32 bracket; a tabletop (Melee or
-- TopDeck) event with 64 or more standings rows is Tier A; everything else
-- tabletop is Tier D.
UPDATE meta_event SET tier_rank = CASE
    WHEN standings_rows = 0 THEN 'C'
    WHEN source = 'MTGO' THEN 'B'
    WHEN standings_rows >= 64 THEN 'A'
    ELSE 'D'
END;

ALTER TABLE meta_event DROP COLUMN tier;
ALTER TABLE meta_event RENAME COLUMN tier_rank TO tier;

CREATE VIEW v_meta_presence AS
SELECT
    e.event_id,
    d.deck_ord,
    e.event_date,
    e.format,
    e.tier,
    da.archetype_key,
    da.archetype_name AS label,
    da.colors
FROM meta_deck d
JOIN meta_event e ON e.event_id = d.event_id
JOIN meta_deck_archetype da ON da.event_id = d.event_id AND da.deck_ord = d.deck_ord;

-- Tier C (leagues) is still excluded: a league dump has no losses in it at
-- all. Tier D is now included alongside A and B — it carries a real swiss
-- behind it, same as A, just under 64 players.
CREATE VIEW v_meta_winrate AS
SELECT
    e.event_id,
    d.deck_ord,
    e.event_date,
    e.format,
    e.tier,
    da.archetype_key,
    da.archetype_name AS label,
    da.colors,
    d.wins,
    d.losses,
    d.draws
FROM meta_deck d
JOIN meta_event e ON e.event_id = d.event_id
JOIN meta_deck_archetype da ON da.event_id = d.event_id AND da.deck_ord = d.deck_ord
WHERE e.tier IN ('A', 'B', 'D');

CREATE VIEW v_meta_matchup AS
WITH sides AS (
    SELECT
        rm.event_id, e.tier, e.format, e.event_date,
        da_a.archetype_key AS archetype_key, da_a.archetype_name AS label,
        da_b.archetype_key AS opponent_key, da_b.archetype_name AS opponent_label,
        rm.wins_a AS wins, rm.wins_b AS losses, rm.draws AS draws
    FROM meta_round_match rm
    JOIN meta_event e ON e.event_id = rm.event_id
    JOIN meta_deck_archetype da_a ON da_a.event_id = rm.event_id AND da_a.deck_ord = rm.deck_ord_a
    JOIN meta_deck_archetype da_b ON da_b.event_id = rm.event_id AND da_b.deck_ord = rm.deck_ord_b
    UNION ALL
    SELECT
        rm.event_id, e.tier, e.format, e.event_date,
        da_b.archetype_key AS archetype_key, da_b.archetype_name AS label,
        da_a.archetype_key AS opponent_key, da_a.archetype_name AS opponent_label,
        rm.wins_b AS wins, rm.wins_a AS losses, rm.draws AS draws
    FROM meta_round_match rm
    JOIN meta_event e ON e.event_id = rm.event_id
    JOIN meta_deck_archetype da_a ON da_a.event_id = rm.event_id AND da_a.deck_ord = rm.deck_ord_a
    JOIN meta_deck_archetype da_b ON da_b.event_id = rm.event_id AND da_b.deck_ord = rm.deck_ord_b
)
SELECT
    archetype_key, label, opponent_key, opponent_label, tier, format, event_date,
    COUNT(*)                                          AS n,
    SUM(CASE WHEN wins > losses THEN 1 ELSE 0 END)     AS matches_won,
    SUM(CASE WHEN wins < losses THEN 1 ELSE 0 END)     AS matches_lost,
    SUM(CASE WHEN wins = losses THEN 1 ELSE 0 END)     AS matches_drawn,
    SUM(wins)                                          AS games_won,
    SUM(losses)                                        AS games_lost
FROM sides
GROUP BY archetype_key, label, opponent_key, opponent_label, tier, format, event_date;
