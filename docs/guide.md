# The deck guide

Read this when touching `guide/`, or deciding whether a new signal belongs
in the deck guide versus the per-match report (`docs/review.md`) or the
metagame corpus itself (`docs/metagame.md`).

## Why this exists

A hand-written deck guide, backed by a throwaway read-only script, proved
to be the thing worth having in this dashboard and replaced the old Review
tab, for reasons that turned out to generalise:

- It is **deck-scoped**. `review/leaks.py`'s leak finder pools every
  completed match across every deck; a deckbuilding signal like "did I flood
  with this list" only means something read against one deck's own games.
- It **joins the player's own play to the current field** — their list
  against what winning tournament pilots register, their matchup rates
  against the field's shares.
- It **reasons over card text** for the parts no query can produce: how the
  deck's engine actually works, and per-matchup sideboard reasoning.
- It is **honest about its own window**. Its worst bug, caught and fixed
  before publishing, was pooling data across a Standard ban that reset the
  format — two of the field's "top decks" no longer existed. `guide/
  window.py` is what makes that mistake structurally impossible rather than
  merely documented.

`guide/` productizes it: given a deck, regenerate the same kind of document
from every game the player has played and the freshest corpus, on demand.

## The modules, in dependency order

Each is a pure function of the projected DB (or, for `narrative.py` and
`markdown.py`, of an already-built `DeckGuide`) — same discipline as
`review/`: only the modules that say so touch `sqlite3`, and the evidence
bundle is never persisted (a rebuild is one request; see `review/__init__.py`'s
reasoning, which applies here for the same cause — the corpus and the card
database change independently of any projector rebuild, and the user's
MTGO pick changes which deck a match reads through `v_match_deck` with no
rebuild at all). The authored narratives are: `authored.py` writes
`deck_narrative` and `rcq_authored.py` writes `rcq_guide`.

### `deck.py` — deck identity, stitched across list edits

`decks.deck_id` is a content hash of the maindeck
(`projector/matches.py`'s `deck_identity`), so a single sideboard swap mints
a new row for what is, to the player, the same Arena deck. `deck_guids`
records Arena's own stable GUID beside each content hash and is written on
every match. The grouping itself lives in the SQL view `v_deck_identity`
(migration `033_deck_identity.sql`), which `/api/metrics/winrate` also
reads, though no page calls that route. One content hash resolves to
exactly one identity, tie-broken by `deck_guids.last_seen` (whichever
Arena deck used the list most recently owns it) with `arena_deck_id`
breaking an exact tie, falling back to a bare `deck:<deck_id>` key for
a truncated log that never paired the two.
`list_identities` reads that view and attaches each group's match record,
name and current cards; `resolve` looks up one by its API key
(`"guid:<arena_deck_id>"` or `"deck:<deck_id>"`).

An MTGO deck has no GUID, so it is always a `deck:<deck_id>` identity. Its
matches are the ones the user picked it for (`mtgo_match_pick`): the guide
reads a match's deck through `v_match_deck`, never `matches.deck_id`, which
the projector leaves NULL for every MTGO match (`docs/architecture.md`).

**A deck's format** is `identity_format(conn, identity)` (`deck_format(conn,
key)` from an API key): its `decks.format` when that maps to one of
`formats.FORMATS` (`TraditionalStandard` is Standard; Draft and every other
non-constructed spelling maps to nothing), else the format most of its
matches resolve to in `v_match_format` (log, pick, then inference; a tie
goes to the format played most recently, then the lower name), else `None`.
A match with no resolved format counts toward none. Everything downstream
reads the field of this one format — the guide's resets, field, consensus
and own archetype; the brief and its coverage (`docs/brief.md`); the RCQ
guide's evidence — and a deck with no format gets no field at all rather
than another format's.

Before the view existed, `list_identities` grouped by hand and double-counted
a content hash that `deck_guids` had registered under two different
`arena_deck_id`s (the same list re-registered as a second Arena deck): it
added that hash's matches to both groups, inflating one identity's total past
its true match count. The view's tie-break is what makes deck_id → identity
a function instead of a relation.

### `window.py` — format resets, detected, not declared

`format_resets(conn, fmt)` needs no hand-maintained ban date: a card's
`card_legality` row for the format reading `'banned'` (from Scryfall's own
`legalities`, `migrations/053_card_legality.sql`) says it is banned, and
that format's tournament corpus says when it stopped being played — the
last `meta_event.event_date` on which it appeared in enough decks to be
real evidence, not a data error. Cards whose last-appearance dates cluster
within a few days are one reset (bans ship together). Each format has its
own resets and its own window; `consensus_window_resolver` maps a format to
its window, resolving each format once, for a caller that measures matches
of more than one format (`review/leaks.py::find_leaks`'s
`consensus_window`).

That legality column is a hard prerequisite, and it only ever arrives from
`sensei-top cards --scryfall`: the installed-client card database carries
no legality at all (`cards.read_arena_cards`), so a machine that has only
ever imported from Arena has `'banned'` for nothing and detects no reset no
matter how plainly the corpus shows one. `legality_known(conn, fmt)` is what
separates that from the real "nothing is banned" answer, and every caller of
`format_resets` must branch on it — `bundle.py`'s gaps and
`brief/narrative.py`'s `_window_note` both do. Reporting the two the same
way is not a cosmetic difference: it once pooled a Standard corpus across a
ban and opened a guide prompt with a 20.7% field share for an archetype that
had already dropped to 9%.

`cards --scryfall`'s name backfill (`cards.py`'s module docstring) widens
`legality_known`'s coverage without changing what it means: an alternate-art
or bonus-sheet sibling grp_id that used to have no legality now carries the
same `card_legality` rows as the printing Scryfall did attach an `arena_id`
to, each format filled on its own, so fewer real cards fall on the wrong
side of the "known vs. unknown" line.

`structural_change` is the check that would have caught the hand-written
guide's own worst mistake: for each archetype with enough pre-reset decks,
what fraction of its lists played a card the reset banned. Above
`CHANGED_THRESHOLD` (0.30) its pre-reset matchup rate is **void, not merely
stale** — `verdict = "changed"`, or `"gone"` if it has zero post-reset
decks. Only `"intact"` may carry a rate forward.

### `play.py` — the deck's own play evidence

Four views of one question, each scoped to a `DeckIdentity`'s `deck_ids`:
`board_curve` (median hand/life/lands/opponent-permanents by the player's
own turn, split win/loss), `zone_curve` (median card-type-bucket count per
zone per turn, split win/loss, ranked by which buckets diverge most —
generalises the hand-written guide's "instants and sorceries in the
graveyard" to any deck's own resource curve), `key_card_timing` (win rate
bucketed by the turn a card first resolved, cards chosen automatically —
maindeck at ≥3 copies, ranked by `review.effects.is_finisher` then mana
value), `mulligan_record` and `game_length`.

Two bugs the hand-written version shipped once, now pinned by
`tests/test_guide_play.py`: `turns.turn_number` counts player-turns
*alternating seats*, so a player-turn index is `(turn_number + 1) // 2`; and
a "first resolved by turn N" bucketing must iterate every game, not just
games where the card resolved, or "never resolved" silently undercounts.

