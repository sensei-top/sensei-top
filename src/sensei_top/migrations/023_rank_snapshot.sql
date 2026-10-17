-- 023_rank_snapshot.sql — a bare observation of the player's rank at a point
-- in time, retroactive over data already captured: RankGetCombinedRankInfo
-- responses have always been in raw_events (they carry no board state, no
-- opponent, nothing per-match), this table just projects them.
--
-- Deliberately NOT a column on `matches`. A match's rank is "the most recent
-- snapshot at or before matches.started_at" — a lookup against an
-- observation, resolved at query time, NULL when no snapshot precedes it.
-- Writing a rank guess into `matches` would make a derived approximation
-- look like a recorded fact (AGENTS.md rule 4): Arena polls rank on its own
-- schedule, not once per match, so no snapshot is ever guaranteed to be
-- "this match's own" rank — only the closest thing observed before it
-- started.
CREATE TABLE rank_snapshot (
    observed_at              TEXT NOT NULL,
    constructed_class        TEXT,      -- Arena's own tier name, e.g. 'Platinum'
    constructed_level        INTEGER,
    constructed_step         INTEGER,
    constructed_season       INTEGER,   -- constructedSeasonOrdinal
    constructed_matches_won  INTEGER,
    constructed_matches_lost INTEGER
    -- Limited rank fields exist in the same payload but are out of scope —
    -- this table only serves the Standard/constructed 1v1 read.
);

CREATE INDEX idx_rank_snapshot_observed ON rank_snapshot (observed_at);

-- One winrate metric, conditioned on rank — the one rank-aggregated view
-- this round adds (deliberately not threading a rank filter through every
-- existing metric view; docs/architecture.md, "Two retroactive projections:
-- rank and sideboarding"). Same
-- shape as v_deck_winrate (001_init.sql): grouped, with matches_completed
-- always alongside a count so a percentage never appears without one.
--
-- Each match's rank is resolved the same way the API's own per-match lookup
-- is (the most recent snapshot at or before matches.started_at) — a
-- correlated subquery per match row, same as v_deck_winrate joins one row
-- of decks per match; a match with no snapshot before it (rank_class NULL)
-- is grouped separately rather than dropped, so "rank not yet observed" is
-- visible instead of silently excluded.
CREATE VIEW v_rank_winrate AS
SELECT
    (SELECT r.constructed_class FROM rank_snapshot r
      WHERE r.observed_at <= m.started_at
      ORDER BY r.observed_at DESC LIMIT 1)                      AS constructed_class,
    (SELECT r.constructed_level FROM rank_snapshot r
      WHERE r.observed_at <= m.started_at
      ORDER BY r.observed_at DESC LIMIT 1)                      AS constructed_level,
    COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw')) AS matches_completed,
    COUNT(*) FILTER (WHERE m.result = 'win')                    AS matches_won,
    SUM(COALESCE(m.games_won, 0))                               AS games_won,
    SUM(COALESCE(m.games_lost, 0))                               AS games_lost
FROM matches m
GROUP BY constructed_class, constructed_level;
