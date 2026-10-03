-- 033_deck_identity.sql — one row per Arena deck, not per content hash.
--
-- decks.deck_id is a maindeck content hash (projector/matches.py's
-- deck_identity), so one Arena deck mints a new row on every card swap.
-- deck_guids carries the stable GUID beside each hash. A hash can appear
-- under two GUIDs — the same list registered as two Arena decks — so this
-- picks one: whichever Arena deck used the list most recently owns it,
-- arena_deck_id breaking an exact tie. Without that, a hash counts twice
-- and per-identity totals stop reconciling with matches.
--
-- Views only: no table change, so no re-projection is needed and a running
-- serve --watch applies this the moment it appears. guide/deck.py's
-- list_identities() and the Winrate page's /api/metrics/winrate route both
-- read v_deck_identity, so the two groupings can never disagree.
CREATE VIEW v_deck_identity AS
WITH ranked AS (
    SELECT g.deck_id, g.arena_deck_id,
           ROW_NUMBER() OVER (PARTITION BY g.deck_id
                              ORDER BY g.last_seen DESC, g.arena_deck_id) AS rn
      FROM deck_guids g
),
owned AS (
    SELECT DISTINCT m.deck_id FROM matches m WHERE m.deck_id IS NOT NULL
),
mapped AS (
    -- LEFT JOIN: a truncated log can leave a played deck_id with no
    -- deck_guids row at all, and it still needs an identity of its own.
    SELECT o.deck_id,
           r.arena_deck_id,
           COALESCE('guid:' || r.arena_deck_id, 'deck:' || o.deck_id) AS deck_key
      FROM owned o
      LEFT JOIN ranked r ON r.deck_id = o.deck_id AND r.rn = 1
)
SELECT p.deck_id,
       p.deck_key,
       p.arena_deck_id,
       -- the name of the most recently played version in the group, so an
       -- Arena rename shows through and the choice is deterministic.
       (SELECT d.name
          FROM mapped q
          JOIN decks d   ON d.deck_id = q.deck_id
          JOIN matches m2 ON m2.deck_id = q.deck_id
         WHERE q.deck_key = p.deck_key AND d.name IS NOT NULL
         GROUP BY d.deck_id
         ORDER BY MAX(m2.started_at) DESC, d.deck_id
         LIMIT 1) AS deck_name
  FROM mapped p;

-- v_deck_winrate with the identity attached. Grouped one level finer than
-- the dashboard needs so the deck and event filters still apply before the
-- rollup; the API sums these already-aggregated counts.
CREATE VIEW v_deck_identity_winrate AS
SELECT i.deck_key,
       i.arena_deck_id,
       i.deck_name,
       d.deck_id,
       m.event_id,
       COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw')) AS matches_completed,
       COUNT(*) FILTER (WHERE m.result = 'win')                    AS matches_won,
       SUM(COALESCE(m.games_won, 0))                               AS games_won,
       SUM(COALESCE(m.games_lost, 0))                              AS games_lost
  FROM matches m
  JOIN decks d            ON d.deck_id = m.deck_id
  JOIN v_deck_identity i  ON i.deck_id = m.deck_id
 GROUP BY i.deck_key, d.deck_id, m.event_id;