### `list_diff.py` — your 75 against the field's consensus

Classifies the player's current decklist with the same `archetypes.classify`
engine `review/snapshot.py` already uses for one match at a time
(`_classify_own_deck`, reused rather than duplicated) under the deck's
format's archetype rules, then compares it against
`review.consensus.build_consensus` for that archetype in that format —
only decks from that format's events count, since one archetype key can
name a list in more than one format's corpus, and `fmt=None` has no
consensus rather than an all-format one. The comparison is separate
for the maindeck and the sideboard (`board="main"` / `board="side"`;
`build_consensus` read only `mainboard_json` before this package needed
sideboard consensus too, and comparing a sideboard against the field's
*maindeck* staples recommended boarding in cards the player already ran —
see that function's own docstring). Each card gets one of four verdicts:
`flex` for a card the player runs that the corpus has simply never
recorded; for one the field plays at or above `STAPLE_SHARE`, `correct` at
the consensus count, `trim` above it and `add` below it; `correct` for one
the field plays less often; and `add` for a staple the player doesn't run
at all.

`duplicate_warnings` is the fallback for one card counted under two names
that `cards.oracle_id` canonicalisation didn't already catch (no
`oracle_id` on file for one of the printings — a real, observed gap in
Scryfall's own export, not a bug here): two consensus cards sharing an
identical `type_line` and `mana_cost` that never co-occur in one real
decklist are flagged, never silently merged.

**The list**, the Guide's reading of this (`components/guide/ListCard.tsx`),
draws no table. Each board (Maindeck, Sideboard) gets a sentence counting
how many of its cards differ from the field (`differSentence`: "3 of the
23 cards differ from the field."), then the differing cards as rows: the
card's name, a chip naming its verdict when it is not `correct`, a
caption of what the player runs against what the field runs
(`copiesLine`), and, once a written guide exists, that card's own note.
The cards in line with the field are not repeated as rows; they sit
behind a closed disclosure ("The 52 cards in line with the field").
`duplicate_warnings` is drawn above both boards as a `warn` callout
titled "Possibly one card under two names".

### `field.py` — the field, after the reset

The field is the deck's format's (`build_field(..., fmt=)`, read from the
deck when omitted). A deck with no format has no field: `FieldEvidence.fmt`
is `None` and every share, rate and record comes back empty, never another
format's field borrowed in its place — the guide's `gaps` carries
`FORMAT_UNKNOWN_GAP` instead, and the Field card says "No tournament format
is known for this deck, so there is no tournament field to show." The
corpus's latest event date is that format's own too.

Share now vs. before the reset, with the **denominator always every
classified deck in the window, not the displayed top-N** — the hand-written
guide's other real bug, dividing by a truncated list inflated every share
by about six points. The player's personal rate per opponent archetype
carries `structural_change`'s `carryable` flag through, so a `"changed"` or
`"gone"` archetype's pre-reset rate renders as void rather than a stale
number that looks current.

**The field**, the Guide's reading of this (`components/guide/FieldCard.tsx`),
draws up to three tiles above the table (the deck's own archetype's win
rate in the field, the most played archetype, and, only once a reset was
found, how many of the shown archetypes changed at it), then a table of
every archetype's share, most played first. Its `Before` column is drawn
only when a row carries a pre-reset share. A row whose personal record
`structural_change` voids (`"changed"` or `"gone"`) shows the record
muted, with the caption "Your record does not carry over."

### `plans.py` — validate a sideboard plan against the real 75

It checks balanced IN/OUT counts, nothing boarded in beyond what the
sideboard holds, nothing boarded out beyond what the maindeck holds, every
sideboard card used by at least one plan. Operates on structured data
(`narrative.py`'s response shape), not regex over prose, so a plan the model
gets wrong is caught and surfaced next to that matchup — never silently
repaired.

### `bundle.py` — assembly

`build_deck_guide(conn, key)` pulls every module above into one `DeckGuide`,
under the deck's format (`identity_format`, above); it takes no format of
its own. The window defaults to the day after the most recent detected
reset in that format (or the whole corpus when none is found); **personal
matches are never dropped by that window** — every game played with the
deck counts, and `Provenance.matches_before_reset` states how many predate
it. A deck with no format gets no reset, no list diff and an empty field,
and `FORMAT_UNKNOWN_GAP` in `gaps` says why; its play evidence and leaks
are still built.

Leaks are computed **twice**: deck-scoped (`leaks`) and across the whole
history (`leaks_all_decks`), both carried side by side. A deck with a few
dozen matches cannot clear `review.leaks.MIN_SAMPLE` (10, on both sides of a
comparison) for many splits; the all-decks column gives a thin sample
context without the two ever being confused for one another. Both measure
each match against its own format's consensus window (one
`consensus_window_resolver`, seeded with the deck's format's window), since
the all-decks history spans every format. This is also
why the per-match postmortem was left exactly where it was
(`MatchReportPanel` on the match drill-down, `docs/review.md`) rather than
folded in here — it is the evidence behind any single match a leak cites.

`gaps` states what could not be computed and why, in place of guessing:
a deck with no format, an unclassifiable deck, missing oracle text (with the
exact fix — `sensei-top cards --scryfall`), no detected reset — or,
distinctly, no legality data to detect one *with* — and a never-played deck.

**Performance note.** Two real inefficiencies were found and fixed while
building this: `archetypes.classify._card_colors_by_name` — a full scan of
`cards` — used to run twice per match report (once via `rank_candidates`,
once via `_classify_own_deck`); `build_snapshot`/`build_match_report`/
`find_leaks` now accept an optional `colors_cache`/`consensus_cache` pair
that `bundle.py` shares across its two `find_leaks` calls, so the scan
happens at most once per request rather than once per match. The same three
functions later gained a `view_cache` (memoizing four of `build_snapshot`'s
own statements that otherwise rescanned a whole view per match) and
`find_leaks` gained a `report_cache` (reusing a whole `MatchReport` built
under a repeated match_id instead of rebuilding it); `bundle.py` shares one
of each across its two `find_leaks` calls the same way it shares the first
pair. `window.py`'s
`format_resets` used to scan the whole corpus once per banned card
(Scryfall's bulk export carries every card ever banned in Standard's
history, not just this format's own bans); it is now one pass over the
corpus, checking each deck's cards against the banned set instead. Together
these took a real ~536-deck, ~80-match corpus from ~34s to ~10s per guide
build — still the single most expensive route in this API, acceptable for
a click-triggered, non-heartbeat page rather than something polled.

### `narrative.py` — the prompt, and the shape of the answer

**No call is made from here** — only `sensei_top.llm.client` imports
`anthropic` (AGENTS.md non-negotiable #5, `docs/llm.md`). `build_guide_context`
assembles the evidence, `full_prompt` wraps it with the framing and the
answer schema, and `guide_narrative_from_json` reads a written answer back —
the one parser both round trips converge on:

- **Opt-in, one click.** With a Claude credential configured, `POST
  /api/guide/{key}/narrative` sends the prompt via `llm.write_json` against
  `_GUIDE_TOOL`'s own schema (made strict by `llm.strict_schema`) and parses
  the structured answer straight through `guide_narrative_from_json`.
- **No credential, the same round trip, now ending in the dashboard.**
  The Guide page's prompt → an assistant → its answer pasted into the
  card and saved (`PUT /api/guide/{key}/narrative`), or from a terminal
  `guide --deck KEY --prompt` → `guide --deck KEY --import FILE`. Both
  read the answer through `answers.py::read_answer`, which checks its
  `for: guide:{key}` line and unwraps its `answer` object, before
  `guide_narrative_from_json`. The stored `list_hash` is the answer's
  `context`, the hash of the 75 the prompt was built from, so a guide
  answered for an older list reads as out of date.

Either way the result stores the deck-level half in `deck_narrative`
(`guide/authored.py`) and every matchup plan in `matchup_brief`, so one
write also fills the Live page. See `docs/brief.md`.

**What the prompt carries** (`build_guide_context`): the whole evidence bundle
rendered as the same Markdown tables `guide/markdown.py`'s export uses (so
whoever writes it is never asked to re-derive a number the reader can
already see),
the player's current 75 with oracle text, opponent-archetype sections with
their consensus staples and oracle text (see below for which archetypes get
a section), the detected reset and what it voided, and the bundle's own
gaps. This is a large prompt, comparable to the evidence file the
hand-written guide this replaces was built from.

**Which archetypes get a section, and why it's not just "top 6 by
share."** The field's top `TOP_ARCHETYPES_FOR_ORACLE_TEXT` (6) archetypes by
share are the ones a tournament faces — but the ones this specific deck
actually meets on the ladder are often a different list. `build_guide_context`
adds up to `MOST_FACED_ARCHETYPES` (5) more: any archetype not already
covered by the top-6 pass, faced at least `MIN_TIMES_FACED` (3) times since
the guide's own reset window opened (`guide.field.faced_archetypes`, the
same "faced" definition `brief/coverage.py`'s own faced counts delegate to,
so the guide's most-faced list and brief coverage never disagree about what
counts as a match against an archetype), sorted by times-faced descending.
Every added archetype also gets its own `matchup_brief` written
(`brief/from_guide.py` stores one per plan), so this is also what widens
which matchups the Live page's break card already has a plan for —
see `docs/brief.md`. Oracle text is de-duplicated globally across every
section, including the player's own 75: a staple that recurs across
archetypes (or that the player already runs) is described once, the first
time it appears, never repeated.

Measured on the real corpus, comparing before this widening to after: the
Spellementals prompt grew from 11.3k to 14.3k tokens (6 sections to 11: it
picked up Azorius Momo, Boros Dragons, Reanimator, Azorius Flash and
Mono-Red Aggro from the ladder), Boros Dragons stayed effectively flat at
11.0k (one section added, Jund Aggro), and Fling *shrank*, 10.2k to 9.7k —
oracle de-duplication saved more than its added sections cost.
The written answer grows correspondingly — up to 11 matchup plans instead
of 6.

**Resolving an archetype's display name back to its corpus key is a
majority vote, not `SELECT DISTINCT`.** `guide.field.archetype_key_by_name`
is the one name→key lookup this prompt and `brief/from_guide.py` both use,
so a plan named in one is filed under the same key by the other. A display
name is not unique to a key — the corpus files 290 "Dimir Midrange" decks
under `UBMidrange` and 2 under `BxMidrange` — and the function it replaced (`SELECT DISTINCT`, last row wins)
resolved "Dimir Midrange" (13.2% of the field on the real corpus) to a key
with only 2 decks behind it and no consensus, silently dropping the field's
#3 archetype from every guide prompt; a written plan for it would also have
been filed under the wrong key. `archetype_key_by_name` instead maps each
name to whichever key has the most corpus decks behind it, ties broken by
key.

**What comes back**: a structured JSON object, not free prose —
`GuideNarrative`. `_GUIDE_TOOL`'s schema is the contract for both the
generate route's structured-output request (`llm.strict_schema`, then
`llm.write_json`) and a pasted or imported answer; it travels inside the
prompt so whoever writes the answer knows the exact shape. A structured
shape is what lets `plans.validate_plans` check every sideboard plan before it is ever shown, and lets the frontend
render each section with the same components as the deterministic evidence
around it, rather than a Markdown-rendering dependency.

### `markdown.py` — the exported document

`render(guide, narrative=None)` — one renderer, used by the markdown route,
`guide --markdown`, and the guide and RCQ prompts (`narrative.py`, `rcq.py`;
`narrative=None`, the evidence-only form).
Section order follows the hand-written guide this replaces: Scope → How it
works → Your play (curves, then the leak finder and its fix, deck-scoped
beside all-decks) → The list → The field → Matchups → Between rounds.

## API surface

Every route here is `GET` except two `POST`s and four `PUT`s, all writing
authored artifacts only. The `POST`s — `POST /api/guide/{key}/narrative`
and the RCQ guide's `POST /api/guide/{key}/rcq/narrative` (below) — call
out only when a Claude credential is configured (`docs/llm.md`). The `PUT`s
store a pasted answer with no model call: the guide's narrative, one brief,
the multi-brief coverage answer, and the RCQ guide's
`PUT /api/guide/{key}/rcq/narrative` (below). Between them they write only
`deck_narrative` plus `matchup_brief` (the RCQ ones write
`rcq_guide`), all on the
authored-artifact allowlist `AGENTS.md` non-negotiable #6 now states;
`tests/test_api.py::test_only_authored_artifact_routes_write` asserts the
exact set of writing routes.

| Route | Returns |
|---|---|
| `GET /api/guide/decks` | every deck with recorded matches, last played first |
| `GET /api/guide/{key}` | the whole evidence bundle |
| `GET /api/guide/{key}/narrative` | the stored narrative, and always the prompt to (re)write it from |
| `POST /api/guide/{key}/narrative` | writes the narrative with Claude and stores it (503 with no credential configured) |
| `PUT /api/guide/{key}/narrative` | stores a pasted narrative, and the briefs it covers, with no model call |
| `GET /api/guide/{key}/markdown` | the evidence-only exported document |
| `GET /api/guide/{key}/briefs` | every matchup brief cached for this deck |
| `PUT /api/guide/{key}/briefs/{archetype_key}` | stores one pasted brief, with no model call |
| `GET /api/guide/{key}/coverage` | how much of the field this deck's cached briefs cover (`brief/coverage.py`'s `Coverage`) |
| `PUT /api/guide/{key}/coverage` | stores every brief in a pasted multi-brief answer, with no model call |
| `GET /api/guide/{key}/briefs/{archetype_key}/prompt` | the single-brief prompt for one archetype, fetched on demand |
| `GET /api/guide/{key}/coverage/prompt` | the multi-brief prompt for every `missing`/`stale` coverage row |

