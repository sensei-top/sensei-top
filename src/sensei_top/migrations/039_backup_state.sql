-- 039_backup_state.sql — one row of facts about the daily database backup
-- (`src/sensei_top/backup/`).
--
-- The 24 h gate this feature lives by has to be persisted here rather than
-- held in memory: a wall-clock check in a process-local variable resets on
-- every restart, and restarting `serve` three times in an evening would mean
-- three multi-minute, multi-gigabyte `VACUUM INTO` runs instead of one. This
-- table is what lets a brand-new process know a backup already ran today.
--
-- One row, not history like `coach_report` — a backup is measured against
-- nothing, so there is no "since last time" to diff a run against, only
-- "when did the last one succeed and is the copy on disk still good."
--
-- `last_error`/`last_error_at` exist because `cli.main()` sets logging to
-- ERROR unless `--verbose`, so the background thread's own `log.warning` on a
-- failed run is otherwise invisible in normal use. This column is the only
-- channel a user actually sees it through — `sensei-top config` reads it
-- back and prints it next to the last good backup's age.
--
-- `running_since`/`running_pid` are an *advisory claim, not a lock*: safety
-- against a corrupted backup comes from the pid-suffixed temp file plus
-- `os.replace`'s atomicity, not from anything winning this row. A claim only
-- prevents two runs from wasting a copy on each other; a stale one (older
-- than `CLAIM_STALE_SECONDS`) is simply taken over.
--
-- project() must NEVER DELETE FROM this table, the same way it must not touch
-- projection_state or ingest_state. It is backup bookkeeping, not projected
-- data, so it sits outside non-negotiable #3's "delete every derived row and
-- recompute" rule — and a rebuild that wiped it would silently re-arm the 24 h
-- gate, costing a multi-gigabyte copy the machine did not need.
CREATE TABLE backup_state (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    last_backup_at       TEXT,     -- ISO-8601 UTC 'Z' form, NULL = never succeeded
    last_path            TEXT,     -- absolute path of the slot written
    last_bytes           INTEGER,  -- os.stat().st_size of that file
    last_duration_ms     INTEGER,  -- measured wall time of the whole run
    last_schema_version  INTEGER,  -- the source's MAX(schema_version.version)
    backups              INTEGER NOT NULL DEFAULT 0,  -- successful runs, ever
    last_error           TEXT,     -- most recent failure; survives a later success
    last_error_at        TEXT,
    running_since        TEXT,     -- advisory claim; NULL when idle
    running_pid          INTEGER,
    updated_at           TEXT
);
