# Metagame

`metagame/` adds one thing the rest of this project cannot supply on its
own: what the *format* looks like, not just this player's own results.
Arena publishes no event results at all — every Arena-derived metagame
figure anyone has ever seen comes from self-selected tracker uploads or an
aggregator that declines automated reads (see `docs/review.md`'s
"Metagame data: real tournament results, not Arena aggregators" section for
the two sites rejected on inspection). So this package reads real tournament
results instead: MTGO leagues and challenges, and paper events reported
through Melee.gg, via
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

A reader that pools tiers gives the same totals whatever their order: the
win-rate card pools the three tiers with standings (A, B and D), and
consensus and the guide's and coach's field shares pool all four
(`review/consensus.py`, `guide/field.py`). Only a reader that picks one tier
depends on the order:

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
the dashboard's field numbers (`docs/frontend-pages.md`, "Field, and the
field-winrate join") and `review/narrative.py`'s `FieldContext` both key
off `opponent_key`'s `'archetype:' + archetype_key` form, and both
refuse to join anything else. A manual label, a colours-only guess, or
`'unknown'` shares no vocabulary with the corpus, so there is nothing
honest to look up.

One key holds several labels ("Control" holds Jeskai Control and Sultai
Control), and the field's rows are one per key and label. The dashboard
joins them two ways. Field and Home count the viewer's record against a
row over the matches whose opponent carries both the key and the label,
from the selected format's matches only (`lib/field.ts::ownCounts`,
`matchesInFormat`; a match with no format counts toward none).
A deck's Matchups page and a pairing's page group the viewer's matches
by key alone, so their field win rate is pooled over every label of the
key: the wins, losses, draws and lists added up, never one label's row
standing for the key. That field is the deck's own format's (the
coverage answer's `fmt`); a deck with none asks for no field.

## Fetching the corpus

`metagame/source.py` is windowed and incremental, unlike
`archetypes/source.py`'s one-shot tarball — the archetype definitions are
~350 KB; this corpus is ~157 MB of history this project mostly does not
need (`Topdeck` and `Manatrader` are both dead in this cache, stopped at
2025 and 2024 respectively; `CardsRealm` was never evaluated).

1. **Two GitHub API calls** resolve `main` to a commit SHA, then list the
   whole repository's file tree at that pinned commit. Every file fetched
   in one refresh comes from the same snapshot, and the SHA is stored
   (`meta_fetch.commit_sha`) so any report can name exactly which snapshot
   it reasoned from — the whole reproducibility story in one column.
2. **`select_paths`** keeps only `Tournaments/{MTGO,MTGmelee}/...` inside the
   requested date window, pre-filtered on the filename carrying one of the
   fetched formats as a whole token before anything is downloaded
   (`premodern-league-…` carries `premodern`, never `modern`).
   `parse_event` cross-checks the fetched file's own `Tournament.Formats`
   afterward, since a filename is a hint, not a guarantee.
3. **Each selected file** is fetched individually from
   `raw.githubusercontent.com`, but only if its blob SHA differs from what
   is already stored (`already_fetched`) — a second refresh over the same
   window re-fetches nothing that hasn't actually changed upstream.
4. **`MAX_FILES_PER_REFRESH`** is a hard ceiling, so a misconfigured window
   can never turn one refresh into thousands of requests.

Fail-soft, the same posture as `refresh_archetypes`: a GitHub failure
(`resolve_commit_sha`/`list_tree` raising) keeps whatever was fetched last
time and reports how old it is; a single unreadable file, or one in none of
the fetched formats, is skipped and counted, never fatal to the rest of the
refresh. `store_events` never deletes by scope before inserting — unlike
`archetypes.store_archetypes`, which replaces a whole format — because a
narrow, recent-window refresh must not erase events an earlier,
wider-windowed refresh already stored. Each event replaces only its own
rows, keyed on `event_id` (the file's own path, already globally unique).

**The refresh runs on its own while `serve` runs**,
with or without `--watch`, unless `--no-corpus-refresh` is given. A thread
of its own, "corpus-refresh" (`cli.py::_start_corpus_refresh`), ticks every
five minutes, the first time at startup, and each tick calls
`metagame/auto.py::refresh_corpus`: fbettega's cache, then mtgo.com, then
TopDeck, each through its own `refresh_*` function. A tick asks; each
source's freshness rule decides, so a tick with nothing due sends no
request. The cadences are those functions' `MAX_AGE_SECONDS`: fbettega every
24 h, mtgo.com every 3 h, and TopDeck every 24 h, only with a key
configured. The loop never forces a run and never shortens a hold ("A third
source: mtgo.com" below): a paused source stays paused until `sensei-top
meta` is run by hand. A run that was attempted and did not complete — a
refusal, a 429, a 503, a timeout, no connection, GitHub unreachable, an
exception — leaves that source alone for an hour. The hour is kept in
memory, so a restart forgets it, while a stored not-before outlives the
restart. One source's failure never stops the others in the same tick. A
tick that stored events then runs `reclassify_corpus` (dedup, then
`classify_meta_decks`), and a reclassification that fails is owed until a
later tick's succeeds. `serve` prints a line only when its own attempt moved
a hold. Every other run that was attempted is logged as a warning
(`cli.py::_log_corpus_result`), which the log file beside the database
always takes, and the console only under `sensei-top --verbose serve`.

**Which formats a refresh fetches**:
`metagame/auto.py::followed_formats`. Standard and Modern always
(`metagame/source.py::FETCH_FORMATS`), plus every format of
`formats.FORMATS` the stored corpus already holds an event in, so a
format fetched once is followed from then on, by the loop and by
`sensei-top meta` alike. `sensei-top meta --format X` (repeatable, any of
the seven in `formats.FORMATS`, refused otherwise) adds one to that run,
and once its events are stored the loop follows it too. Nothing reads the
user's own matches to widen the list: a Pauper player fetches Pauper by
asking for it once. Nothing unfollows a format either; it stays followed
while the corpus holds an event in it. `--format` implies `--force`,
because the freshness window is kept per source, not per format, and a
format the stored corpus has never held must not be skipped as "fresh";
unchanged files are still skipped by their blob SHA. All three sources
follow the same list.

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

Each group's survivor is `min(event_id)` — the file path sorts by source
folder, then date: within one source the survivor is the group's earliest
publication, and across sources it is the copy whose source folder sorts
first. Either way it is deterministic, without needing to know which copy
the source repository considers canonical. Every other member is marked
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
TopDeck standings row and round table carry a real player name, and a round
table an account id too. Only the name is read, purely as an in-memory join
key — mapped into the same
`CacheItem["Decks"][i]["Player"]` field `parse_event` already resolves to a
`deck_ord` and discards — so nothing in `topdeck.py` has to re-earn the
"no third-party identifier reaches SQLite" guarantee; it falls out of reusing
`parse_event` unchanged. `tests/test_metagame_topdeck.py` pins this the same
way `test_parse_event_never_retains_a_player_name` does for the fbettega side.

**Credential, deliberately not the metered kind.** TopDeck's key is free and
rate-limited (~100 requests/minute), not billed — it exists for attribution
and abuse prevention, not cost. AGENTS.md non-negotiable #5 says so
explicitly: `llm/config.py` is the only place a *metered*
credential is resolved, and TopDeck's key is resolved by its own sibling,
`metagame/config.py` (`TOPDECK_API_KEY` env var, else the system keyring
(service `sensei-top`), else a `[topdeck]` table in the same
`~/.config/sensei-top/config.toml` the Claude credential lives in;
`sensei-top config --set-topdeck-key` writes the keyring where one exists,
else the file). With no key
configured, `refresh_topdeck` returns `status="not_configured"` and makes no
network call at all — `sensei-top meta --source all` (the default) simply
skips it, the same way an unreachable host is skipped, never an error.

**Attribution is contractual, not a courtesy.** TopDeck's API terms
require a visible credit and link back to TopDeck.gg wherever the data
is shown. The Field page carries it as a caption on the page, outside
its closed "Where these numbers come from" ("<format> tournament data from
TopDeck.gg."), drawn only when the selected format's corpus holds a TopDeck
event: `GET /api/metagame/status?format=`'s `corpus_topdeck_events`, which
counts that format's non-duplicate `Topdeck` events, is above zero. A key
configured, or TopDeck fetched for another format, draws no credit on a
format whose numbers carry none of TopDeck's data; the disclosure's sources
table still lists the TopDeck source either way.
Each TopDeck event's own page carries the credit too, "Data provided by
TopDeck.gg.", linked, with a second line linking the event on TopDeck.gg
(`web/src/lib/fieldEvent.ts::sourceLines`).

**Per-source freshness**, not a second freshness column bolted onto
`meta_fetch`: `migrations/022_meta_source_fetch.sql` adds
`meta_fetch_source`, one row per source (`fbettega`, `topdeck`, and `mtgo`
since mtgo.com became a source), which `refresh_metagame` writes to in
addition to (never instead of) `meta_fetch`'s own single-row reproducibility
record. `cache_age_seconds` takes a `source=` parameter: scoped, it reads
one source's row; unscoped, it returns the *oldest* (most stale) age across
every source that has ever been fetched, so the Field page's one freshness
sentence can never hide a source that hasn't refreshed in weeks behind one
that just did.

This is unrelated to the scraper `fbettega/mtg_decklist_scrapper` mentioned
below under "What is not implemented" — that tool also needs a Topdeck token,
but to *regenerate the shared cache itself* from primary sources, which this
project still does not do and has no plan to. `metagame/topdeck.py` instead
queries TopDeck's own public tournament API directly, as an independent
additional corpus source alongside the published cache — the two have
nothing to do with each other beyond both eventually touching the word
"Topdeck".

**The base URL.** `API_BASE` is `https://topdeck.gg/api/v2`.
`api.topdeck.gg` does not resolve, and a base there stores no TopDeck event
at all; `tests/test_metagame_topdeck.py` pins the URL, the POST method and
the `Authorization` header.

**Only constructed events.** TopDeck's own format field is not trusted: it
labelled Commander, draft and prerelease events Standard. `_NOT_CONSTRUCTED_RE`
in `topdeck.py` matches commander, edh, draft, sealed, cube, jumpstart and
pre-release spellings in the event name (leading word boundary only, so it
can over-match). A matching event is skipped on fetch with a warning, and
already-stored matching Topdeck events are purged with their child rows
after each refresh.

**One query per format, through the hold.** `refresh_topdeck` sends one
tournament query for each followed format ("Fetching the corpus" above),
with the one key, `FORMAT_SPACING_S` (15 s) apart, every 24 h. It passes
the source's hold first (`metagame/holds.py::gate`), the same gate
mtgo.com's run passes, with TopDeck's own transitions. A 401, 403 or 451
is a refusal: the run ends, keeping what it parsed, and the source pauses
until `sensei-top meta` is run by hand. A 429 ends the run and waits for
TopDeck's own time, `retryAfterSeconds` in the body, else `Retry-After`,
else an hour, to the second and with no floor; a second 429 in a
row pauses the source. Any other status, a timeout or no connection is
"no answer" for that one format, and the run goes on to the next: the
refresh reports which formats got no answer and the `sensei-top meta
--format …` command that retries them, and only every query unanswered
is `failed`, which leaves the hold as it was. A run that reached its
last format completed: it is stamped in `meta_fetch_source` and lifts
any hold. An event whose lists TopDeck no longer returns loses them on
the next refresh, unlike mtgo.com's ("When a source empties an event"
below).

## A third source: mtgo.com

`metagame/mtgo_site.py` reads MTGO's public result pages directly, because
the fbettega cache lags mtgo.com by about six days (`docs/attribution.md`
records the terms reading). Same reuse as TopDeck: it normalises a page
into the `CacheItem` shape and calls `parse_event` and `store_events`
unchanged, so tiering, dedup and the privacy guarantee are inherited.

- **Index to slugs.** `list_event_slugs` takes every
  `href="/decklist/<slug>"` on `https://www.mtgo.com/decklists` whose slug
  starts with one of the fetched formats' names and a hyphen (`standard-`,
  `modern-`, …; "Fetching the corpus" above), de-duplicated, order kept.
  Other formats are not fetched.
- **The page's data script.** `extract_data` reads the JSON after
  `window.MTGO.decklists.data =` in the page; it returns `None` when that is
  absent, never raising. The page's format code (`C<NAME>`) becomes a format
  name through `mtgo/formats.py::FORMAT_CODES`; a code that table doesn't
  know, or a format not being fetched, skips the event.
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
- **What a run reads.** The index on every run, then event pages, newest
  first and at most 40, from three lists: the index's slugs not stored
  yet; the slugs of month pages a gap needs; and the stored leagues read
  again, today's (UTC) on every run and yesterday's once after
  12:00 UTC, because a league's page gains lists through its day. A
  challenge's page is read once.
- **The gap fill**. A month's archive page (`/decklists/YYYY/MM`) is
  read only when the last completed run is in an earlier calendar month
  than today, or there is none. A format's start is that run's day, or,
  with none, the day of the format's newest stored MTGO event; it is
  never earlier than the format's window (`guide.window`) and never more
  than 90 days back (`GAP_DAYS`). Month pages run from the earliest
  start's month through the previous month, newest first, while the work
  list is under 40, and from a month page only events dated on or after
  their format's start are taken. So the first run after a month boundary
  normally reads one month page, the previous month's, and every other
  run reads none. fbettega's cache stays the source for older history.
- **Pacing and failure.** One second between requests, a 90 s timeout,
  and the User-Agent `sensei-top/0.1 (+local analytics; results pages
  only)`. Only a timeout, or a failure that drew no HTTP status, is tried
  again, once (`fetch_with_retry`); a status is never sent again. An
  event page that is unparsable, gone or of another format counts as
  `skipped`, as does a parsed event that was not stored (the guard in
  "When a source empties an event" below); `skipped` counts events, so a
  month page that cannot be read is logged as a warning and counts
  nowhere. Three unparsable event pages in a row end the run as a
  completed one, so a changed layout costs four requests, not forty. The
  refresh is fresh for three hours (`MAX_AGE_SECONDS`) unless forced. A
  run that completed writes `meta_fetch_source` `('mtgo', …)` and lifts
  any hold; a run that ended on an answer is not stamped, and keeps what
  it parsed.
- **Privacy.** Player handles and login ids are join keys in memory only,
  as for TopDeck; no handle reaches SQLite
  (`test_mtgo_site_never_retains_a_player_name`).
- **CLI.** `sensei-top meta --source {cache,topdeck,mtgo,all}`; `all`
  (the default) runs cache, then mtgo, then topdeck, then the dedup and
  classify steps. A hand run is the one way to try a paused source again:
  it makes one ordinary run, which stops at the first refusal. It never
  shortens a wait, since `--force` and `--format` override the freshness
  rule, never a hold. The lines it prints are
  `metagame/fetch_lines.py`'s, pinned in `tests/test_metagame_lines.py`.

**When the site answers with something other than a page**, the fetcher
stops rather than adapts. A source's hold is its row in
`meta_fetch_hold` (migration 061), written by `metagame/holds.py`; a
paused or waiting hold is shown on the Field page and printed by
`sensei-top meta`:

| The site answers | The fetcher |
|---|---|
| 200 | reads the page |
| 404 or 410 at a month or event page, or a redirect away from one | skips the page; a stored event keeps its decklists, and its page in the app says the latest read found no page |
| 403, 401 or 451 | ends the run, keeping what it parsed; pauses the source until `sensei-top meta` is run by hand |
| 429 | ends the run, keeping what it parsed; waits until `Retry-After` or three hours, whichever is later; a second 429 in a row, at any page of the next run, pauses the source |
| 503 | ends the run, keeping what it parsed; waits an hour, or until `Retry-After` if that is later; if the first request of every run for a whole day — at least three runs — is answered 503, the source pauses |
| 404 or 410 at the index, another 5xx, a timeout, no connection | ends the run, keeping what it parsed; tries again an hour later, with no hold |

The table follows one clause of Daybreak's Terms of Service, §7.1: no
attempt to "disable or circumvent any measures that we use to prevent or
restrict access to our accounts, servers, databases, data, computers, and
networks". The fetcher stops rather than adapts — a request that drew an
HTTP status is not sent again in that run, and no User-Agent, address or
timing changes in answer to one, so a run looks the same to the site whether
it is the first or the hundredth. The statuses differ in what they are, not
in how the request is treated. A 403, 401 or 451 is the site refusing this
client; what to do about that is the user's decision, taken after re-reading
the terms, so the source pauses until `sensei-top meta` is run by hand, and
the hand run is one ordinary run, stopping at the first refusal. A 429 is a
rate measure, honoured with time: the next attempt waits for `Retry-After`
or the source's own cadence, whichever is later, and a second 429 in a row
pauses the source, because the pace that drew it is the only pace the
fetcher has. A 503 is the server's own unavailability, waited out for an
hour or for `Retry-After`; a day of them pauses the source, because a
challenge page meant for browsers can arrive as a 503, and the fetcher must
never try to pass one. A 404 restricts nothing and takes no hold. What a run
parsed before the answer is kept, because it was read while the page was
open to the fetcher and nothing in the terms asks for it to be dropped. The
reading behind this is the mtgo.com row of `docs/attribution.md`.

## When a source empties an event

`store_events` declines an incoming copy of an event that carries no
decklists when the stored copy has them — or when the stored copy is a twin
(`duplicate_of` set) of an event that has them. The declined copy's
`blob_sha` is recorded all the same, so neither fetcher downloads the same
empty copy again; the event's decks, its twins and its `duplicate_of` are
untouched; it is stamped `empty_read_at` with `empty_read_kind = 'empty'`, a
warning is logged, and it is not counted as stored — the refresher counts it
as skipped. The guard applies to every copy whose source is MTGO or
MTGmelee, by whichever route it arrived (mtgo.com directly, or the cache);
TopDeck is exempt, below. An event with no lists that was never stored — a
league already emptied when it was first seen — is stored with no decks and
stamped `'empty'`, so it is not fetched again as unknown.

The guard exists because an emptied page on mtgo.com is a publication
process, not a statement about the event. Measured 2026-10-03 to 05: a
league's page gains lists through its day; of twelve event pages re-read on
2026-10-05, two leagues, four and seven days old, had lost their whole
`decklists` key, and no challenge had; one of the two had its lists back
later that same day — the same seven decklists the database had stored on
2026-10-03, some card names spelled differently — and the other now
redirects to the index. Following the source would have erased seven
decklists that the source itself republished within the day, and since a
league that old is not read again, the loss would have stood. Nothing in
Daybreak's terms or the cache's licence asks a reader to keep a copy in step
with the page it came from (the mtgo.com row of `docs/attribution.md`
carries the reading), and the kept copy is data that was read, not a guess —
rule 4 is what the guard protects.

The twin case is dedup's doing. `mark_duplicate_events` removes a twin's
`meta_deck` rows outright ("Duplicate tournament events" above), so a twin's
stored copy never has lists in its own right. Without the twin case an empty
copy of a twin was stored, which resets `duplicate_of` to `NULL`, and that
left a deckless event `mark_duplicate_events` never regroups — it hashes
only events with at least one deck — counted on its own by
`metagame_status`'s tier counts and the `MAX(event_date)` reads. So the
stored copy counts as having lists when the event it duplicates has them.

TopDeck is exempt, and its emptied events follow the source: the next
refresh removes the stored lists, the standings rows stay with their
records, and whatever was derived from a removed list — its archetype label
— goes with it, `NULL` rather than a remembered guess (rule 4). The
difference is documented by TopDeck itself. Under every read endpoint its
API page says "Decklists: Only when tournament has ended OR organizer
enabled "Show Decks"", so a finished event whose lists were present and are
now absent has had that switch turned by the organizer, or a submission
removed — a choice, which the app follows. mtgo.com documents no such
switch, and its emptying pattern is the one measured above.

A page that is gone is treated like one that came back empty, with a
different stamp. When a month or event page answers 404 or 410, or redirects
away from the address requested (the site answers a removed event page
with a redirect to the index), the mtgo.com fetch skips the page,
and a stored event is stamped `empty_read_kind = 'gone'` with its decks
untouched. A page that redirects away from its address is treated exactly as
a 404 at that page: whatever the redirect leads to is never parsed as the
event, and the page never counts toward the three unparsable event pages in
a row that end the run. The index is not special-cased: whatever it
redirects to is read as the index.

The event's page in the app says what happened, in a line under its
decklists, so that someone who follows the link to the source and finds
nothing there can tell a kept copy from an invention. The line is shown when
the event has stored lists and its latest read returned none or found no
page; it gives the date the lists were read — or says that date was not
recorded, for an event stored before the read dates existed — and the date
of that latest read. An event stored with standings and no lists at all gets
a line saying so instead. The words are pinned in
`web/src/lib/fieldEvent.test.ts`. A later read that returns lists clears
`empty_read_at` and `empty_read_kind`, and the line goes.

None of this can tell the app why a page emptied — the measurements show a
process, and a redirect says no more than an absent key does. The one way a
source can say that an emptying was on purpose is to ask, and
`docs/attribution.md`'s "Rules for a new source", rule 5, is the answer: the
data is deleted by the next release and kept out of later refreshes. That
rule cites this section by its title, so renaming the section means changing
the rule's parenthesis in the same commit.

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

## Formats: how well each is named (measured 2026-10-04)

The corpus and the archetype definitions are kept per format, so the
classifier's quality is per format too. These numbers were measured once,
on a copy of real data, with every stored deck from 2026-07-06 to
2026-10-04. They are a baseline, not a guarantee. Re-measure after a
definitions update or a new fetch source.

**The corpus**, every stored deck, by format:

| Format | Decks | Named by rule | Colour fallback | Unnamed |
|---|---|---|---|---|
| Modern | 12,044 | 10,270 (85.3%) | 663 (5.5%) | 1,111 (9.2%) |
| Pauper | 7,615 | 5,754 (75.6%) | 75 (1.0%) | 1,786 (23.5%) |
| Standard | 4,398 | 3,158 (71.8%) | 300 (6.8%) | 940 (21.4%) |

Standard and Modern were also read by hand: 20 labelled decks each. Pauper
was not.

The hand reads gave these results:

- **Standard:** all 20 were named right. One, Naya Ouroboroid, was right
  on colours and shell, though its namesake card was not among the deck's
  top spells.
- **Modern:** 16 of the 20 were right in substance. The defects are in
  the definitions' names, not in the matching:
  - names with no space (`GenericTron`, `RubyStorm`, `GoryoReanimator`;
    Standard's `Bant AirbendingCombo` too);
  - doubled names ("Esper Belcher Blue Belcher", "Eldrazi Black
    Eldrazi");
  - one "Azorius Control" whose colours were WUR;
  - a loose colour-fallback "Affinity" on a WU artifact shell.

**The user's own matches**, every MTGO match, after the back-face rule and
the token exemption of migration 060. Measured again on 2026-10-05, on a
copy of the real database with its full card table (338 matches):

| Format | Matches | Named by archetype or corpus | Colours only | Unknown |
|---|---|---|---|---|
| Modern | 178 | 163 | 15 | 0 |
| Standard | 102 | 93 | 9 | 0 |
| Premodern | 38 | 0 | 36 | 2 |
| Pioneer | 5 | 0 | 5 | 0 |
| no format | 15 | — | 11 | 4 |

One of Standard's 102 is a format the user confirmed; every other format
in the table is inferred. Premodern has no corpus and no definitions, so a
colours label is the most it gets: 36 of its 38 matches (95%) have one.
Pioneer's corpus is not fetched by default (Standard and Modern are), so
its five matches get colours only.

Of the 15 matches with no format:
- 6 fit more than one format;
- 5 revealed too few cards to tell;
- 4 name a card the card database doesn't resolve, the same name in all
  four.

The first measurement, on 2026-10-04, ran on an older scratch copy whose
card table lacked the installed client's cards, and counted 23 matches
with an unresolved card; the full table resolves all but 4. Before the
back-face rule, that older copy had 176 matches with no format, 174 of
them for an unresolved card, out of 306.

## The format-reset boundary

Nothing in `metagame/` itself knows about bans — this corpus is presence and
results, not a banlist. `guide/window.py` detects one instead of requiring
it be declared, one format at a time (`format_resets(conn, fmt)`): a card's
`card_legality` row for that format reading `'banned'`
(`migrations/053_card_legality.sql`, from the same Scryfall bulk rows
`cards.py` already fetches) says it is banned there; the last `meta_event.
event_date` on which it still appeared in enough decks to be real evidence
in that format's corpus says when. Each format has its own resets and so
its own window: a Modern ban never moves Standard's. Pooling data across
an undetected reset is a real, sharp failure mode — the hand-written guide
`guide/` replaced did exactly that once, and its "top two decks" turned out
not to exist post-reset.

`guide/window.py::structural_change` is what decides whether a *pre-reset*
matchup rate may be carried forward at all: an archetype whose pre-reset
lists relied on a banned card is a different deck now, and its old rate
must render as void, not merely stale. See `docs/guide.md` for the full
mechanism and `docs/guide.md`'s own note on the corpus scan this requires
(one pass, not one per banned card — Scryfall's bulk export carries every
card ever banned in a format's history, most of them irrelevant to any one
corpus snapshot).

### Every field number that can pool across the boundary, doesn't

Detecting a reset is only half the rule — every route and query that turns
`v_meta_matchup`/`v_meta_winrate` into a number the user reads has to stop at
the boundary too, or the detection buys nothing. `v_meta_matchup`
(`migrations/044_meta_matchup_date_grain.sql`) carries `event_date` through
both halves of its `sides` CTE and its outer `GROUP BY` specifically so every
consumer downstream can add an `event_date >= ?` cutoff without a second join
back to `meta_event`. `api/sql.py::_consensus_window(conn, fmt)` is the one
place that turns "the latest detected reset of this format" into that cutoff
date — `None` for a `fmt` of `None`, since no format means no reset to window
against — and every route below calls it rather than re-running
`guide/window.py::format_resets` itself:

- `GET /api/metagame/status`, `/presence`, `/winrate`, and `/matchups` each
  read one format: the `format` query param, else `api/sql.py
  ::default_format` (the most recent match's format, else Standard).
  `/presence`, `/winrate`, and `/matchups` each take an
  optional `since` query param that wins over the existing `days` cutoff when
  both are given (`api/routes/metagame.py::_since_cutoff`); `matchups` also
  now takes its own `days`, previously fixed at a fixed lookback with no
  override. `GET /api/metagame/status` reports `format_reset_start` — `null`
  when no reset of that format has been detected, else the same date
  `_consensus_window` would use — so the frontend can offer a "Since last
  reset" option without running the detection itself.
- The Field page's window (`?window=`) defaults to "Since the last
  reset" whenever `format_reset_start` is set, and governs the share,
  the win rate and the matchups together; with no reset it falls back
  to the last 90 days. A deck's Matchups page and a pairing's page
  read their field win rate in the deck's own format (`docs/guide.md`,
  "A deck's format"), windowed the same way with no control of their
  own: that format's reset window when one exists, else a fixed 365
  days (`web/src/api.ts::useFieldRecords`). A deck with no format has
  no field win rate at all.
- `review/snapshot.py::build_snapshot`'s `field_matchup` (surfaced by
  `review/analyzers/baseline.py` in the match report) and
  `brief/narrative.py`'s "Field record for this pairing" line both
  read one format's field — the match report the match's format, the brief
  the deck's — windowed to that format's latest reset rather than the whole
  corpus. Each passes its format to `metagame/matchup.py::ranked_field_matchup
  (..., fmt=)`, which answers `None` when there is none — see
  `docs/review.md` and `docs/brief.md`. `api/routes/matches.py::
  _field_context` (the match-report narrative prompt's field section) reads
  the match's format the same way, and both `review/leaks.py::find_leaks`
  call sites in `api/routes/review.py` (the leak finder and its narrative
  prompt) build each match's report under its own format's window.

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
pipeline (`docs/opponent-deck.md`'s "A second evidence source: the corpus's
own decklists" has the full mechanism and the naive-Bayes formula).

The ban-handling here is deliberately not the format-reset window described
above. Windowing to post-reset dates alone leaves too few decks to score
against (measured: 655 decks / 14 archetypes, 82% precision on the truth
set this feature was calibrated against) — a card-to-archetype *association*
is not a win rate or a share, so the "never window `meta_*` across a ban"
rule that protects those does not forbid using pre-reset decks here. Instead,
`archetypes/corpus.py::build_prior(conn, fmt)`, built from one format's
corpus at a time, drops that format's banned cards themselves from
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
