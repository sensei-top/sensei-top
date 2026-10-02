-- 022_meta_source_fetch.sql — per-source fetch bookkeeping for the metagame
-- corpus, so a second tournament source (TopDeck.gg, metagame/topdeck.py)
-- can report its own freshness without cramming a second source into
-- meta_fetch's single row.
--
-- meta_fetch (012_metagame.sql) stays exactly as it was — the fbettega
-- cache's own commit-pinned reproducibility story — and refresh_metagame()
-- keeps writing it unchanged. This table is additive: refresh_metagame()
-- now *also* upserts a 'fbettega' row here, and metagame/topdeck.py's
-- refresh_topdeck() writes a 'topdeck' row the same way, so both sources
-- report through one per-source query instead of two different shapes.
--
-- `ref` is source-specific and never interpreted structurally: the fbettega
-- row's `ref` is the commit SHA every file was read from (meta_fetch's own
-- `commit_sha`); the topdeck row's `ref` is just its API base URL, since a
-- REST query has no single pinned snapshot to name.
CREATE TABLE meta_fetch_source (
    source       TEXT PRIMARY KEY,
    ref          TEXT,
    fetched_at   TEXT NOT NULL,
    window_days  INTEGER,
    events       INTEGER NOT NULL DEFAULT 0,
    skipped      INTEGER NOT NULL DEFAULT 0
);

-- Backfill: the existing single-source fetch state becomes the 'fbettega'
-- row, so a database that already has a cache refresh doesn't read back as
-- "never fetched" the moment this migration applies.
INSERT INTO meta_fetch_source (source, ref, fetched_at, window_days, events, skipped)
SELECT 'fbettega', commit_sha, fetched_at, window_days, events, skipped
FROM meta_fetch WHERE id = 1;
