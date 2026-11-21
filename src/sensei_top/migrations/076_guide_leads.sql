-- One-sentence leads the deck guide writes beside each long section. Nullable:
-- an answer written before this column existed has none, and NULL is a real
-- absence, never backfilled.
ALTER TABLE deck_narrative ADD COLUMN engine_lead TEXT;
ALTER TABLE deck_narrative ADD COLUMN fix_lead TEXT;
ALTER TABLE matchup_brief ADD COLUMN lead TEXT;
