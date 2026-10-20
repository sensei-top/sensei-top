# The live matchup brief

Read this when touching `brief/`, or deciding whether a new signal on the
Live page belongs here versus the deck guide (`docs/guide.md`) or the
per-match report (`docs/review.md`).

## Why this question is worth writing down once

`advisor.py` — since folded into `review/narrative.py` — asked *"what is the
right play on this board?"* during a match, and was retired because the
projector only ever has an end-of-turn snapshot to reason from mid-match: no
combat, no stack, no opponent hand. The advice rested on a board the player
could not verify, offered at the exact moment they could least afford to be
wrong.

`brief/` asks a different question: *"what does this archetype do to me, and
what do I board?"* That is a question about **two decklists and the
tournament corpus**, not about a game — and `brief/narrative.py`'s prompt
carries **no board state, no turn, no life total, no hand, no match result,
ever**. `tests/test_brief_context.py::
test_context_never_carries_any_game_in_progress_signal` pins this by seeding
a live match with distinctive life totals and turn numbers and asserting none
of them leak into the built context.

That property is what makes the whole thing practical: a brief is a function
of `(deck, archetype)`, so **one is written once and reused in every future
match against that archetype**. Writing prose per game would be unaffordable
in effort even with no money involved; writing it per matchup is a handful of
paragraphs that keep paying off all season.

## Prompt out, answer in — this feature has no generate button

AGENTS.md non-negotiable #5 now permits an opt-in Claude call (`docs/llm.md`)
elsewhere in this project, but `brief/` deliberately doesn't use it: nothing
generates a standalone brief on its own. The round trip:

1. `sensei-top brief --deck KEY --archetype KEY --prompt` prints the
   framing plus the evidence. The Live page offers the same text
   behind **Copy the prompt** when no brief is stored yet, and
   a pairing's page offers it behind **Build the prompt**, or **Write it
   again** once a stored one is out of date ("The brief on a pairing's
   page", below).
2. Paste it into whatever assistant you already pay for. It answers with one
   JSON object: a `for` and a `context` line, then an `answer` matching
   `_BRIEF_TOOL`'s schema (the prompt's last section says so).
3. Paste the answer into the card's box and save it
   (`PUT /api/guide/{key}/briefs/{archetype_key}`), or from a terminal
   `sensei-top brief --deck KEY --archetype KEY --import FILE`. Either
   way it is read through `answers.py::read_answer`, whose
   `for: brief:{deck key}:{archetype key}` line must name this deck and
   opponent, then validated against your real 75 and stored.

**Most briefs never need step 1 or 3 individually.** A generated, pasted or
imported deck guide (`POST` or `PUT /api/guide/{key}/narrative`, or
`guide --deck KEY --import FILE`) writes a brief for every matchup that
narrative covers, via
`from_guide.py` — so one guide lights up the whole Live page. This is
exactly why a generate button here would mostly duplicate a call the guide
already made; per-matchup imports are for filling a gap the guide missed.

A plan that does not balance, or that names a card the deck does not hold, is
**stored with the problem recorded** rather than rejected or silently
repaired (`guide/plans.py`) — the dashboard shows the problem next to the
plan, and `tests/test_brief_importer.py` pins that.

## Why a brief is persisted

`guide/__init__.py` and `review/__init__.py` both refuse to persist their
evidence, because both packages compute *derivations* of the current database
that a later rebuild could silently disagree with; only their authored
narratives are stored (`deck_narrative`, `rcq_guide`, `match_narrative`,
`leaks_narrative`). `brief/` persists one authored artifact per `(deck,
archetype)`, in `matchup_brief`. A brief is different from a derivation: it
is prose written once from a decklist and a corpus snapshot, both stamped
beside it (`matchup_brief.list_hash`, `.corpus_commit`), so a stored brief
cannot go silently wrong the same way — the two things that would make it
wrong are recorded and checked before it is ever read back as current.

- **`list_hash`** (both boards, sha256) makes a brief *wrong*, not stale: a
  sideboard edit changes what the IN half of a plan should be, and
  the API reports it as `stale` so the page says the plan predates the current
  list rather than rendering it as current.
- **`corpus_commit`** only makes a brief *stale*. Nothing here acts on that
  difference automatically — the API surfaces it as `stale: true` and lets
  the reader judge, the same posture `docs/guide.md`'s own provenance takes.

