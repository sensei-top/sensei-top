# The coach

Read this when touching `coach/`, `api/routes/coach.py`, or the Coach page.

## What the coach is

The match report (`docs/review.md`) reviews one match. The deck guide
(`docs/guide.md`) reviews one deck against the field. Neither can answer
"what should I actually practise?" — that question is about the player, not
a game or a decklist, and it only has an answer once enough matches exist to
separate a real pattern from one bad night.

The coach is that third scope: one button that writes a dated report for one
format, read from *every* completed Arena and MTGO Constructed match at once.
Habits are read across every format the player played; what
is about the format — the decks, the roles, the opponents, the field — is
read from that format alone (see "The two windows"). It sees three things
nothing else in this project computes:

- **Cross-deck records** — overall, game 1 against post-sideboard games, on
  the play against on the draw, kept seven against mulliganed hands, across
  every format; and per deck, per role a matchup cast the player in, per
  opponent archetype, in the report's format since its last format reset —
  each with its own sample size and 95% Wilson
  interval, never a bare percentage (`review/leaks.py::_wilson`, reused
  rather than re-derived).
- **Recurring patterns at two scopes** — `review/leaks.py::find_leaks`
  unscoped, the way the leak finder already works, plus a second run scoped
  to each deck with enough of its own sample to say something about that
  deck specifically.
- **Where losses turn**, bucketed by stage and severity, with three worked
  example losses the report can point at turn by turn.

Every report is history, not a single row a regenerate overwrites
(`coach/store.py`) — a new report's "Since your last report" section reads
the metrics a *previous* report of the same format stored, so writing a new
one must never erase the one it will be measured against.

Each row names its format in `coach_report.format`
(`059_coach_report_format.sql`). Every report written before that migration
was a Standard one, so a NULL there means Standard: `coach/store.py` reads it
so, and the old rows are not backfilled, since rule 4 forbids writing an
answer a row never recorded. `latest_coach_report(conn, fmt)` is the newest
report of `fmt`, a NULL row counting as Standard; `list_coach_reports` is
every report of every format.

