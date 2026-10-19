-- 064_match_best_of.sql — a match's best-of, projected: 3, 1, or NULL.
--
-- Arena: the first gameInfo.matchWinCondition seen on the match's GRE
-- messages, MatchWinCondition_Best2of3 -> 3, MatchWinCondition_SingleElimination
-- -> 1. Any other value, or none ever seen, is NULL (an unknown value also
-- warns). MTGO's log names no structure; its matches are written as 3.
-- Rebuilt by project() like every other column on this table, so existing
-- rows are NULL until the next projection.
ALTER TABLE matches ADD COLUMN best_of INTEGER;
