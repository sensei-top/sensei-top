-- 005_turn_zones.sql — per-turn zone *contents*, next to the per-turn counts
-- already in `turns`.
--
-- Projector-owned, deleted and rebuilt on every projection. seat is the raw
-- systemSeatNumber for the same reason card_events keeps it raw: the row
-- survives a truncated session that left self_seat unresolved, and
-- v_turn_zones does the mapping. A NULL grp_id means the card was hidden from
-- us — Arena omits the game object for a card we may not see, so an opponent's
-- hand is a list of instance ids with no identities. That is the expected
-- shape of hidden information, and it is what lets the UI draw N card backs.
CREATE TABLE turn_zones (
    match_id      TEXT NOT NULL,
    game_number   INTEGER NOT NULL,
    turn_number   INTEGER NOT NULL,
    seat          INTEGER NOT NULL,
    zone          TEXT NOT NULL,      -- 'hand' | 'battlefield' | 'graveyard'
    idx           INTEGER NOT NULL,   -- position within (turn, zone, seat), from 0
    instance_id   INTEGER NOT NULL,
    grp_id        INTEGER,            -- NULL = hidden from us / face-down
    card_types    TEXT,               -- Arena CardType_* strings, comma-joined (NULL if unseen)
    drawn_on_turn INTEGER,            -- turn this instance entered hand via Draw; else NULL
    PRIMARY KEY (match_id, game_number, turn_number, zone, seat, idx),
    FOREIGN KEY (match_id, game_number) REFERENCES games (match_id, game_number)
);

-- Mirrors v_card_events: maps the raw seat to self/opp and joins the
-- downloaded card names, reporting NULL when it cannot.
CREATE VIEW v_turn_zones AS
SELECT
    tz.match_id, tz.game_number, tz.turn_number, tz.zone, tz.idx,
    tz.instance_id, tz.grp_id, tz.card_types, tz.drawn_on_turn,
    c.name AS card_name,
    CASE WHEN m.self_seat IS NULL THEN NULL
         WHEN tz.seat = m.self_seat THEN 1
         ELSE 0 END AS is_self
FROM turn_zones tz
JOIN matches m USING (match_id)
LEFT JOIN cards c ON c.grp_id = tz.grp_id;
