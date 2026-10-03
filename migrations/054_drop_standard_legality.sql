-- cards.standard_legality (017) is replaced by card_legality (053), where
-- Standard is one format among seven. Every reader moved to the table in the
-- phase before this one, and the importer no longer writes the column.
-- 053 copied the column into card_legality; nothing else references it (no
-- index, view or trigger), so the drop loses nothing.

ALTER TABLE cards DROP COLUMN standard_legality;
