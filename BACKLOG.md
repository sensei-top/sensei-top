# Backlog

The known debt and deferred work of Sensei Top, one item each: what is
wrong or missing, why it was deferred, and what picking it up needs. An
item does not describe how to fix it, because that belongs to the session
that does the fix. [ROADMAP.md](ROADMAP.md) holds the order work is taken
in, and cites the items each of its steps covers by ID;
[CHANGELOG.md](CHANGELOG.md) records what shipped. What works today, what
is limited on purpose and the decisions behind both are facts, not work,
and stay in [docs/status.md](docs/status.md).

Every item was checked against the tree on 2026-10-20.

## Labels

Each item has an ID heading, then one label line with four keys:

- `type`: `feat`, `fix`, `perf`, `refactor`, `docs` or `chore`, the
  Conventional Commits words, so an item's type is the type of the commit
  that closes it.
- `priority`: `P1` is on `ROADMAP.md`'s Now or Next, or puts a wrong number
  in front of the user; `P2` is to do when its area is next touched; `P3`
  waits on evidence or is optional.
- `status`: `ready`, `needs-decision`, `needs-data` (a capture or a fixture
  is missing, rule 7), `blocked` (on a person or a party outside the code)
  or `in-progress`.
- `area`: one or more of `reader`, `projector`, `mtgo`, `table`, `api`,
  `web`, `desktop`, `site`, `review`, `guide`, `brief`, `coach`,
  `archetypes`, `metagame`, `cards`, `llm`, `i18n`, `backup`, `docs`,
  `release`, `legal` and `cli`.

The sections go by type: Features, Bugs, Performance, Code health, and
Outside the code (the user's or a third party's to do). Status is a label,
so an item never changes section, and a status change is a one-line diff.

## Adding and closing an item

When you knowingly leave something behind, add an item at the end of its
section, with the ID `Next ID` gives, and move `Next ID` on by one. An ID is
`BL-NNN`, given once and never reused or renumbered. Two open branches that
both add an item collide on `Next ID`, the same way they collide on a
migration number ([docs/branching.md](docs/branching.md), "Two branches
open at once").

When you finish an item, delete it in the commit that finishes it, with a
`Closes: BL-NNN` trailer, so `git log --grep 'BL-NNN'` finds its history. A
user-visible change also gets its line in `CHANGELOG.md`. There is no Done
section.

Next ID: BL-087

## Features

### BL-001 · Reader health in the dashboard

type: feat · priority: P1 · status: ready · area: api web

Next 1. Reader health in the dashboard: the log's path and whether it was
found, the last read, "waiting for the log to grow", raw and projected
counts, and Detailed Logs off with the setting's exact path (on the empty
Matches page too); a "Total matches · Last updated" line; a warning for a
match that looks missing; a dated changelog in the app.

