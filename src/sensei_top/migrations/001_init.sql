-- 001_init.sql — initial schema (M0 scope: raw_events; M1/M2 tables created now so
-- migrations stay linear, populated later by the projector).

CREATE TABLE schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Stage 1: append-only raw event store. The reader writes here and nowhere else.
-- ---------------------------------------------------------------------------
CREATE TABLE raw_events (
    id           INTEGER PRIMARY KEY,
    digest       TEXT NOT NULL UNIQUE,          -- sha256 of raw payload bytes: idempotent re-reads
    source_file  TEXT NOT NULL,                 -- e.g. 'Player.log', 'Player-prev.log'
    logged_at    TEXT,                          -- header timestamp, ISO-8601 UTC; NULL if unparseable (never synthesized)
    ingested_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    kind         TEXT NOT NULL,                 -- coarse classifier: 'request' | 'response' | 'event'
    label        TEXT,                          -- method name (==>/<==) or top-level event key when cheap to extract
    payload      TEXT NOT NULL                  -- raw JSON, exactly as extracted from the log
);

CREATE INDEX idx_raw_events_kind   ON raw_events (kind);
CREATE INDEX idx_raw_events_label  ON raw_events (label);

-- ---------------------------------------------------------------------------
-- Stage 2: derived tables. The projector owns these and may drop/rebuild them
-- from raw_events at any time (--rebuild). Nothing else writes here.
-- ---------------------------------------------------------------------------
CREATE TABLE decks (
    deck_id     TEXT PRIMARY KEY,               -- sha256 over sorted (grpId, count) maindeck list
    name        TEXT,                           -- most recent human name seen in Arena
    format      TEXT,
    cards_json  TEXT NOT NULL,                  -- canonical maindeck + sideboard as JSON
    first_seen  TEXT,
    last_seen   TEXT
);

CREATE TABLE matches (
    match_id          TEXT PRIMARY KEY,
    event_id          TEXT,                     -- e.g. 'Traditional_Ladder'
    deck_id           TEXT REFERENCES decks (deck_id),
    self_seat         INTEGER,
    opponent_seat     INTEGER,
    opponent_user_id  TEXT,                     -- kept per project decision (no anonymization)
    opponent_name     TEXT,
    started_at        TEXT,
    ended_at          TEXT,
    result            TEXT CHECK (result IN ('win', 'loss', 'draw', 'incomplete')),
    games_won         INTEGER,
    games_lost        INTEGER,
    completed_reason  TEXT                      -- e.g. 'MatchCompletedReasonType_Success'
);

CREATE INDEX idx_matches_deck ON matches (deck_id);

CREATE TABLE games (
    match_id        TEXT NOT NULL REFERENCES matches (match_id),
    game_number     INTEGER NOT NULL,
    on_play         INTEGER,                    -- 0/1, per game (Bo3 alternates within a match)
    result          TEXT CHECK (result IN ('win', 'loss', 'draw', 'incomplete')),
    result_reason   TEXT,                       -- 'ResultReason_Concede' | '_Timeout' | ...
    turn_count      INTEGER,
    self_mulligans  INTEGER,
    opp_mulligans   INTEGER,
    PRIMARY KEY (match_id, game_number)
);

CREATE TABLE turns (
    match_id         TEXT NOT NULL,
    game_number      INTEGER NOT NULL,
    turn_number      INTEGER NOT NULL,
    active_seat      INTEGER,
    self_life        INTEGER,
    opp_life         INTEGER,
    self_hand        INTEGER,
    opp_hand         INTEGER,
    self_lands       INTEGER,
    self_permanents  INTEGER,
    opp_permanents   INTEGER,
    PRIMARY KEY (match_id, game_number, turn_number),
    FOREIGN KEY (match_id, game_number) REFERENCES games (match_id, game_number)
);

-- ---------------------------------------------------------------------------
-- MVP metric views (thin API reads these; SQL aggregation stays in the DB).
-- ---------------------------------------------------------------------------

-- Metric 1: winrate by deck (match- and game-level).
CREATE VIEW v_deck_winrate AS
SELECT
    d.deck_id,
    d.name                                                          AS deck_name,
    m.event_id,
    COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw'))     AS matches_completed,
    COUNT(*) FILTER (WHERE m.result = 'win')                        AS matches_won,
    SUM(COALESCE(m.games_won, 0))                                   AS games_won,
    SUM(COALESCE(m.games_lost, 0))                                  AS games_lost
FROM matches m
JOIN decks d USING (deck_id)
GROUP BY d.deck_id, m.event_id;

-- Metric 2: winrate on the play vs on the draw, per game, overall and per deck.
CREATE VIEW v_play_draw_winrate AS
SELECT
    m.deck_id,
    g.on_play,
    COUNT(*) FILTER (WHERE g.result IN ('win', 'loss', 'draw'))     AS games_completed,
    COUNT(*) FILTER (WHERE g.result = 'win')                        AS games_won
FROM games g
JOIN matches m USING (match_id)
WHERE g.on_play IS NOT NULL
GROUP BY m.deck_id, g.on_play;

-- Metric 3a: per-deck game length and winrate bucketed by length.
CREATE VIEW v_deck_game_length AS
SELECT
    m.deck_id,
    g.turn_count,
    COUNT(*)                                                        AS games,
    COUNT(*) FILTER (WHERE g.result = 'win')                        AS games_won
FROM games g
JOIN matches m USING (match_id)
WHERE g.turn_count IS NOT NULL
GROUP BY m.deck_id, g.turn_count;

-- Metric 3b: per-deck averages by turn number (life/hand/board curves).
CREATE VIEW v_deck_turn_curves AS
SELECT
    m.deck_id,
    t.turn_number,
    COUNT(*)                    AS samples,
    AVG(t.self_life)            AS avg_self_life,
    AVG(t.opp_life)             AS avg_opp_life,
    AVG(t.self_hand)            AS avg_self_hand,
    AVG(t.opp_hand)             AS avg_opp_hand,
    AVG(t.self_lands)           AS avg_self_lands,
    AVG(t.self_permanents)      AS avg_self_permanents,
    AVG(t.opp_permanents)       AS avg_opp_permanents
FROM turns t
JOIN matches m USING (match_id)
GROUP BY m.deck_id, t.turn_number;
