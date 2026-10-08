-- 024_game_decks.sql — the deck actually submitted for one game, from
-- ClientMessageType_SubmitDeckResp: the sideboarding decision itself,
-- stored exactly like `decks.cards_json` stores a maindeck — a sorted flat
-- JSON array of grpIds, one entry per copy (Arena's own shape; verified
-- against a real capture, not assumed).
--
-- game_number identity, not "before"/"after": each row is the 60+15 held
-- for the game that follows the submission (see
-- Projector._handle_submit_deck in projector/matches.py for how that game
-- number is actually determined — read off the GameStateMessage that
-- follows the SubmitDeckResp, never assumed or counted). Game 1 is never
-- submitted this way (Arena's connectResp.deckMessage already covers it,
-- matches.py's module docstring), so a Bo3's sideboard story is games 2
-- and/or 3 having their own row here and game 1 having none — the diff
-- between game 1's deck (decks.cards_json, the maindeck the match was
-- played with) and game 2's row here is the actual sideboard plan as
-- played, not merely as written.
CREATE TABLE game_decks (
    match_id              TEXT NOT NULL REFERENCES matches (match_id),
    game_number           INTEGER NOT NULL,
    deck_cards_json       TEXT NOT NULL,   -- sorted JSON array of grpIds, e.g. '[70382,70382,...]'
    sideboard_cards_json  TEXT NOT NULL,
    PRIMARY KEY (match_id, game_number)
);
