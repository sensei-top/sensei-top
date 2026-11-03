-- 070_undated_header_index.sql — finding a stored undated row by its stamp.
--
-- Every dated entry a read meets asks whether its stamp and payload are stored
-- with no time, so that row can take the date in place (reader/ingest.py,
-- _insert_entries; docs/architecture.md, "Idempotency"). Partial on the undated
-- rows, so on a database that has none the question costs one look at an empty
-- index, for every entry of every poll.
CREATE INDEX idx_raw_events_undated_header ON raw_events (header) WHERE logged_at IS NULL;