`GET /api/review/leaks` gained an optional `?deck_id=` rather than being
retired — `guide_narrative`'s deck-scoped leak section and the pre-existing
all-decks route now share one implementation (`review.leaks.find_leaks`),
never two.

**A deck's pages are chosen by their address, not a picker.** The
layout a deck's Overview, Matchups and Guide share resolves `:id`
against `GET /api/guide/decks`'s rows, by key or by one of the
identity's `deck_ids` (`docs/frontend.md`, "A deck's pages").
`DeckGuidePage` hands the resolved key to `GuideView`; to read another
deck's guide is to follow a link to that deck's address.

**The Guide's `MatchupCoverageCard`** draws `GET /api/guide/{key}/coverage`
as three stat tiles (`coverageTiles`, `lib/brief.ts`: Matches covered,
Field covered, To write, the last also saying how many more have too few
tournament lists to write from); then, when any row is `missing` or
`stale`, a **Write every missing brief** button that shows the
multi-brief prompt in place (`/coverage/prompt`, fetched only when
pressed); then a row per archetype: its name a link to that
archetype's pairing (`/decks/:id/matchups/archetype:<key>`), its status
a word on a neutral chip (`coverageStatusWord`: Written, Out of date,
Not written, Too few lists), and its share of the field. A row offers no
prompt of its own: one archetype's prompt is on its pairing's page
(`docs/brief.md`, "The brief on a pairing's page").

