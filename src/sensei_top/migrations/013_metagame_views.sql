-- 013_metagame_views.sql — the field's numbers, built on top of
-- 012_metagame.sql's tables. The evidence-tier constraint from
-- docs/metagame.md is enforced here, structurally: a Tier C (MTGO league)
-- event has no losses in it at all — every ``Result`` is literally "5-0" —
-- so ``v_meta_winrate`` excludes it in the ``WHERE`` clause below, where no
-- future query, API route, or agent can accidentally include it. Presence is
-- the one thing a Tier C event is licensed for, so ``v_meta_presence`` keeps
-- every tier.
--
-- Both are deck-grain, not pre-aggregated by archetype: the API's own
-- ``?days=`` window has to filter by ``event_date`` before counting, and a
-- view cannot take a runtime parameter. Aggregation still happens entirely
-- in SQL (AGENTS.md's own rule for this API layer) — it happens in the
-- route's own ``SELECT ... GROUP BY``, the same way ``matchups()`` already
-- builds its own query on top of ``v_matchup_winrate`` rather than reading
-- a view verbatim.
--
-- Only classified decks appear in either view (the join to
-- ``meta_deck_archetype`` is inner): an unclassified deck is not a named
-- archetype to show a share or a win rate for.

CREATE VIEW v_meta_presence AS
SELECT
    e.event_id,
    d.deck_ord,
    e.event_date,
    e.format,
    e.tier,
    da.archetype_key,
    da.archetype_name AS label,
    da.colors
FROM meta_deck d
JOIN meta_event e ON e.event_id = d.event_id
JOIN meta_deck_archetype da ON da.event_id = d.event_id AND da.deck_ord = d.deck_ord;

CREATE VIEW v_meta_winrate AS
SELECT
    e.event_id,
    d.deck_ord,
    e.event_date,
    e.format,
    e.tier,
    da.archetype_key,
    da.archetype_name AS label,
    da.colors,
    d.wins,
    d.losses,
    d.draws
FROM meta_deck d
JOIN meta_event e ON e.event_id = d.event_id
JOIN meta_deck_archetype da ON da.event_id = d.event_id AND da.deck_ord = d.deck_ord
WHERE e.tier IN ('A', 'B');

-- ---------------------------------------------------------------------------
-- Archetype-vs-archetype, from real completed matches only
-- (``meta_round_match``, which a Tier C event never populates — see
-- ``metagame/tiers.py``). Pre-aggregated here, unlike the two views above:
-- the matchup matrix carries no date-window parameter in the API (Phase 4),
-- so there is nothing a runtime filter would need row-grain access for.
--
-- Every real match becomes two rows, one from each side's perspective —
-- "X vs Y" and "Y vs X" — so a lookup never has to know which side of the
-- stored ``deck_ord_a``/``deck_ord_b`` pair its archetype happened to land
-- on. ``n`` is carried explicitly so the dashboard can never show a
-- percentage without the sample size behind it (docs/metagame.md's residual-
-- bias note: challenge events publish only the top 32, so even a Tier B row
-- here is conditioned on making that cut).
-- ---------------------------------------------------------------------------
CREATE VIEW v_meta_matchup AS
WITH sides AS (
    SELECT
        rm.event_id, e.tier, e.format,
        da_a.archetype_key AS archetype_key, da_a.archetype_name AS label,
        da_b.archetype_key AS opponent_key, da_b.archetype_name AS opponent_label,
        rm.wins_a AS wins, rm.wins_b AS losses, rm.draws AS draws
    FROM meta_round_match rm
    JOIN meta_event e ON e.event_id = rm.event_id
    JOIN meta_deck_archetype da_a ON da_a.event_id = rm.event_id AND da_a.deck_ord = rm.deck_ord_a
    JOIN meta_deck_archetype da_b ON da_b.event_id = rm.event_id AND da_b.deck_ord = rm.deck_ord_b
    UNION ALL
    SELECT
        rm.event_id, e.tier, e.format,
        da_b.archetype_key AS archetype_key, da_b.archetype_name AS label,
        da_a.archetype_key AS opponent_key, da_a.archetype_name AS opponent_label,
        rm.wins_b AS wins, rm.wins_a AS losses, rm.draws AS draws
    FROM meta_round_match rm
    JOIN meta_event e ON e.event_id = rm.event_id
    JOIN meta_deck_archetype da_a ON da_a.event_id = rm.event_id AND da_a.deck_ord = rm.deck_ord_a
    JOIN meta_deck_archetype da_b ON da_b.event_id = rm.event_id AND da_b.deck_ord = rm.deck_ord_b
)
SELECT
    archetype_key, label, opponent_key, opponent_label, tier, format,
    COUNT(*)                                          AS n,
    SUM(CASE WHEN wins > losses THEN 1 ELSE 0 END)     AS matches_won,
    SUM(CASE WHEN wins < losses THEN 1 ELSE 0 END)     AS matches_lost,
    SUM(CASE WHEN wins = losses THEN 1 ELSE 0 END)     AS matches_drawn,
    SUM(wins)                                          AS games_won,
    SUM(losses)                                        AS games_lost
FROM sides
GROUP BY archetype_key, label, opponent_key, opponent_label, tier, format;
