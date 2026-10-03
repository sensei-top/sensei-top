# Metagame

`metagame/` adds one thing the rest of this project cannot supply on its
own: what the *format* looks like, not just this player's own results.
Arena publishes no event results at all — every Arena-derived metagame
figure anyone has ever seen comes from self-selected tracker uploads or an
aggregator that declines automated reads (see `docs/architecture.md`'s
"Metagame data" section for the two sites rejected on inspection). So this
package reads real tournament results instead: MTGO leagues and challenges,
and paper events reported through Melee.gg, via
[`fbettega/MTG_decklistcache`](https://github.com/fbettega/MTG_decklistcache)
— the maintained successor to the archived `Badaro/MTGODecklistCache`.

Read this when touching `metagame/`, or the personal/field matchup join in
`api/app.py` or `MatchupsView.tsx`.

## The evidence tiers

The cache mixes three event shapes under one JSON schema, and only some of
them are real matchup data. `metagame/tiers.py` tags every stored event at
ingest time — never at query time — and the letters are also the order in
which the dashboard, the brief and the match report reach for them:

| Tier | Event | Test | Licensed for |
|---|---|---|---|
| **A** — paper, 64+ players | Melee or TopDeck event | `Standings` has 64 or more rows | Meta share, win rate, matchups |
| **B** — MTGO challenge | MTGO event with standings | source is MTGO, `Standings` non-empty | Meta share, win rate; matchups are usable but small (a top-8 bracket is 3 rounds, 7 matches) |
| **C** — MTGO league | any event without standings | `Standings` empty — every deck's `Result` is literally `"5-0"` | **Presence only.** A league dump contains no losses anywhere in it — a win rate computed from one would be 100% by construction, not an approximation |
| **D** — paper, under 64 players | Melee or TopDeck event | `Standings` has 1–63 rows | Meta share, win rate, matchups |

The ranking is the user's call, made on 2026-09-29: a large paper event
first, then the online events, then the small paper ones. A 64-player swiss
is six or more rounds with a field wide enough to mean something; a
twelve-player store championship is not a better read on the format than an
MTGO challenge, even though its rounds are complete.

The tier is no longer decided from shape alone. Size cannot tell a small
paper swiss from a challenge, and MTGO publishes only a challenge's top 32
standings, so its real field size is not in the file at all. The source is
consulted for exactly one thing: whether an event with standings is MTGO
(B) or paper (A or D). Melee and TopDeck are both treated as paper; Melee
hosts a few online events that cannot be told apart, and at their sizes
they land in D anyway. An event without standings is C whatever its source —
the conservative tier for a file that carries no record to count.

C and D are ranked against the licence, on purpose. D has a real swiss
behind it and is licensed for win rates and matchups; C is presence only.
The ranking decides which tier is *shown first*; the licence decides what
a tier may *say*. This is enforced **structurally**, in the views
(`migrations/013_metagame_views.sql`, rewritten by
`047_meta_event_tier_rank.sql`): `v_meta_winrate`'s
`WHERE tier IN ('A', 'B', 'D')` means there is no SQL path from a Tier C
event to a win-rate number, ever.

Every event with standings used to be A or B and is now A, B or D, so any
reader that pools the tiers with standings — the win-rate card, consensus,
the guide and the coach — gives the same totals as before. Only a reader
that picks one tier changes:

- **The share of the field** (Field and Home) shows the first tier with
  lists in the window, A, then B, then C, then D.
- **One quoted matchup number** — the live brief's field record and the
  match report's — walks the tiers with rounds, A, then B, then D, and
  takes the first with at least five matches for the pairing
  (`metagame/matchup.py`), naming the tier it came from. With none that
  large it takes the highest-ranked tier that has any, so the "too few"
  gap still says how few.
- **The Field page's matchup table** counts paper 64+ alone, then adds
  MTGO challenges, then smaller paper, one step at a time, defaulting to
  the first step with lists.

Tier C's presence figures carry their own bias worth naming: a league
publishes only the decks that went undefeated, so its "share" is a share
of *winning* decks, not of decks played. `v_meta_presence` never blends
a Tier C count into another tier's share for exactly this reason: every
row is grouped by `(archetype_key, label, tier)`, and the API computes
`share` within one tier via a SQL window function, never across tiers.

Tier B carries a milder version of the same shape: challenge JSONs publish
only the top 32, so a Tier B win rate is conditioned on making that cut.
Real, but far less severe than Tier C's survivorship problem.

A presence or win-rate row's `colors` is the most common colour
combination among its lists, a tie going to the first in text order,
and null only when no list of the row has colours
(`api/routes/metagame.py`, the `color_rank` step). The largest string
would let a few lists outvote many: Jeskai Control's tier B lists in
one window read WUBR 66 times and WUR 9 times, and the largest string
is WUR.

## Complete decklists invert the classifier's own rule

`archetypes/classify.py`'s entire design rests on one asymmetry, stated in
its module docstring: **absence proves nothing.** Arena reveals perhaps
eight to fifteen of an opponent's cards, so an unmet requirement is
*unknown*, never a failure — that is what `MIN_ARCHETYPE_FIT`, `MIN_MARGIN`
and `colour_factor`'s belief ramp all exist to manage.

A cache decklist is **complete** — 60 cards plus a real sideboard. Running
the partial-information rules over it unchanged would give every archetype
partial credit for cards it never actually needed to prove, and the
confidence gates built to suppress a weak guess from a dozen cards would
suppress a fully-proved 60-card match just as hard. So `evaluate()`,
`choose()` and their helpers all take a `complete: bool` flag (default
`False`, so the personal-match path is untouched byte-for-byte):

- **An unmet positive requirement eliminates the definition outright**
  (`evaluate` returns `None`) instead of counting as `unknown`. Absence in a
  60-card list is real evidence a partial reveal never has.
- **`InSideboard`/`DoesNotContainSideboard` become real checks** against the
  decklist's actual `Sideboard[]`, via a `sideboard_seen` frozenset — under
  partial matching these are always vacuous or always unknown, because a
  live match never shows a sideboard at all.
- **`colour_factor` is skipped.** It exists to weigh a colour that hasn't
  shown up *yet* against one that was screwed; a complete list's colours are
  simply known, not inferred, so the factor is fixed at `1.0`.
- **`MIN_ARCHETYPE_FIT`/`MIN_FALLBACK_FIT`/`MIN_MARGIN` are skipped.**
  Those gates suppress a guess made from insufficient evidence. Once
  `evaluate` has already eliminated every definition that doesn't fully
  match, there is no such guess left to suppress — the top-ranked survivor
  is the answer.

One rule engine, one vocabulary: both `archetypes.classify_matches()` (a
live match, partial) and `metagame.classify_meta_decks()` (a corpus
decklist, complete) write the same `archetype_key`, the `Definition.key`
that is the file stem in `MTGOFormatData`. That shared key is what makes
`v_meta_winrate` and a personal `v_match_opponent` row joinable at all:
the dashboard's field numbers (`docs/frontend.md`, "Field, and the
field-winrate join") and `review/narrative.py`'s `FieldContext` both key
off `opponent_key`'s `'archetype:' + archetype_key` form, and both
refuse to join anything else. A manual label, a colours-only guess, or
`'unknown'` shares no vocabulary with the corpus, so there is nothing
honest to look up.

One key holds several labels ("Control" holds Jeskai Control and Sultai
Control), and the field's rows are one per key and label. The dashboard
joins them two ways. Field and Home count the viewer's record against a
row over the matches whose opponent carries both the key and the label.
A deck's Matchups page and a pairing's page group the viewer's matches
by key alone, so their field win rate is pooled over every label of the
key: the wins, losses, draws and lists added up, never one label's row
standing for the key.

## Fetching the corpus

`metagame/source.py` is windowed and incremental, unlike
`archetypes/source.py`'s one-shot tarball — the archetype definitions are
~350 KB; this corpus is ~157 MB of history this project mostly does not
need (`Topdeck` and `Manatrader` are both dead in this cache, stopped at
2025 and 2024 respectively; `CardsRealm` was never evaluated).

1. **One GitHub API call** resolves `main` to a commit SHA, then lists the
   whole repository's file tree at that pinned commit. Every file fetched
   in one refresh comes from the same snapshot, and the SHA is stored
   (`meta_fetch.commit_sha`) so any report can name exactly which snapshot
   it reasoned from — the whole reproducibility story in one column.
2. **`select_paths`** keeps only `Tournaments/{MTGO,MTGmelee}/...` inside the
   requested date window, pre-filtered on the filename containing
   "standard" before anything is downloaded. `parse_event` cross-checks the
   fetched file's own `Tournament.Formats` afterward, since a filename is a
   hint, not a guarantee.
3. **Each selected file** is fetched individually from
   `raw.githubusercontent.com`, but only if its blob SHA differs from what
   is already stored (`already_fetched`) — a second refresh over the same
   window re-fetches nothing that hasn't actually changed upstream.
4. **`MAX_FILES_PER_REFRESH`** is a hard ceiling, so a misconfigured window
   can never turn one refresh into thousands of requests.

Fail-soft, the same posture as `refresh_archetypes`: a GitHub failure
(`resolve_commit_sha`/`list_tree` raising) keeps whatever was fetched last
time and reports how old it is; a single unreadable or non-Standard file is
skipped and counted, never fatal to the rest of the refresh. `store_events`
never deletes by scope before inserting — unlike `archetypes.store_archetypes`,
which replaces a whole format — because a narrow, recent-window refresh must
not erase events an earlier, wider-windowed refresh already stored. Each
event replaces only its own rows, keyed on `event_id` (the file's own path,
already globally unique).

## Duplicate tournament events

The mirror sometimes publishes one tournament under two or three paths —
different `event_id`s and blob SHAs, but byte-identical decklists and
rounds. Nothing in `select_paths` or `store_events` catches this, since each
path looks like a distinct file; measured on the real database (2026-09,
371 events / 12,170 decks): 43 groups of identical events (35 pairs, 7
triples, 1 quadruple) — 52 surplus events and 1,338 surplus decks (11% of
the corpus). Left alone, every copy is stored and counted again, inflating
field share, field win rate, the consensus decklists and the matchup matrix
everywhere they are read.

`metagame/dedup.py::mark_duplicate_events` finds these groups by hashing
`format`, `tier`, every deck (ordered by `deck_ord`) and every round match
(ordered by `(round_name, deck_ord_a, deck_ord_b, wins_a, wins_b, draws)`)
for each event that has at least one deck. `name`, `event_date`, `source`
and `uri` are deliberately excluded from the key: the event name made no
measured difference to the grouping, a cross-source twin (the same
tournament mirrored under both an MTGO and an MTGmelee path) is still a
twin once the standings match, and — the one that actually matters — 10 of
the 43 real groups were Tier C leagues **republished under a later date
folder**, with a different `Tournament.Date` too. Including the date in the
key would let exactly those slip through undetected.

Each group's survivor is `min(event_id)` — the file path sorts by date
folder first, so this is always the group's earliest publication,
deterministic without needing to know which copy the source repository
considers canonical. Every other member is marked
(`meta_event.duplicate_of = <survivor>`, migration 043) and **loses** its
`meta_deck`, `meta_round_match` and `meta_deck_archetype` rows outright,
rather than having them filtered at query time — that is what lets every
reader that joins those tables (the presence/winrate/matchup views,
`review/consensus.py`, `archetypes/corpus.py`'s prior, `guide/window.py`'s
format-reset scan, and the guide/coach/brief field shares) stay correct
without learning about `duplicate_of` at all. A twin still *keeps* its own
`meta_event` row, though: `already_fetched()` reads `path -> blob_sha` from
that table, and a twin whose file hasn't changed upstream must not look
unfetched and get downloaded again. Only the handful of readers that query
`meta_event` alone — `metagame_status`'s tier counts, and the guide's and
coach's `MAX(event_date)` reads — filter `WHERE duplicate_of IS NULL`,
since a republished league's date can be later than its own survivor's.

`sensei-top meta` calls `mark_duplicate_events` once per invocation,
after any refresh and before `classify_meta_decks` — including the
`--reclassify` path, which is how an existing corpus gets cleaned with no
network at all. `store_events` keeps this self-correcting across refreshes:
re-storing an event resets its own `duplicate_of` to `NULL` (judged afresh),
and re-storing a survivor whose content changed clears its twins'
`blob_sha` so the next refresh re-fetches and re-judges them against the
new content, instead of leaving them stale behind a survivor that moved on
without them.

## Privacy

A cache decklist carries the real MTGO or Melee handle of a third party who
never consented to this project. AGENTS.md's privacy rule forbids storing
one. `parse_event` resolves every `Player` name to a per-event `deck_ord`
(the deck's position in that event's own `Decks[]` list) — round matches
reference decks the same way — and the name is simply gone after that: it
never reaches `ParsedEvent`, `store_events`, or SQLite. `test_metagame.py`'s
`test_parse_event_never_retains_a_player_name` asserts this by dumping the
parsed structures to JSON and checking the fixture's synthetic handles never
appear in it.

## A second source: TopDeck.gg

`metagame/source.py`'s corpus alone has a real gap for Standard specifically:
a live check of one August's corpus found MTGO contributing zero Standard
matchup data all month — every MTGO Standard event that month was a league
(Tier C, presence-only), and the fbettega cache's Melee subset for Standard
that same month held only two Tier A events (178 matches, 58 decks total;
tiers as they were before migration 047).
Standard is played in paper RCQs and Regional Championships, which run on
Melee and TopDeck — and TopDeck.gg's own Tournaments v2 API is a second,
independent way to reach that evidence, added as `metagame/topdeck.py`.

**Reuse, not a second pipeline.** `metagame/topdeck.py` does not reimplement
selection, parsing, storage, or tiering. It normalises a TopDeck tournament
response (`POST /v2/tournaments`, query mode — one call returns every
matching tournament's standings *and* round-by-round tables already, so
there is no separate per-event fetch) into the exact `CacheItem` shape
`parse_event` above already reads, then calls `parse_event` and
`store_events` unchanged. `classify_tier` is reused unchanged too: a TopDeck
RCQ earns Tier A or D by the same size test as a Melee event (64 or more
standings rows is A), never because of where it came from. `already_fetched`'s
incremental-refresh check works identically, keyed on a synthetic path
(`Tournaments/Topdeck/<TID>.json`, chosen to match the `Tournaments/<source>/…`
shape `parse_event` already parses `ParsedEvent.source` out of) and a
`sha256` of the fetched tournament object standing in for a blob SHA, since a
completed tournament has no git blob of its own to compare against.

**The privacy guarantee (see above) is inherited, not reimplemented.** A
TopDeck standings row and round table carry a real player name and account
id. Both are used purely as an in-memory join key — mapped into the same
`CacheItem["Decks"][i]["Player"]` field `parse_event` already resolves to a
`deck_ord` and discards — so nothing in `topdeck.py` has to re-earn the
"no third-party identifier reaches SQLite" guarantee; it falls out of reusing
`parse_event` unchanged. `tests/test_metagame_topdeck.py` pins this the same
way `test_parse_event_never_retains_a_player_name` does for the fbettega side.

**Credential, deliberately not the metered kind.** TopDeck's key is free and
rate-limited (~100 requests/minute), not billed — it exists for attribution
and abuse prevention, not cost. AGENTS.md non-negotiable #5 was narrowed to
say so explicitly: `llm/config.py` remains the only place a *metered*
credential is resolved, and TopDeck's key is resolved by its own sibling,
`metagame/config.py` (`TOPDECK_API_KEY` env var, or a `[topdeck]` table in
the same `~/.config/sensei-top/config.toml` the Claude credential lives
in, written by `sensei-top config --set-topdeck-key`). With no key
configured, `refresh_topdeck` returns `status="not_configured"` and makes no
network call at all — `sensei-top meta --source all` (the default) simply
skips it, the same way an unreachable host is skipped, never an error.

**Attribution is contractual, not a courtesy.** TopDeck's API terms
require a visible credit and link back to TopDeck.gg wherever the data
is shown. The Field page carries it as a caption on the page, outside
its closed "Where these numbers come from", drawn whenever the status
lists a TopDeck source: a key configured, or TopDeck fetched before.

**Per-source freshness**, not a second freshness column bolted onto
`meta_fetch`: `migrations/022_meta_source_fetch.sql` adds
`meta_fetch_source`, one row per source (`fbettega`, `topdeck`), which
`refresh_metagame` now writes to in addition to (never instead of)
`meta_fetch`'s own single-row reproducibility record. `cache_age_seconds`
gained a `source=` parameter: scoped, it reads one source's row; unscoped, it
returns the *oldest* (most stale) age across every source that has ever been
fetched, so the Field page's one freshness sentence can never hide a source
that hasn't refreshed in weeks behind one that just did.

This is unrelated to the scraper `fbettega/mtg_decklist_scrapper` mentioned
below under "What is not implemented" — that tool also needs a Topdeck token,
but to *regenerate the shared cache itself* from primary sources, which this
project still does not do and has no plan to. `metagame/topdeck.py` instead
queries TopDeck's own public tournament API directly, as an independent
additional corpus source alongside the published cache — the two have
nothing to do with each other beyond both eventually touching the word
"Topdeck".

**The base URL.** `API_BASE` is `https://topdeck.gg/api/v2`. The module
first pointed at `api.topdeck.gg`, which never resolved, so no TopDeck event
was ever stored before this was fixed; `tests/test_metagame_topdeck.py`
pins the URL, the POST method and the `Authorization` header.

## A third source: mtgo.com

`metagame/mtgo_site.py` reads MTGO's public result pages directly, because
the fbettega cache lags mtgo.com by about six days (`docs/attribution.md`
records the terms reading). Same reuse as TopDeck: it normalises a page
into the `CacheItem` shape and calls `parse_event` and `store_events`
unchanged, so tiering, dedup and the privacy guarantee are inherited.

- **Index to slugs.** `list_event_slugs` takes every
  `href="/decklist/<slug>"` on `https://www.mtgo.com/decklists` whose slug
  starts with `standard-`, de-duplicated, order kept. Other formats are not
  fetched.
- **The page's data script.** `extract_data` reads the JSON after
  `window.MTGO.decklists.data =` in the page; it returns `None` when that is
  absent, never raising. A format other than `CSTANDARD` skips the event.
- **Normalisation to fbettega's shape.** `normalize` writes `Tournament`
  (date, name, URI), `Decks` (cards summed per name across a player's
  several `docid`s, placement wording as fbettega writes it, a league's
  `5-0` record), `Standings` (standings joined to win/loss records) and
  `Rounds` (the bracket's 4/2/1 matches as quarterfinals, semifinals and
  finals). `tests/test_metagame_mtgo_site.py` pins that
  `parse_event(normalize(page))` equals `parse_event` of fbettega's file for
  the same event.
- **Same path as fbettega's.** `Tournaments/MTGO/YYYY/MM/DD/<site_name>.json`,
  with a `sha256` of the normalised object as the blob SHA. When fbettega
  later publishes the same event its blob SHA differs, `already_fetched`
  sees a change, and `store_events` replaces this copy by `event_id`: the
  same event is never counted twice.
- **What is re-fetched.** A slug whose path is already in `meta_event` is
  skipped, except an event dated today or yesterday (UTC), because leagues
  republish through the day.
- **Pacing and failure.** One second between page fetches, a 90 s timeout,
  at most 40 pages, and the User-Agent `sensei-top/0.1 (+local analytics;
  results pages only)`. The index failing returns `status="failed"` and
  keeps the cache; a page failing counts as `skipped`. The refresh is
  fresh for three hours (`MAX_AGE_SECONDS`) unless forced, and writes a
  `meta_fetch_source` row `('mtgo', …)`.
- **Privacy.** Player handles and login ids are join keys in memory only,
  as for TopDeck; no handle reaches SQLite
  (`test_mtgo_site_never_retains_a_player_name`).
- **CLI.** `sensei-top meta --source {cache,topdeck,mtgo,all}`; `all`
  (the default) runs cache, then mtgo, then topdeck, then the existing
  dedup and classify steps. One line is printed per source.

Refresh is manual: `serve --watch` does not refresh the corpus.

## A trap: `Decks[].Result` is not a score

Verified against the live cache on 2026-08-18, not assumed: for events with
`Standings` (now Tier A, B and D), every deck's `Result` field is a
bare placement string — `"1st Place"`, `"2nd Place"`, ... — never a
win-loss record. Only Tier C (leagues, which never publish `Standings` at
all) uses the `"N-M"` form. An early version of `parse_event` read `Result`
as each deck's match record for every tier, which degraded silently to
`(0, 0, 0)` for every deck with standings (`_parse_record` correctly refuses
to parse a non-numeric string, but nothing downstream noticed every real deck
had gone quiet) — the corpus stored real events and classified them
correctly, but every field-winrate number was a flat `0%`, and running `meta`
against a scratch database and reading the actual response was what
surfaced it, not the fixture-backed unit tests, whose synthetic `ParsedDeck`
records never round-tripped a placement string in the first place.

The real per-deck match record lives in `Standings[].Wins`/`Losses`/`Draws`
— structured integers, not a string to parse — wherever a `Standings` block
exists (Tier A, B and D, by the tier definition above). `_standings_records`
resolves each `Standings` row's `Player` to the same `deck_ord` the round
matches already use, and `parse_event` prefers it over `_parse_record(Result)`
for every deck it covers; a deck with no `Standings` entry (or an event with
no `Standings` at all — Tier C) still falls back to parsing `Result`
directly, which is exactly where that format is genuine. `GET
/api/metagame/winrate` sums `wins`/`losses`/`draws` across every entry of an
archetype rather than treating one deck as one match, since a `Standings`
record already spans a whole event's rounds.

## Classifying the corpus

`meta --reclassify` (or the `meta` subcommand's default path, after a
refresh) runs `classify_meta_decks()`: a full rebuild over every stored
`meta_deck`, exactly like `classify_matches()` for personal matches, and for
the same reason — a corpus refresh may replace a decklist's own row, so a
kept classification could point at a deck that no longer exists. It never
touches the network, so it is safe to re-run immediately after
`sensei-top archetypes` picks up a new definition, without waiting on
another corpus fetch.

## The format-reset boundary

Nothing in `metagame/` itself knows about bans — this corpus is presence and
results, not a banlist. `guide/window.py` detects one instead of requiring
it be declared: a card's `cards.standard_legality = 'banned'`
(`migrations/017_card_legality.sql`, from the same Scryfall bulk rows
`cards.py` already fetches) says it is banned; the last `meta_event.
event_date` on which it still appeared in enough decks to be real evidence
says when. Pooling data across an undetected reset is a real, sharp
failure mode — the hand-written guide `guide/` replaced did exactly that
once, and its "top two decks" turned out not to exist post-reset.

`guide/window.py::structural_change` is what decides whether a *pre-reset*
matchup rate may be carried forward at all: an archetype whose pre-reset
lists relied on a banned card is a different deck now, and its old rate
must render as void, not merely stale. See `docs/guide.md` for the full
mechanism and `docs/guide.md`'s own note on the corpus scan this requires
(one pass, not one per banned card — Scryfall's bulk export carries every
card ever banned in Standard's history, most of them irrelevant to any one
corpus snapshot).

### Every field number that can pool across the boundary, doesn't

Detecting a reset is only half the rule — every route and query that turns
`v_meta_matchup`/`v_meta_winrate` into a number the user reads has to stop at
the boundary too, or the detection buys nothing. `v_meta_matchup`
(`migrations/044_meta_matchup_date_grain.sql`) carries `event_date` through
both halves of its `sides` CTE and its outer `GROUP BY` specifically so every
consumer downstream can add an `event_date >= ?` cutoff without a second join
back to `meta_event`. `api/sql.py::_consensus_window(conn)` is the one place
that turns "the latest detected reset" into that cutoff date — every route
below calls it rather than re-running `guide/window.py::format_resets` itself:

- `GET /api/metagame/presence`, `/winrate`, and `/matchups` each take an
  optional `since` query param that wins over the existing `days` cutoff when
  both are given (`api/routes/metagame.py::_since_cutoff`); `matchups` also
  now takes its own `days`, previously fixed at a fixed lookback with no
  override. `GET /api/metagame/status` reports `format_reset_start` — `null`
  when no reset has been detected, else the same date `_consensus_window`
  would use — so the frontend can offer a "Since last reset" option without
  running the detection itself.
- The Field page's window (`?window=`) defaults to "Since the last
  reset" whenever `format_reset_start` is set, and governs the share,
  the win rate and the matchups together; with no reset it falls back
  to the last 90 days. A deck's Matchups page and a pairing's page
  window their field win rate the same way with no control of their
  own: the reset window when one exists, else a fixed 365 days.
- `review/snapshot.py::build_snapshot`'s `field_matchup` (surfaced by
  `review/analyzers/baseline.py` in the match report) and
  `brief/narrative.py`'s "Field record for this pairing" line both
  window to `_consensus_window(conn)` rather than reading the whole corpus —
  see `docs/review.md` and `docs/brief.md`. `api/routes/matches.py::
  _field_context` (the match-report narrative prompt's field section) and
  both `review/leaks.py::find_leaks` call sites in `api/routes/review.py`
  (the leak finder and its narrative prompt) window the same way.

A pre-reset round is never silently dropped and forgotten, either: when a
windowed query has nothing on or after the cutoff, the caller gets `None`/no
rows rather than the query falling back to the unwindowed number — the same
"gap, don't guess" rule non-negotiable #4 states everywhere else. A field
record that predates the reset is not evidence for the archetype as it
exists today; it is evidence for a deck that no longer exists.

## A third consumer: naming a live match from card presence

`review/consensus.py` already turns this corpus into "what does a typical
list for this archetype look like"; `archetypes/corpus.py` asks a different,
narrower question of the same data — "given the cards one opponent has
revealed so far, which archetype's corpus decks look most like that" — as a
second, complementary evidence source for `classify.py`'s deck-naming
pipeline (`docs/architecture.md`'s "A second evidence source: the corpus's
own decklists" has the full mechanism and the naive-Bayes formula).

The ban-handling here is deliberately not the format-reset window described
above. Windowing to post-reset dates alone leaves too few decks to score
against (measured: 655 decks / 14 archetypes, 82% precision on the truth
set this feature was calibrated against) — a card-to-archetype *association*
is not a win rate or a share, so the "never window `meta_*` across a ban"
rule that protects those does not forbid using pre-reset decks here. Instead,
`archetypes/corpus.py::build_prior` drops the banned cards themselves from
every count and excludes any archetype `guide/window.py::structural_change`
marks `"gone"`, keeping every deck the reset didn't invalidate. Measured: 90%
precision on 6,773 decks, better than either the windowed corpus or the
unfiltered one (88%) — a banned card simply never appears in a live match, so
there is nothing to gain from discarding the deck around it too.

## What is not implemented

`fbettega/mtg_decklist_scrapper` — the tool that *generates* the cache — is
documented as an emergency fallback only, not wired in. It requires a
Topdeck API token and a Melee.gg account email/password on disk
(`Api_token_and_login/`); the Melee path is a credentialed scrape against
that site's own terms, which has nothing to do with minimizing egress —
it's a different kind of line, a site's stated terms rather than AGENTS.md
rule 5's fail-soft/inspectable standard. Consuming the published cache, as
this project does, requires none of that. If the cache ever goes stale for
an extended period, that scraper is the documented escape hatch — building
it would still need to meet rule 5's standard on its own outbound calls, the
same way `metagame/` itself did.
