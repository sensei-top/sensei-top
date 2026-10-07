-- The format a coach report was written for (plan 13, D12).
--
-- A report covers one format: its format sections (records per deck, per role
-- and per opponent archetype, the decklists, the field) read that format
-- alone, and its progress is measured against the previous report of the
-- same format (coach/store.py::latest_coach_report).
--
-- Every report written before this migration was a Standard report, so a NULL
-- here means Standard, and every reader treats it so. Existing rows are not
-- backfilled: rule 4 forbids writing an answer into a row that the row never
-- recorded, and reading NULL as Standard is this column's documented meaning.
-- Every report written from now on names its format.
--
-- Same vocabulary and CHECK as matches.format (055_match_format.sql).

ALTER TABLE coach_report ADD COLUMN format TEXT CHECK (format IS NULL OR format IN
    ('Standard', 'Pioneer', 'Modern', 'Pauper', 'Legacy', 'Vintage', 'Premodern'));
