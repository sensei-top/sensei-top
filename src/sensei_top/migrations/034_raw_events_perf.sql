-- 034_raw_events_perf.sql — two changes for the live-play latency pass:
--
-- 1. An index on raw_events.logged_at. /api/live's MAX(logged_at) was a
--    full table-scan of raw_events (4-7 s once the table passes a season
--    of play, per data/sensei-top.db's own measurements) because logged_at
--    carried no index at all. logged_at is *not* monotonic with id — a
--    Player-prev.log recovery pass can insert an older event after a newer
--    one — so, unlike ingested_at (replaced with an id-ordered tail read
--    in api/routes/meta.py instead of indexing it), this one genuinely
--    needs an index rather than a query rewrite.
--
-- 2. projection_state gains projected_through_id: the raw_events.id the
--    last rebuild actually covered. live.py's in-memory
--    LiveIngester._projected_through resets to 0 on every process
--    restart, so the first has_match_boundary/has_draft_boundary check
--    after a restart scanned the entire table with a LIKE. Persisting the
--    watermark here — the same table that already carries
--    last_projection_at across the watcher/API process boundary — lets a
--    restart resume from where the last rebuild left off instead of from
--    zero. project() must never write this column; only live.py's
--    poll_once() does, exactly like last_projection_at above it.
CREATE INDEX idx_raw_events_logged_at ON raw_events (logged_at);

ALTER TABLE projection_state ADD COLUMN projected_through_id INTEGER;
