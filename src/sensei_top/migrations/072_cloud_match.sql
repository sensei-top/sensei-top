-- 072_cloud_match.sql — a match pulled back from the user's own cloud
-- backup, stored as received, for a match this install has no raw events of.
--
-- An authored-artifact table in rule 6's sense: written by one API route
-- (PUT /api/sync/pulled), never read by project(), and it has to outlive the
-- full rebuild, since nothing in raw_events can recompute it. A match read
-- from this install's own log always wins: the route never stores a row for a
-- match_id in matches, and whatever reads this table hides a row whose
-- match_id is there.
--
-- Deliberately NO foreign key, for the reason opponent_deck_override has
-- none (004_archetypes.sql): the rows here are for matches that are not in
-- matches at all.
--
-- payload is the cloud's JSON object, re-serialized canonically (sorted keys,
-- no whitespace: sync/payloads.py::canonical_json), so it reads back as the
-- bytes the pushing install digested. played_at, updated_at and received_at
-- are UTC, written as YYYY-MM-DDTHH:MM:SSZ. updated_at is when the cloud row
-- last changed, received_at when this install last wrote it.
CREATE TABLE cloud_match (
    match_id        TEXT PRIMARY KEY,
    source          TEXT NOT NULL CHECK (source IN ('arena', 'mtgo')),
    played_at       TEXT,
    payload         TEXT NOT NULL CHECK (json_valid(payload)),
    schema_version  INTEGER NOT NULL,
    updated_at      TEXT NOT NULL,
    received_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
