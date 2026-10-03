-- 031_card_body.sql — power, toughness and keywords on `cards`, plus a
-- post-draft read view.
--
-- Same reference-data shape as 015_card_text.sql/017_card_legality.sql/
-- 021_produced_mana.sql: populated by `sensei-top cards --scryfall`, never
-- by the Arena-client path (read_arena_cards carries none of this either —
-- same honest gap those three migrations already record). A 2-mana 3/3
-- flier and a 4-mana 2/2 vanilla are indistinguishable to any grader working
-- from the columns that existed before this migration, and body quality is
-- the single largest input to a Limited creature's value (draft/grade.py).
--
-- power/toughness are TEXT, not INTEGER: '*' and '1+*' are real Scryfall
-- values (Tarmogoyf, Gyruda-style creatures), and storing them as a
-- fabricated number would misstate a card whose body genuinely varies.
-- draft/grade.py treats a non-numeric power/toughness as "no body term",
-- never a guess.
ALTER TABLE cards ADD COLUMN power TEXT;
ALTER TABLE cards ADD COLUMN toughness TEXT;
ALTER TABLE cards ADD COLUMN keywords TEXT;   -- JSON array, like colors/produced_mana

-- v_latest_draft — 029's activity ranking without the "still open" filter.
-- v_current_draft (029) answers "what draft is running right now" and goes
-- empty the instant a draft ends, which is why there has never been a
-- post-draft view: draft/build.py's recommended-deck read needs to answer
-- *after* the last pick too. Ranking logic (latest seen pack, falling back
-- to started_at, falling back to "never") is copied verbatim from 029's own
-- v_current_draft rather than refactored to share a subquery — the two
-- views diverge only in whether they filter on ended_at afterward, and
-- SQLite has no clean way to parameterize "with/without a WHERE" without a
-- view-of-a-view that would just re-run the same ordering twice.
CREATE VIEW v_latest_draft AS
SELECT draft_id, event_name, ordinal, queue, set_code, started_at, ended_at
FROM (
    SELECT d.*,
           COALESCE(
               (SELECT MAX(p.seen_at) FROM draft_packs p WHERE p.draft_id = d.draft_id),
               d.started_at,
               ''
           ) AS last_seen_at
    FROM draft_events d
    ORDER BY last_seen_at DESC, d.rowid DESC
    LIMIT 1
);
