-- 051_mtgo_card.sql — Magic Online's own card number -> card name.
--
-- An MTGO deck-store grouping (the `.xml` MTGO writes for a saved deck) names
-- no card, only `CatId`s, and a `CatId` is Scryfall's `mtgo_id` (plan 12,
-- S9 and D15). This table is that map: written by `cards --scryfall` from the
-- same `default_cards` pass that fills `cards`, one row per printing that has
-- an `mtgo_id`, whether or not it also has an `arena_id`. No new download.
--
-- Reference data, like `cards`: the `cards` command writes it, `project()`
-- never touches it and the API never writes it. `name` is Scryfall's
-- top-level name, the same one `cards.name` stores, so a double-faced card is
-- "Front // Back" and the MTGO projector's name -> grp_id rule applies to it
-- unchanged. The exception is Scryfall's `reversible_card` layout, whose
-- top-level name is "X // X" (or "Front // Adventure // Front") and is no
-- card's name in `cards`: those printings store `card_faces[0].name`, the
-- card's own name. Several MTGO printings of one card share a name; each has
-- its own `mtgo_id`.
CREATE TABLE mtgo_card (
    mtgo_id  INTEGER PRIMARY KEY,
    name     TEXT NOT NULL
);
