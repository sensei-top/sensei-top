-- 003_current_match.sql — card-level events, Scryfall card names, Arena deck
-- GUIDs, library counts on turns, and the current-match / deck-summary reads.

-- ---------------------------------------------------------------------------
-- Reference data. NOT projector-owned: populated by `sensei-top cards` (the
-- one sanctioned outbound call) and deliberately left out of the projector's
-- DELETE set, so a rebuild never throws away a 200 MB download.
-- grp_id is Arena's grpId, which is the same number as Scryfall's arena_id.
-- ---------------------------------------------------------------------------
CREATE TABLE cards (
    grp_id      INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    mana_cost   TEXT,
    type_line   TEXT,
    rarity      TEXT,
    set_code    TEXT,
    colors      TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Projector-owned: one row per observed AnnotationType_ZoneTransfer, keeping
-- Arena's own vocabulary. A NULL grp_id means the card was hidden from us
-- (an opponent draw, say) — expected missing information, not a parse failure.
-- seat is the raw systemSeatNumber, not self/opp: the row stays meaningful
-- even when a truncated session left self_seat unresolved. v_card_events maps
-- it, the same split already used between turns and v_deck_turn_curves.
-- ---------------------------------------------------------------------------
CREATE TABLE card_events (
    match_id     TEXT NOT NULL,
    game_number  INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    turn_number  INTEGER,
    seat         INTEGER,
    grp_id       INTEGER,
    category     TEXT,
    zone_src     TEXT,
    zone_dest    TEXT,
    PRIMARY KEY (match_id, game_number, seq),
    FOREIGN KEY (match_id, game_number) REFERENCES games (match_id, game_number)
);

-- ---------------------------------------------------------------------------
-- Projector-owned: Arena's own stable deck GUID, recorded next to the
-- content-hash identity that deck_id still uses. Stored and not yet read, so
-- that when decks are normalized later the history is already there and old
-- logs need not be re-read. Deliberately its own table rather than columns on
-- decks: one card list can be reached by several Arena decks, and one Arena
-- deck spans many card lists as it is edited, which is the many-to-many the
-- normalization work will need.
-- ---------------------------------------------------------------------------
CREATE TABLE deck_guids (
    deck_id        TEXT NOT NULL REFERENCES decks (deck_id),
    arena_deck_id  TEXT NOT NULL,
    version        TEXT,
    format         TEXT,
    last_seen      TEXT,
    PRIMARY KEY (deck_id, arena_deck_id)
);

-- Cards left in each library, counted from the zone itself rather than
-- subtracted from the decklist, so Bo3 sideboarding needs no special case.
ALTER TABLE turns ADD COLUMN self_library INTEGER;

ALTER TABLE turns ADD COLUMN opp_library INTEGER;

-- ---------------------------------------------------------------------------
-- Read paths.
-- ---------------------------------------------------------------------------

-- Labels for the deck selector. v_deck_winrate cannot serve this: it groups by
-- (deck, event) and counts completed matches only, so a deck whose only match
-- is still being played would vanish from the selector mid-game.
CREATE VIEW v_deck_summary AS
SELECT
    d.deck_id,
    d.name,
    d.format,
    COUNT(m.match_id)                                  AS matches_played,
    COUNT(m.match_id) FILTER (WHERE m.result = 'win')  AS matches_won,
    MAX(m.started_at)                                  AS last_played,
    d.first_seen,
    d.last_seen
FROM decks d
LEFT JOIN matches m USING (deck_id)
GROUP BY d.deck_id;

-- The match in progress, if any: incomplete and the newest one started. An
-- abandoned match therefore stops being current as soon as the next one
-- begins. Until then it stays, with started_at exposed so the dashboard can
-- show how old it is rather than implying a game is live.
CREATE VIEW v_current_match AS
SELECT m.*
FROM matches m
WHERE m.result = 'incomplete'
  AND COALESCE(m.started_at, '') = (SELECT MAX(COALESCE(started_at, '')) FROM matches);

-- Card events with names joined and the seat resolved to self/opponent.
-- is_self is NULL when the match never resolved a self seat.
CREATE VIEW v_card_events AS
SELECT
    ce.match_id,
    ce.game_number,
    ce.seq,
    ce.turn_number,
    ce.category,
    ce.zone_src,
    ce.zone_dest,
    ce.grp_id,
    c.name AS card_name,
    CASE WHEN m.self_seat IS NULL THEN NULL
         WHEN ce.seat = m.self_seat THEN 1
         ELSE 0 END AS is_self
FROM card_events ce
JOIN matches m USING (match_id)
LEFT JOIN cards c ON c.grp_id = ce.grp_id;
