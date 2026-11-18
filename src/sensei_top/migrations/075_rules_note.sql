-- 075_rules_note.sql — the hosted coach's answer to a rules question the app
-- wrote from card names, stored as received.
--
-- An authored-artifact table in rule 6's sense: written by one API route
-- (PUT /api/rules-notes), never read by project(), and it has to outlive the
-- full rebuild, since nothing in raw_events can recompute it. Keeping it is
-- what stops the same question being asked, and paid for, twice.
--
-- Keyed by the question and the rules version it was answered under, so a new
-- rules version asks again. question_hash is the SHA-256 hex of the question
-- after strip and whitespace collapse (ai/rules_notes.py::question_hash).
-- answer_json is the coach's response as received (verdict, explanation,
-- citations, out_of_scope); confidence is copied out of it. asked_at is UTC,
-- YYYY-MM-DDTHH:MM:SSZ.
CREATE TABLE rules_note (
    question_hash  TEXT NOT NULL,
    rules_version  TEXT NOT NULL,
    question       TEXT NOT NULL,
    outcome        TEXT NOT NULL CHECK (outcome IN ('answered', 'refused')),
    answer_json    TEXT NOT NULL CHECK (json_valid(answer_json)),
    confidence     TEXT,
    asked_at       TEXT NOT NULL,
    PRIMARY KEY (question_hash, rules_version)
);
