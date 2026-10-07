-- 002_ingest_state.sql — reader resume state.
--
-- One row per source file. The reader records where it stopped so a restart
-- resumes instead of re-reading (dedupe would catch it, but re-hashing 17 MB
-- on every start is waste). Inode + size let us detect Arena's launch-time
-- truncation and the file rotation to Player-prev.log.

CREATE TABLE ingest_state (
    source_path   TEXT PRIMARY KEY,   -- absolute path as given to the reader
    inode         TEXT,               -- opaque identity token; TEXT because some
                                      -- filesystems (overlayfs) exceed SQLite's INTEGER range
    byte_offset   INTEGER NOT NULL DEFAULT 0,
    last_size     INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
