-- The match summary's four written parts, stored as the model wrote them
-- (`{games, key_leak, counter_argument, confidence}`), beside `prose`, which
-- keeps the same four joined under fixed headings. Nullable: a summary
-- written before this column existed is one paragraph with no parts, and
-- NULL is a real absence, never backfilled.
ALTER TABLE match_narrative ADD COLUMN sections_json TEXT;
-- The coach's one-line "One thing this week", lifted out of the report's
-- prose when it is stored. NULL for a report written before it existed.
ALTER TABLE coach_report ADD COLUMN headline TEXT;
