-- 040_arena_only_current_match.sql — `v_current_match` becomes Arena-only.
--
-- MTGO live tracking works but is useless: MTGO writes a transcript, not a
-- board-state stream, so the opening-hand, keep-guide, remaining-library and
-- opponent-hand panels can never populate for an MTGO match
-- (`table/live.py` already filters `source = 'arena'` by construction) —
-- all an MTGO match ever rendered on the Current match tab was the status
-- strip, the colour-based opponent read and the disclosure bar. And MTGO's
-- own progressive-flush rebuild forced by `has_mtgo_boundary` (deleted in
-- this same change — `projector/mtgo/project.py`) landed it ~2.5 minutes
-- late regardless. The user's decision: stop pretending MTGO is live. Keep
-- ingesting and projecting it for History/Matchups (unaffected by this
-- migration — neither reads this view), and give the Current match tab
-- back to Arena, where every panel actually works.
--
-- `migrations/035_mtgo_source.sql` deliberately left this view untouched:
-- it is a bare `SELECT m.*`, which SQLite re-expands against the table's
-- *current* schema on every query, so `source` (added by that migration)
-- already passed through with no textual change needed. That reasoning
-- doesn't apply here — the view's WHERE clause itself needs to change, not
-- just what `m.*` expands to — so this is a real DROP + CREATE.
--
-- `migrations/036_mtgo_live.sql` asserted this view "needs NO change here"
-- once MTGO started writing a correctly-shaped `started_at`, reasoning that
-- "most recently started incomplete match wins, across both sources" was
-- the desired behaviour. That note also misquoted the inner subquery as
-- already carrying `WHERE result='incomplete'` — it never has; the original
-- 003_current_match.sql subquery is `SELECT MAX(COALESCE(started_at,''))
-- FROM matches` with no WHERE at all. Both the reasoning and the misquote
-- are superseded by this migration; 036 itself is left untouched, since
-- applied migrations are immutable.
--
-- The inner MAX subquery needs the same `source = 'arena'` filter as the
-- outer WHERE, not just the outer one. Before this migration, an MTGO match
-- holding the global-maximum `started_at` would suppress a genuinely
-- in-progress Arena match: `COALESCE(m.started_at,'') = (SELECT
-- MAX(COALESCE(started_at,'')) FROM matches)` compares every Arena match's
-- started_at against a maximum that could belong to MTGO, and no Arena row
-- would ever tie it. Not hypothetical — verified against the real database:
-- 315 MTGO matches, 23 of them `incomplete`, any one of which could have
-- outdated an Arena match's own started_at and blanked the tab. Filtering
-- only the outer WHERE would leave that bug in place; filtering both closes
-- it, and makes this view unambiguously Arena-only rather than merely
-- Arena-preferring.
--
-- Blast radius: the only readers of this view are three call sites in
-- `src/sensei_top/api/routes/current_match.py`. No CLI, projector,
-- review, guide, brief, coach or metrics path reads it, and no other view
-- joins it.
--
-- Both `idx_raw_events_mtgo_id_file`/`idx_raw_events_mtgo_file_id`
-- (036_mtgo_live.sql) are kept, deliberately, even though this migration
-- deletes `has_mtgo_boundary` (the only caller of the "any new MTGO file
-- since the watermark" check `idx_raw_events_mtgo_id_file` was built to
-- serve) — see `live.py`/`projector/mtgo/project.py`. Dropping an unused
-- index would only save a few KB, and re-adding it later would re-incur the
-- one-time 10-30s full-table scan `036_mtgo_live.sql` warns a partial index
-- build costs on a multi-GB `raw_events`. `idx_raw_events_mtgo_file_id`
-- stays in active use regardless: `_select_latest_payload_per_file`
-- (`projector/mtgo/project.py`) still runs it on every rebuild to pick the
-- longest payload per MTGO match file.

DROP VIEW v_current_match;

CREATE VIEW v_current_match AS
SELECT m.*
FROM matches m
WHERE m.result = 'incomplete'
  AND m.source = 'arena'
  AND COALESCE(m.started_at, '') = (SELECT MAX(COALESCE(started_at, ''))
                                       FROM matches WHERE source = 'arena');