**Why deferred:** The pieces exist apart. `doctor` prints the log's path,
whether it was found and the Detailed Logs reading, on the command line
only. `/api/live` already serves the log's path, the last read, the last new
data and the raw and projected counts, and draws none of the first two. In
the desktop app, Settings' Sources says whether the Arena log was found,
Home asks for Detailed Logs until the log says they are on (without the
setting's path), and the live-status pill says when data last changed.

**Needs:** A read-only GET under the guard; the panel reads state and never
drives the reader (rule 1); the changelog is text shipped with the app,
never fetched.

### BL-002 · A CSV export and a definition on every column

type: feat · priority: P1 · status: ready · area: api web i18n

Next 2. A CSV export of the user's own matches, games and per-deck numbers
(an unknown value is an empty cell, never 0); a one-line definition on each
table column; and the help tour below, with an entry that cites Arena's own
article on Detailed Logs for community tools and says the app reads only the
log and sends nothing.

**Why deferred:** Asked by no one yet; the research found the export is what
other trackers charge for.

**Needs:** A GET under the guard; every string keyed in both languages
(`docs/i18n.md`).

### BL-003 · The help pages' tour of the dashboard

type: feat · priority: P1 · status: needs-decision · area: site i18n

Next 2, with the export above: the help pages' tour of the dashboard
(`site/help/`): what each page shows, in both languages, linked from the
welcome steps' last step, Ready. The first cut (2026-10-13) covers
installing, the first run, Magic Online, troubleshooting and the problem
report; `docs/user/dashboard.md` is the English tour until then, and moves
to the site with it.

**Why deferred:** Scoped to what the beta testers need first; then left out
of the onboarding revisit (plan 23) and moved after 1.0.0 (both 2026-10-16),
because Ready's link needs a decision first: nothing in the dashboard links
to the public site today.

**Needs:** Whether the dashboard links out to the site at all, and how it
gets the site's address. Plan 23's shape for the pages (its D12): one page
per language, `site/help/tour/` and `site/pt-br/help/tour/`, one section per
place; screenshots from the demo database through
`web/scripts/site-images.mjs`, inside the page weight `tests/test_site.py`
pins. Ready's label, `welcome.done.tour`, is in both catalogues already, not
drawn.

### BL-004 · Per-card win rates

type: feat · priority: P1 · status: ready · area: projector guide web

Next 4. Per-card win rates from the user's own games: in the opening hand,
drawn and cast, with n beside every rate. Today `key_card_timing`
(`docs/guide.md`) covers maindeck cards with 3 or more copies only.

**Why deferred:** Next in order. An undone cast no longer counts (plan 29).

**Needs:** The user's own opening hand and draws per game, computed in the
rebuild with NULL where the hand is unknown (rules 3 and 4); fixture tests
(rules 7 and 8). On MTGO the opening hand may not be recoverable.

### BL-005 · Sideboard help without a model

type: feat · priority: P1 · status: blocked · area: guide archetypes web

Sideboard help without a model (decided 2026-10-07; `ROADMAP.md`'s Next 3):
candidate ins by a card-role rule over the 75 (answers, threats, hate by the
opponent's archetype), and a link to a sideboard guide for the pairing from
the Skill Issue Magic guide index. No generated outs. The user's own
post-board record per matchup came first and is built (plan 28, 2026-10-19).

**Why deferred:** The research's most-wanted feature, and the one every
competitor sells a model for; the index's creator was asked on 2026-10-07,
in exchange for credit on each link, and had not answered. Not started.

**Needs:** The creator's yes, recorded in `docs/attribution.md` with a row
for the index ("Rules for a new source"): the published CSV's address and
shape, an alias table from the index's archetype names to the corpus keys, a
scheduled fail-soft fetch kept in cache, never any guide content copied.
Plan `release-17-sideboard-referrals.md` (outline).

### BL-006 · The optional subscription

type: feat · priority: P3 · status: blocked · area: llm api web legal

The optional subscription (decided 2026-10-12, `AGENTS.md` rule 5,
`docs/llm.md`, "Nothing hosted writes for the user"): gated by feature,
never by rank or event type; a monthly report allowance inside it, never
tokens, credits or a prepaid balance; a hosted proxy holding the
maintainer's key; the only account in the project, made at checkout (an
email code; Google, Discord and X sign-in). The free tracker, the copy
prompt and the user's own key stay free beside it.

**Why deferred:** Deferred until around 3,000 monthly active users, which
the launch's own counts measure.

**Needs:** Which features it holds. A merchant of record (Paddle). An
account service (Supabase Auth was the pick) and a privacy policy. X
sign-in's terms, unread. Daybreak's Fansite license agreement if §14.3 asks
for one. The notice Anthropic's Commercial Terms (D.3) require, that outputs
are not to be relied on without checking, shown to subscribers. The rewrite
`docs/llm.md` lists, and a new rule 5.

### BL-007 · A provider adapter for the generate routes

type: feat · priority: P3 · status: ready · area: llm api web

A provider adapter for the generate routes (decided 2026-10-07, `AGENTS.md`
rule 5, `docs/llm.md`): the credential becomes a provider, a base URL, a key
and a model id, so the five routes can call Anthropic, any OpenAI-compatible
endpoint or a local model (Ollama, LM Studio). Each stored narrative keeps
naming the model that wrote it, as it does today from its `model` column
(`author` on `deck_narrative`); the coach's web search degrades to the
reading list on a provider without it; an unknown model prices `NULL`. The
brief, coverage and sideboard-plan cards get a generate route with it.

**Why deferred:** The repositioning made the user's own credential the only
writing path, and "any model" was the research's second-most-asked thing
after "no account". Moved from Next to Later on 2026-10-19: the 2026-10-19
tracker research found no demand either way. Not started.

**Needs:** Its plan (`~/.claude/plans/release-16-provider-adapter.md`,
outline). One adapter per protocol under `llm/`, `llm/config.py` widened,
`REPORT_MODELS` reworked into a per-provider list, Settings' Writing
section, and the route additions to rule 5's list and
`test_only_authored_artifact_routes_write`.

### BL-009 · A macOS build

type: feat · priority: P3 · status: ready · area: desktop release

A macOS build, Arena-only, unsigned, from GitHub's free macOS runners, open
to it since the repository went public; notarization when donations cover
the Apple fee.

**Why deferred:** Linux and Windows ship first (decided 2026-10-07); moved
from Next to Later on 2026-10-19, behind wider Linux discovery.

**Needs:** A plan of its own: plan 6, now done, left macOS out of scope.

### BL-010 · MTGO's .txt deck export

type: feat · priority: P3 · status: needs-data · area: reader mtgo

MTGO's `.txt` deck export is not read; only `.dek` exports and the deck
store are (plan 12, D13).

**Why deferred:** No real `.txt` export exists to build a fixture from (rule
7).

**Needs:** A real `.txt` export, from the user or the VM.

### BL-011 · Formats beyond the seven

type: feat · priority: P3 · status: ready · area: metagame archetypes

Formats beyond what plan 13 built. Plan 13 made the format a parameter for
the seven formats in `formats.FORMATS` (Standard, Pioneer, Modern, Pauper,
Legacy, Vintage, Premodern): legality per format (`card_legality`, migration
053, in place of `cards.standard_legality`); a match's format
(`matches.format`, 055, read through `v_match_format`: the log's, then the
MTGO pick, then the format the revealed cards fit); and per-format archetype
rules, corpus prior, consensus, reset window, field record, leaks and coach
reports, with a format choice on the Field and Coach pages. Left out:
Arena-only formats (Historic, Explorer and Timeless are planned after 1.0.0,
BL-012; Alchemy and Brawl never) and Duel Commander; Premodern's archetype
rules, so its opponents are named by colours and signature card only; a
date-aware ban or rotation history (Scryfall's ban list is today's, so a ban
never takes a match out of its format); "&" names (BL-051). The corpus
follows Standard, Modern and every format it already holds an event in, and
`sensei-top meta --format X` adds another (`docs/metagame.md`, "Fetching the
corpus"); the quality pass (`docs/metagame.md`, "Formats: how well each is
named") covers Standard, Modern and Pauper's corpus.

**Why deferred:** Decided with the user, 2026-10-02 (plan 13, D10 and D11):
fetch what is played, and never write Premodern rules here, because it is
not a Wizards-sanctioned format.

**Needs:** Per format: switching its fetch on, then its quality pass.
Premodern rules only from an outside source, if one exists.

### BL-012 · Historic, Explorer and Timeless

type: feat · priority: P3 · status: ready · area: archetypes metagame cards

Historic, Explorer and Timeless, the Arena-only formats other than Alchemy
and Brawl (decided 2026-10-16, after 1.0.0, low priority). Reverses that
part of the 2026-10-01 pivot; Alchemy and Brawl stay out.

**Why deferred:** Asked 2026-10-16, for after 1.0.0.

**Needs:** What plan 13 built per format (legality, archetype rules, corpus
prior, consensus, field), and a corpus source for formats that have no MTGO
events. `ROADMAP.md` keeps them in Later (2026-10-19).

### BL-013 · MTGO on the Live page

type: feat · priority: P3 · status: ready · area: table api web mtgo

MTGO on the Live page: the opponent's revealed cards during a game (MTGO
appends to the game log every 1–8 s mid-game, median 2.3 s, and never
rewrites what it wrote) and the between-games plan (see `docs/status.md`,
"Limited on purpose").

**Why deferred:** Moved out of plan 3, which built the ingest it stands on
(plan 3, D1): it is a `table/`, API and Live-page feature, and migration 040
made the current-match view Arena-only.

**Needs:** Plan 15.

### BL-014 · An authored mulligan plan

type: feat · priority: P3 · status: needs-decision · area: guide table

Mulligan plan "Layer 4": an authored mulligan plan in the guide's
prompt/import round trip

**Why deferred:** Planned during the mulligan work and never built. The
handoff that described it is gone.

**Needs:** A design pass: what the plan says, where it's stored (an
authored-artifact table, rule 6), and how the keep guide shows it.

### BL-015 · The coach per deck version

type: feat · priority: P3 · status: ready · area: coach

Coach breakdown per deck version

**Why deferred:** Deferred feature. A deck's Overview, Matchups and pairing
pages split its versions (`components/VersionSwitcher.tsx`), but the coach
reads each deck identity whole, every version together.

**Needs:** A per-version cut of each identity's `deck_ids` inside
`coach/evidence.py`, which already groups by
`guide/deck.py::list_identities`.

### BL-016 · Combat and timing analyzers

type: feat · priority: P3 · status: needs-decision · area: review

Deferred review analyzers (combat attack/block decisions, timing)

**Why deferred:** Future scope in `docs/review.md`.

**Needs:** Their own design.

### BL-017 · An MTGO deck named by archetype alone

type: feat · priority: P3 · status: needs-decision · area: mtgo guide

An archetype name as the user's MTGO deck with no list behind it (plan 19,
D3), for matches no saved list fits.

