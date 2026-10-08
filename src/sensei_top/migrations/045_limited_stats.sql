-- 045_limited_stats.sql — 17lands' public bulk Limited statistics
-- (`game_data` and `draft_data`, one S3 file per (expansion, format)), the
-- pool-aware value model's evidence source (draft-assistant-rework plan
-- §3a/§4 Spec C). This replaces the live `card_ratings` endpoint's own
-- sample floor as the primary source: that endpoint is fine for ALSA, but
-- the bulk files carry every game and every pick that produced them, so a
-- pick's actual pair-conditioned win rate can be derived rather than read
-- off one aggregate number.
--
-- Reference data, exactly like `card_ratings`/`archetypes`: downloaded, not
-- derived from `raw_events`, and therefore deliberately outside the
-- projector's DELETE set (`projector/matches.py::project()`) — a full
-- rebuild must never discard a fetch that can cost minutes to redo.
-- `draft/bulk.py` is the only module that writes these four tables.
CREATE TABLE limited_stats_fetch (
    expansion TEXT NOT NULL,            -- 17lands' own name: 'SOS', 'Cube - Powered'
    format TEXT NOT NULL,               -- 'PremierDraft' | 'TradDraft'
    kind TEXT NOT NULL,                 -- 'game' | 'draft'
    url TEXT NOT NULL,
    source_last_modified TEXT,          -- S3 Last-Modified, verbatim
    source_bytes INTEGER,
    checked_at TEXT NOT NULL,           -- last HEAD, UTC ISO
    fetched_at TEXT,                    -- last full parse; NULL if never completed
    rows INTEGER, decks INTEGER, parse_seconds REAL,
    draft_time_min TEXT, draft_time_max TEXT,
    PRIMARY KEY (expansion, format, kind)
);

-- Per-card aggregates from `game_data`. `deck_colors` is either 'ALL' (every
-- game this card qualified in, any deck) or one of the ten two-colour pairs
-- in WUBRG order (`draft/bulk.py::PAIRS`) — a three-plus-colour or mono deck
-- contributes to 'ALL' only, since the pair-based value model (§3a) has
-- nothing to compare it against. GIH ("games in hand") counts a game where
-- the card was drawn or opened; GP ("games played") counts a game where it
-- was in the maindeck — the same two denominators 17lands' own site reports.
CREATE TABLE limited_card_stats (
    expansion TEXT NOT NULL, format TEXT NOT NULL, name TEXT NOT NULL,
    deck_colors TEXT NOT NULL,          -- 'ALL' or a WUBRG-ordered pair
    gih_games INTEGER NOT NULL, gih_wins INTEGER NOT NULL,
    gp_games INTEGER NOT NULL, gp_wins INTEGER NOT NULL,
    PRIMARY KEY (expansion, format, name, deck_colors)
);

-- Per-pair aggregates from the same file: how often that pair was played,
-- how often it won, and how many distinct decks (`draft_id`, `build_index`)
-- built it — the "share of the field" and "raw win rate" the format
-- overview (Spec F) and the lane strength model (§3a) both read.
CREATE TABLE limited_color_stats (
    expansion TEXT NOT NULL, format TEXT NOT NULL, deck_colors TEXT NOT NULL,
    games INTEGER NOT NULL, wins INTEGER NOT NULL, decks INTEGER NOT NULL,
    PRIMARY KEY (expansion, format, deck_colors)
);

-- Per-card pick-order aggregates from `draft_data`. `taken_pick_sum` is the
-- sum of (pick_number + 1) over every pick of this card — `pick_number` is
-- stored 0-indexed by 17lands itself, matching `draft_packs.pick_number`'s
-- own convention (migration 025), so the +1 lands here rather than being
-- baked into the stored sum. ATA ("average taken at") is
-- `taken_pick_sum / taken`, computed by the reader, never stored twice.
CREATE TABLE limited_pick_stats (
    expansion TEXT NOT NULL, format TEXT NOT NULL, name TEXT NOT NULL,
    taken INTEGER NOT NULL, taken_pick_sum INTEGER NOT NULL,   -- ATA = sum/taken, 1-based pick-in-pack
    PRIMARY KEY (expansion, format, name)
);
