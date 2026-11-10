-- 074_card_data_fetch.sql — when card data last came from Scryfall, and how many
-- of the installed client's cards it left without rules text.
--
-- A new card set reaches the installed client first: serve's reference refresh
-- imports its names within minutes of the patch, with no rules text and no
-- legality, which only Scryfall carries. serve downloads Scryfall's export again
-- on its own when the count of client cards without rules text has grown past the
-- one recorded here. Comparing against the count the last download left, rather
-- than against zero, is what stops a card Scryfall never fills (a client-only
-- printing, say) from asking for the same download on every tick. It also
-- downloads again once fetched_at is a day old: the names usually arrive a week
-- before the set's release, and its legality turns legal only on release day.
--
-- One row, written by every successful `cards --scryfall` (cards.py::upsert_cards),
-- whoever ran it. Downloaded reference: never deleted, and project() never reads it.
CREATE TABLE card_data_fetch (
    id                 INTEGER PRIMARY KEY CHECK (id = 1),
    fetched_at         TEXT NOT NULL,
    missing_rules_text INTEGER NOT NULL
);

-- The Scryfall save matches every card by name: `_backfill_by_name`'s UPDATE and
-- its legality pass bind one name per statement, tens of thousands of them. With
-- no index each one scanned all of `cards`, and the save held the write lock for
-- over twelve minutes on a real database. That was tolerable behind a button
-- press; the download this migration lets serve start on its own runs while a
-- game is being ingested, so the lock has to be short.
CREATE INDEX IF NOT EXISTS cards_name ON cards(name);
