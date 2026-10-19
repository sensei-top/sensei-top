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

Last reviewed: 2026-10-19, for the docs verification: every doc checked
against the code and against the others, and every row below re-read
(schema version 63, ~3,360 Python tests).

**The roadmap's order, 2026-10-19.** Reordered with the user after the
tracker research (plan 27). Now: the game 1 versus post-board split, the
Arena and MTGO log-reading fixes, wider Linux discovery. Next: reader
health, the CSV export and help tour, sideboard help, per-card win rates.
Written guides with any model and macOS move to Later; match
contributions move to Never, so no match is ever collected or shared;
the one that leaves the machine is a report the user asks for with their
own key.
The rows that carry the order are under "Roadmap order" below.

**The paid tier, 2026-10-12.** Amends the repositioning below: the
licence stays AGPL-3.0-only and the tracker stays free with no account,
and two paid things are planned. The Microsoft Store listing is the same
build as the free download, listed free when it goes up and priced once
the blockers below clear. At around 3,000 monthly
active users, an optional subscription gated by feature, with a monthly
report allowance inside it written through a hosted proxy, and the one
account in the project, made at checkout (`AGENTS.md` rule 5,
`docs/llm.md`, `ROADMAP.md`). Two rows under "Features not built" carry
them. The two third-party questions the repositioning closed because
nothing was sold are open again, the MTGOFormatData licence now blocks the
sale too, and so is whether the Fan Content Policy allows either paid thing
(the Store row), which the repositioning's reason for donations assumed it
did not.

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
Arena-only formats (Historic, Explorer, Timeless; reversed 2026-10-16 for
those three, see the Arena-only formats row, while Alchemy and Brawl stay
out), no in-game overlay or companion window, and never reading the memory
of, injecting into or automating either client. Draft was deleted rather
than hidden (`feature/remove-draft`; the last commit that has it is tagged
`archive/draft` in the pre-public history, not in this repository), and
its rows left with it. The rows the pivot
added are dated 2026-10-01.

## What works today

