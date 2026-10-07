-- 029_current_draft_activity.sql — rank "the current draft" by activity, not
-- by start time, and fix a real bug this exposed in either family.
--
-- The old v_current_draft (025_draft.sql) picked the draft with the newest
-- COALESCE(started_at, ''). started_at is set only from a genuine P1P1 pack
-- message — and projector/draft.py explicitly promises to record a draft
-- whose opening pack the log never captured (a rotation mid-draft) rather
-- than drop it, with started_at left NULL as the honest gap. That draft then
-- loses the MAX comparison to any *older* draft that happens to have a
-- timestamp, and the old view returned zero rows for the entire time that
-- draft was in progress — reproduced end to end against a real capture with
-- its P1P1 line removed. This is not human-draft-specific: Quick Draft's own
-- _feed_pack_state only sets started_at at DraftState creation and never
-- backfills it either, so a Quick Draft missing its opening pack has the
-- identical exposure. This fix covers both families.
--
-- The replacement ranks by the newest known activity for a draft — its
-- latest seen pack, falling back to started_at, falling back to "never" —
-- rather than only ever looking at started_at.
--
-- The naive fix ("filter to unfinished drafts, then rank those by activity")
-- was tried first and is wrong: it resurrects a stale interrupted draft the
-- moment the true newest draft completes, since a completed draft no longer
-- competes for the MAX once finished drafts are filtered out first. The old
-- view's real property — the single most-recently-active draft overall
-- decides "is there a current draft", and it only counts if IT is
-- unfinished — has to be preserved. So this ranks every draft (finished or
-- not) by activity, takes the single newest one, and only then checks
-- whether that one is still open.
--
-- v_current_pack is dropped and recreated alongside v_current_draft even
-- though its own text does not change: SQLite resolves views at query time,
-- so leaving it in place while its dependency is dropped and recreated would
-- still work, but it would read as though nothing downstream depends on this
-- change when something does.
DROP VIEW v_current_pack;
DROP VIEW v_current_draft;

CREATE VIEW v_current_draft AS
SELECT draft_id, event_name, ordinal, queue, set_code, started_at, ended_at
FROM (
    SELECT d.*,
           COALESCE(
               (SELECT MAX(p.seen_at) FROM draft_packs p WHERE p.draft_id = d.draft_id),
               d.started_at,
               ''
           ) AS last_seen_at
    FROM draft_events d
    -- rowid tiebreak = first-seen-in-replay order, since project() inserts
    -- draft_events in that order; relies on draft_events keeping its
    -- default rowid (it is never declared WITHOUT ROWID).
    ORDER BY last_seen_at DESC, d.rowid DESC
    LIMIT 1
)
WHERE ended_at IS NULL;

-- Unchanged from 025_draft.sql. Recreated here only because it was dropped
-- above to satisfy the view dependency, not because its logic changed.
CREATE VIEW v_current_pack AS
SELECT p.*
FROM draft_packs p
JOIN v_current_draft d USING (draft_id)
LEFT JOIN draft_picks k USING (draft_id, pack_number, pick_number)
WHERE k.grp_id IS NULL
ORDER BY p.pack_number DESC, p.pick_number DESC
LIMIT 1;
