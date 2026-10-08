-- 063_coach_cache_tokens.sql — the coach's prompt-cache token counts
-- (plan 8.0, S2: D3).
--
-- The coach's request loop marks every request for caching
-- (llm/client.py::write_report), so a report's prompt is billed in three
-- parts, not one. cache_creation_input_tokens is what the loop wrote to the
-- cache (priced above the input rate) and cache_read_input_tokens is what it
-- read back (priced below it), each the sum of `usage` over the loop. The
-- existing input_tokens is now only the uncached remainder; the prompt's size
-- is the sum of the three.
--
-- NULL means "not measured": every report written before this migration. A
-- generated report stores what `usage` said, 0 included. Existing rows are
-- not backfilled: rule 4 forbids writing a count the row never recorded.
--
-- Only coach_report carries them. Every other generate route sends one
-- unmarked request, so its input_tokens is still the whole prompt.

ALTER TABLE coach_report ADD COLUMN cache_creation_input_tokens INTEGER;
ALTER TABLE coach_report ADD COLUMN cache_read_input_tokens INTEGER;
