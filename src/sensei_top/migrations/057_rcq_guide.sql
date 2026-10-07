-- 057_rcq_guide.sql — the RCQ guide: a tournament-day document for the exact
-- 75 a player is about to register, kept as history (every generation is a
-- row) rather than one slot a regenerate overwrites, the way `coach_report`
-- (038_coach_report.sql) is: each guide is written against the field of its
-- day, and an older one must stay readable.
--
-- An authored-artifact table (AGENTS.md non-negotiable #6): nothing in it is
-- derived from projected data, and `project()` never reads or deletes it.
--
-- `decklist_text` is the 75 exactly as pasted. `expected_json` is the corpus
-- archetype keys the player expected at the store. `guide_json` is the whole
-- RcqNarrative, plan problems included. `corpus_latest_event` is the newest
-- event date the corpus held when it was written.
--
-- `effort` and the token/cost columns follow `020_generated_narrative.sql`:
-- NULL is "not priced" or "not applicable", never a guessed number
-- (AGENTS.md non-negotiable #4/#5).

CREATE TABLE rcq_guide (
    id                  INTEGER PRIMARY KEY,
    deck_key            TEXT NOT NULL,
    generated_at        TEXT NOT NULL,
    model               TEXT NOT NULL,
    effort              TEXT,
    decklist_text       TEXT NOT NULL,
    expected_json       TEXT NOT NULL,
    own_archetype_key   TEXT,
    prompt              TEXT NOT NULL,
    guide_json          TEXT NOT NULL,
    corpus_latest_event TEXT,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    cost_usd            REAL
);

CREATE INDEX rcq_guide_deck ON rcq_guide (deck_key, generated_at);