## The RCQ guide

`/decks/:id/rcq`, the "RCQ" tab beside "Guide" on a deck's page, writes one
document for one event: the exact 75 the player is about to register,
against the field of that week. It is its own tab, not a section of the
Guide, because the Guide's sections are the deck's evidence and this is a
single event's plan. Its address in 1.0.x, `/decks/:id/guide/rcq`, still
opens it. Code: `guide/rcq.py` (evidence and
prompt), `guide/decklist.py` (the parser), `guide/rcq_authored.py`
(storage), `guide/rcq_markdown.py` (the export), `api/routes/rcq.py`.

- **The pasted 75.** `decklist.parse_decklist` reads an Arena export
  (`Deck` / `Sideboard` / `Companion` headers) or plain `N Name` lines into a
  main and a sideboard `Counter`, with warnings and unresolved names. The
  page prefills the identity's current list, editable. The pasted 75
  replaces the identity's list only for the list diff, plan validation and
  oracle text; the deck's match history is still every match played with
  the identity, never cut by the reset window.
- **The format is the deck's.** Everything below — the classification, the
  shares, the events and the chips — is the deck identity's format
  (`guide.field.fmt`, "A deck's format" above), which the preview returns
  as `RcqPreviewOut.format`. With no format the 75 is not classified
  ("archetype definitions are kept per format", the prompt says), the
  chips are not drawn, stored picks are dropped from the preview, and the
  preview says "No tournament format is known for this deck, so there is
  no tournament field to show." in place of the field.
