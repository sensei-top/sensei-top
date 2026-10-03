# Project status

Read this before starting a new feature, or when deciding what to pick up
next. It is the tracked record of what works today, what is limited on
purpose, and what is known to be missing. Debt used to live only in
gitignored handoff notes (`.claude/handoffs/`), and some of it was lost when
those notes were deleted. This file exists so that doesn't happen again.

**Keep it current.** When you finish something listed here, delete its row.
When you knowingly leave something behind, add one. A row says what is
wrong or missing, why it was deferred, and what picking it up needs. It does
not describe how to fix it, because that belongs to the session that does
the fix.

Last reviewed: 2026-10-02, for plan 12's MTGO deck pick (schema version
52, ~1,690 Python tests).

**The pivot, 2026-10-01.** The product became a competitive 1v1 companion
app for Arena and MTGO: every MTGO format that has archetype rules, no
Arena-only formats (Historic, Explorer, Timeless), no in-game overlay or
companion window, and never reading the memory of, injecting into or
automating either client. Draft was deleted rather than hidden
(`feature/remove-draft`; the last commit that has it is tagged
`archive/draft`), and its rows left with it. The rows the pivot
added are dated 2026-10-01.

## What works today

| Surface | Arena | MTGO | Notes |
|---|---|---|---|
| Ingest | live, `serve --watch` / `ingest --watch` | game logs read once at watcher startup, or by hand with `ingest-mtgo`; deck files (the `.dek` exports and MTGO's `grouping *.xml` deck store) polled every 30 s | A running watcher notices rows another process inserted and rebuilds on its next due poll (`docs/architecture.md`). |
| Win rate, play/draw, History, Matchups | yes | yes | History and metrics default to Arena and can switch to MTGO or all. |
| Match detail and match report | yes | yes | MTGO has no board-state stream, so its turn-based analyzers report gaps instead of building on zeros (`tests/test_review_mtgo.py`). |
| Leak finder, Coach | yes | yes | The coach pools both sources and reports them separately (`by_source`). An MTGO match's confirmed format decides whether it counts (`docs/coach.md`). |
| Deck guide, matchup briefs | yes | once the match's deck is picked | MTGO's transcript never names your deck, so the user confirms it on the match's page; Home lists the matches still waiting. The pick is `mtgo_match_pick`, read through `v_match_deck` (`docs/architecture.md`). |
| Current match (replay, keep guide, hand read, sideboard break) | yes | no, by design | `v_current_match` is Arena-only (migration 040), because MTGO has no stream for the replay to run against. |
| RCQ guide (`/decks/:id/guide/rcq`) | yes | once the deck is picked | One document for the exact 75 the user pastes, against the last 14 days of the field and the last 7 days of events; a Claude button writes it, `rcq --prompt/--import` is the offline path (`docs/guide.md`). The corpus now also reads mtgo.com directly, fresh to within hours (`docs/metagame.md`). |
| Field | — | — | The field's tournament corpus. It defaults to the window since the last format reset. Duplicate events are marked, not double-counted (migration 043). |

Every metered Claude call is a button press and nothing else (AGENTS.md
non-negotiable #5). `serve` refuses to bind anything but loopback, and
`api/guard.py` refuses a foreign `Host` or `Origin` and any write without the
dashboard's own header, so another page open in the browser can't use the
API either (`tests/test_guard.py`).

## Limited on purpose

These look like gaps but are decisions. Don't "fix" them without reopening
the decision.

- **MTGO never reaches a live view.** Its game logs are read once per
  watcher start and never polled (only its deck files are), and the Live
  page never shows it (AGENTS.md's repo
  map, `docs/current-match.md`). *Reopened 2026-10-01:* see "MTGO ingest
  while `serve` runs" under "Features not built".
- **Field matchup records are post-reset only.** Until one of the ranked
  tiers (A, then B, then D) has results after the last format reset, the
  report shows "no field sample" rather than pooling across a ban
  (`docs/metagame.md`).
- **A coach refusal surfaces as a bare 502.** The route has nothing more
  specific to say, and the prompt round trip still works.
- **`idx_raw_events_mtgo_id_file` is unused but kept.** Rebuilding it later
  would cost a full-table scan (see the comment in migration 040).
- **The opening-hand read is built on every current-match poll,** even with
  no match open, because the mulligan decision comes before the match row
  exists (`api/routes/current_match.py::current_match_read`).
- **The frontend's AbortSignal and visibility handling** were proposed and
  declined.

## Backlog register

### Features not built

| Item | Why deferred | Needs |
|---|---|---|
| `LICENSE` is a short proprietary notice, marked as a placeholder: copyright, a free-of-charge grant to run official builds, no redistribution or modification, no warranty. | Decided on 2026-10-01 with the move from AGPL-3.0-only to a closed client. Nobody outside the maintainer runs the software yet. | An end-user licence agreement, reviewed by someone qualified, shipped with the installer (plans 6 and 9). It also has to cover the Pro terms (plan 8). |
| Writing becomes Pro-only, and the copy-prompt path leaves the dashboard (decided 2026-10-01, `AGENTS.md` rule 5). `CopyPromptCard`, `CopyPromptBody` and the "Show the prompt" toggle are removed. An unconfigured surface shows the Pro call to action. There is no trial. Three tiers: free, with no writing; a free account, with one coach report and two deck guides a month; Pro, with five and ten (decided 2026-10-01, the numbers reviewed in plan 8). The account is for the hosted service only. The brief, coverage and sideboard-plan cards get CTA routes that write `matchup_brief`. A local `llm/config.py` credential becomes a development setting. `guide --import` and `brief --import` stay as CLI tools. | The hosted proxy doesn't exist yet. Removing the copy prompt before it ships leaves users no way to generate at all. | The plan 8 proxy. The new routes, added to rule 5's list and to `test_only_authored_artifact_routes_write`. The `GenerateCard` writer table without `nobody`'s copy body or `plan`'s used-allowance fallback. A rewrite of what `docs/frontend.md`, `docs/llm.md`, `docs/brief.md`, `docs/guide.md`, `docs/review.md`, `docs/architecture.md`, `docs/current-match.md` and `docs/design-system.md` say about the round trip. What the proxy receives, stated in plan 8 and the privacy notice. |
| An MTGO deck's cards that Arena never carried. A `decks` row from an MTGO export or the deck store holds only the cards that resolve to a `grp_id`; each other copy is a warning and is counted in `cards_json`'s unresolved count, which the match report and the leak finder treat as unknown cards (plan 12, D7 and D18). | Card identity beyond Arena's `grp_id` is plan 13's, which needs it before its format work. | Plan 13. |
| MTGO's `.txt` deck export is not read; only `.dek` exports and the deck store are (plan 12, D13). | No real `.txt` export exists to build a fixture from (rule 7). | A real `.txt` export, from the user or the VM. |
| Settings' Draft data section (`settings/SharingSection.tsx`), `components/sharing/` and the `Sharing`, `SharedDraft`, `DraftPayload` and `Deleted` types in `web/src/bridge.ts` describe drafts, which the app no longer reads. Nothing draws them outside `/design/surfaces`. | Kept on purpose when the draft assistant and the overlay's leftovers were removed (2026-10-01): plan 10 reworks them for match data rather than starting again. | Plan 10's payload and consent text, then the rework. |
| Formats other than Standard. `matches` has no format column; `cards.standard_legality` (migration 017) is the only legality column; about 140 hard-coded "standard" across about 25 Python files and 5 web files (counted 2026-10-01, not read one by one). Archetype definitions, metagame events, `decks` and the corpus are already keyed by format. | The tool grew on the author's Standard play. The pivot covers every MTGO format with archetype rules (Modern, Standard, Pauper, Legacy, Pioneer and Vintage) and Premodern. | Format inference findings for the 238 unidentified MTGO matches, then format as a parameter through `archetypes/`, `metagame/`, `guide/`, `coach/`, the routes and the Field page, with one quality pass per format. Premodern is in with the corpus prior only, since MTGOFormatData has no archetype rules for it; its rules come from an outside source if one exists, never written here, because it is not a Wizards-sanctioned format; Duel Commander is out (decided 2026-10-01). |
| The mtgo.com fetch (`metagame/mtgo_site.py`) is built for Standard only, and runs by hand (`meta --source mtgo`); `serve --watch` does not refresh the corpus. The hosted, scheduled refresh is plan 14's (decided 2026-10-01). | The local fetch shipped with the RCQ guide, after the terms reading of 2026-10-03 (`docs/attribution.md`). | Plan 14 reopens the commercial clauses of that reading before anything is hosted, then the format-parametric field above. |
| MTGO ingest while `serve` runs (see "Limited on purpose"). | MTGO rewrites a game's log while the game runs, so a naive poll would store a copy per rewrite. | A measured "quiet" threshold (a copy once the content stops changing, about one per game), fixture-backed, verified on the Windows VM. Whether the Live page shows MTGO's revealed cards (the log updates about every 7 s) is decided with it. Plan 3 builds that read and the between-games plan, with their Windows behaviour (plan 12, D12). |
| Community constructed data (decided 2026-10-01): opt-in, revocable contributions of finished matches from both clients, with the exact payload shown before it is sent. Aggregates stay in the app, free, labelled as user data and kept apart from the A–D tiers. No public dataset. | Needs the desktop app's onboarding and background loop, a privacy policy and the format column. The MTGO pick exists since 2026-10-02. | The standing-consent rule in AGENTS.md next to rule 5. The payload, the consent text naming both purposes (matchup statistics, card performance) and the retention period, reviewed by the user. An ingest endpoint and an aggregation job. |
| Mulligan plan "Layer 4": an authored mulligan plan in the guide's prompt/import round trip | Planned during the mulligan work and never built. The handoff that described it is gone. | A design pass: what the plan says, where it's stored (an authored-artifact table, rule 6), and how the keep guide shows it. |
| Coach breakdown per deck version | Deferred feature. Deck versions are split elsewhere (the guide) but not in the coach. | Reusing `guide/`'s identity split inside `coach/evidence.py`. |
| Deferred review analyzers (combat attack/block decisions, timing) | Future scope in `docs/review.md`. | Their own design. |
| The live replay's `deck_maindeck` (`projector/live_state.py`) only ever reads `connectResp.deckMessage` — game 1's submitted list, reused as-is for games 2/3 of a Bo3, even after a mid-match sideboard swap. The projector already parses that swap (`ClientMessageType_SubmitDeckResp`, `matches.py::_handle_submit_deck`) into `game_decks`; the live replay doesn't. | Scoped out of the mulligan-read-latency fix, which only needed *a* maindeck fast, not the boarded one. | Reading `ClientMessageType_SubmitDeckResp` into `LiveState` too, and preferring it once a break has happened this match. |

### Correctness: latent or unmeasured

| Item | Why deferred | Needs |
|---|---|---|
| Coach web-search citations are never stored. `sources_json` holds only the reading-list ids. | Diagnosing it needs a paid run. | The user's go-ahead for one coach run, then a read of the response's block types. |
| `cards.py::_backfill_by_name` only fills NULLs, so a later ban reaches the primary grpId row but never its siblings. | Zero names with conflicting legality in the real db as of 2026-09-23. | Its own session. Overwriting on an unambiguous name touches rule-4 reasoning. |
| `table/hand_read.py::_seen_elsewhere` counts per game, while the classifier counts per match. | The asymmetry is undocumented but harmless today. | A decision on which grain is right, then a doc line or a change. |
| `review/analyzers/baseline.py`'s `GAME_LENGTH_MIN_GAMES` gate counts projected games, so it couples to projection details. | Raised during review and left unchanged. | A look at whether the gate should count completed games only. |
| The deck guide's field shares group by archetype name, while the coach and brief coverage group by key. | Found in the coach↔guide helper consolidation, which kept behaviour byte-identical on purpose. | A decision on one grain, then a real-data diff of the guide output. |
| A deck's coverage table and a pairing's heading can show one label on rows of distinct archetype keys: `brief/coverage.py` labels a row `field_name or faced_name`, and the corpus files "Dimir Midrange" under more than one key, so two rows can read alike. | Found while rebuilding a deck's pages; telling the rows apart is a naming decision, not a patch. | Decide how a shared label is told apart (a qualifier in the label, or the address alone as the identity), then fix `coverageName` (`web/src/lib/brief.ts`) and `pairingHeading` (`web/src/lib/pairing.ts`). |
| The corpus-naming confidence constants are provisional (44% measured against a 60% target). | Needs more classified data. | A re-measurement against the corpus. |
| The coach's Limited filter (`coach/evidence.py::_is_limited_event`) does not know `PickTwoDraft`, so Pick-Two matches count as Constructed evidence. The real log of 2026-10-01 holds 5 (`PickTwoDraft_FRA_20260929`). The prefix list is the deleted draft projector's, which never had it either. | Found by the real-log check on `feature/remove-draft`, out of that branch's scope. | The prefix added, with a test over a real Pick-Two event id (rule 7), and a look at whether any other Limited queue (Sealed, Jump In) is missing. |
| TopDeck's non-constructed events (Commander, draft, sealed, cube, jumpstart, pre-release) are filtered by name only. `topdeck.py`'s `_NOT_CONSTRUCTED_RE` skips a matching event on fetch with a warning, and purges already-stored matching Topdeck events with their child rows after each refresh. The match has a leading word boundary only, so it can over-match ("Cubes", "Prelude" would also match). | TopDeck's own format field is not trusted: it labelled these events Standard (found when the base URL fix first returned data). | A look at what TopDeck's own fields say per event, and a fixture-backed tighter rule if over-matching shows up in the stored events (rule 7). |
| No paper source after 2026-08-16: fbettega's Melee data stops there, so paper RCQs reach the field only through TopDeck (needs the user's key). | Measured while planning the RCQ guide. | A working TopDeck run, or another paper source (`docs/attribution.md`, "Rules for a new source"). |
| MTGO draws and disconnects are untested. | No fixture captures either. | A real MTGO capture of each. |
| 9 of the 335 real MTGO game-log files project no match (326 matches, 2026-10-02). | Found in plan 12's real-data check, out of its scope. Not investigated: they may be logs with no finished match, or a drop. | Reading those files with `scripts/mtgo_probe.py`, then a warning for any that should have projected (rule 4). |
| The deck guide's deck-level format (`guide/deck.py`) and the coach's own-archetype read take an MTGO deck's format from `decks.format`, the store's `FormatCode`, not from the user's confirmed picks. | On purpose in plan 12: a deck's format is the deck's, and a pick is per match. | A decision on whether confirmed picks should override the store's format there. |
| `mtgo_read_at_startup` reports true when a directory resolved, even if the read itself failed. | Minor. The watcher logs the failure. | Plumbing the read's outcome through to the status route. |
| `serve` on SIGTERM orphans its watcher child. uvicorn 0.52.3's `capture_signals` re-raises SIGTERM after shutdown, so the process dies before `cmd_serve`'s `finally: watcher.stop()` runs. Ctrl-C (SIGINT) is fine. | Pre-existing. Found during the rework's reality check. | Stopping the children from a lifespan/shutdown hook rather than the `finally`, or ignoring the re-raise. |
| Segmenter entry shape 5 (a non-JSON response body) would swallow a header that came directly after `<==`. | Never observed in either real log. | Harden only if a capture shows it. DeckDeleteDeck's second body line falls through as noise, which is harmless. |
| Arena's 24-hour header timestamps (`reader/segmenter.py`) are pinned by string tests only. | No capture from a client set to a 24-hour clock exists; every real log so far is 12-hour. | A real 24-hour capture, added as a fixture (rule 7). |
| `tests/test_backup.py::test_config_is_re_resolved_every_check` fails now and then: 1 run in 5 when run alone, and once in a full run (2026-09-27). | A timing flake, met while reviewing another change. Not diagnosed. | Find the timing assumption in the test and make it deterministic. |
| Play and draw are not on the Matches page. | `/api/metrics/play-draw` answered 500 for MTGO when the page was built; it answers for every source now, deckless matches in one row per side. | Put the split on the page, or count it from the list's games as the band does. |
| No route lists the matches past the 500th or counts the matches of a filter. | Found while building the Matches page. The list says where it stops. | A design for paging. |
| Home's field card takes its art from the newest match against the first row's archetype key, not its key and label, so the art can come from a match against another label of that key. | Found while joining the field's records on key and label; the record moved, the art pick did not. | Pick the art by the row's key and label in `homeField` (`web/src/lib/home.ts`), as `recordAgainst` does. |

### Performance

| Item | Now | Needs |
|---|---|---|
| Coach page, warm | ~2.5 s. The report cache removed the per-match rebuild; what's left is non-report work. | Profiling `build_coach_evidence` outside `build_match_report`. |
| Coach narrative route (the prompt the page loads on every visit) | ~3.8 s | The same profile. |
| Sideboard break, cold path | ~2 s against a 1 s target (`brief/narrative`'s full prompt and consensus) | A cache, or trimming what the break needs from the brief. |
| Live page at the opening hand | Fixed on 2026-09-24. The delay was ingest waiting behind the match-boundary rebuild (22 s `project()` plus 2 s classify on a real database). Ingest now runs on its own thread. In a replayed match start on a 1.7 GB copy of the real database, the mulligan offers landed in 0.13 s, against 16–22 s before. The verdict had also been blank on 47% of Boros Dragons hands, because of Multiversal Passage's missing `produced_mana`. Replayed over the real hands, none are withheld now. What's left: `project()`'s own write lock (5.7 s measured) still holds up an ingest tick that lands during the commit. The ingest connection's 30 s `busy_timeout` waits it out rather than failing. | Shrinking the write lock, which means a smaller `BEGIN`…`COMMIT` in `project()`. |

### Code health

| Item | Needs |
|---|---|
| Nothing guards `web/src/types/api.ts` against drifting from the backend: `test_openapi_schema_is_generated` checks paths only. | A test that regenerates the types and diffs them, or a CI step. |
| 21 imports reach into another package's leading-underscore helpers (8 of them in `coach/evidence.py`). | Promote the shared ones to public names, or pin them with a test. |
| Big file: `review/snapshot.py::build_snapshot` (~490 lines) | Out of scope for the sweep. Split it when a feature next touches it. |
| `NBSP` is a private constant in eight files under `web/src`; `lib/matchups.ts` exports one. `lib/scrollSpy.ts` imports `scrollEdge` and `spyCurrent` from `lib/guide.ts`, a hook depending on one page's module. | Import `NBSP` from one place; move the two spy functions beside the hook. |
| `projector/matches.py` calls `mtgo.config.load_handle()` on every `project()`, so a config file with no `[mtgo]` table (an Arena-only user with a Claude key, say) logs a warning on every rebuild. | Loading the handle only when MTGO `raw_events` exist, or a silent absence like `resolve_log_dir()`'s. |
| Several tracked files (`git grep -l '\.claude/handoffs'`) cite notes under the gitignored `.claude/handoffs/`, so the citations dangle for anyone else reading the repo. | A wording pass before a public release: state what the note established, or drop the citation. |
| `docs/guide.md`'s `narrative.py` section justifies the guide prompt's size by quoting an AGENTS.md "outbound-call standard" that AGENTS.md no longer states. | Restating the reasoning in `docs/guide.md` itself, or dropping the quote. |
| A build carries no licence texts: not for the npm and Python libraries it bundles, and not the SIL Open Font License its fonts and mana glyphs are under. The credits view and `docs/attribution.md` list the fonts and the mana glyphs with their copyright notices and a link to the licence. The bundled libraries are not listed at all. | A packaging step that collects the texts, when the installer is built. |

### Data the real database still carries

`raw_events` is append-only (non-negotiable #2), so these stay unless the db
is rebuilt from logs that no longer exist. The projector already copes with
each of them.

- About 1,700 duplicate request rows from before the reader persisted its
  carry state (migration 042). `project()` dedups them by request id, so
  derived tables are unaffected.
- 15 old `DeckDeleteDeck` rows that swallowed the lines after them before the
  segmenter learned non-JSON bodies. The swallowed requests stay inside those
  rows, and recovering them is not planned.
- About 2,200 MTGO card events whose names Arena never printed (City of
  Brass, The Rack…) keep a NULL `grp_id`, one warning per name per rebuild.
  They only occur in matches that are already `not_legal` or have too few
  cards, so no verdict depends on them.

### Waiting on the user

- The mulligan offer's real ingest lag, once a session has run on the
  two-thread watcher. Compare `raw_events.ingested_at` against `logged_at`
  (which is local time, UTC−3) for rows carrying
  `ClientMessageType_MulliganResp`. Before the fix: median 3.1 s, p90 13.3 s
  (n = 1,099). Target: median ~1 s, p90 ≤ 6 s, the bound the write lock sets.
- The backup's real cost. Every daily run records its duration in
  `backup_state.last_duration_ms` (`sqlite3 "file:data/sensei-top.db?mode=ro"
  "SELECT last_duration_ms FROM backup_state"`); read it after a few runs and
  put it in `docs/architecture.md`'s Backups section. The WAL peak there is
  still an estimate, because nothing records it.
- The Windows 10 VM's setup for the windows-runner agent (2026-10-01). It is
  the user's to do, since it changes their system: the OpenSSH Server
  optional feature, a revocable key (for an admin account it goes in
  `C:\ProgramData\ssh\administrators_authorized_keys`), a static lease
  on libvirt's network, and uv and git in the VM. The VM is where the user
  plays MTGO, so the agent stops if `MTGO.exe` is running.
- A public source release: not planned. The client is proprietary, decided
  on 2026-10-01 "for now" (`LICENSE`), and no copy was ever published under
  the AGPL-3.0-only licence it replaced. The one-commit snapshot and its
  address, `https://github.com/sensei-top/sensei-top`, are on hold rather
  than cancelled. The working repository stays private. If the client is
  opened again, what was established on 2026-09-27 still holds:
  - The history cannot be published. `scripts/privacy_scan.py --history`
    found local paths in old versions of `README.md`, `tests/conftest.py`
    and the MTGO reader, the MTGO handle in old versions of
    `tests/test_llm.py`, and the author's identity on every commit. The tree
    itself scanned clean.
  - So the source goes out as a fresh one-commit snapshot in a new
    repository, never over this one: GitHub keeps every pull request's
    commits under `refs/pull/*`, where rewriting a branch does not reach
    them.
  - The snapshot's commits identify the maintainer: the name git records
    today, and GitHub's no-reply address for the maintainer's account.
    `--history` reads every commit's author and committer, so it cannot
    pass there as written. That release settles how the scan accepts the
    log's own identity fields while still refusing them in a file.
- The trademark filing. Clearance searches were run before the name was
  taken, but nothing was filed, by decision, for the first release. The
  name is used as an unregistered mark (`TRADEMARK.md`). The filing date is
  what sets priority, so the cost of waiting is that someone else files
  first.
- A code-signing certificate, paid. The free routes, SignPath's
  open-source tier and Certum's open-source certificate, both require
  open source, and the client is proprietary since 2026-10-01. The choice
  is made when a Windows release is being prepared (plan 9). Until a
  certificate is bought, a Windows release is unsigned.

### Waiting on a third party

None of these has been asked, by decision (2026-09-27): core work comes
first, and nothing below blocks it. Each row says what the other party's
own pages already answer, as read on that day, and what is left to ask.
The user sends each question. A row leaves this list when the answer is
recorded in `docs/attribution.md`.

- **MTGOFormatData's licence.** Neither repository has a licence file: the
  one read first, and the fork tried when it cannot be reached. The
  maintainer opened the question himself, in the repository's issue 148
  (September 2025): MIT, with each contributor asked to agree. Four of the
  six listed there have, the maintainer among them, and the file has not
  been added. An agreement in an issue is not a licence. What is left is a
  comment on that issue, never a second issue. A hosted paid tier cannot
  launch on the data until the file lands. If it never does, deck naming
  falls back to the corpus read plus rules written here.
- **Daybreak's terms for mtgo.com** (2026-10-01). The ToS (updated
  2026-07-13) and the MTGO EULA (2022-05-31) were read only through a
  summary, which found no clause on automated access to the website. ToS
  §14.3 lets fan sites and apps use game data "acquired via Daybreak's
  API, subject to Daybreak's API Policy", and that policy is unread. There
  is no `robots.txt`. What is left is a full reading of all three before
  any code fetches; asking Daybreak is a later step, and only if the
  reading leaves a question.
