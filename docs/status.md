# Project status

Read this before starting a new feature, or when deciding what to pick up
next. It is the tracked record of what works today, what is limited on
purpose, the decisions behind both, and the data the real database still
carries. What is known to be wrong or missing, the debt and the deferred
work, is [BACKLOG.md](../BACKLOG.md), one item per ID; the order work is
taken in is [ROADMAP.md](../ROADMAP.md). Debt used to live only in
gitignored handoff notes (`.claude/handoffs/`), and some of it was lost when
those notes were deleted. The backlog exists so that doesn't happen again.

Last reviewed: 2026-10-19, for the docs verification: every doc checked
against the code and against the others, and every row below re-read
(schema version 63, ~3,360 Python tests).

**Coach and accounts, 2026-11-02.** Supersedes four lines the entries
below drew: rule 5's "nothing hosted writes for the user", "nothing free
needs an account", "no telemetry", and the site never saying "AI".
Planned, not built: a free, optional account with Google sign-in, which
adds a backup of the match history and error reports, each its own yes,
and a hosted rules coach that answers rules and card questions with cited
rule numbers and is never sent a match (`BACKLOG.md`'s BL-100 to BL-102;
AGENTS.md rules 5 and 6; `docs/llm.md`, "What is hosted, and what it
receives"). The tracker keeps working fully without an account. The copy
prompt and the user's own key stay as they are, and an "AI features"
switch hides them and the coach together. Since the account shipped, the
"no account" claims in the README and the site read "Sensei Top works
fully without an account. A free, optional account adds cloud backup of
your match history and error reports." (`docs/llm.md`); the dashboard's
footer, "No account needed", is still true and stays.

**The roadmap's order, 2026-10-19.** Reordered with the user after the
tracker research (plan 27). Written guides with any model and macOS move
to Later; match contributions move to Never, so no match is ever
pooled or shared (reversed 2026-11-02, plan 40: contributing your games
is an opt-in of its own, anonymous, with or without an account); the one
that leaves the machine is a report the user
asks for with their own key (and, since 2026-11-02, the user's own
cloud backup, above). The order itself is `ROADMAP.md`'s alone.

**The freeze, 2026-11-09.** Nothing is sold, and nothing that only
prepares a sale is worked on, until the updater's feed counts about 100
active installs a day or the app has 1,000 monthly active users, whichever
comes first. Reviewed on 2027-03-01; below the trigger it holds through
2027. The paid tier below is still the plan for that day, unchanged.
`BACKLOG.md`, "Outside the code", lists what is frozen, and `ROADMAP.md`,
"On hold", says it to players.

**The paid tier, 2026-10-12.** Amends the repositioning below: the licence
stays AGPL-3.0-only and the tracker stays free with no account (an
optional one since 2026-11-02, above), and two paid things are planned. The Microsoft Store listing is the same build as
the free download, listed free since 2026-10-21 and priced once the
blockers in `BACKLOG.md`'s BL-070 (its Needs) clear. At around 3,000
monthly active users, an optional subscription gated by feature, with a
monthly report allowance inside it written through a hosted proxy, and an
account made at checkout, which since 2026-11-02 is the free one
(`AGENTS.md` rule 5, `docs/llm.md`, `ROADMAP.md`). `BACKLOG.md`'s BL-070
and BL-006 carry them.
The two third-party questions the repositioning closed because nothing was
sold are open again, the MTGOFormatData licence now blocks the sale too,
and so is whether the Fan Content Policy allows either paid thing
(BL-070), which the repositioning's reason for donations assumed it did
not.

**The repositioning, 2026-10-07.** The licence is AGPL-3.0-only again, the
Pro tiers, the hosted proxy and the account are gone, and the copy-prompt
round trip stays beside the user's own key. Donations fund the work and buy
nothing inside the app, because the Fan Content Policy forbids charging for
it. The public plan is `ROADMAP.md` at the repository root. The items this
added, now in `BACKLOG.md`, are dated 2026-10-07; the rows it removed were
the EULA, the Pro writing path and the two third-party questions that only
a sold product raised.

**The pivot, 2026-10-01.** The product became a competitive 1v1 companion
app for Arena and MTGO: every MTGO format that has archetype rules, no
Arena-only formats (Historic, Explorer, Timeless; reversed 2026-10-16 for
those three, see `BACKLOG.md`'s BL-012, while Alchemy and Brawl stay
out), no in-game overlay or companion window (the overlay reversed
2026-11-02 for Arena only, see `BACKLOG.md`'s BL-098), and never reading the memory
of, injecting into or automating either client. Draft was deleted rather
than hidden (`feature/remove-draft`; the last commit that has it is tagged
`archive/draft` in the pre-public history, not in this repository), and
its rows left with it. The items the pivot
added, now in `BACKLOG.md`, are dated 2026-10-01.

## What works today

| Surface | Arena | MTGO | Notes |
|---|---|---|---|
| Ingest | live, `serve --watch` / `ingest --watch` | live too: the watcher checks game logs every 2 s and stores each game once it ends (`docs/architecture.md`, "MTGO's game logs"), or by hand with `ingest-mtgo`; deck files (the `.dek` exports and MTGO's `grouping *.xml` deck store) polled every 30 s | A running watcher notices rows another process inserted and rebuilds on its next due poll (`docs/architecture.md`). |
| Win rate, play/draw, History, Matchups | yes | yes | History and metrics default to Arena and can switch to MTGO or all. |
| Match detail and match report | yes | yes | MTGO has no board-state stream, so its turn-based analyzers report gaps instead of building on zeros (`tests/test_review_mtgo.py`). |
| Leak finder, Coach | yes | yes | The coach pools both sources and reports them separately (`by_source`). A report is for one format: habits are read across every format played, a deck's and an opponent's records from that format alone. A match counts under its format, an MTGO one under the format the user confirmed, else the one its revealed cards fit (`docs/coach.md`). |
| Deck guide, matchup briefs | yes | once the match's deck is picked | MTGO's transcript never names your deck, so the user confirms it on the match's page, or many at once on `/mtgo/picks`, grouped by the saved list that fits; Home lists the matches still waiting. The pick is `mtgo_match_pick`, read through `v_match_deck` (`docs/architecture.md`). |
| Current match (replay, keep guide, hand read, sideboard break) | yes | no, by design | `v_current_match` is Arena-only (migration 040), because MTGO has no stream for the replay to run against. |
| RCQ guide (`/decks/:id/rcq`, the deck page's RCQ tab) | yes | once the deck is picked | One document for the exact 75 the user pastes, against the last 14 days of the field and the last 7 days of events; a Claude button writes it, or the answer to its copied prompt is pasted into the page (`docs/guide.md`). The corpus now also reads mtgo.com directly, fresh to within hours (`docs/metagame.md`). |
| Field | — | — | The field's tournament corpus, one format at a time (`?format=`, by default the format of the most recent match). It defaults to the window since that format's last reset. Duplicate events are marked, not double-counted (migration 043). Each stored event is listed and has a page of its own (`/field/events/…`): every deck's standing, archetype and list, and a link to where the results were published. `serve` keeps the corpus current on its own (`docs/metagame.md`, "Fetching the corpus"). |

Every metered Claude call is a button press and nothing else (AGENTS.md
non-negotiable #5). `serve` refuses to bind anything but loopback, and
`api/guard.py` refuses a foreign `Host` or `Origin` and any write without the
dashboard's own header, so another page open in the browser can't use the
API either (`tests/test_guard.py`).

Besides the error reports and contributed games, which only the user's
yes sends (the privacy policy), the measurements are these: the daily
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
  (`docs/current-match.md`). See `BACKLOG.md`'s BL-013, "MTGO on the Live
  page".
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

## Not planned

Decisions about the product as a whole, not gaps: each one was considered
and refused. Moved here from `ROADMAP.md` on 2026-11-06; the site's "What
is not planned" card links to this section.

- **Live advice during an event.** In an Arena event (paid events,
  drafts, the Arena Open, Directs, Qualifiers, a Direct Challenge) the Live
  page shows what any tracker shows: your library, draw odds, the cards
  your opponent has revealed and what deck they point to. Keep advice, hand
  reads and play-arounds appear in casual games, on the ranked ladder and
  between games, and a switch in Settings hides them everywhere. Until
  October 2026 the ladder got none either. The rules that could reach a
  tracker are the
  [Digital Tournament Rules](https://blogs.magicjudges.org/rules/dtr/) and
  the [Digital Infraction Procedure Guide](https://blogs.magicjudges.org/rules/dipg/2-2/):
  they allow deck tracking software that shows no private information,
  they count play advice from an outside source as outside assistance, and
  they govern tournaments, which the ladder is not. On the ladder only
  [Wizards' Terms](https://company.wizards.com/en/legal/terms) apply, and
  they treat every tracker alike. The terms of the
  [Arena Open](https://magic.wizards.com/en/news/mtg-arena/arena-open-terms-and-conditions)
  and [Arena Direct](https://magic.wizards.com/en/news/mtg-arena/arena-direct-terms-and-conditions)
  say nothing of trackers either way, so events keep the stricter line.
- **Reading the memory of, injecting into or automating either client.**
  The tracker reads the log files Arena and MTGO already write, with
  Arena's own Detailed Logs setting on, and nothing else.
- **Pooling or sharing your matches without your yes.** Your match
  history is never pooled or shared by default. Two things leave your
  computer only when you turn them on: a backup of your match summaries
  that only you can read, with the free account, and, with or without
  one, your games contributed to the stats, stripped of everything that
  names you or your opponent. A report you generate with your own key
  sends that match to the model you configured. The matchup numbers from
  outside your own games come from published tournament results.
- **Draft.** The draft assistant was removed in October 2026 and is not
  coming back in this project.
- **Mobile.** iOS makes log reading impossible and Android impractical.
- **Alchemy and Brawl.** Games in them still appear in your history, but
  no field data or format-specific feature is built for them.

## Data the real database still carries

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