- **Classifying it.** The pasted list goes down the corpus path as a
  complete decklist (`docs/metagame.md`). When nothing classifies it the page
  offers a picker of corpus archetypes (`own=`); a list is never guessed
  into an archetype.
- **Expected archetypes are a nudge, not a fact.** The user picks corpus
  archetype keys (`/api/metagame/presence?format=`, the deck's format, the
  last 14 days), not free
  text, which shares no vocabulary with the corpus. A chip's share is the
  sum of its key's labels at the tier with the most decks (one key holds
  every colour pair of an archetype); a key at 2% or more (`MAIN_SHARE`) is
  shown up front, the rest behind "Other". Each pick always gets a prompt section with
  consensus and oracle text, even outside the top six, and the prompt says
  it is the player's prior about the store, not evidence about it.
- **Evidence windows.** Besides the guide's post-reset shares, the prompt
  carries shares over the last 14 days (`RECENT_SHARE_DAYS`) and every
  event of the last 7 days (`RECENT_EVENT_DAYS`): date, name, tier, players
  and the top eight archetypes where placements exist. Both windows are
  cut at the reset. The page shows each source's freshness
  (`docs/metagame.md`, "A third source: mtgo.com").
- **Round trip.** The same as the guide's. `GET …/rcq/preview` always
  returns the prompt, for the no-credential path.
  `POST …/rcq/narrative` (`{decklist, expected[], own?}`) calls Claude and
  stores the answer (503 with no credential, `docs/llm.md`).
  Or the answer to the copied prompt is pasted into the page's box
  (`PUT …/rcq/narrative`, the generate body plus `answer`): the server
  rebuilds the prompt from that body and checks the answer's
  `for: rcq:{key}` line. The RCQ prompt carries no `context` hash
  (`docs/status.md`).
  `sensei-top rcq --deck KEY --decklist FILE [--expect K1,K2] [--own K]
  --prompt` prints the prompt and makes no call; `--import FILE [--author
  NAME]` stores a written answer.
