-- The format a match was played in (plan 13, D8).
--
-- Arena's log names it (the deck's Format attribute and the event id), so the
-- Arena projector fills this from formats.arena_format. Limited and Arena-only
-- queues stay NULL. MTGO's log never names one, so MTGO matches are NULL here.
-- The user's pick (mtgo_match_pick) and the inference are never written into
-- this column: they are resolved at read time (D6, v_match_format), because
-- project() may not read the pick (non-negotiable 6).
-- Rebuilt by project() with the rest of matches, so existing rows are NULL
-- until the next projection.

ALTER TABLE matches ADD COLUMN format TEXT CHECK (format IS NULL OR format IN
    ('Standard', 'Pioneer', 'Modern', 'Pauper', 'Legacy', 'Vintage', 'Premodern'));
