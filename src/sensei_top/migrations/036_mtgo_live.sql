-- 036_mtgo_live.sql — live MTGO ingest: fix stored timestamps, index the
-- boundary check.
--
-- Bug A — `reader/mtgo.py::_mtime_iso` used to write UTC-with-`Z`
-- (`2026-09-14T15:42:44Z`) while every Arena timestamp
-- (`reader/segmenter.py::parse_header_timestamp`, `matches.started_at`) is a
-- naive local wall-clock string with no zone at all. `logged_at` and
-- `started_at` are compared as TEXT across sources (`v_current_match`'s
-- `MAX(COALESCE(started_at,''))`, `/api/matches`' `ORDER BY`, `/api/live`'s
-- `MAX(logged_at)`), so on a UTC-3 host an MTGO row sorted as though it were
-- 3 hours newer than an Arena row at the same instant, and `'Z'` (0x5A)
-- sorts after every digit, inverting order across a one-second boundary
-- besides. `_mtime_iso` itself is already fixed in code (this migration only
-- repairs rows written before the fix).
--
-- This edits a reader-derived *metadata* column only — `logged_at`, never
-- `payload` — so verbatim raw-event storage (AGENTS.md non-negotiable #2) is
-- untouched: the bytes MTGO actually wrote are not being reinterpreted, only
-- the bookkeeping timestamp this tracker itself attached on read.
--
-- Verified on SQLite 3.53.1: bare datetime('2026-09-14T15:42:44Z', 'localtime')
-- -> '2026-09-14 12:42:44' (this host's UTC-3 offset) — a SPACE separator,
-- not the 'T' every Arena timestamp uses. strftime('%Y-%m-%dT%H:%M:%S', ...)
-- around it reshapes that same value to '2026-09-14T12:42:44'. Only 'mtgo'
-- rows carry the old shape; Arena rows are untouched by the WHERE clause
-- below.
UPDATE raw_events
   SET logged_at = strftime('%Y-%m-%dT%H:%M:%S', datetime(logged_at, 'localtime'))
 WHERE source = 'mtgo';

-- has_mtgo_boundary (projector/mtgo/project.py) asks "is there a raw_events
-- row for a *new* mtgo source_file past a given id" on every live poll. Both
-- orderings are partial indexes scoped to `source='mtgo'` — a few KB even
-- against a multi-GB raw_events, since Arena rows (the overwhelming
-- majority) never match the predicate.
--
-- Building a partial index still requires one full scan of raw_events to
-- find the qualifying rows: on a table that has grown to ~1.5 GB this is a
-- one-time cost of roughly 10-30 s the first time a database upgrades past
-- this migration. Expected, not a hang — `serve --watch` applies migrations
-- synchronously on startup (see AGENTS.md's "live watcher applies
-- migrations" note), so that one startup will pause before serving.
CREATE INDEX idx_raw_events_mtgo_id_file
    ON raw_events (id, source_file) WHERE source = 'mtgo';
CREATE INDEX idx_raw_events_mtgo_file_id
    ON raw_events (source_file, id) WHERE source = 'mtgo';

-- `v_current_match` (003_current_match.sql) needs NO change here. It already
-- reads `WHERE result='incomplete' AND COALESCE(started_at,'') = (SELECT
-- MAX(COALESCE(started_at,'')) FROM matches WHERE result='incomplete')` —
-- "most recently started incomplete match wins" — and it is a bare
-- `SELECT m.*`, so `source` (added in 035_mtgo_source.sql) already passes
-- through with no textual change to the view. Once `projector/mtgo/project.py`
-- writes a real, correctly-shaped `started_at` (this migration's UPDATE plus
-- the `_mtime_iso` fix), that comparison starts working for MTGO rows too:
-- today every MTGO match has `started_at = NULL`, so they all tie at `''`
-- and SQLite's `.fetchone()` on ties picks arbitrarily.
--
-- One case this view still cannot express, deliberately left unfixed: an
-- MTGO match live at 14:00 while an Arena match both starts *and finishes*
-- at 14:30. `MAX(started_at)` picks the completed Arena match, so the tab
-- shows neither. Do NOT "fix" this with
-- `MAX(COALESCE(ended_at, started_at, ''))` — that is a regression for pure
-- Arena play, since a just-finished match would then hide a still-incomplete
-- earlier one. The real fix is a `matches.last_event_at` column, populated
-- by both projectors on every rebuild, that `v_current_match` could order by
-- instead of `started_at`; it only matters when Arena and MTGO are being
-- played interleaved, and until it exists this edge case degrades to
-- "tab shows no match" rather than "tab shows the wrong match."
