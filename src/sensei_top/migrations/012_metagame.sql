-- 012_metagame.sql — the field's own numbers: tournament results downloaded
-- from fbettega/MTG_decklistcache (MTGO and paper/Melee only — never Arena,
-- which publishes no event results at all), the evidence tier each event is
-- licensed for, and the classifier's verdict over each stored decklist.
--
-- See docs/metagame.md for the tier rules and why they are enforced both
-- here and in the views built on top of this schema
-- (013_metagame_views.sql), not left as a convention future code could
-- violate silently.

-- ---------------------------------------------------------------------------
-- Reference data, exactly like `archetypes`: downloaded, not derived, and
-- deliberately outside the projector's DELETE set so a rebuild never
-- discards a fetch. `event_id` is the file's own path in the source
-- repository — already globally unique, so no synthetic id is needed.
-- `blob_sha` is what makes a refresh incremental: a file whose blob has not
-- changed upstream is never re-fetched.
--
-- Deliberately NO player names anywhere in this file's tables.
-- metagame/source.py's module docstring explains why: a cache decklist
-- carries a real MTGO/Melee handle, and AGENTS.md's privacy rule forbids
-- storing one for a third party who never consented to this project.
-- `Player` is resolved to a per-event deck ordinal at parse time and never
-- reaches SQLite.
-- ---------------------------------------------------------------------------
CREATE TABLE meta_event (
    event_id        TEXT PRIMARY KEY,
    path            TEXT NOT NULL,
    blob_sha        TEXT NOT NULL,
    source          TEXT NOT NULL,
    name            TEXT NOT NULL,
    event_date      TEXT,
    format          TEXT,
    tier            TEXT NOT NULL CHECK (tier IN ('A', 'B', 'C')),
    standings_rows  INTEGER NOT NULL DEFAULT 0,
    uri             TEXT
);

CREATE INDEX idx_meta_event_date ON meta_event (event_date);

-- One row, so a refresh can decide staleness without counting rows, and an
-- offline run can say how old the corpus it is using is. `commit_sha` is
-- the pinned snapshot every file in the refresh was read from — one column,
-- the whole reproducibility story.
CREATE TABLE meta_fetch (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    commit_sha   TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    window_days  INTEGER NOT NULL,
    events       INTEGER NOT NULL,
    skipped      INTEGER NOT NULL DEFAULT 0
);

-- One row per deck in one event. `deck_ord` is the deck's position within
-- its event's own Decks[] list — the only identity a player-less row needs,
-- since meta_round_match below references decks the same way.
--
-- Mainboard/sideboard are stored verbatim (the same discipline AGENTS.md
-- rule 2 asks of raw_events, applied to this corpus too): when archetype
-- definitions change, reclassifying is a re-run over these rows, never a
-- re-download.
CREATE TABLE meta_deck (
    event_id        TEXT NOT NULL REFERENCES meta_event (event_id),
    deck_ord        INTEGER NOT NULL,
    result          TEXT,
    wins            INTEGER NOT NULL DEFAULT 0,
    losses          INTEGER NOT NULL DEFAULT 0,
    draws           INTEGER NOT NULL DEFAULT 0,
    mainboard_json  TEXT NOT NULL,
    sideboard_json  TEXT NOT NULL,
    PRIMARY KEY (event_id, deck_ord)
);

-- Never populated for a Tier C event, which has no rounds at all (see
-- metagame/tiers.py). Deck references are ordinals into the same event's
-- meta_deck, never a player name.
CREATE TABLE meta_round_match (
    event_id    TEXT NOT NULL REFERENCES meta_event (event_id),
    round_name  TEXT NOT NULL,
    deck_ord_a  INTEGER NOT NULL,
    deck_ord_b  INTEGER NOT NULL,
    wins_a      INTEGER NOT NULL DEFAULT 0,
    wins_b      INTEGER NOT NULL DEFAULT 0,
    draws       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_meta_round_match_event ON meta_round_match (event_id);

-- ---------------------------------------------------------------------------
-- The classifier's output over the corpus. A full rebuild, like
-- `opponent_archetype` for personal matches, and deleted-and-recomputed for
-- the same reason: its rows point at decks a corpus refresh may have
-- replaced. A deck with no verdict simply has no row here — same convention
-- as `opponent_archetype`.
--
-- `archetype_key` matches the same column in `opponent_archetype` and the
-- same `Definition.key` from `archetypes`: the file stem MTGOFormatData
-- itself uses, which is what makes a personal matchup and a field matchup
-- joinable on one vocabulary at all.
-- ---------------------------------------------------------------------------
CREATE TABLE meta_deck_archetype (
    event_id        TEXT NOT NULL REFERENCES meta_event (event_id),
    deck_ord        INTEGER NOT NULL,
    archetype_key   TEXT NOT NULL,
    archetype_name  TEXT NOT NULL,
    colors          TEXT,
    label           TEXT NOT NULL,
    method          TEXT NOT NULL CHECK (method IN ('archetype', 'fallback')),
    classified_at   TEXT NOT NULL,
    PRIMARY KEY (event_id, deck_ord)
);