`GET /api/coach`, `GET /api/coach/narrative`,
`POST /api/coach/narrative` and `PUT /api/coach/narrative` (a pasted
report, `docs/llm.md`, "Saving a pasted answer") take an optional
`?format=`; omitted, they use `api/sql.py::default_format`
(the most recent match's format, else Standard), and every response
says which format it used. The Coach page always sends it on the `PUT`, so a
pasted answer's `coach:{format}` line is checked against the format the page
shows. Only a report of the requested format is ever the
latest one on the narrative route, so another format's report can never read
as current. The Coach page carries the format in its address and draws the
same "Format" select the Field page does, only when more than one format has
matches or a written report (`lib/coach.ts::coachFormatChoices`); its "Every
report" list stays the whole history, each row
naming its format.

`coach/evidence.py::build_coach_evidence` is a pure function of the
projected database, like every other analytics package in this project:
nothing here is persisted itself, and a rebuild costs one request, not a
migration. It reuses `review/`'s and `guide/`'s own building blocks rather
than re-deriving them — `build_match_report`, `find_leaks`, `build_snapshot`,
`list_identities` — sharing one `consensus_cache`/`colors_cache`/
`view_cache`/`report_cache` set across every call, the way `guide/bundle.py`
already does for the deck guide.

## Scope

The population is every match with `result IN ('win', 'loss')` that is
**Constructed** and has a **format**: `v_match_format.format` is not NULL
(the format Arena's log named, else the user's MTGO pick, else the format the
match's revealed cards fit; `docs/opponent-deck.md`). Every
format is kept, not only the report's own: which sections a match reaches is
the report's choice (see "The two windows"), not the population's. Every
exclusion that actually removes at least one match earns its own line in
`gaps`, with a count — silence about an exclusion would look like the report
never noticed those matches existed.

**Arena** matches are first asked about their event, three checks:

- **No `event_id` at all.** Genuinely rare on Arena; kept as its own reason
  because it is a different claim from an excluded event or a Limited queue.
- **An excluded event.** `DualColorPrecons` (a preconstructed-deck event) —
  not a real ladder result.
- **A Limited queue.** `coach/evidence.py::_is_limited_event` — an event
  id whose first `_`-separated part is `QuickDraft`, `PremierDraft`,
  `TradDraft`, `CubeDraft` or `PickTwoDraft` — out of scope for a report about deckbuilding and matchup decisions across a player's own 75s.

**MTGO** has no event to ask: `projector/mtgo/project.py` always writes
`event_id = NULL` (and `deck_id = NULL`) for an MTGO match, so it skips those
three.

Then, for either client, a match with no format is excluded, never counted
under a guessed one (rule 4). An MTGO match whose format was neither picked
nor inferred lands in the bucket of the reason `match_format_inference` gave
(`archetypes/classify.py::infer_formats`, `FORMAT_REASONS`):
`unresolved_cards` (a revealed card the card database could not name),
`unknown_legality` (a card with no legality on file — run `sensei-top cards
--scryfall`), `no_fit` (no one of the seven formats allows every card),
`too_few_cards`, or `ambiguous` (the cards fit two formats, neither inside the
other). Tokens and MTGO's game markers are left out of that read rather than
blocking it (`infer_formats`' own docstring). Anything else with no format —
an Arena queue for a format this app doesn't track, an MTGO match never
inferred — lands in `no_format`. A banned card does not exclude a match:
Scryfall's ban list is today's, so a card banned since the match was played
still fits its format.

An included MTGO match counts in `overall`, the skill splits, the leaks and
the turning points exactly like an Arena one. It reaches `by_deck` only when
the user picked its deck (`mtgo_match_pick`, read through `v_match_deck`):
MTGO writes no deck id, and rule 4 forbids inventing one. Its `decks` rows
come from deck files, an exported `.dek` or MTGO's own deck store
(`grouping *.xml`), reached only through that pick (`docs/architecture.md`,
"What a turn snapshot holds"). A gap line says so whenever at least one
included MTGO match has no picked deck.
`CoachEvidence.by_source` (and `metrics_snapshot`'s own `"by_source"` key)
always carries both an `"arena"` and an `"mtgo"` rate, `n=0` when a source
contributed nothing, so a caller never has to guess which source is empty
versus simply not yet measured.

`build_coach_evidence` returns `None` below `review/leaks.py::MIN_SAMPLE`
(10) matches in that population — the same floor the leak finder already
applies before it will show a rate at all.

## The two windows

One population, not two: a *skill* window and a *format* window sit on top
of it, because how a player mulligans or which patterns cost them games are
habits, while a deck's record, the roles a matchup casts it in and an
opponent's metagame share are knowledge of one format, and go stale with it.

- **Skill sections** — `overall`, `overall_games`, game 1 against
  post-sideboard, on the play against on the draw, `mulligans`, the leaks
  (`leaks`, `deck_leaks`), the turning points, the examples, `by_source` —
  use the whole population: every format played, all history.
  `format_counts` names every format in it, with its count.
- **Format sections** — `by_deck`, `by_role`, `by_opponent`, the current
  decklists, `field` — are restricted to the report's format's matches since
  `guide/window.py::window_start` of that format's latest `format_resets(conn,
  fmt)`. `format_population` counts them.

This is the same rule `guide/field.py` exists to enforce, and the memory
behind it is the same one: **never window metagame data across a ban.** An
opponent-archetype rate from before a format-defining archetype changed is
void, not merely old. When no reset is on file for the format, its format
sections fall back to every match of that format and the report says so
plainly — one gap line when a reset genuinely wasn't detected, a different
one when there is no card legality data for that format to detect a reset
from at all (`guide/window.py::legality_known(conn, fmt)`), since those are
different claims and only the first means the corpus really has no reset in
it. A report whose format has no match in its window is still written, since
the skill sections cleared the floor: a gap line says the per-deck, per-role
and per-opponent records and the decklists are empty, and the field section
still shows that format's field.

Every match report behind either kind of section is built under the window
of *its own* format, not the report's: `build_coach_evidence` seeds
`guide/window.py::consensus_window_resolver` with the report format's window
and hands that one resolver to every `build_match_report`, `build_snapshot`
and `find_leaks(consensus_window=...)` call, so a Modern match in a Standard
report's skill sections is still read against Modern's consensus and window,
and shares its `report_cache` entry with the leak finder's own read of it.

## The evidence sections

Each is a rollup over the same population — the whole of it for a skill
section, the report format's window of it for a format section — capped so a
report stays readable and a caller always knows what got cut:

- **Overall and splits.** Match and game win rate, game 1 vs. post-sideboard
  games, on the play vs. on the draw, kept seven vs. mulliganed — the whole
  population, every rate through `format_rate` so "no data" and "anecdotal"
  never drift between two lines.
- **By deck (format window).** The top 8 decks by their matches in the
  report's format since its reset (`TOP_DECKS`), each with its
  own archetype (classified the same way `guide/field.py` classifies its own
  deck — the most recently played `deck_id` under that identity, full 60,
  no event conditioning, under the report format's rules) and the same four
  splits as overall. Only a deck whose own format (`guide/deck.py
  ::identity_format`) is the report's gets a line; a match of the
  report's format played with a deck of another format still counts in the
  other format records, and a gap line counts those. Everything past the top
  8 is a gap line naming how many decks and matches it covers.
- **By role (format window).** Read from the `role_assignment` finding's own
  `"role"` Evidence (`review/analyzers/frame.py`) — a role that never fired
  (either side unclassified, too few tagged cards) counts as `unknown`,
  never a guess. A role bucket the format window never produced is omitted,
  unlike mulligans below, since the role vocabulary isn't a fixed split.
- **Mulligans.** Game-level, kept seven vs. mulliganed, from
  `guide/play.py::mulligan_split` — the one definition of the bucket split
  that `guide/play.py::mulligan_record` (one deck's own `deck_ids`) and this
  report (its whole match population) both build from.
- **By opponent archetype (format window).** The top 12 opponent archetypes
  by sample size (`TOP_OPPONENTS`), resolved through `v_match_opponent
  .opponent_key` — a manual deck pick that named a real archetype
  (`api/routes/matches.py`'s `set_opponent_deck`) merges into the same key an
  automatic classification of that archetype would produce, so a renamed or
  manually-corrected opponent doesn't split into two rows. Every distinct
  label a key has carried rides along as `variants`. Beyond the top 12, and
  every unclassified opponent, is a gap.
- **Recurring patterns, all decks and per deck.** `find_leaks` unscoped for
  the top 8 (`TOP_LEAKS`), plus a second `find_leaks` run per deck among the
  top 8 by whole-population match count (every format, not `by_deck`'s
  set) with at least `2 * MIN_SAMPLE` (20) of its own population matches,
  in every format the deck was played in — below that
  a deck can never clear the leak finder's own per-side sample gate even in
  the best case, so it is skipped rather than scanned for nothing. Each
  deck's own top 3 (`TOP_DECK_LEAKS`) are kept.
- **Where lost games turned.** Every lost *game* (not just a match lost
  outright — a match won 2-1 can still have dropped game 1) with a
  `turning_point` finding, bucketed by the player's own turn — `early`
  (turns 1-3), `mid` (4-6), `late` (7+) — and by severity (`decisive` or
  `notice`; `trajectory.py`'s `turning_point` never emits the other two
  `Severity` values). Always all 6 cells, even at zero, so a caller renders
  a fixed grid rather than a shape that changes report to report. A lost
  game with no turning point at all (never behind, too few recorded turns,
  or a missing report) is a gap, not a guessed bucket.
- **Current decklists.** The current 75 of up to 3 kept decks
  (`TOP_DECKLISTS`), ordered by format-window match count — a kept identity
  with zero matches since the reset is omitted, since its list is not
  "current" by this report's own definition of the word. A card with no
  matching `cards` row is counted as `unnamed` rather than rendered as `"?"`.
- **The field.** The top 10 archetypes (`TOP_FIELD`) in the report
  format's public MTGO/paper results since its reset, with the true
  classified-deck total as the share denominator
  (`guide/field.py::_classified_deck_total`, reused rather than recomputed —
  the exact bug that module's own docstring exists to prevent) and this
  report's own record against each archetype, joined through the same
  `'archetype:' + key` vocabulary `by_opponent` already resolves opponents
  into.

## How the example games are chosen

Up to 3 (`MAX_EXAMPLES`) worked losses, chosen by a fixed rule so the
selection — and the `context_hash` computed over it — never depends on
anything but the database:

1. Walk this report's own kept leaks in gap-descending order to the first
   whose pattern actually goes with *losing* (`win_rate_with <
   win_rate_without` — a pattern that correlates with winning, or is even,
   is skipped). Only that one leak is ever used.
2. Its own `match_ids_with`, filtered to losses that have `turns` rows (the
   only losses this module can render turn by turn), ordered most-recent
   first with match id as the tie-break, fill the first slots.
3. If that yields fewer than 3 — including none, when no leak qualified at
   all — the remaining slots are filled from every eligible recent loss in
   the same order, skipping anything already chosen, labelled
   `"recent_loss"` instead of a leak code.

`match_id` is deliberately the one field allowed to appear on `CoachEvidence`
outside this rule — everywhere else, a match id, opponent name, opponent
user id, or deck GUID would be a privacy leak; `ExampleGame.match_id` exists
only so the Coach page can link an example back to its match page, and
`coach/narrative.py` never renders it into a prompt.

## The leak line's signed difference

The leak finder's own `Leak.gap` is unsigned — it ranks patterns by how much
they move the win rate *either* direction, since both a lucky pattern and an
unlucky one are worth surfacing. A coach report needs the direction too, so
`coach/narrative.py::_leak_line` recomputes it from the two rendered rates:
`present.rate - absent.rate`, shown as `win rate ±N points with it`.
Negative means the pattern shows up alongside losing; positive means it
shows up alongside winning. This sign is derived once, in one place, so a
prompt line and the finder's own ranking can never quietly disagree about
which is more damaging.

## The reading list

`coach/canon.py::CANON` is a checked-in, hand-verified tuple of
`CanonEntry`s — Mike Flores, Reid Duke's Level One course, Paulo Vitor Damo
da Rosa, Frank Karsten's mana-base math, Richard Garfield on variance. It
exists because a coach that can only quote a player's own numbers back at
them has nothing to teach; grounding advice in real strategy writing is the
second of the coach's three evidence sources (rule 4's "own data, a curated
reading list, or a restricted web search" — never anything recalled from
model memory).

Every entry is curated, not generated: **every URL and author was checked
against the live page before check-in** (2026-09-18), and its `summary` is
2-3 sentences written from that page's own content in this project's words
— never a pasted quote. Two TCGplayer entries were checked through the
publisher's search index instead, since TCGplayer serves its articles as a
script-rendered app no fetch can read; their `note` says so. A candidate
entry that could not be verified was dropped rather than guessed at, per
rule 4.

`topics` mixes two vocabularies: codes, which are the `Finding.code`s an
analyzer actually emits (`role_assignment`, `race_behind`,
`over_committed_into_sweeper`, …) plus the leak finder's two synthetic
codes (`mana_screwed`, `mana_flooded`, `review/leaks.py::_mana_flags`), and
broad tags a report's evidence sections carry
(`sideboarding`, `mulligans`, `play-draw`, `deckbuilding`, `review`,
`variance`, `tournament-prep`, `tilt`). `coach/narrative.py::reading_list`
collects the codes and tags this report's *own* evidence actually surfaced —
a leak code that fired, a role that occurred, a mulligan that was taken —
and `entries_for` returns every entry whose topics intersect that set. Three
entries (`CORE_IDS`: role assignment, Duke's *Becoming a Better Player*,
Garfield on variance) are always included regardless, since role and review
method and variance are relevant to every report. The full 18-entry list
never goes into a prompt — only what a report's own evidence calls for.
Entries are cited in the prompt, and in a stored report's prose, as `[R<n>]`.

## The domain allowlist

`coach/canon.py::ALLOWED_DOMAINS` is the set of sites `llm.write_report`'s
server-side web search tool may read — checked 2026-09-18 for live Standard
metagame or strategy content, the same day the reading list itself was
verified. It is deliberately **not** every site the reading list cites:
`starcitygames.com` carries several reading-list articles but publishes no
current Standard coverage, so it is left off the search allowlist even
though it stays a valid `[R<n>]` citation source. `channelfireball.com`
redirects to `tcgplayer.com`, `cardkingdom.com` has no Standard content, and
`melee.gg` is results data with no prose — all three are named in the
module's own comment as deliberate omissions, not oversights. A report on
another format searches the same nine domains: the list was checked for
Standard only and has not been re-checked for the other formats, and adding
a domain waits for the user.

Two domains here, `mtgdecks.net` and `mtgazone.com`, are sites
`metagame/` will not download from (`docs/review.md`, "Metagame data: real
tournament results, not Arena aggregators"). They stay, by the user's
decision of 2026-10-13: `metagame/`'s fetch is this app's own automated
reader, which those sites' robots rules address, while the coach's search
is Anthropic's tool, run under its own crawler policy, once per button
press, on the user's own credential.

Web search exists for exactly one job — the `Format notes` section's
current-format facts (bans, top decks, recent articles on the archetypes a
player plays and faces) — and nowhere else. `SYSTEM_PROMPT` states this as a
rule the model must follow (never search for the player or an opponent),
and the allowlist is the structural backstop: even a prompt-injected request
to search anywhere else can only ever reach one of these nine domains.

## Progress

`coach/evidence.py::metrics_snapshot(evidence)` records a small, JSON-safe
dict at generation time — a `"version"` key (`2`), `"fmt"` (the report's
format), `as_of`, the overall win-loss-rate, and each shown leak's
code/gap/pattern. `overall` and the leaks are skill sections, so they span
every format played. It is deliberately
not a way to reconstruct `CoachEvidence` itself, only enough for a later
comparison; every value is a plain dict/list/str/int/float/None because a
tuple or dataclass would come back reshaped after the `json.dumps`/
`json.loads` round trip this function's own contract depends on.

`progress_since(conn, metrics, source=...)` reads that stored dict back
against a *fresh* read of the population — never a second full
`CoachEvidence`, which would pay for every other rollup just to answer "what
changed." It reports the win rate over matches strictly newer than the
stored `as_of`, then, for each leak code the previous report knew about,
whether it recurred in the new matches and at what rate — expected to read
`anecdotal` almost every time, and labelled as such rather than presented
with false confidence, since a handful of new matches will almost never
clear `find_leaks`'s own sample gate. Progress is a skill reading: the new
matches are every format's, each one's report built under its own format's
window (a fresh `consensus_window_resolver`). The stored dict it reads is the
previous report *of the same format* — `build_coach_prompt` picks it with
`coach/store.py::latest_coach_report(conn, fmt)`, so a Modern report is never
measured against a Standard one's focus areas.

For the two mana-leak codes specifically, the denominator is narrower than
"every new match": `progress_since` counts only the new matches whose flag
`leaks.py::_mana_flags` could actually answer (`True` or `False`), never one
it read as `None` — an MTGO match, which carries no `turns` row at all, would
otherwise silently inflate or deflate a recurrence rate it never had
evidence for. When every new match is unmeasured for a flag, the line says
so plainly ("could not be measured in any new match (no turn data)") rather
than reporting "0 of 0" or falling silent.

A previous report whose metrics carry `"version": 1` was written before
reports covered every format: its `overall` and leaks counted Standard
alone, a different population from version 2's, so `build_coach_prompt` does
not diff the two. It says the previous report was written before reports
covered every format and progress can't be measured against it. When a
previous report's `metrics_json` carries neither version — written by some
future, incompatible schema, or corrupted — it does not guess at a
comparison either. It states plainly that the previous report's metrics are
unreadable and progress can't be measured, per rule 4.

## The prompt and the report

`SYSTEM_PROMPT` is a template: `system_prompt(fmt)` fills each `{fmt}` with
the report's format name, so the prompt says which records are that
format's alone and which are habits read across every format, and tells the
model never to present one as the other. It fixes seven `## ` headings, in
order (`coach/narrative.py::HEADINGS`), and the Coach page draws one card
per `## ` section (`web/src/lib/markdown.ts::parseReport`): Player profile,
Since your last report (omitted entirely on a first report), Focus areas,
Training plan, At the LGS, Format notes, Sources. `build_coach_context`
renders every evidence section above as labelled text blocks, ending with the
gap lines and the same "not tracked at all" sentence
(`review/narrative.py::UNTRACKED`) every other prompt in this project uses
verbatim — the stack, counters and continuous effects, attachments, exact
phase/step, and the opponent's hand. Combat *is* projected
(`migrations/014_combat.sql`), so it is not on that list.

**Two things the measured reports show that the design didn't expect.** Both
were seen on real data on 2026-09-22. Both are fixed at read time, since
stored prose stays verbatim and neither report can be rewritten in place.

- **Narration can swallow the first heading.** Both models narrate their
  searches, each narration in a text block of its own. The Opus 5 report
  opens `I'll check the current Standard format context before writing the
  report.# MTG Coaching Report — …`. The Fable 5.1 report opens
  `I'll start by gathering the current-format facts for the Format notes
  section.Now the current metagame and the specific archetypes this player
  faces.## Player profile`. `llm/client.py::write_report` joins text blocks
  with no separator. That is right inside a cited paragraph, which the API
  splits into several blocks, and wrong between narration and a heading.
  The Opus report survived because an unrequested `#` title sat between its
  narration and `## Player profile`. The Fable report had nothing there, so
  `parseReport`, which starts a section at a line beginning `## `, never sees
  its first heading: the player profile renders as untitled leading text, with
  the narration in front of it. `coach/narrative.py::clean_report` fixes this
  at read time — it finds the first occurrence of `## ` followed by a
  `HEADINGS` entry, even glued mid-line as in the Fable shape, and returns the
  prose from there; `api/routes/coach.py::_report_out` is the one place all
  four routes' prose passes through it, so the fix reaches every route with no
  duplicated logic. Stored prose is still verbatim — the row on disk keeps its
  narration — only what the API returns is trimmed.
- **No web citations are stored.** Neither report stored a single web
  citation, although the Opus 5 run searched 6 times and the Fable 5.1 run 8.
  `sources_json` holds reading ids only, so the Sources section lists the
  reading list and nothing from the searches, and the Format notes facts
  arrive without links. It isn't known yet why no
  `web_search_result_location` citation came back — unverified hypothesis:
  `web_search_20260209`'s dynamic filtering runs search plus code execution
  server-side, so the text blocks it returns may simply carry no citation
  objects. `llm/client.py::write_report` now logs a `Counter` of every
  content block type seen across the loop, plus how many text blocks
  carried a non-empty `citations` list, in one `log.info` line when the
  loop ends — the next real report confirms or refutes the hypothesis
  instead of leaving it a guess (rule 4).

  Until a real citation object shows up, `coach/narrative.py::web_sources`
  reads the pages back out of the prose itself: it scans the cleaned
  prose's own `## Sources` section for lines carrying an `http(s)://` URL
  — the reading-list lines above them carry none, so no `"Web sources:"` /
  `"Web:"` label needs recognizing, and both were seen on real reports. A
  URL is kept only when its host equals, or is a subdomain of, an entry in
  `coach/canon.py::ALLOWED_DOMAINS` — the search tool is restricted to that
  list, so anything else came from the model's memory, not a citation, and
  is dropped and counted rather than trusted. `api/routes/coach.py::
  _sources_out` appends these after the stored web citations and reading
  ids, skipping any URL already present. `CoachReport.tsx`'s `SourcesBody`
  labels the two groups "Reading list" / "From the web" once both are
  non-empty.

`build_coach_prompt` computes `context_hash` — reused from
`review/narrative_store.py`, the same SHA-256-of-the-prompt-context
`match_narrative` and `leaks_narrative` use to mean "the evidence changed"
— over the evidence **alone**: `build_coach_context` called with
`previous=None, progress=()`, never the full context actually sent to
Claude. The full context does embed the previous report's own focus section,
so hashing it would make a freshly-stored report register as stale the
instant the very next build lists it as its own "previous" — a report
should read stale only when new matches change the evidence, and only then.
The evidence names its format in its scope block, so a report on one format
never hashes the same as a report on another.

Every report is a plain `INSERT` (`coach/store.py::write_coach_report`),
never an upsert — a coach report is history, the same way a match itself
is, not a single current slot the way `match_narrative`/`leaks_narrative`
are. Each row is written with its format. `list_coach_reports` reads that
history back newest first, every format; `latest_coach_report(conn, fmt)`
the newest of one format. A pasted report keeps the same metrics snapshot
and cited reading ids a generated one does, so the next report's progress
reads against it; its cost and search count are `NULL`.

## Cost

Planning estimates made before the first report, at `effort: high`, assuming
roughly 50-60k input tokens, 20-30k output tokens (thinking included), and
8 or fewer web searches at $0.01 each:

| Model | Price per MTok, in / out | Est. per report | Why |
|---|---|---|---|
| Opus 5 | $5 / $25 | ~$0.9-1.2 | Strong reasoning over statistics; supports the dynamic-filtering search tool. |
| **Opus 5.5** (default) | $4 / $20 | ~$0.7-1.0 — **measured $1.04** uncached, **$0.60** with prompt caching (`docs/llm.md`) | Cheaper than Opus 5 per token; same dynamic-filtering search tool. |
| Fable 5.1 | $10 / $50 | ~$1.8-2.5 — **measured $3.23** (below) | Thinking is always on. |
| Sonnet 5 | $2 / $10 | ~$0.4-0.5 | The cheaper option if quality holds. |

These four are `llm/client.py::REPORT_MODELS` — the Coach page's model
dropdown picks one of them per report, preselected to the `[claude.coach]`
model or the base `[claude]` model (`load_coach()`'s own resolution); left
alone, the dropdown sends nothing and the server uses that same configured
model. `--set-coach-model` sets only that preselected default, not the
ceiling on what a report can be written with.

`llm/client.py::_PRICES` also prices `claude-haiku-4-5` ($1/$5), but it is
not offered in the dropdown or `REPORT_MODELS`: it rejects the adaptive
thinking and explicit effort `write_report` always sends, so it can't take
a coach call regardless of price. It remains available as a `--set-coach-model`
override in name only — a call with it would fail.

**Measured, 2026-09-20.** One Opus 5 run at `effort: high` over 245
constructed matches: 110,718 input / 9,384 output tokens, 6 searches,
**$0.8482**, 148.6s. Inside the estimate on money, but not for the reason
the estimate gave.

The prompt itself is small — about 37,700 characters, call it 10k tokens,
against the 50-60k the estimate assumed. The billed 110,718 is that prompt
charged about eleven times over, because `write_report`'s `pause_turn` loop
re-sends the whole accumulated conversation on every continuation and sums
`usage.input_tokens` across all of them. **Search count, not match count, is
what moves this bill.** Match count moves the 10k base; each search round
multiplies it. A report with web search off costs a few cents.

Both measurements in this section predate prompt caching. Since migration
063 every request in that loop is marked for caching, so a continuation
reads the re-sent prefix back at a tenth of the input price or less instead
of paying it in full, and the row keeps the two cache counts beside
`input_tokens` (`docs/llm.md`, "Model, effort, and cost"). The saving is
measured for Opus 5.5 only: the cached run of 2026-10-07 in that section's
table. The other models have no cached measurement.

Output came in at about a third of the estimate, which is the ordinary kind
of miss.

**Measured, 2026-09-22 — Fable 5.1.** One run at `effort: high` over 249
constructed matches, picked from the dropdown: 238,886 input / 15,206 output
tokens, 8 searches, **$3.2292** — about 3.8× the Opus 5 run, and above the
$1.8-2.5 estimate. Only 2× of that is Fable's per-token price. The rest is
volume: 2.2× the billed input from a prompt of about the same size, which
is the same `pause_turn` re-send mechanism as above, just more of it. How
much of that came from extra continuations and how much from bigger search
results isn't recorded, because `coach_report` stores only totals. 8 searches
is also `write_report`'s `max_searches` default, so this run used the whole
search budget. Output was 1.6× the Opus run's. Wall time wasn't recorded
either: it exists only in `serve`'s own log line, never in the database.

This was not a controlled side-by-side. It covered four more matches, and it
was the second report, so its prompt also carried the previous report and
its progress material, which the first Opus run had none of.

**Measured, 2026-09-22 — Opus 5.5.** One run at `effort: high` over 282
constructed matches (253 Arena, 29 MTGO; the first report to pool both
sources): 179,177 input / 12,051 output tokens, 8 searches, **$1.0377** —
$0.72 input + $0.24 output + $0.08 search, just above the ~$0.7-1.0
estimate. Like the Fable run it used the whole 8-search budget and carried
the previous report in its prompt (about 39,100 characters), so its billed
input is again the `pause_turn` re-send multiplying a small prompt, not the
prompt itself. It cost about 1.2× the Opus 5 run, on two more searches and
37 more matches.

Sonnet 5 is still unmeasured. A run is always a button press, per rule 5 —
nothing here calls out on its own.
