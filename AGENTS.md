# AGENTS.md

Guidance for anyone — human or agent — changing this repo. These rules were
derived from the existing code, not imposed on it: every one of them is already
followed somewhere, and the surrounding code is the best reference.

Read [`docs/`](docs/) for the detail behind each section — but only the ones
your task touches; they are not required reading up front:

| Document | Covers | Read when |
|---|---|---|
| [docs/architecture.md](docs/architecture.md) | The two-stage pipeline, module boundaries, schema and migrations | touching `reader/`, `projector/`, `live.py`, or a migration |
| [docs/arena-log.md](docs/arena-log.md) | What Arena's log actually does, and the traps that cost real debugging | parsing or interpreting log entries |
| [docs/conventions.md](docs/conventions.md) | Code style, comments, error handling, CLI and API patterns | writing any Python |
| [docs/testing.md](docs/testing.md) | Fixture discipline and what counts as verification | writing or changing tests |
| [docs/frontend.md](docs/frontend.md) | Dashboard: the shell and its addresses, typed API contract, chart rules | touching `web/` |
| [docs/design-system.md](docs/design-system.md) | The visual system: palette + validation, type ramp, radii, elevation, density, mana-pip rules, the rules a new component follows | touching visual styling anywhere in `web/`, `components/ui/`, or `scripts/validate_palette.py` |
| [docs/metagame.md](docs/metagame.md) | The evidence tiers, complete- vs. partial-decklist classification, corpus fetch policy | touching `metagame/` or the personal/field matchup join |
| [docs/review.md](docs/review.md) | What each match-report analyzer measures, the strategy article behind it, and the leak finder | touching `review/` |
| [docs/guide.md](docs/guide.md) | The deck guide: format-reset detection, the list-vs-consensus diff, the field join, the prompt/import round trip | touching `guide/` or a deck's Guide page |
| [docs/brief.md](docs/brief.md) | The live matchup brief, and the prompt-out/answer-in round trip that replaced every paid call | touching `brief/` or the matchup-brief card |
| [docs/coach.md](docs/coach.md) | The coach's scope and exclusions, the skill/format evidence windows, the leak and example-game selection rules, the reading list and web-search allowlist, and progress-since-last-report | touching `coach/`, `api/routes/coach.py`, or the Coach page |
| [docs/current-match.md](docs/current-match.md) | The live replay, the keep guide, the opponent-hand read and the remaining-library panel — the current-match reads, why they replay `raw_events` instead of reading `turns`, and their degradation rules | touching `table/`, `/api/current-match/read`, or the Live page |
| [docs/llm.md](docs/llm.md) | The opt-in Claude API call: credential resolution, config file, which routes call out and what they send, cost accounting, the no-credential fallback, why nothing hosted ever writes for the user | touching `llm/`, a `.../narrative` POST route, or `GenerateCard`; planning anything hosted |
| [docs/attribution.md](docs/attribution.md) | Every outside source the app downloads from, what it takes from each and on what terms; the Fan Content Policy notice | adding or changing a download source, or writing text that names a third party |
| [docs/status.md](docs/status.md) | Where the project stands, and the register of known debt and deferred work | starting a new feature, or deciding what to pick up next |
| [docs/branching.md](docs/branching.md) | The gitflow model: `main` and `develop`, feature, release and hotfix branches, merge commits, what two open branches collide on (migration numbers, generated files, lockfiles), commit messages, who pushes and merges | creating a branch, opening or merging a pull request, renumbering a migration, cutting a release |

## The project in one paragraph

A fully local Magic: The Gathering analytics tool. It reads the log files
Arena and MTGO already write — `Player.log` and `Match_GameLog_*.dat`
respectively — stores raw events verbatim in SQLite, projects them into
matches/games/turns, and serves a dashboard on loopback. No account, no
upload, no writes to anything either client owns.

## Repo map

One line each; the detail is in the doc named, and
`repo_map.py --path <dir>` lists a directory's files and symbols.

