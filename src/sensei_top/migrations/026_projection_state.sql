-- 026_projection_state.sql — watcher bookkeeping for the last projection run,
-- readable across a process boundary.
--
-- The watcher used to report last_projection_at from an in-memory LiveStats
-- dataclass, which only works when the watcher and the API share a process.
-- Running the watcher as a separate process (so its project() rebuild stops
-- contending with the API for the GIL — see live.py's module docstring)
-- means that field has to cross via the database instead. A single row,
-- like ingest_state's one-row-per-file bookkeeping.
--
-- project() must NEVER DELETE FROM this table. It is watcher bookkeeping,
-- exactly like ingest_state — not projected data — so it sits outside
-- project()'s "delete every derived row and recompute" rule.
CREATE TABLE projection_state (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    last_projection_at  TEXT,
    projections         INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT
);