| Surface | Arena | MTGO | Notes |
|---|---|---|---|
| Ingest | live, `serve --watch` / `ingest --watch` | live too: the watcher checks game logs every 2 s and stores each game once it ends (`docs/architecture.md`, "MTGO's game logs"), or by hand with `ingest-mtgo`; deck files (the `.dek` exports and MTGO's `grouping *.xml` deck store) polled every 30 s | A running watcher notices rows another process inserted and rebuilds on its next due poll (`docs/architecture.md`). |
| Win rate, play/draw, History, Matchups | yes | yes | History and metrics default to Arena and can switch to MTGO or all. |
| Match detail and match report | yes | yes | MTGO has no board-state stream, so its turn-based analyzers report gaps instead of building on zeros (`tests/test_review_mtgo.py`). |
| Leak finder, Coach | yes | yes | The coach pools both sources and reports them separately (`by_source`). A report is for one format: habits are read across every format played, a deck's and an opponent's records from that format alone. A match counts under its format, an MTGO one under the format the user confirmed, else the one its revealed cards fit (`docs/coach.md`). |
| Deck guide, matchup briefs | yes | once the match's deck is picked | MTGO's transcript never names your deck, so the user confirms it on the match's page, or many at once on `/mtgo/picks`, grouped by the saved list that fits; Home lists the matches still waiting. The pick is `mtgo_match_pick`, read through `v_match_deck` (`docs/architecture.md`). |
| Current match (replay, keep guide, hand read, sideboard break) | yes | no, by design | `v_current_match` is Arena-only (migration 040), because MTGO has no stream for the replay to run against. |
| RCQ guide (`/decks/:id/rcq`, the deck page's RCQ tab) | yes | once the deck is picked | One document for the exact 75 the user pastes, against the last 14 days of the field and the last 7 days of events; a Claude button writes it, or the answer to its copied prompt is pasted into the page; `rcq --prompt/--import` is the terminal path (`docs/guide.md`). The corpus now also reads mtgo.com directly, fresh to within hours (`docs/metagame.md`). |
| Field | — | — | The field's tournament corpus, one format at a time (`?format=`, by default the format of the most recent match). It defaults to the window since that format's last reset. Duplicate events are marked, not double-counted (migration 043). Each stored event is listed and has a page of its own (`/field/events/…`): every deck's standing, archetype and list, and a link to where the results were published. `serve` keeps the corpus current on its own (`docs/metagame.md`, "Fetching the corpus"). |

Every metered Claude call is a button press and nothing else (AGENTS.md
non-negotiable #5). `serve` refuses to bind anything but loopback, and
`api/guard.py` refuses a foreign `Host` or `Origin` and any write without the
dashboard's own header, so another page open in the browser can't use the
API either (`tests/test_guard.py`).

The only measurement the no-account decision leaves is built: the daily
version check reads the latest GitHub release's `latest.yml`, which the
release job publishes with the installer (`docs/testing.md`, "CI"); the
site (`site/`, `docs/frontend-site.md`, "The site") counts its page views with
Cloudflare Web Analytics, cookieless, and GitHub counts each release's
downloads. Nothing about anyone's games is in any of them.

## Limited on purpose

These look like gaps but are decisions. Don't "fix" them without reopening
the decision.

- **MTGO doesn't reach the Live page yet.** Since plan 3 the watcher stores
  each MTGO game once it ends, so History and the metrics follow a session
  as it is played, but the current-match reads stay Arena-only
  (`docs/current-match.md`). See "MTGO on the Live page" under "Features not
  built".
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
- **Names, prompts, exports and the CLI stay English in every language.**
  Card names are Arena's and Scryfall's English names, a deck's name is
  the user's own, and an archetype's name is the corpus's or the rule
  engine's, so the same deck reads the same on the dashboard, in a
  tournament result and in a guide someone else wrote. Prompts are built
  in English, and so are the deck and RCQ guides' Markdown exports, which
  are prompt input; console output and log lines are English too. Stored
  prose stays in the language it was written in. Decided with the user,
  2026-10-08 (plan 18, D3 and D7); `docs/i18n.md`, "What is never
  translated".

## Backlog register

### Roadmap order

Added 2026-10-19: `ROADMAP.md`'s "Now" and "Next", in its order, from the
tracker research (plan 27; its notes are local to the maintainer). Each
is prioritized and specced on its own before work starts; a row says what
is wanted, not how. The Store listing waits on Microsoft outside this
order (under "Features not built").

| Item | Why deferred | Needs |
|---|---|---|
| Now 1. Each matchup's record split into game 1 and games 2 and 3, for best-of-three matches. Arena's post-board games come from `game_decks` (migration 024); MTGO's log has no per-game deck, so its post-board cells are NULL with a warning. | The first step of sideboard help, split out on 2026-10-19 because it needs no outside source; the most-asked competitive statistic in the research. | Computed in the rebuild or at request time (rule 3), nothing stored; where it shows (a deck's Matchups, the pairing page). |
| Now 2a. Arena log reading: a `[Message summarized …]` marker replacing an oversized `GameStateMessage` is dropped silently by `reader/segmenter.py`, so the replay loses messages with no warning; an exception in one message of a `greToClientMessages[]` event loses its siblings, GameOver included, because `projector/matches.py` catches per raw event; `GameStateUpdate_Undo` resets the board but `card_events` keeps the cancelled cast, which is phantom opponent evidence; `QueuedGameStateMessage` has no decided treatment; nothing fails when a label's handler stops matching (a per-label count ratchet); derived rows carry no projector version; `docs/arena-log.md`'s trap 6 says Full and diff messages have no distinguishing flag, while `projector/game_state.py` branches on `GameStateType_Full`. | Found by the tracker research (2026-10-19) in other trackers' bug histories; none is measured against the real log yet. Each is a silent loss, and rule 2 makes each fix retroactive. | A grep of the real log for each marker (`Message summarized`, `QueuedGameStateMessage`, `GameStateUpdate_Undo`), then fixture-backed tests (rules 7 and 8). The marker is the segmenter's to find and the projector's to interpret (rule 1); an incomplete game is flagged, never patched (rule 4). |
| Now 2b. MTGO log reading: games ended by a disconnection, running out of time, drawing from an empty library, inaction or a bare "loses the game" stay undecided, since `projector/mtgo/parse.py` reads only concessions and wins; a reconnect ("joined the game" again) opens a phantom game; `projector/mtgo/decode.py`'s text check rejects a whole string holding a control character or NUL, so that player's lines vanish, a lead for the 9 unprojected files under "Correctness"; the deck played is not matched against deck files, so more matches need a manual pick. | Found by the tracker research (2026-10-19). "MTGO draws and disconnects are untested" (below) is the same gap. | Real captures from the VM (a pulled network, a timeout) for the fixtures; `scripts/mtgo_probe.py` over the 9 files. Unknown results stay undecided (rule 4); `mtgo_match_pick` stays the user's override (rule 6). |
| Now 3. Arena's log found on more Linux setups: every Steam library root, Flatpak and Snap Steam, `~/.steam/root`, Lutris, Bottles and Heroic, and any Wine user (`reader/ingest.py` hard-codes `steamuser`; `steam.py` knows two roots); duplicates removed by realpath and the newest `Player.log` preferred, so a stale prefix can't shadow the live one. | Found by the tracker research (2026-10-19); helps the Steam Deck tester. | Filesystem tests against fake home directories, one per layout; discovery stays filesystem-only (rule 1). |
| Next 1. Reader health in the dashboard: the log's path and whether it was found, the last read, "waiting for the log to grow", raw and projected counts, and Detailed Logs off with the setting's exact path (on the empty Matches page too); a "Total matches · Last updated" line; a warning for a match that looks missing; a dated changelog in the app. | Most of it exists in `doctor` on the command line only. | A read-only GET under the guard; the panel reads state and never drives the reader (rule 1); the changelog is text shipped with the app, never fetched. |
| Next 2. A CSV export of the user's own matches, games and per-deck numbers (an unknown value is an empty cell, never 0); a one-line definition on each table column; and the help tour below, with an entry that cites Arena's own article on Detailed Logs for community tools and says the app reads only the log and sends nothing. | Asked by no one yet; the research found the export is what other trackers charge for. | A GET under the guard; every string keyed in both languages (`docs/i18n.md`). |
| Next 3. The rest of sideboard help, after the split in Now 1 | See "Sideboard help without a model" under "Features not built". | That row. |
| Next 4. Per-card win rates from the user's own games: in the opening hand, drawn and cast, with n beside every rate. Today `key_card_timing` (`docs/guide.md`) covers maindeck cards with 3 or more copies only. | Waits on Now 2a's undo fix, so a cancelled cast never counts. | The user's own opening hand and draws per game, computed in the rebuild with NULL where the hand is unknown (rules 3 and 4); fixture tests (rules 7 and 8). On MTGO the opening hand may not be recoverable. |
| Next 2, with the export above: the help pages' tour of the dashboard (`site/help/`): what each page shows, in both languages, linked from the welcome steps' last step, Ready. The first cut (2026-10-13) covers installing, the first run, Magic Online, troubleshooting and the problem report; `docs/user/dashboard.md` is the English tour until then, and moves to the site with it. | Scoped to what the beta testers need first; then left out of the onboarding revisit (plan 23) and moved after 1.0.0 (both 2026-10-16), because Ready's link needs a decision first: nothing in the dashboard links to the public site today. | Whether the dashboard links out to the site at all, and how it gets the site's address. Plan 23's shape for the pages (its D12): one page per language, `site/help/tour/` and `site/pt-br/help/tour/`, one section per place; screenshots from the demo database through `web/scripts/site-images.mjs`, inside the page weight `tests/test_site.py` pins. Ready's label, `welcome.done.tour`, is in both catalogues already, not drawn. |

### Features not built

| Item | Why deferred | Needs |
|---|---|---|
| The paid Microsoft Store listing (decided 2026-10-12, `ROADMAP.md`): the Store build is the same app as the free download, listed free at release and priced once the blockers in the third column clear; the free download stays free (unsigned until an open-source signing programme takes it; see "Code signing" below). | Planned for the first release, not set up. The maintainer stays an individual, not a company, until income asks otherwise. | Microsoft's answer on selling from an Individual developer account, whose eligibility text names "non-commercial purposes" and "not in relation to their business, trade, or profession", and whose type cannot be changed later (a Company account is a new account and needs a registered business or DUNS number). The Daybreak, TopDeck.gg and MTGOFormatData rows under "Waiting on a third party". The Fan Content notice in `README.md` and `docs/attribution.md` read again before anything is sold, by a Fable agent where one is available and Opus otherwise (it is legal text): once anything is sold, "permitted under the Fan Content Policy" is no longer true, and the 2026-10-12 check proposed a non-affiliation notice for that day. The policy lets Wizards withdraw permission "for any reason or no reason", so the sale stays reversible: the listing can go back to free. Decided 2026-10-12 (plan 9, D9): the listing goes up free and is priced once they answer. |
| The optional subscription (decided 2026-10-12, `AGENTS.md` rule 5, `docs/llm.md`, "Nothing hosted writes for the user"): gated by feature, never by rank or event type; a monthly report allowance inside it, never tokens, credits or a prepaid balance; a hosted proxy holding the maintainer's key; the only account in the project, made at checkout (an email code; Google, Discord and X sign-in). The free tracker, the copy prompt and the user's own key stay free beside it. | Deferred until around 3,000 monthly active users, which the launch's own counts measure. | Which features it holds. A merchant of record (Paddle). An account service (Supabase Auth was the pick) and a privacy policy. X sign-in's terms, unread. Daybreak's Fansite license agreement if §14.3 asks for one. The notice Anthropic's Commercial Terms (D.3) require, that outputs are not to be relied on without checking, shown to subscribers. The rewrite `docs/llm.md` lists, and a new rule 5. |
| A provider adapter for the generate routes (decided 2026-10-07, `AGENTS.md` rule 5, `docs/llm.md`): the credential becomes a provider, a base URL, a key and a model id, so the five routes can call Anthropic, any OpenAI-compatible endpoint or a local model (Ollama, LM Studio). Each stored narrative is labelled with the model that wrote it; the coach's web search degrades to the reading list on a provider without it; an unknown model prices `NULL`. The brief, coverage and sideboard-plan cards get a generate route with it. | The repositioning made the user's own credential the only writing path, and "any model" was the research's second-most-asked thing after "no account". Moved from Next to Later on 2026-10-19: the 2026-10-19 tracker research found no demand either way. Not started. | Its plan (`~/.claude/plans/release-16-provider-adapter.md`, outline). One adapter per protocol under `llm/`, `llm/config.py` widened, a `model` column on every narrative table (one migration), `REPORT_MODELS` reworked into a per-provider list, Settings' Writing section, and the route additions to rule 5's list and `test_only_authored_artifact_routes_write`. |
| The deck guide's Export card copies `guide/markdown.py`'s document but has no download, while the RCQ guide downloads its `.md` (`components/rcq/RcqResult.tsx`). A PDF and a phone or print layout were dropped on 2026-10-19: the Markdown is enough. | Asked 2026-10-16 as guides as files; the RCQ half shipped first. | A download button beside the copy, as the RCQ guide's. |
| Sideboard help without a model (decided 2026-10-07; `ROADMAP.md`'s Next 3): the user's own post-board record per matchup, split out as Now 1 on 2026-10-19 ("Roadmap order"), then candidate ins by a card-role rule over the 75 (answers, threats, hate by the opponent's archetype), and a link to a sideboard guide for the pairing from the Skill Issue Magic guide index. No generated outs. | The research's most-wanted feature, and the one every competitor sells a model for; the index's creator was asked on 2026-10-07, in exchange for credit on each link, and had not answered. Not started. | The creator's yes, recorded in `docs/attribution.md` with a row for the index ("Rules for a new source"): the published CSV's address and shape, an alias table from the index's archetype names to the corpus keys, a scheduled fail-soft fetch kept in cache, never any guide content copied. Plan `release-17-sideboard-referrals.md` (outline). |
| The launch itself (plan 9, S7): the accounts (GitHub Sponsors on the `sensei-top` organisation, Cloudflare's site Worker and its Web Analytics token, X; Apoia.se is live at `https://apoia.se/senseitop` since 2026-10-12; GitHub Sponsors was still unapproved at 1.0.0, and Stripe refused the maintainer's CPF, so PayPal stands in as the worldwide link from 1.0.1 on the site and in `FUNDING.yml`), the public repository with its labels and Discussions categories, the `0.7.x` beta installed from the site by the testers, the Store listing, the `1.0.0` release and its posts per venue, which never say "AI". Done by 2026-10-19: the public repository, the `1.0.0` and `1.0.1` releases and their posts, Apoia.se and PayPal in `.github/FUNDING.yml`. Left: the Store listing, GitHub Sponsors' approval and the credits perk. Perks never gate anything: credits, a roadmap vote, sponsor-a-feature; no Discord role while there is no Discord. The credits perk has nothing to show it yet: `web/src/credits.ts` and the Credits view list sources and software, not supporters. No early builds for donors, because the policy forbids requiring payment or a subscription for fan content. | Every part of it that lives in the tree is built (2026-10-12): the site in `site/`, the tag-driven release job, the issue forms and the funding file. What is left is the maintainer's own sequence of accounts and releases. | The user's steps in plan `release-9-launch.md`, S7. The Store identity (its S3) waits on the Partner Center account. |
| A macOS build, Arena-only, unsigned, from GitHub's free macOS runners, open to it since the repository went public; notarization when donations cover the Apple fee. | Linux and Windows ship first (decided 2026-10-07); moved from Next to Later on 2026-10-19, behind wider Linux discovery. | A plan of its own: plan 6, now done, left macOS out of scope. |
| MTGO's `.txt` deck export is not read; only `.dek` exports and the deck store are (plan 12, D13). | No real `.txt` export exists to build a fixture from (rule 7). | A real `.txt` export, from the user or the VM. |
| Settings' Draft data section (`components/settings/SharingSection.tsx`), `components/sharing/` and the `Sharing`, `SharedDraft`, `DraftPayload` and `Deleted` types in `web/src/bridge.ts` describe drafts, which the app no longer reads. Nothing draws them outside `/design/surfaces`. | Kept when the draft assistant and the overlay's leftovers were removed (2026-10-01), for plan 10 to rework for match data. Plan 10 was refused on 2026-10-19 (`ROADMAP.md`, "Never"), so nothing will. | Their removal, with the shell side of `deleteContributions` (`web/src/bridge.ts`, `views/SettingsView.tsx`, `lib/sampleShell.ts`, and in the desktop shell `desktop/src/preload.ts` and `desktop/src/settings.ts`, which set `sharing` to null) and `docs/frontend.md`'s paragraph on them. |
| Formats beyond what plan 13 built. Plan 13 made the format a parameter for the seven formats in `formats.FORMATS` (Standard, Pioneer, Modern, Pauper, Legacy, Vintage, Premodern): legality per format (`card_legality`, migration 053, in place of `cards.standard_legality`); a match's format (`matches.format`, 055, read through `v_match_format`: the log's, then the MTGO pick, then the format the revealed cards fit); and per-format archetype rules, corpus prior, consensus, reset window, field record, leaks and coach reports, with a format choice on the Field and Coach pages. Left out: Arena-only formats (Historic, Explorer and Timeless are planned after 1.0.0, row below; Alchemy and Brawl never) and Duel Commander; Premodern's archetype rules, so its opponents are named by colours and signature card only; a date-aware ban or rotation history (Scryfall's ban list is today's, so a ban never takes a match out of its format); "&" names (below). The corpus follows Standard, Modern and every format it already holds an event in, and `sensei-top meta --format X` adds another (`docs/metagame.md`, "Fetching the corpus"); the quality pass (`docs/metagame.md`, "Formats: how well each is named") covers Standard, Modern and Pauper's corpus. | Decided with the user, 2026-10-02 (plan 13, D10 and D11): fetch what is played, and never write Premodern rules here, because it is not a Wizards-sanctioned format. | Per format: switching its fetch on, then its quality pass. Premodern rules only from an outside source, if one exists. |
| Historic, Explorer and Timeless, the Arena-only formats other than Alchemy and Brawl (decided 2026-10-16, after 1.0.0, low priority). Reverses that part of the 2026-10-01 pivot; Alchemy and Brawl stay out. | Asked 2026-10-16, for after 1.0.0. | What plan 13 built per format (legality, archetype rules, corpus prior, consensus, field), and a corpus source for formats that have no MTGO events. `ROADMAP.md` keeps them in Later (2026-10-19). |
| MTGO on the Live page: the opponent's revealed cards during a game (the log is rewritten about every 7 s) and the between-games plan (see "Limited on purpose"). | Moved out of plan 3, which built the ingest it stands on (plan 3, D1): it is a `table/`, API and Live-page feature, and migration 040 made the current-match view Arena-only. | Plan 15. |
| Mulligan plan "Layer 4": an authored mulligan plan in the guide's prompt/import round trip | Planned during the mulligan work and never built. The handoff that described it is gone. | A design pass: what the plan says, where it's stored (an authored-artifact table, rule 6), and how the keep guide shows it. |
| Coach breakdown per deck version | Deferred feature. Deck versions are split elsewhere (the guide) but not in the coach. | Reusing `guide/`'s identity split inside `coach/evidence.py`. |
| Deferred review analyzers (combat attack/block decisions, timing) | Future scope in `docs/review.md`. | Their own design. |
| An archetype name as the user's MTGO deck with no list behind it (plan 19, D3), for matches no saved list fits. | It needs a column, a view change and a decision on how a deck with no list reaches Decks and the guide. | Its own plan, if asked. |
| A pasted-decklist importer for MTGO lists the user no longer has as files. | A pasted list must enter `raw_events` to survive the rebuild (rules 2 and 3). Until then such matches are picked format-only. | Its own plan, if asked. |
| A Live clip or a short video on the landing (plan 21, D2): the page shows the Live capture of a real unranked match cut mid-game, and no motion beyond a row rising into view. | Deferred to after the beta, by the user's choice (2026-10-13): a clip is a second pipeline (a cut match replayed through the dashboard, recorded, then cut and encoded) and a weight cap of its own. | A decision on clip or video; the recording pipeline beside `site-images.mjs`; a cap in `tests/test_site.py`; `ffmpeg` is on the machine. |
| Caution cards: the cards to watch for from the opponent's leading candidate deck, with rules text on expand. The brief and the sideboard plan cover part of it. | Seen in the tracker research (2026-10-19); in `ROADMAP.md`'s Later. | Its own design: where it sits on Live (and whether it is advice under `table/ranked.py`'s rule), and its source (the candidate's consensus list). |
| Finding history faster: date presets (7, 30, 90 days, a custom range), a search, matches grouped by day, league runs with their trophies. | Seen in the tracker research (2026-10-19); in `ROADMAP.md`'s Later. | A check of what the Matches page and Home's session block already do, then a design per piece; league runs need the log's event records read. |

### Correctness: latent or unmeasured

| Item | Why deferred | Needs |
|---|---|---|
| Coach web-search citations are never stored. `sources_json` holds only the reading-list ids. The pages are not lost: `coach/narrative.py::web_sources` recovers them from the prose's "Sources" section when the report is read. | The 2026-09-22 runs found no citation objects in the response to store. | Storing the recovered pages at write time, if a reader ever needs them without the prose. |
| A prepare spell half that several cards share has no legality and no `oracle_id`: Reality Fracture's "Peer Review" is the back of three different creatures, so `cards.py::_backfill_by_name` skips the face name as two cards sharing it (15 face grp_ids across five names). No match's format read depends on one: MTGO resolves the combined name, and no MTGO match sat at `unknown_legality` on 2026-10-05. | The skip is the guard that keeps Odyssey's Careful Study apart from an Arena face; loosening it for shared faces is its own change. | A rule telling a face shared by several cards (same face, different whole cards) from an unrelated card of the same name, then a test over a real `prepare` line. |
| `table/hand_read.py::_seen_elsewhere` counts per game, while the classifier counts per match. | The asymmetry is undocumented but harmless today. | A decision on which grain is right, then a doc line or a change. |
| `review/analyzers/baseline.py`'s `GAME_LENGTH_MIN_GAMES` gate counts projected games, so it couples to projection details. | Raised during review and left unchanged. | A look at whether the gate should count completed games only. |
| The deck guide's field shares group by archetype name, while the coach and brief coverage group by key. | Found in the coach↔guide helper consolidation, which kept behaviour byte-identical on purpose. | A decision on one grain, then a real-data diff of the guide output. |
| A deck's coverage table and a pairing's heading can show one label on rows of distinct archetype keys: `brief/coverage.py` labels a row `field_name or faced_name`, and the corpus files "Dimir Midrange" under more than one key, so two rows can read alike. | Found while rebuilding a deck's pages; telling the rows apart is a naming decision, not a patch. | Decide how a shared label is told apart (a qualifier in the label, or the address alone as the identity), then fix `coverageName` (`web/src/lib/brief.ts`) and `pairingHeading` (`web/src/lib/pairing.ts`). |
| The corpus-naming confidence constants are provisional (44% measured against a 60% target). | Needs more classified data. | A re-measurement against the corpus. |
| TopDeck's non-constructed events (Commander, draft, sealed, cube, jumpstart, pre-release) are filtered by name only. `topdeck.py`'s `_NOT_CONSTRUCTED_RE` skips a matching event on fetch with a warning, and purges already-stored matching Topdeck events with their child rows after each refresh. The match has a leading word boundary only, so it can over-match ("Cubes", "Prelude" would also match). | TopDeck's own format field is not trusted: it labelled these events Standard (found when the base URL fix first returned data). | A look at what TopDeck's own fields say per event, and a fixture-backed tighter rule if over-matching shows up in the stored events (rule 7). |
| No paper source after 2026-08-16: fbettega's Melee data stops there, so paper RCQs reach the field only through TopDeck (needs the user's key). | Measured while planning the RCQ guide. | A working TopDeck run, or another paper source (`docs/attribution.md`, "Rules for a new source"). |
| MTGO draws and disconnects are untested. | No fixture captures either. | A real MTGO capture of each. |
| The RCQ paste stores an answer against the list in the box at save time. The RCQ prompt carries no `context` hash, and the box stays usable while the preview catches up after an edit, so an answer copied for one list and saved after the list was edited is stored against the edited list, and the page's "changed" note cannot tell. | Found in plan 24's review of phase 9c. Disabling the box while the preview updates would unmount it and lose the pasted text. | A `context` hash on the RCQ prompt (the list as typed and the expected keys), stored with the guide so the page can say it was answered for another list. |
| `doctor`'s Detailed Logs reading `disabled` rests on a `DISABLED` line that no capture has shown, so that branch is untested (`docs/desktop.md`, "Support commands"). | No capture of Arena with Detailed Logs off exists (rule 7). | A real `Player.log` header from Arena with the option off, then a fixture-backed test. |
| 9 of the 335 real MTGO game-log files project no match (326 matches, 2026-10-02). | Found in plan 12's real-data check, out of its scope. Not investigated: they may be logs with no finished match, or a drop. | Reading those files with `scripts/mtgo_probe.py`, then a warning for any that should have projected (rule 4). |
| A deck's format (`guide/deck.py::identity_format`) is its `decks.format` when that names one of the seven formats, the store's `FormatCode` for an MTGO deck; only otherwise does it come from its matches' formats, the user's confirmed picks among them (plan 13, D15). A pick never overrides the store's format. | On purpose in plan 12: a deck's format is the deck's, and a pick is per match. | A decision on whether confirmed picks should override the store's format there. |
| `mtgo_watching` reports true while the running watcher has an MTGO directory, even while that directory is unreachable (a share not mounted, a folder MTGO moved). | Minor. The watcher logs each failed check. | Plumbing the last check's outcome through to the status route. |
| On Windows a file another process holds open cannot be renamed unless it was opened with `FILE_SHARE_DELETE`, which Python's `open()` never asks for (`WinError 32`). Arena renames `Player.log` to `Player-prev.log` at launch, so a launch that lands inside one of the watcher's reads would fail that rename, with an effect on Arena's side nobody has seen. The watcher holds no handle between polls, so the window is one read a second. | Found in plan 3's Windows work; never observed. | A capture of the failure, then opening the log through `CreateFileW` with the flag (and `msvcrt.open_osfhandle`). |
| A database or backup path given as a UNC path (`\\server\share\…`) fails where it is opened read-only: those opens use SQLite's URI form, and SQLite rejects the `file://server/…` URI a UNC path becomes. A mapped drive letter works, since the URI is built from `Path.absolute()`, not `resolve()`. | Found in plan 3's Windows work (S2); out of its scope. | Building a URI SQLite accepts from a UNC path, or refusing one with a message. |
| Not checked on Windows: `pnpm start` (the dashboard build plus `serve --watch` in one), and the daily backup to a mapped network drive. | Out of plan 3's hand checks on the VM. | One run of each on a Windows machine. |
| `config` says it wrote the file "mode 600" (`cli.py`'s `_written`, `path.chmod(0o600)`), but on Windows `chmod` only sets or clears the read-only flag. Since plan 6 a key goes to the system keyring when one exists (Windows Credential Manager on Windows), so the file holds a credential only when no keyring exists, which on Windows is not expected; the message is still printed for any file write. | Found in plan 3 (S4); the keyring made it rare rather than gone. | A Windows wording for the message, or leaving it out where `chmod` does nothing. |
| Segmenter entry shape 5 (a non-JSON response body) would swallow a header that came directly after `<==`. | Never observed in either real log. | Harden only if a capture shows it. DeckDeleteDeck's second body line falls through as noise, which is harmless. |
| An entry stored with no time by `--locale auto` (`reader/dates.py`, step 6) gets a dated twin if the same bytes are read again once its shape's order is learned (`ingest --file` reads from the start), because the digest includes `logged_at`. A `--locale` change between two reads of one file does the same. | Known when `auto` was built (plan 3, S10); out of its scope. | Re-deriving `logged_at` from `raw_events.header`, which migration 062 keeps for this. |
| Whether Windows' regional format reaches Arena's header while Arena is in English is not known. The header followed the in-game language in all eight captured languages. | Every capture so far ran under Proton, where setting the locale did not change the header. | One Windows capture with Arena in English and a day-first regional format. A new shape is a fixture and a row in `docs/arena-log.md`'s table; a day-first `slash-12h` header is one `auto` already settles. |
| The keep guide's mulligan table counts one deck version (`table/keep.py`'s query on `m.deck_id = ?`), while its mulligan-cost line counts the whole deck identity (`guide_play.mulligan_record`), so the two can differ for a deck whose list was edited; both say "Kept 7". | Found in plan 26's review of phase 3b; the two reads predate it. | A decision on which grain the table should have, then the same grain for both, with a fixture-backed test (rule 7). |
| In a game 2 or 3 hand, the Live status strip's Game numeral lags beside a live play or draw, since `OpeningHandOut` has no game number and the strip reads the last projected game. In the sideboard break the strip's record and Game numeral read the projected match too, so they can trail the plan card's "Lost game 1". | Found in plan 26's reviews of phases 3a and 3c. A server field is outside that plan ("No server-side change"). | A game number on `OpeningHandOut` (`IntermissionOut` already carries the game that just ended), read by the strip in place of the projected game's. |
| `/api/metrics/play-draw` has no games-lost field, and its `games_completed` counts draws, so the deck strip's Play vs draw (`web/src/lib/deckOverview.ts`) writes a drawn game as a loss in a side's record, counts it toward the side's ten games and lowers its rate (`docs/design-system.md`, "Numbers": a draw is never a loss). | Plan 26, phase 4: accepted as debt on 2026-10-18. The fix is on the server, on its own branch. | A `games_lost` column in `v_play_draw_winrate` (a migration), the route and its model, then the strip reading it. |
| Play and draw are not on the Matches page. | `/api/metrics/play-draw` answered 500 for MTGO when the page was built; it answers for every source now, deckless matches in one row per side. | Put the split on the page, or count it from the list's games as the band does. |
| No route lists the matches past the 500th or counts the matches of a filter. | Found while building the Matches page. The list says where it stops. | A design for paging. |
| A deck's Matchups and pairing pages (`web/src/lib/matchups.ts::matchupRows`) group its matches by `opponent_key` alone, not by format and key. An MTGO deck whose matches were picked as different formats would mix them in one row. | Safe while a deck's matches share one format: D15 gives the deck one, and on 2026-10-04 no deck in the real history had matches in more than one. | Rows keyed on format and key, and a format in the pairing's address. |
| Arena's Day and Night rows share one oracle_id, given by `cards.py`'s name backfill, which suppresses Night // Day's synthetic row. Which card's oracle_id it is was not verified (most likely Night // Day's). | Found in plan 13's review; outside its scope. | A read of the rows in a scratch copy, then a decision on whether the backfill should skip the pair. |
| Arena's "Wheel of Fortune" (60053) carries no oracle_id or legality, and its name is shared in Scryfall's export by another card's face, so an MTGO "Wheel of Fortune" resolves to NULL (`projector/mtgo/project.py::_lookup`). Whether a shared name resolves at all depends on which Arena rows happen to match an `arena_id` in the export. | Found in plan 13's review; NULL with a warning is the rule-4 answer. | A way to tell the shared name's cards apart, or a decision that NULL stays. |
| `_lookup` (`projector/mtgo/project.py`) takes the lowest positive id among same-name rows. That lands Swords to Plowshares (59771), Ancestral Recall (59671) and Fast // Furious (76075) on rows with no legality, though another row of the same name has one, so a match revealing them can't be judged on that card. | Predates plan 13; found in its review. Not pinned by a test, nor is the shared single front-face candidate. | Preferring a row that carries legality, with a fixture-backed test (rule 7). |
| The Modern corpus names an archetype "GoryoReanimator", with no space; `docs/metagame.md` lists the other names like it. | The name comes from the downloaded definitions, not from this code. | A display-name rule, or a report upstream. |
| "&" names (*Wear & Tear*) never resolve on MTGO and stay unresolved with a warning (plan 13, D16), counted in `cards_json`'s unresolved count, which the match report and the leak finder treat as unknown cards. Split-card halves resolve by the back-face rule since plan 13. | No fixture holds one (rule 7). | A real capture naming one. |
| On `/mtgo/picks`, an unsure match with no saved list in its format reads "No saved list fits." instead of naming the format. | The unsure item carries no format field. | Add the inferred format to `MtgoUnsurePick` and use "No saved list in {format}." |

### Performance

| Item | Now | Needs |
|---|---|---|
| Coach page, warm | ~2.5 s. The report cache removed the per-match rebuild; what's left is non-report work. | Profiling `build_coach_evidence` outside `build_match_report`. |
| Coach narrative route (the prompt the page loads on every visit) | ~3.8 s | The same profile. |
| Sideboard break, cold path | ~2 s against a 1 s target (`brief/narrative`'s full prompt and consensus) | A cache, or trimming what the break needs from the brief. |
| Live page at the opening hand | Fixed on 2026-09-24. The delay was ingest waiting behind the match-boundary rebuild (22 s `project()` plus 2 s classify on a real database). Ingest now runs on its own thread. In a replayed match start on a 1.7 GB copy of the real database, the mulligan offers landed in 0.13 s, against 16–22 s before. The verdict had also been blank on 47% of Boros Dragons hands, because of Multiversal Passage's missing `produced_mana`. Replayed over the real hands, none are withheld now. What's left: `project()`'s own write lock (5.7 s measured) still holds up an ingest tick that lands during the commit. The ingest connection's 30 s `busy_timeout` waits it out rather than failing. On 2026-10-17 the same lock made a dashboard write (an MTGO pick) fail after its own 5 s wait. The MTGO projection, which runs inside the lock, took at least 4.5 s of it alone. The API's writes now wait 60 s (`api/deps.py::WRITE_BUSY_TIMEOUT_MS`) and answer 503 past that, rather than a 500. | Shrinking the write lock, which means a smaller `BEGIN`…`COMMIT` in `project()`. |

### Code health

| Item | Needs |
|---|---|
| Big file: `review/snapshot.py::build_snapshot` (~515 lines) | Out of scope for the sweep. Split it when a feature next touches it. |
| `projector/matches.py` calls `mtgo.config.load_handle()` on every `project()`, so a config file with no `[mtgo]` table (an Arena-only user with a Claude key, say) logs a warning on every rebuild. | Loading the handle only when MTGO `raw_events` exist, or a silent absence like `resolve_log_dir()`'s. |
| Several tracked files (`git grep -l '\.claude/handoffs'`) cite notes under the gitignored `.claude/handoffs/`, so the citations dangle for anyone else reading the repo. | A wording pass, overdue since the repository went public on 2026-10-17 (15 files besides this one on 2026-10-19): state what the note established, or drop the citation. |
| About 17 lists in `web/src` are joined by hand with `", "`, not through `lib/format.ts`'s `formatList` (`docs/i18n.md`, "Keying a string in the dashboard"), so they read as English in another language. `OpponentRead` was fixed in plan 26, phase 3a. | Finding them (a `join(', ')` in `web/src`), then `formatList` at each, with the test the file already has. |
| `docs/guide.md`'s `narrative.py` section justifies the guide prompt's size by quoting an AGENTS.md "outbound-call standard" that AGENTS.md no longer states. | Restating the reasoning in `docs/guide.md` itself, or dropping the quote. |
| The rule that reads a seat's colours from its played cards exists twice: `archetypes/classify.py`'s `live_opponent_colors` (which `table/intermission.py` calls), and `_colors_by_played_name`/`_colors_of` in `api/routes/mtgo_picks.py` (plan 19, one query per request instead of one per match), kept equal by a test. | One helper both import, from `archetypes/`. |
| The installer's uninstall page (`desktop/build/installer.nsh`, both languages) and `INSTALL.md`'s folder table name `%APPDATA%\sensei-top` as the settings folder, which holds only the server's `config.toml`; the shell's own `shell.json` (language, autostart, onboarding) sits in `%APPDATA%\Sensei Top`, Electron's userData, and is named nowhere. Found in plan 18's VM read, 2026-10-12. | A decision on whether the uninstall page names the second folder, then the same sentence in both `LangString`s and in `INSTALL.md`. |
| `scripts/build_server.py` accepts python-build-standalone 20260623 and 20260807 only (`VENDORED_PBS_TAGS`): a bare `uv sync` in the Windows VM picked 3.12.14 (PBS 20260929) on 2026-10-12 and the freeze refused it; `--python 3.12.13` is the workaround. | Re-checking `desktop/server/licenses/cpython-deps/` against the newer tag, then adding it to the tuple. |
| 37 imports reach into another package's leading-underscore names (counted 2026-10-16, the gettext alias `_` aside): 17 from `archetypes/classify.py`, 8 into `coach/evidence.py`, one each into `cli.py` from `reader/` and into `projector/` from `formats.py`. | Promote the shared ones to public names, or pin them with a test. Moved after 1.0.0 on 2026-10-16; no visible effect. |

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
- The public source release. The licence is AGPL-3.0-only since
  2026-10-07; between 2026-10-01 and then it was a proprietary notice, and
  no copy was published under either. The source is public at
  `https://github.com/sensei-top/sensei-top` since 2026-10-13: one
  snapshot commit per tag from `v0.7.0` to `v1.0.0`, and since 2026-10-17
  the development itself (`docs/branching.md`). What was established on
  2026-09-27 still explains why the public history starts at a snapshot:
  - The history cannot be published. `scripts/privacy_scan.py --history`
    found local paths in old versions of `README.md`, `tests/conftest.py`
    and the MTGO reader, the MTGO handle in old versions of
    `tests/test_llm.py`, and the author's identity on every commit. The tree
    itself scanned clean.
  - So the source goes out as a fresh one-commit snapshot in a new
    repository, never over this one: GitHub keeps every pull request's
    commits under `refs/pull/*`, where rewriting a branch does not reach
    them. The README says why the history starts there. The old working
    repository stays private as the record of everything before it.
  - The snapshot's commits identify the maintainer: the name git records
    today, and GitHub's no-reply address for the maintainer's account.
    `scripts/publish_snapshot.py` made those snapshots (plan 9, 2026-10-12)
    and is unused since development went public, still in the tree:
    the tag's tree into a clone of the public repository, one commit, one
    tag, scanned before any push. The scan reads the global git identity
    as well as the clone's, and accepts the clone's declared local
    identity only in `history:log`'s author and committer fields; the same
    values in any file still count.
  - `sourceUrl` in `web/src/credits.ts` is the address, and the Windows
    installer's welcome page links it. Its finish page links the GitHub
    Sponsors page beside the Apoia.se one in 1.0.0, a page GitHub had
    not approved, so that installer's link leads to a 404. From 1.0.1 the
    finish page links the site's Donate section instead
    (`SENSEI_TOP_DONATE_URL` at the top of `desktop/build/installer.nsh`),
    so changing a platform never needs a new installer. The site's second
    link is PayPal until Sponsors is approved.
    `CONTRIBUTING.md`, `DCO` and `CODE_OF_CONDUCT.md`, restored
    on 2026-10-07, are what a contributor reads.
- The trademark filing. Clearance searches were run before the name was
  taken, but nothing was filed, by decision, for the first release. The
  name is used as an unregistered mark (`TRADEMARK.md`). The filing date is
  what sets priority, so the cost of waiting is that someone else files
  first.
- Code signing (decided 2026-10-07). Windows: a Microsoft Store individual
  developer account (about US$20 once), which the user agreed to pay, so the
  Store build is signed by the Store; the direct download is unsigned, and
  `site/` and `INSTALL.md` tell the user how to get past SmartScreen.
  SignPath Foundation turned the application down on 2026-10-13 (sent
  after the 0.7.1 release): not for the requirements, which the public
  snapshot and plan 9's release job meet, but for too few public signals
  of trust (stars, forks, contributors, outside articles and discussions,
  sustained activity). They invited a new application once the project
  has broader recognition, so it is sent again after the `1.0.0` launch
  has had time to produce those. If the SmartScreen prompt costs users
  before then, the fallback is Certum's Open Source Code Signing
  certificate (about EUR 49, cloud): its terms revoke a certificate that
  signs "software distributed commercially", which the paid Store build
  of the same app may trigger, so a Fable agent reads them first (it is
  legal text). A standard certificate does not clear SmartScreen at once
  either; reputation builds with downloads. Microsoft's Artifact Signing
  (formerly Trusted Signing) takes individuals only in the USA and
  Canada. SignPath's paid plan was not taken. macOS: notarization (US$99
  a year) when donations cover it.
- melee.gg's terms, unread (2026-10-05). Sensei Top never fetches from
  melee.gg; its paper events arrive through fbettega's cache, and the
  event page links each one to its page there. The site refused a
  program's reading (HTTP 403 on `/`, `/robots.txt` and `/Terms`), which
  was not worked around, so its terms are unread. What is left is a
  reading from a browser, by the user, for two things: a clause on
  linking, and a claim to database rights over results. Nothing to ask
  Melee unless that reading raises it.
- The PT-BR wording left as is after plan 18's screenshot pass (2026-10-12),
  each one cosmetic and a catalogue edit away: `decks.overview.daysWithinMonth`
  renders "7 de set. a 8"; coach reports keep their English section headings
  (the prompt contract); `/design` stays English and Settings shows the raw
  model id; `decks.written.on` reads "Escrito em {{day}}, sem autor
  registrado."; the Field's empty states put the window in a parenthetical;
  and the restore-without-status sentence ("The restore ended without a
  status code.") is new English wording chosen without the user.

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
  comment on that issue, never a second issue. A free AGPL tracker reading
  the definitions is the use the maintainer proposed MIT for, so the free
  download does not block on the answer. The paid Store build and the
  subscription (2026-10-12) sell an app that names decks from these
  definitions, so neither is sold until the file lands. If it never does,
  deck naming falls back to the corpus read plus rules written here.
- **Daybreak's terms for mtgo.com** (2026-10-05). Read in full: the ToS
  (2026-07-13), the MTGO EULA (2022-05-31), the API Policy on the Census
  page (undated) and the Legal Notices (2026-08-24); recorded in the mtgo.com
  row of `docs/attribution.md`. The pages answer the fetch: no clause on a
  program reading the website, no `robots.txt`, load addressed only in
  general words; ToS §14.3 lets fan sites and apps "share ... information
  about any Daybreak Game(s)" and grants "Permission to link from the
  Fansite to the associated Daybreak Website". The subscription question,
  closed on 2026-10-07 because nothing was sold, is open again with the
  paid tier (2026-10-12). §14.3 names paid downloads among the revenue a
  fan app may earn, and asks for a Fansite license agreement before "a
  subscription or access fee". Before the paid Store build is sold:
  whether §14.3(c), which permits charging "to download your App(s)" but
  defines Apps as "mobile apps", reaches a desktop app, and whether game
  data read from mtgo.com's pages rather than "acquired via Daybreak's
  API" is inside the permission at all. Before the
  subscription ships: the agreement, which that clause asks for in so
  many words, and the request for a copy is the question. Before plan 9's
  snapshot: written consent to redistribute
  the site's results (§7.1 "make available ... for any commercial purposes";
  §13(a) "distribute"), which no clause permits without it. Not a question
  but a check, for plan 9: the Census API's rendered MTGO documentation lists
  no decklist collection, while its page source names five; a service id the
  user registers settles whether they exist, and only a "no" turns into a
  question for Daybreak.
- **TopDeck.gg** (2026-10-05, closed 2026-10-07, open again 2026-10-12). Read in full: the API
  page (undated, API version 2026-07), the site's Terms and Conditions and
  Privacy Policy (both 2022-03-01); recorded in the TopDeck.gg row of
  `docs/attribution.md`. The pages answer the daily fetch and the event
  page: "free to use, providing tournament data for your projects and
  applications", a visible credit and link back required, rate limits with
  a 429 to wait out. The one open question is whether the grant covers a
  product sold for money, with the TopDeck features in the free download
  and the credit shown. It closed on 2026-10-07 because nothing was sold,
  and opened again with the paid Store build and the subscription
  (2026-10-12); the site's general Terms reserve its own content "solely
  for your personal use", say its content "is not for resale" and forbid
  use that would "in any way exploit any of the content"; only the API
  page's grant answers it today, and the question to TopDeck should quote
  both.
  The fetch runs on the user's own key.
