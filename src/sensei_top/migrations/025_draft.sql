-- 025_draft.sql — the live draft assistant: pack contents, the pick actually
-- made, and the field's own Limited card ratings to rank a pack by.
--
-- Verified against a real Quick Draft capture (2026-09-05, SOS, 42 picks):
-- there is no draft-instance id anywhere in the log. `EventName`
-- ("QuickDraft_SOS_20260831") names the *event*, which is redrafted
-- repeatedly, so `projector/draft.py` synthesizes `draft_id` itself —
-- `f"{event_name}#{ordinal}"` — the same reasoning `metagame/source.py`
-- already uses to resolve MTGO/Melee handles to per-event ordinals rather
-- than trusting an identifier the source never actually provides.

-- ---------------------------------------------------------------------------
-- Projector-owned: rebuilt by project() on every run, same as matches/games.
-- Pack/pick numbers are stored exactly as Arena sends them (0-indexed) — P1P1
-- is (0, 0) — so the stored data stays faithful to the log; the +1 for
-- display happens once, at the API boundary.
-- ---------------------------------------------------------------------------
CREATE TABLE draft_events (
    draft_id    TEXT PRIMARY KEY,
    event_name  TEXT NOT NULL,   -- Arena's own string, e.g. 'QuickDraft_SOS_20260831'
    ordinal     INTEGER NOT NULL,   -- this event's Nth draft (0-indexed) -- part of the identity
    queue       TEXT CHECK (queue IN ('quick', 'premier', 'traditional') OR queue IS NULL),
    set_code    TEXT,   -- parsed from event_name; NULL when unrecognized (rule 4, never guessed)
    started_at  TEXT,   -- NULL when the log did not capture this draft's opening pack
    ended_at    TEXT    -- NULL while the draft is still in progress — this is v_current_draft
);

CREATE TABLE draft_packs (
    draft_id     TEXT NOT NULL REFERENCES draft_events (draft_id),
    pack_number  INTEGER NOT NULL,
    pick_number  INTEGER NOT NULL,
    card_count   INTEGER NOT NULL,   -- from len(DraftPack); never hardcode a pack size (set-dependent)
    seen_at      TEXT,
    PRIMARY KEY (draft_id, pack_number, pick_number)
);

-- Rows rather than a JSON column, following turn_zones over decks.cards_json:
-- keeps the pool/pack read a plain join instead of a client-side JSON parse.
CREATE TABLE draft_pack_cards (
    draft_id     TEXT NOT NULL,
    pack_number  INTEGER NOT NULL,
    pick_number  INTEGER NOT NULL,
    idx          INTEGER NOT NULL,   -- Arena's own order in DraftPack — the honest "no opinion" sort
    grp_id       INTEGER NOT NULL,
    PRIMARY KEY (draft_id, pack_number, pick_number, idx),
    FOREIGN KEY (draft_id, pack_number, pick_number)
        REFERENCES draft_packs (draft_id, pack_number, pick_number)
);

CREATE TABLE draft_picks (
    draft_id     TEXT NOT NULL,
    pack_number  INTEGER NOT NULL,
    pick_number  INTEGER NOT NULL,
    grp_id       INTEGER,   -- NULL = pack seen, pick not yet observed — not a guess (rule 4)
    picked_at    TEXT,
    PRIMARY KEY (draft_id, pack_number, pick_number),
    FOREIGN KEY (draft_id, pack_number, pick_number)
        REFERENCES draft_packs (draft_id, pack_number, pick_number)
);

-- ---------------------------------------------------------------------------
-- Reference data, exactly like `cards`/`archetypes`: downloaded, not derived,
-- and therefore deliberately outside the projector's DELETE set so a rebuild
-- never discards a fetch.
--
-- 17lands' own `url`/`url_back` image fields are deliberately NOT stored.
-- docs/frontend.md's rule is that the browser never talks to a third-party
-- image host — images come only from /api/cards/{grp_id}/image, which
-- card_images.py already serves by grp_id. An unused URL column would only
-- invite a future violation.
--
-- Every stat column is nullable: 17lands itself withholds a statistic below
-- its own sample floor (measured: ever_drawn_win_rate below ~500
-- ever_drawn_game_count, avg_seen below ~200 seen_count) by sending null, and
-- that null must survive storage rather than becoming a fabricated zero.
-- ---------------------------------------------------------------------------
CREATE TABLE card_ratings (
    expansion                  TEXT NOT NULL,  -- 17lands' own code ('SOS'), never cards.set_code —
                                                -- that column's semantics differ by source (see draft/source.py)
    format                     TEXT NOT NULL,  -- the 17lands format actually fetched ('QuickDraft', 'PremierDraft', ...)
    grp_id                     INTEGER NOT NULL,   -- 17lands' mtga_id IS Arena's grpId — direct integer join
    name                       TEXT NOT NULL,
    rarity                     TEXT,
    color                      TEXT,           -- 17lands' own string, not cards.colors
    seen_count                 INTEGER,
    avg_seen                   REAL,           -- ALSA
    pick_count                 INTEGER,
    avg_pick                   REAL,
    game_count                 INTEGER,
    pool_count                 INTEGER,
    play_rate                  REAL,
    win_rate                   REAL,
    ever_drawn_game_count      INTEGER,
    ever_drawn_win_rate        REAL,           -- GIH WR
    drawn_improvement_win_rate REAL,           -- IWD
    fetched_at                 TEXT NOT NULL,
    PRIMARY KEY (expansion, format, grp_id)
);

CREATE INDEX idx_card_ratings_grp ON card_ratings (grp_id);

-- No status/error column, matching archetype_fetch/meta_fetch_source: only
-- successful fetch state is stored here; a failure lives in the RefreshResult
-- draft/source.py returns plus a log.warning, never in this table.
CREATE TABLE card_ratings_fetch (
    expansion   TEXT NOT NULL,
    format      TEXT NOT NULL,
    url         TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    cards       INTEGER NOT NULL DEFAULT 0,
    rated       INTEGER NOT NULL DEFAULT 0,   -- rows with a non-null ever_drawn_win_rate
    skipped     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (expansion, format)
);

-- ---------------------------------------------------------------------------
-- Read paths.
-- ---------------------------------------------------------------------------

-- The draft in progress, if any — v_current_match's exact shape: the newest
-- draft by start time, still missing an ended_at. An interrupted draft (the
-- log rotated mid-session) therefore stays "current" until a new one starts.
CREATE VIEW v_current_draft AS
SELECT d.*
FROM draft_events d
WHERE d.ended_at IS NULL
  AND COALESCE(d.started_at, '') = (SELECT MAX(COALESCE(started_at, '')) FROM draft_events);

-- The pack actually on screen right now: the current draft's newest pack with
-- no pick recorded against it yet.
CREATE VIEW v_current_pack AS
SELECT p.*
FROM draft_packs p
JOIN v_current_draft d USING (draft_id)
LEFT JOIN draft_picks k USING (draft_id, pack_number, pick_number)
WHERE k.grp_id IS NULL
ORDER BY p.pack_number DESC, p.pick_number DESC
LIMIT 1;

-- Every pick made so far, joined to what the card table knows about it.
CREATE VIEW v_draft_pool AS
SELECT k.draft_id, k.pack_number, k.pick_number, k.grp_id,
       c.name, c.mana_cost, c.type_line, c.rarity, c.colors
FROM draft_picks k
LEFT JOIN cards c ON c.grp_id = k.grp_id
WHERE k.grp_id IS NOT NULL;
