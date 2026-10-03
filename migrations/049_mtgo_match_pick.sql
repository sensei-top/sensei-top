-- 049_mtgo_match_pick.sql — the user's own answer to "which deck, in which
-- format" for an MTGO match.
--
-- MTGO's game log never names the deck or the format played, so
-- matches.deck_id is NULL for every MTGO match and no other source has the
-- answer: the user confirms it (plan 12, D1). That makes this an
-- authored-artifact table, the same kind as opponent_deck_override
-- (004_archetypes.sql): it is written by one API route, never read by
-- project(), and it has to outlive the full rebuild that erases every derived
-- row.
--
-- Deliberately NO foreign key, for opponent_deck_override's reason: with
-- foreign_keys ON, a reference to matches would make the rebuild's
-- DELETE FROM matches fail outright. Nor is deck_id a reference to decks,
-- which a rebuild also empties and refills; an MTGO deck's id is a content
-- hash, so a rebuild writes the same id back (projector/mtgo/decks.py,
-- mtgo_deck_identity). A pick whose match or deck file has gone is harmless:
-- v_match_deck joins to this table, it never drives the join.
--
-- Either column may be NULL, but not both. A format may be confirmed without
-- a deck, since no match played before the deck folder was read has an
-- exported list (D9). `format` is the seven formats MTGO matches are played
-- in; there is no "other".
CREATE TABLE mtgo_match_pick (
    match_id    TEXT PRIMARY KEY,
    deck_id     TEXT,
    format      TEXT CHECK (format IN
                    ('Standard', 'Pioneer', 'Modern', 'Pauper', 'Legacy', 'Vintage', 'Premodern')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (deck_id IS NOT NULL OR format IS NOT NULL)
);

-- The deck of every match, as the user has it: the pick where there is one,
-- else what the log named. Every read of "the match's deck" outside the
-- rebuild goes through this view rather than matches.deck_id, which stays
-- exactly what the projector wrote.
--
-- The pick is joined to MTGO matches only, so a stray row for an Arena match
-- id can never override a deck the Arena log already names.
--
-- deck_confirmed is 1 for an Arena match (the log names its deck), 1 for an
-- MTGO match that has a pick, and 0 for an MTGO match that has none. A pick
-- that confirms only the format still counts as a pick: the user has been
-- asked and answered.
CREATE VIEW v_match_deck AS
SELECT
    m.match_id,
    m.source,
    COALESCE(p.deck_id, m.deck_id) AS deck_id,
    p.format                       AS format,
    CASE WHEN m.source = 'mtgo' AND p.match_id IS NULL THEN 0 ELSE 1 END AS deck_confirmed
FROM matches m
LEFT JOIN mtgo_match_pick p ON p.match_id = m.match_id AND m.source = 'mtgo';
