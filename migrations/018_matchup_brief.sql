-- A written matchup brief: what to play around against one opponent archetype,
-- and the game-2 board plan, for one of the player's decks.
--
-- This is the one authored artifact this project stores. Everything else
-- derived is recomputed on demand (review/__init__.py, guide/__init__.py both
-- state why). The difference is that a brief is not a derivation of the
-- current database -- it is prose someone wrote once, from a decklist and a
-- corpus snapshot that are both recorded here beside it. `list_hash` is the
-- 75 it was written for: a different 75 makes the board plan wrong, not
-- stale, so the watcher regenerates. `corpus_commit` only makes it *stale*,
-- and the UI says how old rather than silently refiring a paid call.
--
-- No board state, no game, no match id: a brief is a function of two
-- decklists and the field, which is what makes it reusable across every
-- future match against this archetype (see src/sensei_top/brief/__init__.py).
CREATE TABLE matchup_brief (
    deck_key         TEXT NOT NULL,   -- guide.DeckIdentity.key ("guid:..." / "deck:...")
    archetype_key    TEXT NOT NULL,   -- bare archetype key, no 'archetype:' prefix
    list_hash        TEXT NOT NULL,
    archetype_label  TEXT,
    -- Both NULL is a real gap, not a guess: an archetype the corpus has too
    -- few decks of to share, or a matchup this deck has never played.
    archetype_share  REAL,            -- this archetype's share of the classified field, 0..1
    personal_matches INTEGER,
    personal_wins    INTEGER,
    personal_losses  INTEGER,
    prose            TEXT NOT NULL,
    play_around_json TEXT NOT NULL,   -- [{"card": str, "why": str}, ...]
    board_in_json    TEXT NOT NULL,   -- [{"card": str, "n": int}, ...]
    board_out_json   TEXT NOT NULL,   -- [{"card": str, "n": int}, ...]
    staples_json     TEXT NOT NULL,   -- [{"name": str, "copies": float, "share": float}, ...]
    problems_json    TEXT NOT NULL,   -- guide.plans.validate_plans output, never repaired
    prompt           TEXT NOT NULL,   -- exactly what was sent, so it stays inspectable after
    model            TEXT NOT NULL,
    generated_at     TEXT NOT NULL,
    corpus_commit    TEXT,            -- meta_fetch.commit_sha when written
    source           TEXT NOT NULL CHECK (source IN ('live', 'guide')),
    PRIMARY KEY (deck_key, archetype_key)
);

-- A failed attempt, so the watcher backs off instead of retrying every tick.
CREATE TABLE matchup_brief_failure (
    deck_key      TEXT NOT NULL,
    archetype_key TEXT NOT NULL,
    failed_at     TEXT NOT NULL,
    error         TEXT NOT NULL,
    PRIMARY KEY (deck_key, archetype_key)
);
