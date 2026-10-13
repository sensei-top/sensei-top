-- 062_header_date_order.sql — the header as written, and the day/month order
-- learned per header shape (plan 3, S10: D4 and D11).
--
-- raw_events.header is the stamp of the header an entry inherited its
-- logged_at from, exactly as written (reader/segmenter.py's LogEntry.header),
-- NULL when no header preceded it. It is outside the digest, so adding it
-- changes no row's identity. A date misread today stays re-derivable from it
-- later; nothing re-derives yet.
--
-- ingest_state.carry_header is the third segmenter carry value, beside
-- carry_ts and carry_context (migration 042), so an entry that opens a poll
-- inherits the previous poll's header text along with its time. NULL for
-- every MTGO row, like the other two.
--
-- header_date_order is what --locale auto learned (reader/dates.py): one row
-- per shape key (segmenter.py's _SHAPES, keys that never change), the order
-- (mdy or dmy), the stamp that settled it, the file it was read from (as
-- raw_events.source_file records it) and when, in UTC
-- (%Y-%m-%dT%H:%M:%SZ). Only the reader writes it, and only when a shape's
-- order changes. Reader state like ingest_state: project() never reads or
-- deletes it.
--
-- No backfill (rule 4): rows stored before this migration keep NULL.

ALTER TABLE raw_events ADD COLUMN header TEXT;
ALTER TABLE ingest_state ADD COLUMN carry_header TEXT;

CREATE TABLE header_date_order (
    shape       TEXT PRIMARY KEY,
    date_order  TEXT NOT NULL CHECK (date_order IN ('mdy', 'dmy')),
    settled_by  TEXT NOT NULL,
    source_file TEXT NOT NULL,
    settled_at  TEXT NOT NULL
);
