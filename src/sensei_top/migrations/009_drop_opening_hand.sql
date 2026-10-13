-- 009_drop_opening_hand.sql — remove the opening-hand reconstruction.
--
-- Arena only emits the kept hand's zone transfers after the mulligan
-- decision is already committed, so by the time this projection could
-- report anything, the decision it might have informed is over. The view
-- drops before the column: SQLite refuses to drop a column a view
-- references.
DROP VIEW v_opening_hand;

ALTER TABLE turn_zones DROP COLUMN library_exit_turn;