- **Storage.** `rcq_guide` (migration 057) keeps every row, like
  `coach_report`: each guide is written against one day's field and an
  older one stays readable. It holds the list as pasted, the expected keys,
  the prompt, the whole narrative with its plan problems, the newest corpus
  event date and the measured cost (`NULL` when the model is unpriced).
  `project()` never reads it.
- **Routes.** `GET …/rcq` returns the latest stored guide (`status:
  "none"` before one exists); `GET …/rcq/markdown` renders it for the
  user's phone, since the server is loopback only.

## CLI

`sensei-top guide` with no `--deck` lists deck keys; `sensei-top guide
--deck <key> [--markdown PATH]` prints (or writes) one guide, including any
narrative that has been generated or imported for it. `--prompt` prints the
text to write that narrative from; `--import FILE` stores it, as the Guide
page's box does with a pasted answer. A deck's Guide page does the same
round trip in one press, in its "Write the guide" section, when `sensei-top
config --set-key` has been run (`docs/llm.md`). This is what makes a one-off
script per deck redundant — regenerate any deck's guide the same way
instead.

## What this does not do

- It does not judge a mulligan. This is a post-game read over projected
  data, and the hand a player actually shipped — after bottoming cards
  under the London rule — is never in the log at any point
  (`migrations/009_drop_opening_hand.sql`), unlike the pre-decision offer
  `table/opening_hand.py` reads live for the Live page. The guide
  reports the kept-seven-vs-mulliganed record and nothing about any one
  decision, the same invariant `review/`'s own
  `test_the_report_never_judges_a_mulligan` enforces there.
- It does not blend tournament evidence tiers. Share and win rate stay
  scoped exactly as `docs/metagame.md` already requires; nothing in `guide/`
  reads `v_meta_winrate` or `v_meta_presence` directly, always through
  `build_consensus`/`structural_change`/`field.py`'s own queries, which
  carry the same tier discipline.
- It does not merge two cards on a guess. `oracle_id` canonicalisation
  requires a real shared identity from Scryfall's own data; anything short
  of that is a flagged `duplicate_warnings` entry, never a silent merge.