**Why deferred:** It needs a column, a view change and a decision on how a
deck with no list reaches Decks and the guide.

**Needs:** Its own plan, if asked.

### BL-018 · A pasted-decklist importer for MTGO

type: feat · priority: P3 · status: needs-decision · area: mtgo reader

A pasted-decklist importer for MTGO lists the user no longer has as files.

**Why deferred:** A pasted list must enter `raw_events` to survive the
rebuild (rules 2 and 3). Until then such matches are picked format-only.

**Needs:** Its own plan, if asked.

### BL-019 · A Live clip on the landing

type: feat · priority: P3 · status: needs-decision · area: site

A Live clip or a short video on the landing (plan 21, D2): the page shows
the Live capture of a real unranked match cut mid-game, and no motion beyond
a row rising into view.

**Why deferred:** Deferred to after the beta, by the user's choice
(2026-10-13): a clip is a second pipeline (a cut match replayed through the
dashboard, recorded, then cut and encoded) and a weight cap of its own.

**Needs:** A decision on clip or video; the recording pipeline beside
`site-images.mjs`; a cap in `tests/test_site.py`; `ffmpeg` is on the
machine.

### BL-020 · Caution cards

type: feat · priority: P3 · status: needs-decision · area: table web

Caution cards: the cards to watch for from the opponent's leading candidate
deck, with rules text on expand. The brief and the sideboard plan cover part
of it.

**Why deferred:** Seen in the tracker research (2026-10-19); in
`ROADMAP.md`'s Later.

**Needs:** Its own design: where it sits on Live (and whether it is advice
under `table/queues.py`'s rule), and its source (the candidate's consensus
list).

### BL-021 · Finding history faster

type: feat · priority: P3 · status: needs-decision · area: web api

Finding history faster: date presets (7, 30, 90 days, a custom range), a
search, matches grouped by day, league runs with their trophies.

**Why deferred:** Seen in the tracker research (2026-10-19); in
`ROADMAP.md`'s Later.

**Needs:** A check of what the Matches page and Home's session block already
do, then a design per piece; league runs need the log's event records read.

### BL-022 · Coach web-search citations stored

type: feat · priority: P3 · status: needs-decision · area: coach

Coach web-search citations are never stored. `sources_json` holds only the
reading-list ids. The pages are not lost: `coach/narrative.py::web_sources`
recovers them from the prose's "Sources" section when the report is read.

**Why deferred:** The 2026-09-22 runs found no citation objects in the
response to store.

**Needs:** Storing the recovered pages at write time, if a reader ever needs
them without the prose.

### BL-023 · Play and draw on the Matches page

type: feat · priority: P3 · status: ready · area: web

Play and draw are not on the Matches page.

**Why deferred:** `/api/metrics/play-draw` answered 500 for MTGO when the
page was built; it answers for every source now, deckless matches in one row
per side.

**Needs:** Put the split on the page, or count it from the list's games as
the band does.

### BL-024 · Paging past the 500th match

type: feat · priority: P3 · status: needs-decision · area: api web

No route lists the matches past the 500th or counts the matches of a filter.

**Why deferred:** Found while building the Matches page. The list says where
it stops.

**Needs:** A design for paging.

## Bugs

### BL-025 · A prepare face several cards share

type: fix · priority: P3 · status: needs-decision · area: cards

A prepare spell half that several cards share has no legality and no
`oracle_id`: Reality Fracture's "Peer Review" is the back of three different
creatures, so `cards.py::_backfill_by_name` skips the face name as two cards
sharing it (15 face grp_ids across five names). No match's format read
depends on one: MTGO resolves the combined name, and no MTGO match sat at
`unknown_legality` on 2026-10-05.

**Why deferred:** The skip is the guard that keeps Odyssey's Careful Study
apart from an Arena face; loosening it for shared faces is its own change.

**Needs:** A rule telling a face shared by several cards (same face,
different whole cards) from an unrelated card of the same name, then a test
over a real `prepare` line.

### BL-026 · The hand read's per-game count

type: fix · priority: P3 · status: needs-decision · area: table archetypes

`table/hand_read.py::_seen_elsewhere` counts per game, while the classifier
counts per match.

**Why deferred:** The asymmetry is undocumented but harmless today.

**Needs:** A decision on which grain is right, then a doc line or a change.

### BL-027 · The game-length gate's game count

type: fix · priority: P3 · status: needs-decision · area: review

`review/analyzers/baseline.py`'s `GAME_LENGTH_MIN_GAMES` gate counts
projected games, so it couples to projection details.

**Why deferred:** Raised during review and left unchanged.

**Needs:** A look at whether the gate should count completed games only.

### BL-028 · Field shares by name, coverage by key

type: fix · priority: P3 · status: needs-decision · area: guide coach brief

The deck guide's field shares group by archetype name, while the coach and
brief coverage group by key.

**Why deferred:** Found in the coach↔guide helper consolidation, which kept
behaviour byte-identical on purpose.

**Needs:** A decision on one grain, then a real-data diff of the guide
output.

### BL-029 · One label on distinct archetype keys

type: fix · priority: P2 · status: needs-decision · area: brief web

A deck's coverage table and a pairing's heading can show one label on rows
of distinct archetype keys: `brief/coverage.py` labels a row `field_name or
faced_name`, and the corpus files "Dimir Midrange" under more than one key,
so two rows can read alike.

