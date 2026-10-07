-- Two more authored artifacts, and cost columns on the two this project
-- already had. AGENTS.md non-negotiable #5 now permits an opt-in, button-
-- triggered Claude API call (`src/sensei_top/llm/`) alongside the
-- prompt/import round trip that still works with no credential configured
-- -- see docs/llm.md. These tables hold whichever path filled them; nothing
-- here cares which one did.
--
-- `match_narrative`: the "Coach's summary" for one match -- prose over this
-- game's turn-by-turn shape and its report's findings, never a raw hand or
-- graveyard (review/narrative.py's own prompt, unchanged). One row per
-- match; a match report has no importer today (review/narrative.py's
-- docstring: a review is read once), so before this feature the prompt was
-- read and thrown away. `context_hash` is the same staleness signal
-- `matchup_brief.list_hash` plays for a brief: a SHA-256 of the prompt
-- context string itself, so any evidence change is caught without a
-- per-feature hashing rule. Reported, never acted on -- nothing here
-- regenerates itself.
CREATE TABLE match_narrative (
    match_id      TEXT PRIMARY KEY,
    prose         TEXT NOT NULL,
    prompt        TEXT NOT NULL,   -- exactly what was sent, kept inspectable
    model         TEXT NOT NULL,
    generated_at  TEXT NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    context_hash  TEXT NOT NULL
);

-- `leaks_narrative`: prose over the cross-match leak finder
-- (review/leaks_narrative.py). `GET /api/review/leaks/narrative` calls
-- `find_leaks(conn)` unfiltered -- there is no per-deck scope to key on, so
-- there is exactly one row, not a table of them.
CREATE TABLE leaks_narrative (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    prose         TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    model         TEXT NOT NULL,
    generated_at  TEXT NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    context_hash  TEXT NOT NULL
);

-- Cost is NULL, not 0.0, for anything imported by hand -- a hand-written
-- narrative genuinely has no cost to report, and NULL is what "not priced"
-- means everywhere else in this schema (AGENTS.md non-negotiable #4).
-- `model`/`author` already exist on both tables and keep recording who or
-- what wrote the prose; these three columns only add what it cost.
ALTER TABLE deck_narrative ADD COLUMN input_tokens INTEGER;
ALTER TABLE deck_narrative ADD COLUMN output_tokens INTEGER;
ALTER TABLE deck_narrative ADD COLUMN cost_usd REAL;

ALTER TABLE matchup_brief ADD COLUMN input_tokens INTEGER;
ALTER TABLE matchup_brief ADD COLUMN output_tokens INTEGER;
ALTER TABLE matchup_brief ADD COLUMN cost_usd REAL;
