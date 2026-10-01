-- Standard legality and Scryfall's oracle id, both from the same bulk row
-- oracle_text already comes from (see migrations/015_card_text.sql).
--
-- standard_legality = 'banned' is what makes a format reset detectable
-- without a hand-maintained ban list: guide/window.py finds when each
-- banned card stopped appearing in the tournament corpus. 'not_legal' means
-- a card rotated out, not a ban -- the two must never be conflated.
--
-- oracle_id is the identity of a card across printings and alternate names.
-- The Izzet Spellementals guide counted "Hydro-Man, Fluid Felon" and
-- "Belion, the Parched" separately and halved a 52% inclusion rate into
-- 39% + 14%; consensus counting canonicalises on oracle_id to make that
-- class of bug impossible.
--
-- Both are NULL for any card only ever named by the installed Arena client,
-- which carries neither -- the same honest gap 015 records for oracle_text.
ALTER TABLE cards ADD COLUMN standard_legality TEXT;
ALTER TABLE cards ADD COLUMN oracle_id TEXT;
