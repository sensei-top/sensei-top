-- 011_review_views.sql — post-game match report views.
--
-- Views only: no new table, no new column, nothing added to project()'s
-- DELETE set and nothing for it to rebuild. src/sensei_top/review/ (the
-- analyzers behind GET /api/matches/{id}/report) reads these on every
-- request rather than storing their output, for the same reason
-- v_match_opponent is a view and not a column (docs/architecture.md,
-- "Naming the opponent's deck"): several of these views join `cards` and
-- `decks`, neither of which the projector owns, and both of which the user
-- may populate (`sensei-top cards`) long after a match was projected. A
-- stored table would read wrong — not merely stale — for every match
-- projected before that; a view is always current.
--
-- The SQL-aggregation rule still holds ("Metrics live in SQL" in
-- docs/architecture.md): these views do the counting and windowing, and the
-- Python analyzers only apply thresholds and build Finding objects from
-- numbers a view already produced.

-- Our own player-turns, indexed from 1 over the rows that actually exist —
-- never assumed contiguous. turn_number is a single counter both seats
-- share and alternate on, so "your third turn" is never turn_number == 3,
-- and which turn_number is yours shifts with who was on the play.
-- self_turn_index is what every analyzer anchors on instead.
CREATE VIEW v_self_turns AS
SELECT
    t.match_id, t.game_number, t.turn_number,
    ROW_NUMBER() OVER (
        PARTITION BY t.match_id, t.game_number ORDER BY t.turn_number
    ) AS self_turn_index,
    t.self_life, t.opp_life, t.self_hand, t.self_lands, t.self_permanents,
    t.opp_permanents, t.self_library, t.self_graveyard, t.self_open_mana,
    LAG(t.self_permanents) OVER (
        PARTITION BY t.match_id, t.game_number ORDER BY t.turn_number
    ) AS prev_self_permanents
FROM turns t
JOIN matches m USING (match_id)
WHERE m.self_seat IS NOT NULL AND t.active_seat = m.self_seat;

-- Lands we actually put onto the battlefield via PlayLand, per our own turn.
-- Only turns with at least one exist here — a turn with none is simply
-- absent, read as 0 by whoever looks it up.
CREATE VIEW v_self_lands_played AS
SELECT ce.match_id, ce.game_number, ce.turn_number, COUNT(*) AS lands_played
FROM card_events ce
JOIN matches m ON m.match_id = ce.match_id
WHERE ce.seat = m.self_seat AND ce.category = 'PlayLand' AND ce.turn_number IS NOT NULL
GROUP BY ce.match_id, ce.game_number, ce.turn_number;

-- Our own hand's land count at the end of each turn (any turn_number, not
-- only our own — a card sitting in hand is observed regardless of whose
-- turn it was), plus how many of that turn's hand cards are named at all.
-- named_cards is what lets an analyzer distinguish "no lands in hand" from
-- "the card table hasn't been downloaded yet" (rule 4) — the same em-dash
-- type-line split 004_archetypes.sql's v_opponent_cards uses, since a
-- basic land's type line is "Basic Land — Island" and testing the whole
-- line would misread e.g. "Artifact Land" or a line with no dash at all.
CREATE VIEW v_self_hand_lands AS
SELECT
    tz.match_id, tz.game_number, tz.turn_number,
    COUNT(*) FILTER (
        WHERE instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))), 'Land') > 0
    ) AS hand_lands,
    COUNT(*) FILTER (WHERE c.name IS NOT NULL) AS named_cards
FROM turn_zones tz
JOIN matches m USING (match_id)
LEFT JOIN cards c ON c.grp_id = tz.grp_id
WHERE tz.zone = 'hand' AND tz.seat = m.self_seat
GROUP BY tz.match_id, tz.game_number, tz.turn_number;

-- Each deck's own maindeck land ratio, from `cards.type_line` — the same
-- em-dash split above. unnamed_count is nonzero whenever any maindeck card
-- (including duplicate copies) has not been named yet, so a flood
-- comparison is never computed against a partly-known list. json_each over
-- cards_json's maindeck array is this project's first use of SQLite's JSON1
-- functions; app.py's _deck_cards already parses the same JSON in Python,
-- but that path only lists cards, it does not aggregate — counting land
-- copies belongs in SQL per the rule above.
CREATE VIEW v_deck_land_count AS
SELECT
    d.deck_id,
    COUNT(*) AS maindeck_size,
    SUM(
        CASE WHEN instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))), 'Land') > 0
             THEN 1 ELSE 0 END
    ) AS land_count,
    SUM(CASE WHEN c.name IS NULL THEN 1 ELSE 0 END) AS unnamed_count
FROM decks d
JOIN json_each(json_extract(d.cards_json, '$.maindeck')) je
LEFT JOIN cards c ON c.grp_id = je.value
GROUP BY d.deck_id;
