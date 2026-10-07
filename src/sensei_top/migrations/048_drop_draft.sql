-- 048_drop_draft.sql — drop everything the draft assistant derived or
-- downloaded (2026-10-01).
--
-- The roadmap pivot of 2026-09-30 scoped the product to competitive 1v1
-- Constructed; Limited is out, and the draft code was deleted on
-- `feature/remove-draft`. The last commit that has it is tagged
-- `archive/draft`. Migrations 025, 028, 029, 031 and 045 stay as history:
-- a migration that has run is never edited, so removal is this new step.
--
-- Nothing of the user's is lost. The draft tables were the projector's
-- output, rebuilt from `raw_events` on every projection, and a draft
-- session's raw events stay in `raw_events` verbatim (AGENTS.md
-- non-negotiable #2) — the segmenter still labels them, so a draft feature
-- that returns can rebuild these tables from history. `card_ratings*` and
-- `limited_*` were 17lands downloads, re-fetchable on demand.
--
-- Kept: `cards.power`, `toughness` and `keywords` (031). The draft
-- assistant added them and nothing reads them today, but they are the
-- card's printed body, part of the card database rather than draft state,
-- and `cards.py` still fills them on every import.
--
-- Views first, since they name the tables; then children before parents,
-- since `db.migrate` runs with `foreign_keys=ON`. `idx_card_ratings_grp`
-- goes with its table.

DROP VIEW v_current_pack;
DROP VIEW v_current_draft;
DROP VIEW v_draft_pool;
DROP VIEW v_latest_draft;

DROP TABLE draft_pack_cards;
DROP TABLE draft_picks;
DROP TABLE draft_packs;
DROP TABLE draft_events;

DROP TABLE card_ratings;
DROP TABLE card_ratings_fetch;

DROP TABLE limited_pick_stats;
DROP TABLE limited_color_stats;
DROP TABLE limited_card_stats;
DROP TABLE limited_stats_fetch;