`matchup_brief.prompt` holds the build context `brief/importer.py`
is given, not the text a card offered to copy, for a brief stored by
`brief --import` or either `PUT`: one coverage prompt covers up to
eight briefs, and nothing reads the column back.

## Never pooled across an undetected reset either

A brief skips the deck guide's most expensive machinery
(`structural_change`, the leak finder, `list_diff`) — but it does not skip
`guide.window.format_resets`. Everything here is the deck's own format's
(`guide.deck.identity_format`, `docs/guide.md`): a deck with no format has
no field to read, so `full_prompt` and `full_multi_prompt` return `None`
for it. `brief/narrative.py::_current_window_start(conn, fmt)`
computes the same "day after the most recent detected reset" window
`guide/bundle.py` uses, for that format, once per generation, and threads
it into `build_consensus`, the archetype's own field share (both read only
that format's events), and the "Field record for this pairing" line, which
reads `v_meta_matchup` for that format (`ranked_field_matchup(..., fmt=)`)
windowed the same way (`migrations/044_meta_matchup_date_grain.sql` gave
that view the date column this needs). Skipping this would reintroduce, in a
second place, the exact mistake `guide/window.py` exists to prevent
(`docs/metagame.md`'s "format-reset boundary") — an un-windowed share,
matchup record, or consensus list is real evidence of a deck that may no
longer exist. The rendered line names the tier the number came from and the
window when one applies: "Field record for this pairing, from paper
tournaments of 64 or more players since {since}: …".

One case needs saying out loud rather than windowing: with no
`card_legality` rows for the deck's format on this machine, no ban is
detectable at all, and `_current_window_start` returns `None` for a reason
that has nothing to do with the format. `_window_note` branches on
`guide.window.legality_known(conn, fmt)` so the prompt says "no card
legality data is present … these numbers may pool across a ban" instead of
the flatly wrong "no format reset detected".

Verified against the real corpus: before this window was wired in, a Mardu
Discard brief reported 4.5% of the field over the whole corpus; windowed to
the detected reset it reports 9.0%, matching the hand-written guide's own
post-ban figure (8.6%) far more closely.

One thing a brief does *not* window: `guide.field.personal_rate`'s
`carryable` flag is always `True` here, same as when `guide/field.py` calls
it without a `changes` map of its own — computing `structural_change` per
archetype is expensive, and the full deck guide is where that question gets
answered properly.

## No watcher, no background anything

An earlier version of this package ran a second daemon thread that polled for
a live, unbriefed opponent and made an API call to fill the gap. That thread
is gone with the call. Nothing in `brief/` runs on a timer, and no thread
`serve --watch` starts ever writes a brief or calls a model.

What survives from that design is the guard order it needed, now
inside the API route (`api/routes/current_match.py::_brief_response`):
no current match (`no_match`); an opponent the classifier has not
named, `format_unknown` when the deck has no format (the classifier
never names an opponent in a match with no format, so `unclassified`
would promise a read that never comes) and `unclassified` otherwise; a
named opponent on a deck with no format, which returns a stored brief
(`ok`, with no `prompt`, since none can be built without a format) and
`format_unknown` only when nothing is stored; an archetype with too
little corpus to anchor a brief to (`no_consensus`). Each is a
distinct, honestly-reported status rather than an empty card, and a
stored brief outranks `format_unknown` here as on a pairing's page
(below).

## The Bo3 break reuses this exact system — never a call during it

`table/intermission.py`'s break read (`docs/current-match.md`) is built
entirely on what this package already stores: the exact `matchup_brief` for
the opponent the live replay just named, or — with none stored — the closest
one already written for a different archetype this deck could plausibly be
facing (`_closest_alternatives`, best `fit` first). Neither path ever calls
out. Measured on 392 real breaks, the median is ~39 s (80% end within 60 s);
a Claude call plus building its own prompt would eat most of that before an
answer could even come back, so "call out mid-break" was never on the table
— AGENTS.md non-negotiable #5's "every call is a button press, never a
schedule" already rules it out, and a break is exactly the kind of moment a
schedule would be tempting to add one for. What the break phase *does*
offer, with no plan stored at all, is the same prompt/import round trip as
any other missing brief: a **Copy prompt** card that takes the written
answer back in its box, with the `brief --import` command beside it when
running from source.

## `brief/coverage.py` — which of the field this deck's briefs actually cover

*"How much of what I'll actually face already has a plan?"* — a read, not a
computation the guide performs: nothing here is stored, and nothing here
writes a brief; it only says which already-written briefs cover the field
and which gaps are worth writing next.

**Rows are a union of two evidence sources**, not just one: every archetype
this deck identity has actually faced (`guide.field.faced_archetypes`,
unwindowed personal history — the same "faced" definition the guide's own
most-faced matchup list uses, so the two never disagree about what counts),
and the field's own top `TOP_FIELD_ARCHETYPES` (6) archetype keys by
windowed deck count in the deck's format. A row exists for the union of
the two, and **every row carries its own windowed field share** — `0.0`
when the window has classified decks but none of this archetype (a
measured zero, not a gap), `None` only when the window has no classified
decks at all. A deck with no format has no field: `Coverage.fmt` is
`None` and there are no rows at all, rather than rows that would all read
`no_consensus` (`CoverageOut.fmt` null; no row ever carries
`format_unknown`, it is the whole deck's answer).

**`status` distinguishes two different reasons a brief is missing.**
`missing` means a consensus decklist exists for this archetype in the
current window — `build_consensus` would answer — but no brief has been
written yet: real, actionable work. `no_consensus` means the window holds
fewer decklists than `build_consensus`'s own `min_decks` gate requires, so
no brief *can* be written yet no matter what (`full_prompt` would return
`None` the same way it does everywhere else in this package) — keeping the
two apart stops an archetype faced once, long since dropped from the field,
from reading as work still waiting to be done. `ok` and `stale` cover a
brief that already exists, `stale` per `brief/store.py::is_stale` exactly as
elsewhere in this file.

**Measured on the real Spellementals deck:** 29 coverage rows, 12
`no_consensus`. Every stored brief was stale on that run (a corpus refresh
had moved past every `list_hash`/`corpus_commit` stamp), so coverage read
0 of 63 faced matches covered until `brief --missing` was rerun.
`build_coverage` itself costs ~0.73 s on that database.

## The brief on a pairing's page

A pairing (`/decks/:id/matchups/:opponent`, `PairingView`) carries its
matchup's brief as a card of its own, `PairingBrief`, titled "Matchup
brief". It reads the deck's coverage (`useGuideCoverage`, one query the
coverage card and the pairing's heading share) and every brief stored
for the deck (`useGuideBriefs`), and `briefState` (`lib/pairing.ts`)
turns the pairing's opponent key and those two reads into one of five
states:

- **Not a named archetype**: the key is not an `archetype:` key (a
  manual pick, a colours-only read, or an opponent the classifier never
  named). One sentence says a brief is written against an archetype
  named from tournament results; nothing to build.
- **No format**: no stored brief, and coverage's `fmt` is null — the deck
  has no format, so there are no tournament lists to write from. Checked
  before any coverage row is read; one sentence says so and how to set the
  format on MTGO. A stored brief wins over this state, since it is the
  user's own authored artifact.
- **Too few tournament lists**: the archetype's coverage row is
  `no_consensus`. One sentence says so.
- **Not written yet**: no stored brief for the archetype. A sentence
  says how the round trip goes, above a **Build the prompt** button.
- **Written**: the card draws the brief (play-around items, then the
  swap, its problems and its prose laid out as a guide's own plan is,
  `PlanBody` from `WrittenCards.tsx`, then who wrote it and when). When
  coverage says the row is `stale`, a `warn` callout above the brief
  says the list or the tournament results have changed since it was
  written, and a **Write it again** button sits below it.

Either button opens the prompt in place; the prompt is fetched only on that
press (`useGuideBriefPrompt`), never on the page's load. Under it, a box
takes the answer back (`PUT /api/guide/{key}/briefs/{archetype_key}`);
running from source, the import command is filled in too, `sensei-top brief
--deck "<deck key>" --archetype "<archetype>" --import brief.json`. When the
route answers `format_unknown` or `no_consensus` instead of a prompt, the
sentence for that state stands where the prompt would have been.

## The multi-brief prompt, and `brief --missing`

Writing one archetype's brief at a time is fine when coverage is already
good; it is not fine the day a deck guide's own top-6 pick misses most of
what a deck actually faces on the ladder (`docs/guide.md`'s guide-prompt
coverage section exists for exactly this reason). `brief/narrative.py`'s
`full_multi_prompt` builds
**one prompt covering several matchups at once** — the player's 75 and its
oracle text appear exactly once, not once per matchup, and each opponent
archetype gets its own section with its consensus staples and oracle text
(a card already described in an earlier section is never repeated) plus
this deck's personal record against it. `MULTI_BRIEF_MAX` (8) caps how many
sections one prompt covers; anything past the cap comes back in
`MultiBriefPrompt.deferred`, waiting for the next round, and an archetype
with no consensus at all comes back in `.no_consensus` rather than silently
dropped. The model still answers with one JSON object — `_MULTI_BRIEF_TOOL`
wraps `_BRIEF_TOOL`'s own per-matchup shape in a `briefs` array, one entry
per section, and `brief/importer.py`'s `import_briefs` stores each answer
through the same single-brief path a one-at-a-time import would have used,
so nothing about how a brief is validated or stored depends on how it
arrived.

**CLI:** `sensei-top brief --deck KEY --missing --prompt` prints the
multi-brief prompt for every archetype `brief/coverage.py` marks
`missing`/`stale` for that deck, in coverage order (times faced desc, then
field share desc, then key — the same order the dashboard's own coverage
table uses, so a gap never moves between the two); `--missing --import
FILE` stores every answer via `import_briefs`.
The Guide's coverage card saves the same answer pasted into its box
(`PUT /api/guide/{key}/coverage`), every brief through `import_briefs`;
an archetype with no consensus is skipped, and when every one is, the
answer is refused (409) and nothing is stored. `--missing` and `--archetype`
are mutually exclusive on the same `brief` subcommand. No consensus for
*any* missing/stale archetype prints "No field consensus for any
missing/stale archetype yet." rather than naming which ones — the same
coarse, all-or-nothing message `full_multi_prompt` itself returns `None`
for.

**API:** `GET /api/guide/{key}/coverage` returns the coverage rows
(`CoverageOut`); `GET /api/guide/{key}/briefs` returns every brief stored
for the deck (`MatchupBriefOut[]`), which a pairing's page reads beside
coverage to tell a written brief from a gap; `GET
/api/guide/{key}/briefs/{archetype_key}/prompt` is one archetype's
prompt, fetched only when a pairing's **Build the prompt** or **Write it
again** is pressed; and `GET /api/guide/{key}/coverage/prompt` is the
multi-brief prompt for every `missing` or `stale` row, the same text
`brief --missing --prompt` prints. Both prompt routes answer
`format_unknown` (`BriefPromptOut.status`, `CoveragePromptOut.status`)
when the deck has no format, checked first: there is no field, so nothing
can be missing or short of consensus, and `no_consensus` or
`nothing_missing` would give a false reason. The live brief,
`GET /api/current-match/brief` (`MatchupBriefResponse`), answers the same
status for the same reason (above).

## Backfill: a generated guide is a free source of briefs

A written deck-guide narrative already contains a `MatchupPlan` per top field
archetype — the same shape a brief stores, from a prompt that showed its
author the whole field at once. `brief.from_guide.
store_guide_matchups` writes one `Brief` per plan (`source='guide'`), reusing
the guide's own already-computed `FieldEvidence` for the share and personal-
record numbers rather than re-querying them, and never overwrites an
existing `source='live'` row whose `list_hash` still matches — a brief
written for this exact matchup, from a prompt that carried that matchup's own
consensus staples and oracle text, is not improved by a guide's broader
sweep. `sensei-top guide --deck KEY --import FILE` and `POST` or `PUT
/api/guide/{key}/narrative` drive this.

## What this does not do

- It does not judge the current game. There is no game in the prompt to
  judge.
- It does not write anything by itself, and has no generate button — unlike
  the match report and the deck guide (`docs/llm.md`). The dashboard offers
  the prompt and the import command; the writing happens wherever the user
  chooses, or as a side effect of generating a deck guide. The brief card
  saves a pasted brief through `PUT /api/guide/{key}/briefs/{archetype_key}`,
  on non-negotiable #6's authored-artifact allowlist, and `brief --import`
  is the terminal equivalent.
- It does not compute `structural_change`'s per-archetype "changed/gone"
  verdict. That is a real, small gap (see above), acceptable because the
  Live page's own field-share number is windowed correctly regardless, and
  the full deck guide remains the place a player checks that question
  directly.