**Why deferred:** Found while rebuilding a deck's pages; telling the rows
apart is a naming decision, not a patch.

**Needs:** Decide how a shared label is told apart (a qualifier in the
label, or the address alone as the identity), then fix `coverageName`
(`web/src/lib/brief.ts`) and `pairingHeading` (`web/src/lib/pairing.ts`).

### BL-030 · Provisional corpus-naming constants

type: fix · priority: P3 · status: needs-data · area: archetypes

The corpus-naming confidence constants are provisional (44% measured against
a 60% target).

**Why deferred:** Needs more classified data.

**Needs:** A re-measurement against the corpus.

### BL-031 · TopDeck's non-constructed filter

type: fix · priority: P3 · status: needs-data · area: metagame

TopDeck's non-constructed events (Commander, draft, sealed, cube, jumpstart,
pre-release) are filtered by name only. `topdeck.py`'s `_NOT_CONSTRUCTED_RE`
skips a matching event on fetch with a warning, and purges already-stored
matching Topdeck events with their child rows after each refresh. The match
has a leading word boundary only, so it can over-match ("Cubes", "Prelude"
would also match).

**Why deferred:** TopDeck's own format field is not trusted: it labelled
these events Standard (found when the base URL fix first returned data).

**Needs:** A look at what TopDeck's own fields say per event, and a
fixture-backed tighter rule if over-matching shows up in the stored events
(rule 7).

### BL-032 · No paper source after 2026-08-16

type: fix · priority: P2 · status: blocked · area: metagame

No paper source after 2026-08-16: fbettega's Melee data stops there, so
paper RCQs reach the field only through TopDeck (needs the user's key).

**Why deferred:** Measured while planning the RCQ guide.

**Needs:** A working TopDeck run, or another paper source
(`docs/attribution.md`, "Rules for a new source").

### BL-033 · An RCQ answer stored against an edited list

type: fix · priority: P2 · status: ready · area: guide web

The RCQ paste stores an answer against the list in the box at save time. The
RCQ prompt carries no `context` hash, and the box stays usable while the
preview catches up after an edit, so an answer copied for one list and saved
after the list was edited is stored against the edited list, and the page's
"changed" note cannot tell.

**Why deferred:** Found in plan 24's review of phase 9c. Disabling the box
while the preview updates would unmount it and lose the pasted text.

**Needs:** A `context` hash on the RCQ prompt (the list as typed and the
expected keys), stored with the guide so the page can say it was answered
for another list.

### BL-034 · Detailed Logs off, untested

type: fix · priority: P3 · status: needs-data · area: desktop

`doctor`'s Detailed Logs reading `disabled` rests on a `DISABLED` line that
no capture has shown, so that branch is untested (`docs/desktop.md`,
"Support commands").

**Why deferred:** No capture of Arena with Detailed Logs off exists (rule
7).

**Needs:** A real `Player.log` header from Arena with the option off, then a
fixture-backed test.

### BL-035 · A deck's format and the user's picks

type: fix · priority: P3 · status: needs-decision · area: guide mtgo

A deck's format (`guide/deck.py::identity_format`) is its `decks.format`
when that names one of the seven formats, the store's `FormatCode` for an
MTGO deck; only otherwise does it come from its matches' formats, the user's
confirmed picks among them (plan 13, D15). A pick never overrides the
store's format.

**Why deferred:** On purpose in plan 12: a deck's format is the deck's, and
a pick is per match.

**Needs:** A decision on whether confirmed picks should override the store's
format there.

### BL-036 · mtgo_watching with an unreachable folder

type: fix · priority: P3 · status: ready · area: api mtgo

`mtgo_watching` reports true while the running watcher has an MTGO
directory, even while that directory is unreachable (a share not mounted, a
folder MTGO moved).

**Why deferred:** Minor. The watcher warns once when a run of failed checks
starts, and counts it as one error.

**Needs:** Plumbing the last check's outcome through to the status route.

### BL-037 · Arena's rename during a read on Windows

type: fix · priority: P3 · status: needs-data · area: reader

On Windows a file another process holds open cannot be renamed unless it was
opened with `FILE_SHARE_DELETE`, which Python's `open()` never asks for
(`WinError 32`). Arena renames `Player.log` to `Player-prev.log` at launch,
so a launch that lands inside one of the watcher's reads would fail that
rename, with an effect on Arena's side nobody has seen. The watcher holds no
handle between polls, so the window is one read a second.

**Why deferred:** Found in plan 3's Windows work; never observed.

**Needs:** A capture of the failure, then opening the log through
`CreateFileW` with the flag (and `msvcrt.open_osfhandle`).

### BL-038 · UNC paths for the database and backups

type: fix · priority: P3 · status: ready · area: backup api

A database or backup path given as a UNC path (`\\server\share\…`) fails
where it is opened read-only: those opens use SQLite's URI form, and SQLite
rejects the `file://server/…` URI a UNC path becomes. A mapped drive letter
works, since the URI is built from `Path.absolute()`, not `resolve()`.

**Why deferred:** Found in plan 3's Windows work (S2); out of its scope.

**Needs:** Building a URI SQLite accepts from a UNC path, or refusing one
with a message.

### BL-039 · "mode 600" on Windows

type: fix · priority: P3 · status: ready · area: cli

`config` says it wrote the file "mode 600" (`cli.py`'s `_written`,
`path.chmod(0o600)`), but on Windows `chmod` only sets or clears the
read-only flag. Since plan 6 a key goes to the system keyring when one
exists (Windows Credential Manager on Windows), so the file holds a
credential only when no keyring exists, which on Windows is not expected;
the message is still printed for any file write.

**Why deferred:** Found in plan 3 (S4); the keyring made it rare rather than
gone.

**Needs:** A Windows wording for the message, or leaving it out where
`chmod` does nothing.

### BL-040 · Segmenter shape 5 and a following header

type: fix · priority: P3 · status: needs-data · area: reader

Segmenter entry shape 5 (a non-JSON response body) would swallow a header
that came directly after `<==`.

**Why deferred:** Never observed in either real log.

**Needs:** Harden only if a capture shows it. DeckDeleteDeck's second body
line falls through as noise, which is harmless.

### BL-041 · A dated twin of an undated entry

type: fix · priority: P3 · status: ready · area: reader

An entry stored with no time by `--locale auto` (`reader/dates.py`, step 6)
gets a dated twin if the same bytes are read again once its shape's order is
learned (`ingest --file` reads from the start), because the digest includes
`logged_at`. A `--locale` change between two reads of one file does the
same.

**Why deferred:** Known when `auto` was built (plan 3, S10); out of its
scope.

**Needs:** Re-deriving `logged_at` from `raw_events.header`, which migration
062 keeps for this.

### BL-042 · Windows' regional format in Arena's header

type: fix · priority: P3 · status: needs-data · area: reader

Whether Windows' regional format reaches Arena's header while Arena is in
English is not known. The header followed the in-game language in all eight
captured languages.

**Why deferred:** Every capture so far ran under Proton, where setting the
locale did not change the header.

**Needs:** One Windows capture with Arena in English and a day-first
regional format. A new shape is a fixture and a row in `docs/arena-log.md`'s
table; a day-first `slash-12h` header is one `auto` already settles.

### BL-043 · Two grains in the keep guide's mulligan numbers

type: fix · priority: P2 · status: needs-decision · area: table guide

The keep guide's mulligan table counts one deck version (`table/keep.py`'s
query on `m.deck_id = ?`), while its mulligan-cost line counts the whole
deck identity (`guide_play.mulligan_record`), so the two can differ for a
deck whose list was edited; both say "Kept 7".

