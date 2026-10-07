-- 052_land_count_unresolved.sql — v_deck_land_count exposes the copies an
-- MTGO deck could not resolve to a card.
--
-- An MTGO deck's maindeck is a list of grp_ids, and a card that maps to no
-- grp_id (a non-Arena card, say) is left out of that list rather than guessed
-- at. The projector keeps the dropped copies as a count instead
-- (projector/mtgo/decks.py, plan 12 D18): cards_json carries
-- {"unresolved": {"maindeck": n, "sideboard": n}} on every MTGO deck row,
-- zero included. A deck with unresolved copies has a maindeck shorter than the
-- real one, so its land ratio is computed from a partial list, exactly as one
-- with an unnamed card is. unnamed_count cannot see that: every grp_id that
-- IS in the list may be named.
--
-- unresolved_count is the maindeck's count, read with COALESCE: an Arena deck
-- row has no "unresolved" key at all, and json_extract returns NULL for it,
-- but "nothing was dropped" is 0, not unknown. A guard written as
-- `unnamed_count or unresolved_count` then treats both columns alike.
--
-- Recreated from 011_review_views.sql with every other column unchanged.
-- Nothing else reads this view's body: 050 left it alone (it reads decks and
-- cards only), and no other view selects from it. A deck's unresolved count is
-- a per-deck value, so it is read once per group from cards_json rather than
-- summed over the joined maindeck rows (which would multiply it by the
-- maindeck's size).
--
-- No ALTER VIEW in SQLite, so DROP + CREATE.

DROP VIEW v_deck_land_count;

CREATE VIEW v_deck_land_count AS
SELECT
    d.deck_id,
    COUNT(*) AS maindeck_size,
    SUM(
        CASE WHEN instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))), 'Land') > 0
             THEN 1 ELSE 0 END
    ) AS land_count,
    SUM(CASE WHEN c.name IS NULL THEN 1 ELSE 0 END) AS unnamed_count,
    COALESCE(MAX(json_extract(d.cards_json, '$.unresolved.maindeck')), 0) AS unresolved_count
FROM decks d
JOIN json_each(json_extract(d.cards_json, '$.maindeck')) je
LEFT JOIN cards c ON c.grp_id = je.value
GROUP BY d.deck_id;
