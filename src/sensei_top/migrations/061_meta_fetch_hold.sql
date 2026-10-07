-- Read dates on corpus events, and the hold a fetcher keeps on a source that
-- answered with a refusal (plan 14, S2).
--
-- lists_read_at is when a read of the event last returned decklists.
-- empty_read_at and empty_read_kind are when the latest read returned none
-- ('empty') or found no page at all ('gone'); a later read with lists clears
-- both. Times are %Y-%m-%dT%H:%M:%SZ. There is no backfill (rule 4): an event
-- stored before this migration keeps NULL, which the read lines render as a
-- date that was not recorded.
--
-- meta_fetch_hold is one row per source whose fetch is on hold. http_status
-- is the hold's cause; answers counts the run of first-request 503s (the
-- mtgo.com fetch only, 0 otherwise); last_status and last_at are the latest
-- answer that affected the hold.
--
-- Only the fetchers write any of this, and project() never reads it.

ALTER TABLE meta_event ADD COLUMN lists_read_at TEXT;
ALTER TABLE meta_event ADD COLUMN empty_read_at TEXT;
ALTER TABLE meta_event ADD COLUMN empty_read_kind TEXT CHECK (empty_read_kind IN ('empty','gone'));

CREATE TABLE meta_fetch_hold (
    source TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('waiting','paused')),
    http_status INTEGER NOT NULL,
    answers INTEGER NOT NULL,
    since TEXT NOT NULL,
    last_status INTEGER NOT NULL,
    last_at TEXT NOT NULL,
    not_before TEXT
);
