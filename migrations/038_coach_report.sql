-- 038_coach_report.sql — the coach: a dated, player-level report over every
-- Arena/MTGO match, kept as history rather than a single row a regenerate
-- overwrites (unlike `match_narrative`/`leaks_narrative`, 020_generated_
-- narrative.sql). A new report's "Since your last report" section reads a
-- past report's own `metrics_json` to say whether a focus area moved, so
-- writing a new report must never erase the one it is being compared against.
--
-- `sources_json`: `[{url,title,cited_text}]` for the web-search citations a
-- report used, plus `"R3"`-style reading-list ids (`coach/canon.py`) for
-- whichever curated entries it cited — one array, mixed, because the prompt
-- cites both the same way (`[R3]`, or a fetched URL).
--
-- `metrics_json`: `metrics_snapshot()`'s own numbers at generation time —
-- kept verbatim so a later report's progress review has something fixed to
-- diff against, the same reasoning `context_hash` already carries for a
-- single-row narrative.
--
-- `effort` and the token/cost columns follow `020_generated_narrative.sql`:
-- NULL is "not priced" or "not applicable", never a guessed number
-- (AGENTS.md non-negotiable #4/#5).
CREATE TABLE coach_report (
    id                   INTEGER PRIMARY KEY,
    generated_at         TEXT NOT NULL,
    model                TEXT NOT NULL,
    effort               TEXT,
    prompt               TEXT NOT NULL,
    prose                TEXT NOT NULL,
    sources_json         TEXT NOT NULL,  -- [{url,title,cited_text}] web citations + ["R3",...] cited reading-list ids
    metrics_json         TEXT NOT NULL,  -- metrics_snapshot() at generation, for the next progress review
    context_hash         TEXT NOT NULL,
    input_tokens         INTEGER,
    output_tokens        INTEGER,
    web_search_requests  INTEGER,
    cost_usd             REAL            -- NULL for an unpriced model, never a guess
);