**Why deferred:** Found in plan 26's review of phase 3b; the two reads
predate it.

**Needs:** A decision on which grain the table should have, then the same
grain for both, with a fixture-backed test (rule 7).

### BL-046 · Matchup rows keyed on the opponent alone

type: fix · priority: P3 · status: ready · area: web

A deck's Matchups and pairing pages (`web/src/lib/matchups.ts::matchupRows`)
group its matches by `opponent_key` alone, not by format and key. An MTGO
deck whose matches were picked as different formats would mix them in one
row.

**Why deferred:** Safe while a deck's matches share one format: D15 gives
the deck one, and on 2026-10-04 no deck in the real history had matches in
more than one.

**Needs:** Rows keyed on format and key, and a format in the pairing's
address.

### BL-047 · Day and Night's shared oracle_id

type: fix · priority: P3 · status: needs-decision · area: cards

Arena's Day and Night rows share one oracle_id, given by `cards.py`'s name
backfill, which suppresses Night // Day's synthetic row. Which card's
oracle_id it is was not verified (most likely Night // Day's).

**Why deferred:** Found in plan 13's review; outside its scope.

**Needs:** A read of the rows in a scratch copy, then a decision on whether
the backfill should skip the pair.

### BL-048 · Wheel of Fortune on MTGO

type: fix · priority: P3 · status: needs-decision · area: cards mtgo

Arena's "Wheel of Fortune" (60053) carries no oracle_id or legality, and its
name is shared in Scryfall's export by another card's face, so an MTGO
"Wheel of Fortune" resolves to NULL (`projector/mtgo/project.py::_lookup`).
Whether a shared name resolves at all depends on which Arena rows happen to
match an `arena_id` in the export.

**Why deferred:** Found in plan 13's review; NULL with a warning is the
rule-4 answer.

**Needs:** A way to tell the shared name's cards apart, or a decision that
NULL stays.

### BL-050 · Corpus names without spaces

type: fix · priority: P3 · status: needs-decision · area: archetypes metagame

The Modern corpus names an archetype "GoryoReanimator", with no space;
`docs/metagame.md` lists the other names like it. The dashboard spaces such
a name on a deck's pages, the RCQ guide and the coach
(`web/src/lib/decks.ts::archetypeName`), but not where a match's opponent
label is drawn (the match list, the opponent-deck label, the Field page's
matchups, Home), nor in the CLI's or a prompt's text.

**Why deferred:** The name comes from the downloaded definitions, not from
this code.

**Needs:** The same rule wherever a match's opponent label is drawn, or a
report upstream.

### BL-051 · "&" names on MTGO

type: fix · priority: P3 · status: needs-data · area: mtgo cards

"&" names (*Wear & Tear*) never resolve on MTGO and stay unresolved with a
warning (plan 13, D16), counted in `cards_json`'s unresolved count, which
the match report and the leak finder treat as unknown cards. Split-card
halves resolve by the back-face rule since plan 13.

**Why deferred:** No fixture holds one (rule 7).

**Needs:** A real capture naming one.

### BL-052 · An unsure MTGO pick names no format

type: fix · priority: P3 · status: ready · area: web api i18n

On `/mtgo/picks`, an unsure match with no saved list in its format reads "No
saved list fits." instead of naming the format.

**Why deferred:** The unsure item carries no format field.

**Needs:** Add the inferred format to `MtgoUnsurePick` and use "No saved
list in {format}."

### BL-053 · A summarized block at the end of a dead file

type: fix · priority: P3 · status: ready · area: reader

A summarized block (`docs/arena-log.md`, trap 18) that is the very last
thing in a file that never grows again, such as the `Player-prev.log` the
startup recovery reads, never warns: the segmenter holds the block open
until a later line closes it.

**Why deferred:** No summarized block has appeared in the user's logs, and
closing it needs `reader/ingest.py` to flush the segmenter at the end of a
dead file.

**Needs:** A flush at the end of a dead file in `reader/ingest.py`, and a
held-back-block test in `tests/test_ingest.py`.

### BL-054 · MTGO's score line, unread

type: fix · priority: P3 · status: ready · area: projector mtgo

`ParsedMatch.score_line` (`projector/mtgo/parse.py`) is a self-check that
nothing reads, and `Match Tied <a>-<b>`, MTGO's running score while a match
is level (183 lines in the real history, 2026-10-19), is not parsed into it.
Results come from each game's own lines, never from a score line.

**Why deferred:** Left out of plan 30 (its D9): nothing would read it.

**Needs:** A reader for the check (a warning when the counted score
disagrees with the last score line), then `Match Tied` beside `leads the
match`.

### BL-056 · A warning on every rebuild without [mtgo]

type: fix · priority: P2 · status: ready · area: projector mtgo

`projector/matches.py` calls `mtgo.config.load_handle()` on every
`project()`, so a config file with no `[mtgo]` table (an Arena-only user
with a Claude key, say) logs a warning on every rebuild.

**Needs:** Loading the handle only when MTGO `raw_events` exist, or a silent
absence like `resolve_log_dir()`'s.

### BL-080 · Two cutoffs for an early play

type: fix · priority: P3 · status: needs-decision · area: table

The keep guide's ideal hand counts "plays at 1-2 mana", mana value 2 or
less (`table/keep.py`, `_CHEAP_MANA_VALUE`); the opening-hand verdict counts
cards "castable by turn 3" (`table/opening_hand.py`,
`_EARLY_TURN_THRESHOLD`). The code says the two differ on purpose, and Live
shows both side by side. Found by plan 35's reviewers.

**Why deferred:** Which cutoff a player means by "early" is a product call.

**Needs:** A decision: one cutoff for both, or a sentence on Live that
says why they differ.

### BL-081 · An MTGO deck file's time from a second stat

type: fix · priority: P3 · status: ready · area: reader mtgo

`reader/mtgo_decks.py::_ingest_one_deck` stats the file for its identity
token, then `_mtime_iso(path)` stats it again for `logged_at`. A write
landing between the two leaves `logged_at` newer than the token's mtime.
Found by plan 35's reviewers.

**Why deferred:** No visible effect: the next poll re-reads the file either
way.

**Needs:** `logged_at` from the first `stat()`'s `st_mtime`.

### BL-086 · A drawn game in the report's game-length rates

type: fix · priority: P3 · status: ready · area: cli

`sensei-top report`'s game-length table prints a win rate per turn count,
won over `v_deck_game_length.games`. That count has no result filter, so a
drawn game and an unfinished one both sit in it and lower the rate. The
average length is right to count both; only the rate is wrong. Found while
fixing the play/draw rates.

**Why deferred:** Outside that fix's scope, and the view has no
`games_lost` column, so it needs a migration of its own.

**Needs:** `games_lost` on `v_deck_game_length`, and the rate read as won
over won plus lost.

## Performance

### BL-058 · The coach page and its narrative route

type: perf · priority: P3 · status: ready · area: coach

Coach page, warm; and the coach narrative route (the prompt the page loads
on every visit).

**Now:** The page: ~2.5 s. The report cache removed the per-match rebuild;
what's left is non-report work. The narrative route: ~3.8 s.

**Needs:** Profiling `build_coach_evidence` outside `build_match_report`;
the same profile serves the narrative route.

### BL-059 · The sideboard break, cold

type: perf · priority: P2 · status: ready · area: brief table

Sideboard break, cold path

**Now:** ~2 s against a 1 s target (`brief/narrative`'s full prompt and
consensus)

**Needs:** A cache, or trimming what the break needs from the brief.

### BL-060 · The mulligan offer's real ingest lag

type: perf · priority: P2 · status: needs-data · area: reader table

The mulligan offer's real ingest lag, once a session has run on the
two-thread watcher. Compare `raw_events.ingested_at` against `logged_at`
(which is local time, UTC−3) for rows carrying
`ClientMessageType_MulliganResp`.

**Now:** Before the fix: median 3.1 s, p90 13.3 s (n = 1,099). Target:
median ~1 s, p90 ≤ 6 s, the bound the write lock sets. On 2026-10-19, with
the MTGO projection inside the lock: median 1.1 s, p90 15.9 s (n = 39).

**Needs:** Re-measure after the first session with the lock at 1.8 s.

### BL-061 · The backup's real cost

type: perf · priority: P3 · status: needs-data · area: backup

The backup's real cost. Every daily run records its duration in
`backup_state.last_duration_ms` (`sqlite3 "file:data/sensei-top.db?mode=ro"
"SELECT last_duration_ms FROM backup_state"`); read it after a few runs and
put it in `docs/architecture.md`'s Backups section. The WAL peak there is
still an estimate, because nothing records it.

## Code health

### BL-062 · The draft-sharing leftovers

type: refactor · priority: P2 · status: ready · area: web desktop

Settings' Draft data section (`components/settings/SharingSection.tsx`),
`components/sharing/` and the `Sharing`, `SharedDraft`, `DraftPayload` and
`Deleted` types in `web/src/bridge.ts` describe drafts, which the app no
longer reads. Nothing draws them outside `/design/surfaces`.

**Why deferred:** Kept when the draft assistant and the overlay's leftovers
were removed (2026-10-01), for plan 10 to rework for match data. Plan 10 was
refused on 2026-10-19 (`ROADMAP.md`, "Never"), so nothing will.

**Needs:** Their removal, with the shell side of `deleteContributions`
(`web/src/bridge.ts`, `views/SettingsView.tsx`, `lib/sampleShell.ts`, and in
the desktop shell `desktop/src/preload.ts` and `desktop/src/settings.ts`,
which set `sharing` to null) and `docs/frontend.md`'s paragraph on them.

### BL-063 · Two Windows checks not run

type: chore · priority: P3 · status: ready · area: desktop backup

Not checked on Windows: `pnpm start` (the dashboard build plus `serve
--watch` in one), and the daily backup to a mapped network drive.

**Why deferred:** Out of plan 3's hand checks on the VM.

**Needs:** One run of each on a Windows machine.

### BL-064 · build_snapshot's size

type: refactor · priority: P3 · status: ready · area: review

Big file: `review/snapshot.py::build_snapshot` (~505 lines)

**Needs:** Out of scope for the sweep. Split it when a feature next touches
it.

### BL-065 · Citations of gitignored handoff notes

type: docs · priority: P3 · status: ready · area: docs

Two tracked files still point at notes under the gitignored
`.claude/handoffs/`, so the pointers dangle for anyone else reading the
repo: `migrations/035_mtgo_source.sql` cites `mtgo-implementation.md` twice,
and the counting-downloads skill names `announcement.md` as where the weekly
numbers go. The other hits of `git grep -l '\.claude/handoffs'` name the
folder, not a note.

**Needs:** A wording pass on the migration's two comments: state what the
note established, or drop the citation. The skill's line is the maintainer's
own destination and can stay.

### BL-066 · A seat's colours, read in two places

type: refactor · priority: P3 · status: ready · area: archetypes api

The rule that reads a seat's colours from its played cards exists twice:
`archetypes/classify.py`'s `live_opponent_colors` (which
`table/intermission.py` calls), and `_colors_by_played_name`/`_colors_of` in
`api/routes/mtgo_picks.py` (plan 19, one query per request instead of one
per match), kept equal by a test.

