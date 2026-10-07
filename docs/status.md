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

Last reviewed: 2026-10-07, for the repositioning to free software funded
by donations (schema version 62, ~2,670 Python tests).

**The repositioning, 2026-10-07.** The licence is AGPL-3.0-only again, the
Pro tiers, the hosted proxy and the account are gone, and the copy-prompt
round trip stays beside the user's own key. Donations fund the work and buy
nothing inside the app, because the Fan Content Policy forbids charging for
it. The public plan is `ROADMAP.md` at the repository root. The rows this
added are dated 2026-10-07; the rows it removed were the EULA, the Pro
writing path and the two third-party questions that only a sold product
raised.

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
| Ingest | live, `serve --watch` / `ingest --watch` | live too: the watcher checks game logs every 2 s and stores each game once it ends (`docs/architecture.md`, "MTGO's game logs"), or by hand with `ingest-mtgo`; deck files (the `.dek` exports and MTGO's `grouping *.xml` deck store) polled every 30 s | A running watcher notices rows another process inserted and rebuilds on its next due poll (`docs/architecture.md`). |
| Win rate, play/draw, History, Matchups | yes | yes | History and metrics default to Arena and can switch to MTGO or all. |
| Match detail and match report | yes | yes | MTGO has no board-state stream, so its turn-based analyzers report gaps instead of building on zeros (`tests/test_review_mtgo.py`). |
| Leak finder, Coach | yes | yes | The coach pools both sources and reports them separately (`by_source`). A report is for one format: habits are read across every format played, a deck's and an opponent's records from that format alone. A match counts under its format, an MTGO one under the format the user confirmed, else the one its revealed cards fit (`docs/coach.md`). |
| Deck guide, matchup briefs | yes | once the match's deck is picked | MTGO's transcript never names your deck, so the user confirms it on the match's page; Home lists the matches still waiting. The pick is `mtgo_match_pick`, read through `v_match_deck` (`docs/architecture.md`). |
| Current match (replay, keep guide, hand read, sideboard break) | yes | no, by design | `v_current_match` is Arena-only (migration 040), because MTGO has no stream for the replay to run against. |
| RCQ guide (`/decks/:id/guide/rcq`) | yes | once the deck is picked | One document for the exact 75 the user pastes, against the last 14 days of the field and the last 7 days of events; a Claude button writes it, `rcq --prompt/--import` is the offline path (`docs/guide.md`). The corpus now also reads mtgo.com directly, fresh to within hours (`docs/metagame.md`). |
| Field | — | — | The field's tournament corpus, one format at a time (`?format=`, by default the format of the most recent match). It defaults to the window since that format's last reset. Duplicate events are marked, not double-counted (migration 043). Each stored event is listed and has a page of its own (`/field/events/…`): every deck's standing, archetype and list, and a link to where the results were published. `serve` keeps the corpus current on its own (`docs/metagame.md`, "Fetching the corpus"). |

Every metered Claude call is a button press and nothing else (AGENTS.md
non-negotiable #5). `serve` refuses to bind anything but loopback, and
`api/guard.py` refuses a foreign `Host` or `Origin` and any write without the
dashboard's own header, so another page open in the browser can't use the
API either (`tests/test_guard.py`).

## Limited on purpose

These look like gaps but are decisions. Don't "fix" them without reopening
the decision.

- **MTGO never reaches the Live page.** Since plan 3 the watcher stores
  each MTGO game once it ends, so History and the metrics follow a session
  as it is played, but the current-match reads stay Arena-only
  (`docs/current-match.md`). See "MTGO on the Live page" under "Features not
  built".
- **CI runs on pull requests only, and by hand.** The working repo is
  private and a run costs about 20 of the month's 2,000 Actions minutes
  (`docs/testing.md`, "CI"). The public repository (the one-commit
  snapshot, below) gets unmetered minutes, so the rule is revisited there.
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
| A provider adapter for the generate routes (decided 2026-10-07, `AGENTS.md` rule 5, `docs/llm.md`): the credential becomes a provider, a base URL, a key and a model id, so the five routes can call Anthropic, any OpenAI-compatible endpoint or a local model (Ollama, LM Studio). Each stored narrative is labelled with the model that wrote it; the coach's web search degrades to the reading list on a provider without it; an unknown model prices `NULL`. The brief, coverage and sideboard-plan cards get a generate route with it. | The repositioning made the user's own credential the only writing path, and "any model" was the research's second-most-asked thing after "no account". Not started. | Its plan (`~/.claude/plans/release-16-provider-adapter.md`, outline). One adapter per protocol under `llm/`, `llm/config.py` widened, a `model` column on every narrative table (one migration), `REPORT_MODELS` reworked into a per-provider list, Settings' Writing section, and the route additions to rule 5's list and `test_only_authored_artifact_routes_write`. |
| Sideboard help without a model (decided 2026-10-07): the user's own post-board record per matchup from Arena's `game_decks` (migration 024; MTGO's log has no ins/outs), candidate ins by a card-role rule over the 75 (answers, threats, hate by the opponent's archetype), and a link to a sideboard guide for the pairing from the Skill Issue Magic guide index. No generated outs. | The research's most-wanted feature, and the one every competitor sells a model for; the index's creator was asked on 2026-10-07, in exchange for credit on each link, and had not answered. Not started. | The creator's yes, recorded in `docs/attribution.md` with a row for the index ("Rules for a new source"): the published CSV's address and shape, an alias table from the index's archetype names to the corpus keys, a scheduled fail-soft fetch kept in cache, never any guide content copied. Plan `release-17-sideboard-referrals.md` (outline). |
| A translation layer, then Brazilian Portuguese (decided 2026-10-07: English at launch, PT-BR first on the public roadmap). Measured 2026-10-07: 146 non-test `.tsx` files, about 210 JSX text nodes and 494 quoted labels, no i18n library and `Intl` in one file; 27 prose fields in `api/models`, about 20 backend modules that build English sentences, six prompt modules. | Keying every string before launch means no string written after it is English-only; translating before launch would have delayed it. | Plan `release-18-i18n.md` (outline): a library and a key convention in `web/`, `gettext` behind `Accept-Language` on the API's prose fields, the prompts left in English, a glossary for Magic terms that stay untranslated, then the PT-BR catalogue and a LigaMagic post. |
| The launch setup (decided 2026-10-07, `ROADMAP.md`): a one-screen landing page (the match history first, downloads, the privacy promise, the not-planned list, donation links, the Fan Content notice), GitHub Discussions, two donation platforms at most (Apoia.se for Brazil, GitHub Sponsors or Patreon elsewhere), an X account, launch posts per venue that never say "AI"; a Discord later. Perks never gate anything: credits, a Discord role, a roadmap vote, sponsor-a-feature. No early builds for donors, because the policy forbids requiring payment or a subscription for fan content. | Waits on the public snapshot and the first installer. | Plan `release-9-launch.md`, revised 2026-10-07. |
| A daily version check against a static file of ours, disclosed in the README and switchable in Settings; a user-made diagnostics bundle, redacted before it is written; cookieless website counts (GoatCounter or Cloudflare) and GitHub's release download counts. No telemetry, no account. | The only measurement the no-account decision leaves; opt-in match contributions are revisited on real usage. | Plan 6 (the shell owns the check and the bundle), plan 9 (the site). |
| A macOS build, Arena-only, unsigned, from GitHub's free macOS runners once the repository is public; notarization when donations cover the Apple fee. | Linux and Windows ship first (decided 2026-10-07). | Plan 6 phase 5. |
| MTGO's `.txt` deck export is not read; only `.dek` exports and the deck store are (plan 12, D13). | No real `.txt` export exists to build a fixture from (rule 7). | A real `.txt` export, from the user or the VM. |
| Settings' Draft data section (`settings/SharingSection.tsx`), `components/sharing/` and the `Sharing`, `SharedDraft`, `DraftPayload` and `Deleted` types in `web/src/bridge.ts` describe drafts, which the app no longer reads. Nothing draws them outside `/design/surfaces`. | Kept on purpose when the draft assistant and the overlay's leftovers were removed (2026-10-01): plan 10 reworks them for match data rather than starting again. | Plan 10's payload and consent text, then the rework. |
| Formats beyond what plan 13 built. Plan 13 made the format a parameter for the seven formats in `formats.FORMATS` (Standard, Pioneer, Modern, Pauper, Legacy, Vintage, Premodern): legality per format (`card_legality`, migration 053, in place of `cards.standard_legality`); a match's format (`matches.format`, 055, read through `v_match_format`: the log's, then the MTGO pick, then the format the revealed cards fit); and per-format archetype rules, corpus prior, consensus, reset window, field record, leaks and coach reports, with a format choice on the Field and Coach pages. Left out: Arena-only formats (Historic, Explorer, Timeless) and Duel Commander; Premodern's archetype rules, so its opponents are named by colours and signature card only; a date-aware ban or rotation history (Scryfall's ban list is today's, so a ban never takes a match out of its format); "&" names (below); collecting match data (plan 10). The corpus follows Standard, Modern and every format it already holds an event in, and `sensei-top meta --format X` adds another (`docs/metagame.md`, "Fetching the corpus"); the quality pass (`docs/metagame.md`, "Formats: how well each is named") covers Standard, Modern and Pauper's corpus. | Decided with the user, 2026-10-02 (plan 13, D10 and D11): fetch what is played, and never write Premodern rules here, because it is not a Wizards-sanctioned format. | Per format: switching its fetch on, then its quality pass. Premodern rules only from an outside source, if one exists. |
| MTGO on the Live page: the opponent's revealed cards during a game (the log is rewritten about every 7 s) and the between-games plan (see "Limited on purpose"). | Moved out of plan 3, which built the ingest it stands on (plan 3, D1): it is a `table/`, API and Live-page feature, and migration 040 made the current-match view Arena-only. | Plan 15. |
| Community constructed data (decided 2026-10-01): opt-in, revocable contributions of finished matches from both clients, with the exact payload shown before it is sent. Aggregates stay in the app, free, labelled as user data and kept apart from the A–D tiers. No public dataset. | Later, on purpose (2026-10-07): the research put "no account, no upload" above every other objection, so this is revisited once real usage shows a number worth it. Needs the desktop app's onboarding and background loop, a privacy policy and the format column. The MTGO pick exists since 2026-10-02. | The standing-consent rule in AGENTS.md next to rule 5. The payload, the consent text naming both purposes (matchup statistics, card performance) and the retention period, reviewed by the user. An ingest endpoint and an aggregation job. |
| Mulligan plan "Layer 4": an authored mulligan plan in the guide's prompt/import round trip | Planned during the mulligan work and never built. The handoff that described it is gone. | A design pass: what the plan says, where it's stored (an authored-artifact table, rule 6), and how the keep guide shows it. |
| Coach breakdown per deck version | Deferred feature. Deck versions are split elsewhere (the guide) but not in the coach. | Reusing `guide/`'s identity split inside `coach/evidence.py`. |
| Deferred review analyzers (combat attack/block decisions, timing) | Future scope in `docs/review.md`. | Their own design. |
| The live replay's `deck_maindeck` (`projector/live_state.py`) only ever reads `connectResp.deckMessage` — game 1's submitted list, reused as-is for games 2/3 of a Bo3, even after a mid-match sideboard swap. The projector already parses that swap (`ClientMessageType_SubmitDeckResp`, `matches.py::_handle_submit_deck`) into `game_decks`; the live replay doesn't. | Scoped out of the mulligan-read-latency fix, which only needed *a* maindeck fast, not the boarded one. | Reading `ClientMessageType_SubmitDeckResp` into `LiveState` too, and preferring it once a break has happened this match. |

### Correctness: latent or unmeasured

| Item | Why deferred | Needs |
|---|---|---|
| Coach web-search citations are never stored. `sources_json` holds only the reading-list ids. | Diagnosing it needs a paid run. | The user's go-ahead for one coach run, then a read of the response's block types. |
| A prepare spell half that several cards share has no legality and no `oracle_id`: Reality Fracture's "Peer Review" is the back of three different creatures, so `cards.py::_backfill_by_name` skips the face name as two cards sharing it (15 face grp_ids across five names). No match's format read depends on one: MTGO resolves the combined name, and no MTGO match sat at `unknown_legality` on 2026-10-05. | The skip is the guard that keeps Odyssey's Careful Study apart from an Arena face; loosening it for shared faces is its own change. | A rule telling a face shared by several cards (same face, different whole cards) from an unrelated card of the same name, then a test over a real `prepare` line. |
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
| A deck's format (`guide/deck.py::identity_format`) is its `decks.format` when that names one of the seven formats, the store's `FormatCode` for an MTGO deck; only otherwise does it come from its matches' formats, the user's confirmed picks among them (plan 13, D15). A pick never overrides the store's format. | On purpose in plan 12: a deck's format is the deck's, and a pick is per match. | A decision on whether confirmed picks should override the store's format there. |
| `mtgo_watching` reports true while the running watcher has an MTGO directory, even while that directory is unreachable (a share not mounted, a folder MTGO moved). | Minor. The watcher logs each failed check. | Plumbing the last check's outcome through to the status route. |
| A watcher child that dies on its own is not restarted: `serve` logs one ERROR, `/api/live` reports `watcher_stopped`, and the status pill and a callout above every branch of the Live page say so, but nothing is ingested until the tracker is restarted. | Decided against an in-process restart: forking after `serve`'s threads have started is unsafe (`procs.py`), and a spawned child loses the fork-time guarantees. | Supervision in plan 6's desktop shell. |
| On Windows a file another process holds open cannot be renamed unless it was opened with `FILE_SHARE_DELETE`, which Python's `open()` never asks for (`WinError 32`). Arena renames `Player.log` to `Player-prev.log` at launch, so a launch that lands inside one of the watcher's reads would fail that rename, with an effect on Arena's side nobody has seen. The watcher holds no handle between polls, so the window is one read a second. | Found in plan 3's Windows work; never observed. | A capture of the failure, then opening the log through `CreateFileW` with the flag (and `msvcrt.open_osfhandle`). |
| A `Turn` number in an MTGO game log longer than 4,300 digits raises `ValueError` out of `project_mtgo` (Python's integer-string limit), halting the rebuild instead of warning (rule 4). | Found in plan 3's review; no real log comes near it. | The parse guarded by a length check that warns and skips the line, with a test. |
| A database or backup path given as a UNC path (`\\server\share\…`) fails where it is opened read-only: those opens use SQLite's URI form, and SQLite rejects the `file://server/…` URI a UNC path becomes. A mapped drive letter works, since the URI is built from `Path.absolute()`, not `resolve()`. | Found in plan 3's Windows work (S2); out of its scope. | Building a URI SQLite accepts from a UNC path, or refusing one with a message. |
| Not checked on Windows: `pnpm start` (the dashboard build plus `serve --watch` in one), and the daily backup to a mapped network drive. | Out of plan 3's hand checks on the VM. | One run of each on a Windows machine. |
| `config` says it wrote the file "mode 600" (`cli.py`'s `path.chmod(0o600)`), but on Windows `chmod` only sets or clears the read-only flag, so the file holding the credential is as readable as anything else in the user's profile. | Found in plan 3 (S4); the user's profile is the boundary there for now. | A Windows wording for the message, and a decision on where a credential belongs on Windows (plan 6). |
| Segmenter entry shape 5 (a non-JSON response body) would swallow a header that came directly after `<==`. | Never observed in either real log. | Harden only if a capture shows it. DeckDeleteDeck's second body line falls through as noise, which is harmless. |
| An entry stored with no time by `--locale auto` (`reader/dates.py`, step 6) gets a dated twin if the same bytes are read again once its shape's order is learned (`ingest --file` reads from the start), because the digest includes `logged_at`. A `--locale` change between two reads of one file does the same. | Known when `auto` was built (plan 3, S10); out of its scope. | Re-deriving `logged_at` from `raw_events.header`, which migration 062 keeps for this. |
| Whether Windows' regional format reaches Arena's header while Arena is in English is not known. The header followed the in-game language in all eight captured languages. | Every capture so far ran under Proton, where setting the locale did not change the header. | One Windows capture with Arena in English and a day-first regional format. A new shape is a fixture and a row in `docs/arena-log.md`'s table; a day-first `slash-12h` header is one `auto` already settles. |
| `tests/test_backup.py::test_config_is_re_resolved_every_check` fails now and then: 1 run in 5 when run alone, and once in a full run (2026-09-27). | A timing flake, met while reviewing another change. Not diagnosed. | Find the timing assumption in the test and make it deterministic. |
| Play and draw are not on the Matches page. | `/api/metrics/play-draw` answered 500 for MTGO when the page was built; it answers for every source now, deckless matches in one row per side. | Put the split on the page, or count it from the list's games as the band does. |
| No route lists the matches past the 500th or counts the matches of a filter. | Found while building the Matches page. The list says where it stops. | A design for paging. |
| Home's field card takes its art from the newest match against the first row's archetype key, not its key and label, so the art can come from a match against another label of that key. | Found while joining the field's records on key and label; the record moved, the art pick did not. | Pick the art by the row's key and label in `homeField` (`web/src/lib/home.ts`), as `recordAgainst` does. |
| A deck's Matchups and pairing pages (`web/src/lib/matchups.ts::matchupRows`) group its matches by `opponent_key` alone, not by format and key. An MTGO deck whose matches were picked as different formats would mix them in one row. | Safe while a deck's matches share one format: D15 gives the deck one, and on 2026-10-04 no deck in the real history had matches in more than one. | Rows keyed on format and key, and a format in the pairing's address. |
| Arena's Day and Night rows share one oracle_id, given by `cards.py`'s name backfill, which suppresses Night // Day's synthetic row. Which card's oracle_id it is was not verified (most likely Night // Day's). | Found in plan 13's review; outside its scope. | A read of the rows in a scratch copy, then a decision on whether the backfill should skip the pair. |
| Arena's "Wheel of Fortune" (60053) carries no oracle_id or legality, and its name is shared in Scryfall's export by another card's face, so an MTGO "Wheel of Fortune" resolves to NULL (`projector/mtgo/project.py::_lookup`). Whether a shared name resolves at all depends on which Arena rows happen to match an `arena_id` in the export. | Found in plan 13's review; NULL with a warning is the rule-4 answer. | A way to tell the shared name's cards apart, or a decision that NULL stays. |
| `_lookup` (`projector/mtgo/project.py`) takes the lowest positive id among same-name rows. That lands Swords to Plowshares (59771), Ancestral Recall (59671) and Fast // Furious (76075) on rows with no legality, though another row of the same name has one, so a match revealing them can't be judged on that card. | Predates plan 13; found in its review. Not pinned by a test, nor is the shared single front-face candidate. | Preferring a row that carries legality, with a fixture-backed test (rule 7). |
| On the live brief (`api/routes/current_match.py::_brief_response`) the format check runs before `read_brief`, so a deck with no format answers `format_unknown` even when a brief is stored; the pairing page (`web/src/lib/pairing.ts::briefState`) shows the stored brief. | Found in plan 13's docs pass. | Reading the stored brief first, with a test. |
| `api/sql.py::_report_inputs_token` does not hash `match_format_inference`, so a changed inferred format clears the shared report cache only indirectly. | Predates plan 13; found in its review, optional there. | The table added to the token, with a test that a changed inference misses the cache. |
| The Modern corpus names an archetype "GoryoReanimator", with no space; `docs/metagame.md` lists the other names like it. | The name comes from the downloaded definitions, not from this code. | A display-name rule, or a report upstream. |
| "&" names (*Wear & Tear*) never resolve on MTGO and stay unresolved with a warning (plan 13, D16), counted in `cards_json`'s unresolved count, which the match report and the leak finder treat as unknown cards. Split-card halves resolve by the back-face rule since plan 13. | No fixture holds one (rule 7). | A real capture naming one. |

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
| 21 imports reach into another package's leading-underscore helpers (8 of them in `coach/evidence.py`). | Promote the shared ones to public names, or pin them with a test. |
| Big file: `review/snapshot.py::build_snapshot` (~490 lines) | Out of scope for the sweep. Split it when a feature next touches it. |
| `NBSP` is a private constant in eight files under `web/src`; `lib/matchups.ts` exports one. `lib/scrollSpy.ts` imports `scrollEdge` and `spyCurrent` from `lib/guide.ts`, a hook depending on one page's module. | Import `NBSP` from one place; move the two spy functions beside the hook. |
| `projector/matches.py` calls `mtgo.config.load_handle()` on every `project()`, so a config file with no `[mtgo]` table (an Arena-only user with a Claude key, say) logs a warning on every rebuild. | Loading the handle only when MTGO `raw_events` exist, or a silent absence like `resolve_log_dir()`'s. |
| Several tracked files (`git grep -l '\.claude/handoffs'`) cite notes under the gitignored `.claude/handoffs/`, so the citations dangle for anyone else reading the repo. | A wording pass before a public release: state what the note established, or drop the citation. |
| The dashboard still carries the paid plan's surfaces, dead since 2026-10-07: the `plan` writer and its two `GenerateCard` states (`lib/writer.ts`, `docs/frontend.md`, "Writing prose"), `settings/PlanSection.tsx`, `settings/SyncSection.tsx`, the `plan` and `sync` fields of the shell bridge, and the paid-plan half of `/design/surfaces`. Nothing draws them without a shell that offers a plan, and none will. | Remove them on a branch of their own, with the `docs/frontend.md` rows and the bridge types; plan 11's cloud sync goes with them, since it needed an account. |
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
- MTGO card events whose names the card database doesn't hold keep a NULL
  `grp_id`, one warning per name per rebuild. Since plan 13 such a card
  holds back its match's format inference (`unresolved_cards`, tokens and
  game markers exempt): on 2026-10-05, 4 of the 15 MTGO matches with no
  format were held back this way, all by the same name
  (`docs/metagame.md`).

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
- The public source release (planned, `ROADMAP.md`). The licence is
  AGPL-3.0-only since 2026-10-07; between 2026-10-01 and then it was a
  proprietary notice, and no copy was published under either. The
  address is `https://github.com/sensei-top/sensei-top`, a repository that
  does not exist yet. What was established on 2026-09-27 holds:
  - The history cannot be published. `scripts/privacy_scan.py --history`
    found local paths in old versions of `README.md`, `tests/conftest.py`
    and the MTGO reader, the MTGO handle in old versions of
    `tests/test_llm.py`, and the author's identity on every commit. The tree
    itself scanned clean.
  - So the source goes out as a fresh one-commit snapshot in a new
    repository, never over this one: GitHub keeps every pull request's
    commits under `refs/pull/*`, where rewriting a branch does not reach
    them. The README says why the history starts there. The working
    repository stays private as the record.
  - The snapshot's commits identify the maintainer: the name git records
    today, and GitHub's no-reply address for the maintainer's account.
    `--history` reads every commit's author and committer, so it cannot
    pass there as written. That release settles how the scan accepts the
    log's own identity fields while still refusing them in a file.
  - `sourceUrl` in `web/src/credits.ts` is set to the address in the same
    change, and `CONTRIBUTING.md`, `DCO` and `CODE_OF_CONDUCT.md`, restored
    on 2026-10-07, are what a contributor reads.
- The trademark filing. Clearance searches were run before the name was
  taken, but nothing was filed, by decision, for the first release. The
  name is used as an unregistered mark (`TRADEMARK.md`). The filing date is
  what sets priority, so the cost of waiting is that someone else files
  first.
- Code signing (decided 2026-10-07). Windows: a Microsoft Store individual
  developer account (about US$20 once), which the user agreed to pay, so the
  Store build is signed by the Store; the direct download is unsigned until
  SignPath's open-source program answers. Its requirements, read 2026-10-07
  (`about.signpath.io/product/open-source`, `signpath.org/terms`): an
  OSI-approved licence with no commercial dual licensing, no proprietary
  components, a public repository, free downloads, a project that is
  actively maintained and already released, the functionality described
  on the download page, and a fully automated CI build for the
  foundation's certificate. Every one is met by the public snapshot plus
  plan 9's release job, so the application is sent after the first
  release. macOS: notarization (US$99 a year) when donations cover it.
- melee.gg's terms, unread (2026-10-05). Sensei Top never fetches from
  melee.gg; its paper events arrive through fbettega's cache, and the
  event page links each one to its page there. The site refused a
  program's reading (HTTP 403 on `/`, `/robots.txt` and `/Terms`), which
  was not worked around, so its terms are unread. What is left is a
  reading from a browser, by the user, for two things: a clause on
  linking, and a claim to database rights over results. Nothing to ask
  Melee unless that reading raises it.

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
  comment on that issue, never a second issue. Nothing is sold on the
  data (2026-10-07), so nothing blocks on the answer; a free AGPL tracker
  reading the definitions is the use the maintainer proposed MIT for. If
  the file never lands, deck naming falls back to the corpus read plus
  rules written here.
- **Daybreak's terms for mtgo.com** (2026-10-05). Read in full: the ToS
  (2026-07-13), the MTGO EULA (2022-05-31), the API Policy on the Census
  page (undated) and the Legal Notices (2026-08-24); recorded in the mtgo.com
  row of `docs/attribution.md`. The pages answer the fetch: no clause on a
  program reading the website, no `robots.txt`, load addressed only in
  general words; ToS §14.3 lets fan sites and apps "share ... information
  about any Daybreak Game(s)" and grants "Permission to link from the
  Fansite to the associated Daybreak Website". One question is left, tied
  to the hosted snapshot; the subscription question closed on 2026-10-07,
  since nothing is sold and §14.3 names "a subscription or access fee",
  which a donation is not. Before plan 9's snapshot: written consent to redistribute
  the site's results (§7.1 "make available ... for any commercial purposes";
  §13(a) "distribute"), which no clause permits without it. Not a question
  but a check, for plan 9: the Census API's rendered MTGO documentation lists
  no decklist collection, while its page source names five; a service id the
  user registers settles whether they exist, and only a "no" turns into a
  question for Daybreak.
- **TopDeck.gg** (2026-10-05, closed 2026-10-07). Read in full: the API
  page (undated, API version 2026-07), the site's Terms and Conditions and
  Privacy Policy (both 2022-03-01); recorded in the TopDeck.gg row of
  `docs/attribution.md`. The pages answer the daily fetch and the event
  page: "free to use, providing tournament data for your projects and
  applications", a visible credit and link back required, rate limits with
  a 429 to wait out. The one open question was whether the grant covered a
  product sold for money; no product is sold, so nothing is left to ask.
  The fetch runs on the user's own key.
