-- 046_rank_winrate_arena_only.sql — an MTGO match has no Arena rank.
--
-- 035_mtgo_source.sql recreated v_rank_winrate with `source` and said every
-- MTGO row's rank columns are NULL, but the rank lookup it kept is "the most
-- recent rank_snapshot at or before the match started", with nothing tying
-- the snapshot to the match's client. rank_snapshot is only ever written from
-- Arena's log, so an MTGO match played after any Arena session took that
-- session's rank. The same lookup in api/routes/matches.py is guarded the
-- same way, in the same change.
--
-- Recreated from 035_mtgo_source.sql with `m.source = 'arena'` in both
-- subqueries; nothing depends on this view.

DROP VIEW v_rank_winrate;

CREATE VIEW v_rank_winrate AS
SELECT
    (SELECT r.constructed_class FROM rank_snapshot r
      WHERE m.source = 'arena' AND r.observed_at <= m.started_at
      ORDER BY r.observed_at DESC LIMIT 1)                      AS constructed_class,
    (SELECT r.constructed_level FROM rank_snapshot r
      WHERE m.source = 'arena' AND r.observed_at <= m.started_at
      ORDER BY r.observed_at DESC LIMIT 1)                      AS constructed_level,
    m.source,
    COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw')) AS matches_completed,
    COUNT(*) FILTER (WHERE m.result = 'win')                    AS matches_won,
    SUM(COALESCE(m.games_won, 0))                               AS games_won,
    SUM(COALESCE(m.games_lost, 0))                              AS games_lost
FROM matches m
GROUP BY constructed_class, constructed_level, m.source;
