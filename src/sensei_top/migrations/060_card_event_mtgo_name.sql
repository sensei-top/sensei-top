-- MTGO's transcript name for a card event that never resolved to a card
-- (plan 13, S5d).
--
-- projector/mtgo/project.py writes it only when an MTGO card event's grp_id
-- is NULL, and leaves it NULL otherwise: a resolved event is named by its
-- cards row, and a second spelling beside it would only drift. Arena never
-- writes it, since every Arena card event carries Arena's own grpId.
--
-- It exists so archetypes/classify.py::infer_formats can tell an unresolved
-- token ("Map Token") or game marker ("The Initiative") from an unresolved
-- card: the first two say nothing about a match's format, the last one could
-- be any card and still blocks the inference.
--
-- Derived, like every card_events column: project() deletes and rewrites it
-- on every rebuild. Rows projected before this migration read NULL until the
-- next rebuild, and a NULL here still blocks the inference, so nothing reads
-- better than it did before.

ALTER TABLE card_events ADD COLUMN mtgo_name TEXT;
