-- 028_human_draft.sql — make draft_events able to hold a *human* draft
-- (Premier / Traditional / Cube), whose log protocol is a different message
-- family from Quick Draft's and was unverified when 025_draft.sql was written.
--
-- Verified against a real Phantom Cube capture (2026-09-08,
-- CubeDraft_Powered_20260908, 2 packs, 22 picks). Two facts from that capture
-- do not fit the original table:
--
--   1. `CubeDraft` is a real draft queue, but the old CHECK admitted only
--      quick/premier/traditional, so a cube could only be stored as
--      queue = NULL -- and draft/rank.py treats NULL as "not a draft queue at
--      all" (the guard that keeps Sealed from being ranked), which would have
--      left the tab blank for the very event this migration exists to show.
--
--   2. The human family's pack message (`Draft.Notify`) carries a real
--      `draftId` but NO event name. The name is recoverable only from an
--      earlier message (EventJoin / the Course payload), so a capture that
--      begins mid-draft genuinely does not know it. `event_name` therefore
--      becomes nullable: unknown stays NULL rather than being guessed
--      (non-negotiable #4). It stays NOT NULL for nothing that can supply it.
--
-- Emptying the four projector-owned draft tables first is not data loss: they
-- are rebuilt in full from `raw_events` by the next project() run, which is
-- non-negotiable #3. Children before parents, for the foreign keys.
DELETE FROM draft_pack_cards;
DELETE FROM draft_picks;
DELETE FROM draft_packs;
DELETE FROM draft_events;

DROP TABLE draft_events;

CREATE TABLE draft_events (
    draft_id    TEXT PRIMARY KEY,
    event_name  TEXT,
    ordinal     INTEGER NOT NULL,
    queue       TEXT CHECK (queue IN ('quick', 'premier', 'traditional', 'cube') OR queue IS NULL),
    set_code    TEXT,
    started_at  TEXT,
    ended_at    TEXT
);
