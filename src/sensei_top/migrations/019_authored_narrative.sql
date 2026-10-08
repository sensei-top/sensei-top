-- Deck-level authored narrative: the prose half of a deck guide (how the
-- engine works, the fix for the player's biggest leak, per-card notes, the
-- between-rounds checklist).
--
-- Filled two ways (AGENTS.md non-negotiable #5, docs/llm.md, added after
-- this migration first shipped -- see 020_generated_narrative.sql for the
-- cost columns that addition needed): `POST /api/guide/{key}/narrative`
-- fills it automatically when a Claude credential is configured, sending
-- the same prompt/schema this table's `prompt` column always recorded. With
-- none configured, it is filled the way `guides/izzet-spellementals/
-- README.md` was written in the first place: the tool produces the evidence
-- and the exact prompt, a human (or Claude Code, on a subscription that is
-- already paid for) writes the prose, and `sensei-top guide --import`
-- reads the result back.
--
-- Same authored-artifact discipline `matchup_brief` states in 018, for the
-- same reason: `list_hash` is the 75 this was written about, so a list edit
-- makes it *wrong* rather than merely old; `corpus_commit` only makes it
-- stale, and the UI says how old rather than hiding it. `prompt` keeps the
-- evidence it was written from, so a reader can always check the prose
-- against what its author was actually shown.
--
-- One row per deck: re-importing replaces it, which is what makes "edit the
-- prose, import again" the ordinary way to revise a guide.
CREATE TABLE deck_narrative (
    deck_key        TEXT PRIMARY KEY,  -- guide.DeckIdentity.key
    list_hash       TEXT NOT NULL,
    engine          TEXT NOT NULL,
    fix             TEXT NOT NULL,
    card_notes_json TEXT NOT NULL,     -- [{"card": str, "verdict": str, "why": str}, ...]
    checklist_json  TEXT NOT NULL,     -- [str, ...]
    problems_json   TEXT NOT NULL,     -- guide.plans.validate_plans output, never repaired
    prompt          TEXT NOT NULL,
    author          TEXT NOT NULL,     -- free text: who or what wrote this
    authored_at     TEXT NOT NULL,
    corpus_commit   TEXT
);

-- `matchup_brief_failure` (018) recorded a failed API call so a background
-- watcher could back off instead of retrying every tick. Both the watcher
-- and the automatic call are gone for good -- a brief still has no generate
-- button at all, unlike deck_narrative above (brief/narrative.py's own
-- docstring says why) -- and an import either parses or reports the problem
-- to the person who ran it, immediately. Nothing can fail slowly enough to
-- need a cooldown any more.
DROP TABLE IF EXISTS matchup_brief_failure;