- `src/sensei_top/reader/` — files, offsets, hashing, for Arena's `Player.log` and MTGO's `Match_GameLog_*.dat`. Knows nothing about either client's semantics.
- `src/sensei_top/projector/` — match semantics, Arena and MTGO (`mtgo/`). Knows nothing about files.
- `src/sensei_top/live.py` — the only module that drives both reader and projector — `docs/architecture.md`, "Live mode's two cadences".
- `src/sensei_top/api/` — FastAPI app (`app.py`, `routes/`, `models/`), read-only except the authored-artifact routes (non-negotiable #6); `guard.py` refuses foreign requests; `dashboard.py` serves `src/sensei_top/web_dist` and answers a page's address with `index.html` — `docs/frontend.md`, "Ports".
- `src/sensei_top/review/` — the post-game match report, the cross-match leak finder and their prompts — `docs/review.md`.
- `src/sensei_top/guide/` — the deck guide, built on `review/` rather than duplicating it, and the RCQ guide for one pasted 75 — `docs/guide.md`.
- `src/sensei_top/brief/` — the live matchup brief, one per `(deck, archetype)`, persisted as an authored artifact; `coverage.py` reads which archetypes still lack one — `docs/brief.md`.
- `src/sensei_top/coach/` — the dated cross-deck coach report, kept as history; reuses `review/` and `guide/` — `docs/coach.md`.
- `src/sensei_top/table/` — the current-match reads: a request-time replay of `raw_events`, never stored. Arena-only. `ranked.py` is the ranked-play rule: no advice on Live during a ranked game — `docs/current-match.md`.
- `src/sensei_top/archetypes/` — deck-archetype classification from revealed cards: a rule engine (`classify.py`) and a corpus read (`corpus.py`) — `docs/architecture.md`, "Naming the opponent's deck".
- `src/sensei_top/metagame/` — real tournament results, tiered by evidence quality — `docs/metagame.md`.
- `src/sensei_top/backup/` — the daily verified database snapshot; imports neither `reader` nor `projector` — `docs/architecture.md`, "Backups".
- `src/sensei_top/cli.py` — every subcommand (`uv run sensei-top --help` lists them). `serve` refuses any `--host` that isn't loopback (non-negotiable #5). The watcher's flags and how it stores each MTGO game once the game ends are in `docs/architecture.md`, "Live mode's two cadences".
- `src/sensei_top/cards.py`, `card_images.py` — card database and image cache.
- `src/sensei_top/llm/` — the opt-in Claude call; `config.py` resolves the credential, `client.py` is the only `anthropic` import — `docs/llm.md`.
- `src/sensei_top/mtgo/config.py` — the user's MTGO handle and log directory, fail-soft; the directory is never guessed.
- `src/sensei_top/steam.py` — Steam library discovery; filesystem only.
- `src/sensei_top/arena_install.py`, `mtgo/discover.py` — where Arena is installed (from the log's first line) and which folder MTGO writes now (Windows, a suggestion only) — `docs/architecture.md`, "Finding the clients' files".
- `src/sensei_top/logs.py` — the log file under the `--db`'s `logs/` folder; `procs.py` — the watcher child dies with `serve` — `docs/architecture.md`, "The log file".
- `src/sensei_top/db.py` — `open_database()`, the one place migrations are applied.
- `web/src/` — React dashboard: `routes.tsx` is the table of addresses, `shell/` the layout, `pages/` read an address, `views/` and `components/` draw — `docs/frontend.md`, "The shell". Older docs call a view a tab; it is the same view, at its address.
- `tests/` — flat `tests/*.py`, all fixture-backed, no mocks of Arena. The dashboard's own tests sit beside what they test, `web/src/**/*.test.ts` — `docs/frontend.md`, "Checks".
- `src/sensei_top/migrations/NNN_*.sql` — applied only inside `open_database()`, at process startup: a one-shot command's, against the `--db` it is given, or `serve`'s. Everything `serve` opens later uses `connect()`, so a new migration is **pending** until `serve --watch` restarts — `docs/architecture.md`, "Storage". Check `SELECT MAX(version) FROM schema_version` on a read-only connection rather than assuming. The API never migrates.

## Expensive files — do not read

- `web/src/types/api.ts`, `web/openapi.json` — generated from the API schema. Regenerate with `pnpm gen:types`; don't read or hand-edit.
- `uv.lock`, `web/pnpm-lock.yaml` — lockfiles, never worth reading.
- `tests/fixtures/*.log` — raw client captures, in **two formats behind one
  extension**. Arena's are a few dozen lines but hundreds of KB, with single
  lines running past 50,000 characters; `head` gives no protection.
  `mtgo_match_session.log` is MTGO's game log — a binary .NET string stream,
  not text at all. Never `Read`, `cat`, or `head` any of them. Use the
  `navigating-sensei-top` skill's `fixture_peek.py` to index Arena entries
  and extract one at a time, and `scripts/mtgo_probe.py` for the MTGO one
  (`--force --lines 400`); `fixture_peek.py` cannot read the MTGO fixture and
  will say so.
- Scope greps to `src/ web/src tests docs` — an unscoped grep from repo root walks `.venv/`, `web/node_modules/`, and `data/` (real match history, gitignored).

## Non-negotiables

1. **Never break the two stages.** The reader knows about files, offsets and
   hashing; the projector knows about Arena semantics. Neither learns the
   other's job. `live.py` is the only module that drives both.
2. **Raw events are append-only and verbatim.** Store the payload exactly as
   it appeared. Arena wipes `Player.log` on every launch, so a parsing bug can
   destroy data that no longer exists anywhere else — keeping the raw text is
   what makes a fix retroactive.
3. **Projection is always a full rebuild.** `project()` deletes every derived
   row and recomputes from `raw_events`. Never write an incremental path.
4. **Never synthesize data.** Unknown or missing means `NULL` plus a warning —
   never a guess, never an exception that halts ingestion.
5. **Metered API calls are opt-in and user-configured — never silent, never
   automatic.** This project costs nothing to run unless the user configures a
   Claude credential and presses a button that says so. It is a product
   decision, not an implementation detail. Four lines do not move:

   - **No credential, no call.** `llm/config.py` is the only place a metered
     credential is resolved; `llm/client.py` is the only module that imports
     `anthropic`. Unconfigured, every generate route 503s and the dashboard
     falls back to `CopyPromptCard` — no difference from before the feature.
   - **Every call is a button press, never a schedule.** Only the five
     `POST .../narrative` routes call out — the match report, the leak
     finder, the deck guide, the RCQ guide and the coach. No background worker, and nothing
     calls out during ingest, projection, `serve --watch`, or page load. A
     scheduled or triggered call is a different feature, not a variant. The
     coach's is the one that pays for web search too, so it is also the one
     whose cost moves with something other than its own tokens.
   - **Cost is measured, never estimated** — from `response.usage`, per rule 4.
     An unrecognized model prices `NULL`, never a fabricated number.
   - **Loopback binds only.** This is why no part of this app needs an
     authentication story; changing it means building one first. `serve`
     enforces it (`cli.py::_require_loopback`), pinned by `tests/test_cli.py`.
     Binding loopback isn't the whole story, since any page open in the
     user's browser can still send requests to it: `api/guard.py` refuses a
     foreign `Host` or `Origin` and any non-GET request without the
     dashboard's `X-Tracker-Client` header, pinned by `tests/test_guard.py`.

   **Decided 2026-10-07: there is no paid tier, no hosted proxy and no
   account, and the copy-prompt path stays.** This reverses the 2026-10-01
   decision (Pro tiers, a proxy, the prompt removed). The project is free
   software (AGPL-3.0-only, `LICENSE`) funded by donations, and the Fan
   Content Policy forbids charging for it — "You can't require payments,
   surveys, downloads, subscriptions, or email registration to access your
   Fan Content" — so nothing a donation buys is ever inside the app. Two
   paths generate prose, both the user's own: the prompt round trip
   (`CopyPromptCard`, `guide --import`, `brief --import`), kept and kept
   improving, and a credential the user configures themselves. The
   maintainer's own key never writes for anyone else. Planned, not built:
   a provider adapter so the credential can be any OpenAI-compatible
   endpoint or a local model, which widens "the only module that imports
   `anthropic`" to "the only package that talks to a model" and labels each
   stored narrative with the model that wrote it; the coach's web search
   then degrades to the reading list on a provider without it. The brief,
   coverage and sideboard-plan cards stay on the copy prompt until that
   adapter gives them a generate route, which would extend the five-route
   list above and the route set `test_only_authored_artifact_routes_write`
   pins. See `ROADMAP.md` and `docs/status.md`, "Features not built".

   **Free downloads are governed by a different standard, not by this rule** —
   the card database, card images, archetype definitions, the tournament
   corpus, TopDeck.gg: *reference lookups only, fail-soft always, no more than
   the feature needs.* A free rate-limited key is a download source, not a
   metered call, even though TopDeck.gg's is user-supplied.

   Third-party identifiers are not forbidden: an opponent's Arena handle is
   part of the user's own match history and may be used where it earns its
   place.

   Full picture — what each route sends, credential resolution, measured costs,
   and the TopDeck.gg wrinkle: [docs/llm.md](docs/llm.md). Pinned by
   `tests/test_llm.py::test_no_credential_means_no_client_is_constructed`.
6. **The API writes only authored-artifact tables, never anything the
   projector rebuilds.** Every connection opens `PRAGMA query_only=ON` except
   the small allowlist of routes that write one of: `opponent_deck_override`
   (a manual pick of the opponent's deck — the user's own correction of their
   own match, with no other source, and it has to outlive the full rebuild
   that erases every derived row), `mtgo_match_pick` (the user's own deck and
   format for an MTGO match, which MTGO's log never names — the same kind of
   answer, with no other source, kept for the same reason) or one of the
   authored-prose tables `deck_narrative`,
   `matchup_brief`, `match_narrative`, `leaks_narrative`, `coach_report` (a
   generated or imported narrative — never a derivation of projected data,
   so a rebuild can't recompute it either; `coach_report` is the one that
   keeps every row rather than one current slot, because each report is
   measured against the one before it), and `rcq_guide` (a tournament-day guide written for one decklist the user
   pasted; like `coach_report` it keeps every row, because each one is the
   record of a specific event's preparation). Nothing on this allowlist is ever read by
   `project()`.
   `tests/test_api.py::test_only_authored_artifact_routes_write` asserts the
   exact set of non-GET routes against this allowlist — an addition to it is
   a design change, not a patch.
7. **Every parsing rule needs a fixture-backed test.** The log format changes
   without notice; tests against real captured logs are the only early warning.
8. **Derive test expectations from the data, not from the code.** Read the
   fixture to find the right answer — via `fixture_peek.py`, or
   `scripts/mtgo_probe.py` for the MTGO fixture (see "Expensive files"
   above), never by opening the log directly. Never run the code and
   copy its output into an assertion — that tests only that the code does
   what it does.

## Running it

    cd web && pnpm start       # build + live mode, dashboard at http://127.0.0.1:8000
    cd web && pnpm dev         # Vite dev server at :5173, proxies /api to :8000
    uv run sensei-top cards --scryfall   # rules text + legality; the deck guide needs
                                            # this at least once (docs/guide.md), the
                                            # installed-client path never carries either

Every command appends its warnings to `logs/sensei-top.log` beside the
database it opens (`data/logs/` for the real one); `--verbose` adds the
debug lines.

## Before you finish

    uv run ruff check .        # must be clean
    uv run pytest -q           # must be green
    cd web && pnpm lint && pnpm test && pnpm build

Then verify against reality, because the fixture is a curated subset and green
tests are not proof the thing works:

    uv run sensei-top --db /tmp/check.db ingest --file "$MTGA_LOG" --locale mdy
    uv run sensei-top --db /tmp/check.db project
    uv run sensei-top --db /tmp/check.db report

Use a scratch `--db`; never point verification runs at `data/sensei-top.db`.

If a check fails, **report it — do not adjust the check until it passes.** A
surprising result is usually information, not an obstacle. Two of this
project's real bugs were found exactly that way, and one earlier diagnosis was
wrong because a fixture was mistaken for a complete log.

## Privacy

Before committing, confirm no real identifiers leak: run
`uv run python scripts/privacy_scan.py` (and `--history` before anything is
published). It derives your identifiers locally and prints only categories,
paths and counts, never an identifier itself. Fixtures are anonymized;
player names, user IDs and local paths must not appear in tracked files.
`data/`, `*.db`, `*.db-wal` and `*.db-shm` stay gitignored — they hold real
match history. A real Anthropic API key lives outside the repo entirely: in
the system keyring (service `sensei-top`) where one exists, or in
`~/.config/sensei-top/config.toml` — never add a mechanism that copies or
logs either into a tracked file, and never let a test reach the real
keyring. A `[backup] dir` pointing inside the repo but outside `data/` would
put real match history where git can see it — the
`*.db.backup`/`*.db.backup.[0-9]*` gitignore entries cover the default
naming, but a location the user chooses is theirs to keep out of the tree.

## Working style

- **Ask when a decision is the user's**, especially anything touching their
  system (installing packages, `sudo`, git identity) or an interface they will
  live with. Clarify concepts before building on an assumption about them.
- **Say what you actually verified**, and what you did not. "Tests pass" and
  "I watched it work" are different claims.
- **Correct yourself out loud.** If an earlier explanation was wrong, say so
  plainly and explain the real cause.
- **One feature per branch, cut from `develop`.** `feature/<topic>`, merged
  back by pull request with a merge commit; `main` moves only on a release or
  a hotfix. Pushing, opening a pull request and merging wait for the user's
  word — [docs/branching.md](docs/branching.md).
- **One feature per session.** When a task finishes, or context passes ~150k
  tokens, write a handoff note to `.claude/handoffs/<topic>.md` (gitignored;
  any existing note there shows the pattern) and tell the
  user to `/clear` before starting the next thing — every turn re-reads the
  whole context, so a long session pays for its own history over and over.
- **Unattended, by the user's choice only.** `.claude/overnight/run.sh`
  runs the loop above overnight: a fresh session per pull request, the push
  and merge done by the driver after the checks pass, the real server
  restarted on `develop`. A session it starts never pushes or merges
  itself — [docs/branching.md](docs/branching.md), "Who pushes and who
  merges".
