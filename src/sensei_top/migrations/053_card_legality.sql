-- Legality per format, one row per card and format (plan 13, D2).
--
-- cards.standard_legality (017) holds Standard only. The seven formats a match
-- can be played in (formats.py::FORMATS, MTGO's spelling) each get their own
-- row here, written by `cards --scryfall` from Scryfall's `legalities`.
-- A card with no row for a format has an unknown legality there (NULL, never
-- a guess); 'not_legal' is a known answer, and 'banned' is not 'not_legal'.
--
-- standard_legality stays until its readers move to this table; it is
-- backfilled here as format = 'Standard' so those readers can move without
-- another `cards --scryfall` run.
CREATE TABLE card_legality (
    grp_id   INTEGER NOT NULL,
    format   TEXT NOT NULL CHECK (format IN
        ('Standard', 'Pioneer', 'Modern', 'Pauper', 'Legacy', 'Vintage', 'Premodern')),
    legality TEXT NOT NULL CHECK (legality IN ('legal', 'not_legal', 'banned', 'restricted')),
    PRIMARY KEY (grp_id, format)
) WITHOUT ROWID;

INSERT INTO card_legality (grp_id, format, legality)
SELECT grp_id, 'Standard', standard_legality
  FROM cards
 WHERE standard_legality IN ('legal', 'not_legal', 'banned', 'restricted');