**Needs:** One helper both import, from `archetypes/`.

### BL-067 · The shell's settings folder, unnamed

type: docs · priority: P3 · status: needs-decision · area: desktop

The installer's uninstall page (`desktop/build/installer.nsh`, both
languages) and `INSTALL.md`'s folder table name `%APPDATA%\sensei-top` as
the settings folder, which holds only the server's `config.toml`; the
shell's own `shell.json` (language, autostart, onboarding) sits in
`%APPDATA%\Sensei Top`, Electron's userData, and is named nowhere. Found in
plan 18's VM read, 2026-10-12.

**Needs:** A decision on whether the uninstall page names the second folder,
then the same sentence in both `LangString`s and in `INSTALL.md`.

### BL-068 · Newer python-build-standalone tags

type: chore · priority: P3 · status: ready · area: desktop release

`scripts/build_server.py` accepts python-build-standalone 20260623 and
20260807 only (`VENDORED_PBS_TAGS`): a bare `uv sync` in the Windows VM
picked 3.12.14 (PBS 20260929) on 2026-10-12 and the freeze refused it;
`--python 3.12.13` is the workaround.

**Needs:** Re-checking `desktop/server/licenses/cpython-deps/` against the
newer tag, then adding it to the tuple.

### BL-069 · Imports of private names

