-- 044_meta_matchup_date_grain.sql — give v_meta_matchup a date to window by.
--
-- `013_metagame_views.sql` pre-aggregates this view by
-- (archetype_key, label, opponent_key, opponent_label, tier, format) with no
-- date column, on the stated reasoning that "the matchup matrix carries no
-- date-window parameter in the API." That claim no longer holds: every
-- other field number (`v_meta_presence`, `v_meta_winrate`) is windowed
-- against `guide/window.py`'s format-reset boundary before it is shown or
-- fed into a report/brief, per docs/metagame.md's "The format-reset
-- boundary" — pooling a matchup rate across a ban is exactly the failure
-- that section exists to prevent, and the matchup view was the one number
-- left exempt from it by omission, not by design. Applied migrations are
-- never edited, so the correction to 013's own comment lives here instead
-- of there.
--
-- `e.event_date` is carried through both halves of the `sides` CTE and
-- added to the outer SELECT and GROUP BY, taking the view from
-- (archetype pair, tier, format) grain to (archetype pair, tier, format,
-- date) grain. Every current reader (`review/snapshot.py`'s field_matchup,
-- `brief/narrative.py`'s field-record line, `api/routes/metagame.py`'s
-- matchups route) already `SUM`s `n`/`matches_won`/`matches_lost` across
-- every row it selects, so a finer grain changes no total for a query that
-- does not also filter on the new column — only a caller that adds
-- `WHERE event_date >= ?` sees a different result, which is the point.
DROP VIEW v_meta_matchup;

CREATE VIEW v_meta_matchup AS
WITH sides AS (
    SELECT
        rm.event_id, e.tier, e.format, e.event_date,
        da_a.archetype_key AS archetype_key, da_a.archetype_name AS label,
        da_b.archetype_key AS opponent_key, da_b.archetype_name AS opponent_label,
        rm.wins_a AS wins, rm.wins_b AS losses, rm.draws AS draws
    FROM meta_round_match rm
    JOIN meta_event e ON e.event_id = rm.event_id
    JOIN meta_deck_archetype da_a ON da_a.event_id = rm.event_id AND da_a.deck_ord = rm.deck_ord_a
    JOIN meta_deck_archetype da_b ON da_b.event_id = rm.event_id AND da_b.deck_ord = rm.deck_ord_b
    UNION ALL
    SELECT
        rm.event_id, e.tier, e.format, e.event_date,
        da_b.archetype_key AS archetype_key, da_b.archetype_name AS label,
        da_a.archetype_key AS opponent_key, da_a.archetype_name AS opponent_label,
        rm.wins_b AS wins, rm.wins_a AS losses, rm.draws AS draws
    FROM meta_round_match rm
    JOIN meta_event e ON e.event_id = rm.event_id
    JOIN meta_deck_archetype da_a ON da_a.event_id = rm.event_id AND da_a.deck_ord = rm.deck_ord_a
    JOIN meta_deck_archetype da_b ON da_b.event_id = rm.event_id AND da_b.deck_ord = rm.deck_ord_b
)
SELECT
    archetype_key, label, opponent_key, opponent_label, tier, format, event_date,
    COUNT(*)                                          AS n,
    SUM(CASE WHEN wins > losses THEN 1 ELSE 0 END)     AS matches_won,
    SUM(CASE WHEN wins < losses THEN 1 ELSE 0 END)     AS matches_lost,
    SUM(CASE WHEN wins = losses THEN 1 ELSE 0 END)     AS matches_drawn,
    SUM(wins)                                          AS games_won,
    SUM(losses)                                        AS games_lost
FROM sides
GROUP BY archetype_key, label, opponent_key, opponent_label, tier, format, event_date;