type: refactor · priority: P3 · status: ready · area: brief api guide

11 imports in `src/` reach into another package's leading-underscore names
(counted 2026-10-21, the gettext alias `_` aside; 37 before the names from
`archetypes/classify.py` and into `coach/evidence.py` were made public):
4 into `brief/narrative.py` from `guide/`, 3 into `api/routes/` from
`guide/` and `review/`, and one each into `cli.py` from `reader/`, into
`projector/` from `formats.py`, into `coach/narrative.py` from `review/`
and into `guide/rcq.py` from `metagame/`. `tests/` and `scripts/` add 31.

**Needs:** Promote the shared ones to public names, or pin them with a test.
No visible effect.

### BL-083 · Readers that filter `md.deck_id` against a set

type: perf · priority: P2 · status: ready · area: guide coach docs

`docs/architecture.md` ("Filter a deck through `v_match_deck` by match id")
says no reader joins the view and then filters `md.deck_id` against a set,
the shape measured 10 to 100 times slower. Seven queries do, counted
2026-10-21: `guide/field.py` (three), `guide/deck.py`, `guide/list_diff.py`,
`guide/bundle.py` and `coach/evidence.py`. Found by plan 35's reviewers.

**Needs:** Each converted to the `m.match_id IN (SELECT …)` form, or the
doc naming the exception and why.

### BL-084 · Test comments citing pins that don't exist

type: docs · priority: P3 · status: ready · area: metagame

Test comments cite labels no test or doc defines:
`tests/test_metagame_holds.py` ("k4", "k1", "k3"),
`tests/test_metagame_auto.py` ("Defect 1"), and `tests/test_formats.py`
says migration 053's CHECK is pinned to the format tuple, which no test
reads. Found by plan 35's reviewers.

**Needs:** Each comment says what it means in its own words, and 053's
CHECK gets a test or the claim goes.

## Outside the code

Steps that are the user's or a third party's, not the code's. None of the
questions to a third party (BL-076, BL-077, BL-078) has been asked, by
decision (2026-09-27): core work comes first, and nothing here blocks it.
Each of those items says what the other party's own pages already answer, as
read on that day, and what is left to ask. The user sends each question.
Such an item closes when the answer is recorded in `docs/attribution.md`.

### BL-070 · The Microsoft Store listing

type: chore · priority: P1 · status: blocked · area: release legal

The paid Microsoft Store listing (decided 2026-10-12, `ROADMAP.md`): the
Store build is the same app as the free download, listed free at release and
priced once the blockers under Needs clear; the free download stays free
(unsigned until an open-source signing programme takes it; see BL-072, "Code
signing").

**Why deferred:** The first release shipped without it. The Partner Center
account was created on 2026-10-20 as Individual (registration has been free
since Microsoft dropped the fee in September 2025), and the product identity
is reserved as an MSIX app, which the Store signs. 1.2.0's appx was
submitted on 2026-10-21 and passed certification the same day: the listing
(Store ID 9NZ5GQMCG1ZN) is live and free, in every market. What is left is
the price. The maintainer stays an individual, not a company, until income
asks otherwise.

**Needs:** Microsoft's answer on selling from an Individual developer
account, whose eligibility text names "non-commercial purposes" and "not in
relation to their business, trade, or profession", and whose type cannot be
changed later (a Company account is a new account and needs a registered
business or DUNS number). The Daybreak, TopDeck.gg and MTGOFormatData items
(BL-077, BL-078, BL-076). The Fan Content notice in `README.md` and
`docs/attribution.md` read again before anything is sold, by a Fable agent
where one is available and Opus otherwise (it is legal text): once anything
is sold, "permitted under the Fan Content Policy" is no longer true, and the
2026-10-12 check proposed a non-affiliation notice for that day. The policy
lets Wizards withdraw permission "for any reason or no reason", so the sale
stays reversible: the listing can go back to free. Decided 2026-10-12 (plan
9, D9): the listing goes up free and is priced once they answer.

### BL-071 · Launch leftovers: Sponsors and the credits perk

type: chore · priority: P3 · status: blocked · area: release

What is left of the launch (plan 9, S7): GitHub Sponsors' approval on the
`sensei-top` organisation, and the credits perk. Sponsors was still
unapproved at 1.0.0, and Stripe refused the maintainer's CPF, so PayPal
stands in as the worldwide link from 1.0.1 on the site and in `FUNDING.yml`,
beside Apoia.se (live at `https://apoia.se/senseitop` since 2026-10-12).
Perks never gate anything: credits, a roadmap vote, sponsor-a-feature; no
Discord role while there is no Discord. The credits perk has nothing to show
it yet: `web/src/credits.ts` and the Credits view list sources and software,
not supporters. No early builds for donors, because the policy forbids
requiring payment or a subscription for fan content.

**Why deferred:** Every part of it that lives in the tree is built
(2026-10-12): the site in `site/`, the tag-driven release job, the issue
forms and the funding file. What is left is the maintainer's own accounts.

**Needs:** The user's steps in plan `release-9-launch.md`, S7.

### BL-072 · Code signing

type: chore · priority: P3 · status: blocked · area: release legal

Code signing (decided 2026-10-07). Windows: a Microsoft Store individual
developer account, created on 2026-10-20 (registration has been free since
Microsoft dropped the fee in September 2025), so the Store build, reserved
as an MSIX app, is signed by the Store; the direct download is unsigned, and
`site/` and `INSTALL.md` tell the user how to get past SmartScreen. SignPath
Foundation turned the application down on 2026-10-13 (sent after the 0.7.1
release): not for the requirements, which the public snapshot and plan 9's
release job meet, but for too few public signals of trust (stars, forks,
contributors, outside articles and discussions, sustained activity). They
invited a new application once the project has broader recognition, so it is
sent again after the `1.0.0` launch has had time to produce those. If the
SmartScreen prompt costs users before then, the fallback is Certum's Open
Source Code Signing certificate (about EUR 49, cloud): its terms revoke a
certificate that signs "software distributed commercially", which the paid
Store build of the same app may trigger, so a Fable agent where one is
available and Opus otherwise reads them first (it is legal text). A standard
certificate does not clear SmartScreen at once either; reputation builds
with downloads. Microsoft's Artifact Signing (formerly Trusted Signing)
takes individuals only in the USA and Canada. SignPath's paid plan was not
taken. macOS: notarization (US$99 a year) when donations cover it.

### BL-073 · The trademark filing

type: chore · priority: P3 · status: needs-decision · area: legal

The trademark filing. Clearance searches were run before the name was taken,
but nothing was filed, by decision, for the first release. The name is used
as an unregistered mark (`TRADEMARK.md`). The filing date is what sets
priority, so the cost of waiting is that someone else files first.

### BL-074 · melee.gg's terms

type: chore · priority: P3 · status: blocked · area: legal metagame

melee.gg's terms, unread (2026-10-05). Sensei Top never fetches from
melee.gg; its paper events arrive through fbettega's cache, and the event
page links each one to its page there. The site refused a program's reading
(HTTP 403 on `/`, `/robots.txt` and `/Terms`), which was not worked around,
so its terms are unread.

**Needs:** What is left is a reading from a browser, by the user, for two
things: a clause on linking, and a claim to database rights over results.
Nothing to ask Melee unless that reading raises it.

### BL-075 · PT-BR wording left as is

type: fix · priority: P3 · status: needs-decision · area: i18n

The PT-BR wording left as is after plan 18's screenshot pass (2026-10-12),
each one cosmetic and a catalogue edit away:
`decks.overview.daysWithinMonth` renders "7 de set. a 8"; coach reports keep
their English section headings (the prompt contract); `/design` stays
English and Settings shows the raw model id; `decks.written.on` reads
"Escrito em {{day}}, sem autor registrado."; the Field's empty states put
the window in a parenthetical; and the restore-without-status sentence ("The
restore ended without a status code.") is new English wording chosen without
the user.

### BL-076 · MTGOFormatData's licence

type: chore · priority: P2 · status: blocked · area: legal archetypes

MTGOFormatData's licence. Neither repository has a licence file: the one
read first, and the fork tried when it cannot be reached. The maintainer
opened the question himself, in the repository's issue 148 (September 2025):
MIT, with each contributor asked to agree. Four of the six listed there
have, the maintainer among them, and the file has not been added. An
agreement in an issue is not a licence. What is left is a comment on that
issue, never a second issue. A free AGPL tracker reading the definitions is
the use the maintainer proposed MIT for, so the free download does not block
on the answer. The paid Store build and the subscription (2026-10-12) sell
an app that names decks from these definitions, so neither is sold until the
file lands. If it never does, deck naming falls back to the corpus read plus
rules written here.

### BL-077 · Daybreak's terms for mtgo.com

type: chore · priority: P2 · status: blocked · area: legal mtgo

Daybreak's terms for mtgo.com (2026-10-05). Read in full: the ToS
(2026-07-13), the MTGO EULA (2022-05-31), the API Policy on the Census page
(undated) and the Legal Notices (2026-08-24); recorded in the mtgo.com row
of `docs/attribution.md`. The pages answer the fetch: no clause on a program
reading the website, no `robots.txt`, load addressed only in general words;
ToS §14.3 lets fan sites and apps "share ... information about any Daybreak
Game(s)" and grants "Permission to link from the Fansite to the associated
Daybreak Website". The subscription question, closed on 2026-10-07 because
nothing was sold, is open again with the paid tier (2026-10-12). §14.3 names
paid downloads among the revenue a fan app may earn, and asks for a Fansite
license agreement before "a subscription or access fee". Before the paid
Store build is sold: whether §14.3(c), which permits charging "to download
your App(s)" but defines Apps as "mobile apps", reaches a desktop app, and
whether game data read from mtgo.com's pages rather than "acquired via
Daybreak's API" is inside the permission at all. Before the subscription
ships: the agreement, which that clause asks for in so many words, and the
request for a copy is the question. Before a hosted snapshot of the field
feed (`docs/llm.md`), which plan 9 left out and nothing builds: written
consent to redistribute the site's results (§7.1 "make available ... for any
commercial purposes"; §13(a) "distribute"), which no clause permits without
it. Not a question but a check, before that feed: the Census API's rendered
MTGO documentation lists no decklist collection, while its page source names
five; a service id the user registers settles whether they exist, and only a
"no" turns into a question for Daybreak.

### BL-078 · TopDeck.gg's terms

type: chore · priority: P2 · status: blocked · area: legal metagame

TopDeck.gg (2026-10-05, closed 2026-10-07, open again 2026-10-12). Read in
full: the API page (undated, API version 2026-07), the site's Terms and
Conditions and Privacy Policy (both 2022-03-01); recorded in the TopDeck.gg
row of `docs/attribution.md`. The pages answer the daily fetch and the event
page: "free to use, providing tournament data for your projects and
applications", a visible credit and link back required, rate limits with a
429 to wait out. The one open question is whether the grant covers a product
sold for money, with the TopDeck features in the free download and the
credit shown. It closed on 2026-10-07 because nothing was sold, and opened
again with the paid Store build and the subscription (2026-10-12); the
site's general Terms reserve its own content "solely for your personal use",
say its content "is not for resale" and forbid use that would "in any way
exploit any of the content"; only the API page's grant answers it today, and
the question to TopDeck should quote both. The fetch runs on the user's own
key.
