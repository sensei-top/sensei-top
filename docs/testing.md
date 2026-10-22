# Testing

Every test is fixture-backed or synthetic — no mocks of Arena, no network, no
sleeping on real time for logic.

This document is about the Python suite. The dashboard's tests (vitest: the
pure functions under `web/src/lib/`, and the build's notices step under
`web/scripts/`) follow the same rule on ground truth and are described in
[frontend.md](frontend.md), "Checks".

> **Every parsing rule must have a fixture-backed test.** This is the single
> most important quality lever in the project, because the log format changes
> without notice and the change arrives as silently wrong numbers.

## The fixtures

| Fixture | What it is |
|---|---|
| `tests/fixtures/sample_player.log` | Small anonymized capture: entry shapes, noise lines, nested JSON |
| `tests/fixtures/match_session.log` | A real Bo3 session: 2 matches, 5 games, 16 turns, 1 deck |
| `tests/fixtures/combat_session.log` | A real match's combat: attacks, one declared block, creature-vs-creature damage, damage to a player, a non-combat life change — carved from `raw_events` after its own source log had already rotated away (see `migrations/014_combat.sql`'s own comment on why that is still a legitimate carve, not a reconstruction) |
| `tests/fixtures/mulligan_session.log` | One real mulligan-then-keep sequence, 10 events: room start, the deal, the first offer, our own Mulligan, a second offer that includes a stale leftover `gameObject` sharing our hand's `zoneId` but absent from its `objectInstanceIds` (`projector/mulligan.py`'s own trap), our Accept — carved from `raw_events` the same legitimate way `combat_session.log` was, because no earlier capture happened to include a `GameStateMessage` mid-mulligan at all (`docs/arena-log.md` trap 14) |
| `tests/fixtures/intermission_session.log` | One real Bo3 break, 44 entries: the auth and room start, all of game 1 (a turn-4 opponent concede), the whole break (`GameComplete` + `IntermissionReq`, `EnterSideboardingReq`, `SubmitDeckReq`/`Resp`, `SubmitDeckConfirmation`), game 2's `GameStage_Start`, then the match-final `GameComplete`/`MatchComplete` event and the room's `MatchCompleted` (`docs/arena-log.md` trap 11c). Carved from `raw_events` the same legitimate way `combat_session.log` was, because Arena's next launch wiped the source log. **A curated subset**: UIMessage- and TimerStateMessage-only events are dropped, and so is game 2's middle, so game 2's `turn_count` projects NULL. Game 1, the break and both results are complete |
| `tests/fixtures/draft_session.log` | One real Quick Draft, start to finish: 42 packs seen, 42 picks made, set SOS — carved with `DTO_InventoryInfo` (the account's own gems/gold/wildcards/cosmetics, ~61 KB per pick response and irrelevant to drafting) stripped from every response, and every message-correlation uuid replaced with a deterministic synthetic one (`docs/draft.md` at the `archive/draft` tag, in the project's pre-public history, which this repository does not carry). Since the draft assistant was deleted it pins only that the projector keeps a draft's entries raw and derives nothing from them (`test_projector.py`). The parser never reads `DTO_InventoryInfo`, so the carve costs no coverage. Stripped, this fixture is ~40 KB — small enough that it is the one fixture in this list safe to `Read` directly rather than only through `fixture_peek.py`; the others still run individual lines past 50,000 characters |
| `tests/fixtures/human_draft_session.log` | One real Phantom Cube draft (2026-09-08, `CubeDraft_Powered_20260908`) — the human-draft message family (`Draft.Notify`/`EventPlayerDraftMakePick`), distinct from Quick Draft's, kept for the segmenter's `Draft.Notify` labelling (`test_segmenter.py`). **A curated subset, not the full draft**: the real capture ran 3 packs / 45 picks; the fixture keeps only the first 22 (through pack 2 pick 7), then appends the real `DraftCompleteDraft` request/response pair carved from the *end* of the same capture, with its own real header timestamp preserved so both keep the exact `logged_at` the capture gave them. Message-correlation uuids and `CourseId` replaced with deterministic synthetic ones; `CardPool`/`CourseDeckSummary` dropped, since the parser reads neither. Reading pack/pick numbers or "the draft completed" out of this fixture is safe; reading "the pool has 45 cards" or timing for picks 23–45 is not — they were never carved in |
| `tests/fixtures/header_languages.log` | Arena's header timestamp in seven of its eight languages, from one session on 2026-10-06 with the in-game language switched between entries (`docs/arena-log.md`, "Timestamps"). English: one `EventGetActiveMatches` response and an unprefixed `LoadWrapperScene` line, which is not a header. Japanese, Korean, Spanish, German, Italian and French: one `DeckUpsertDeckV3` response and the first `ClientToGreuimessage` event each. The dates' ground truth is in the payloads: `LastPlayed` is local time with its offset and equals its header, and the event's `timestamp` is .NET ticks in UTC. Portuguese writes Spanish's shape and is in `header_relaunch.log`. Uuids replaced with deterministic synthetic ones |
| `tests/fixtures/header_relaunch.log` | The start of a launch with Portuguese already saved, 2026-10-06: the `Startup Timestamp:` line, still in English and not a header; a `GraphGetGraphState` request that comes before any header; the first two Portuguese headers (`dd/MM/yyyy HH:mm:ss`); and an unprefixed `LoadWrapperScene` line |
| `tests/fixtures/client_header.log` | The first 40 lines of a real `Player.log`, its line 35 `DETAILED LOGS: ENABLED`; `doctor`'s and `diagnostics`' tests (`test_doctor.py`) |
| `tests/fixtures/rank_session.log` | One real `RankGetCombinedRankInfo` response, rebuilt in the segmenter's three-line bare-response shape; the payload's values are real and the response uuid a placeholder (`test_rank.py`, `test_api.py`) |
| `tests/fixtures/sideboard_session.log` | Two real entries: a `SubmitDeckResp` and the `GameStateMessage` after it that names game 2, with a small real subset of the deck's `grpId`s (`test_sideboarding.py`) |
| `tests/fixtures/bo1_session.log` | One real best-of-one match (2026-08-31, queue `Play`), 5 entries: the `AuthenticateResponse` (which seat is ours), the room start, the first `GreToClientEvent` (`ConnectResp` and the full game state, whose `gameInfo` reads `matchWinCondition: MatchWinCondition_SingleElimination`), the game-over event (`GameComplete` then `MatchComplete`, a concede; `IntermissionReq` rides it in a Bo1 too) and the room's `MatchCompleted`. The only fixture that is not a Bo3, kept for telling a match's best-of from its log (`matches.best_of` is 1 for it; 3 for `match_session`, `combat_session`, `intermission_session`, `mulligan_session` and `sideboard_session`; `sample_player.log`'s match has no `gameInfo`, so NULL). Carved from `raw_events` the same legitimate way `combat_session.log` was. **A curated subset**: every message between the first state and the game over is dropped, so its turns are not a timeline |
| `tests/fixtures/undo_session.log` | The first five turns of one real game (2026-09-29, game 1 of a Bo3), 24 entries: the `AuthenticateResponse`, the room start, then every `GreToClientEvent` that carries a game state, from the `ConnectResp` and the game's first Full state through two states past an undo. State 96 reaches the log only as a `QueuedGameStateMessage`, and it carries a `CastSpell`. State 100 is a `CastSpell` the player then cancelled: state 101 is a Full state whose `update` is `GameStateUpdate_Undo` and whose `prevGameStateId` is 99, and state 102 casts again. Kept for the undo rollback and the queued state message (`docs/arena-log.md`). Carved from `raw_events` the same legitimate way `combat_session.log` was, with each payload on one line as Arena writes it. **A curated subset**: the game stops at state 103, unfinished, and events carrying no game state (UI and timer messages, the client's own requests) are dropped |
| `tests/fixtures/mtgo_match_session.log` | MTGO's game log for one real two-game match between `Player1` and `Player2000`, 7,838 bytes. **Binary**, a .NET string stream: read it with `scripts/mtgo_probe.py --force --lines 400`, never `fixture_peek.py` (`test_projector_mtgo.py` and the other MTGO tests) |

Beside the logs sit reference fixtures that are not client captures: MTGO
deck files and the `cards` rows they resolve against (`mtgo_deck_*.dek`,
`mtgo_deck_cards.json`, `mtgo_grouping_*.xml`), saved pages and JSON from
the MTGO results site (`mtgo_site_*`), and Scryfall printings
(`scryfall_*.jsonl`).

All of the above are **anonymized** — player names and user IDs are replaced
(`SelfPlayer`, `OppPlayerOne`, `SELFCLIENTID0001`; `Player1` and `Player2000`
in the MTGO log) or, for `draft_session.log`,
account-state fields are stripped entirely since there is no player name in a
draft message to begin with. Never commit a raw capture.

### The fixtures are curated subsets

`match_session.log` holds **34 log entries carved from a 4,595-entry session**.
Intermediate messages were dropped when it was anonymized, so it is not a
faithful timeline: match `fa7a4d16` game 2 records turns 1, 2, 3 and then 24,
because turns 4–23 were cut.

This matters enormously. An earlier investigation concluded turn 24 was a
"stray post-game artifact" and turn 3 was the truth — exactly backwards, and
the mistake came from treating the fixture as complete. **Gaps in the fixture
are expected; contiguity is verified against the full log instead.**

## Ground truth comes from the data

Derive expected values by **reading the fixture** — grep the raw JSON, find the
message, read the number. Never run the code and paste its output into an
assertion: that asserts only that the code does what it currently does, and it
locks in bugs as "expected".

Where a value is non-obvious, the test says where it came from:

```python
def test_life_totals_at_decisive_final_turn(db):
    """Ground truth read directly from the fixture's GameComplete messages,
    not from running the projector and copying its output:

    - fd5624a4 (LOSS match, self seat 2) game 2 ends at gameStateId 733 with
      both players' lifeTotal == 10.
    """
```

## Test style

- **Docstrings explain why the case matters** — the trap being guarded, not the
  mechanics. `test_no_double_counted_games` says *"Arena emits
  GameStage_GameOver twice for the last game of a match."*
- **Names state the claim**: `test_on_play_alternates_within_a_bo3`,
  `test_recovery_does_not_duplicate_rotated_content`,
  `test_absent_mulligan_count_means_zero`.
- **Group with section comments**: `# --- digest ---`, `# --- robustness ---`.
- **Fixtures over setup code**: a `conn` / `db` / `client` pytest fixture that
  builds a temp database, ingests, projects, and yields.
- **`make_client`, not a bare `TestClient`, for anything that talks to the
  API.** `api/guard.py`'s `LoopbackGuard` refuses `TestClient`'s own default
  `Host` (`testserver`, which names nothing loopback) with a 400, so a bare
  `TestClient(create_app(...))` now fails before reaching a route.
  `conftest.py`'s `make_client` fixture wraps one with a loopback `Host` and
  the dashboard's own `X-Tracker-Client` header already set, so it looks like
  the real frontend to the guard and a test can go back to being about the
  route, not the guard. `test_guard.py` is the one module that builds bare
  clients on purpose, to control exactly which headers are present.
- **Synthetic minimal inputs** for edge cases the real log cannot easily show
  (brace counting, escaped quotes, rollback on a bad migration).
- **`tmp_path` always.** A test must never touch `data/sensei-top.db`.

## Determinism over realism in timing tests

Live mode is tested by driving `poll_once()` directly, not by sleeping and
hoping. The loop around it is five lines; the logic is in the method.

Where a thread genuinely must be tested (start/stop, surviving a failing poll),
poll until a condition with a deadline rather than sleeping a fixed interval:

```python
deadline = time.monotonic() + 5
while live.stats.projections == 0 and time.monotonic() < deadline:
    time.sleep(0.02)
```

## Truncated-prefix parametrization

MTGO's game-log file has no line-oriented framing to resume from mid-file —
it only means something decoded whole, and the reader stores the whole file
as it stands when it is stored (`reader/mtgo.py`). While the watcher runs
that is once a game ends, but the watcher's first pass and `ingest-mtgo`
store a match in progress mid-game, and a file quiet for 10 minutes is
stored whatever its last game says. That means the
parser must hold true against **any** prefix of a real file, not just its
final, complete form. `tests/test_projector_mtgo.py`'s
`test_truncated_prefixes_are_monotonically_honest` is the pattern for any
future live-source parser that faces the same situation: parametrize over a
spread of byte cuts of one real fixture
(`@pytest.mark.parametrize("cut", [40, 200, 800, 2000, ...])`) and assert the
one property a mid-flush snapshot must satisfy — **a prefix may lose the
tail, never gain content** (`set(prefix_strings) <= set(full_strings)`, never
the reverse). A parser that hallucinates something from a truncated string —
finishing a bracketed card name, inferring a game result, guessing a count —
would violate append-only, never-synthesize semantics (non-negotiable #2 and
#4) the moment a live poll caught the file mid-write, and this is the test
shape that would catch it. `test_prefix_cut_mid_mulligan_is_incomplete_with_no_ended_at`
extends the same idea one level up the pipeline: a specific, deliberately
mid-mulligan cut of the fixture (`FIXTURE_BYTES[:222]`) must project to an
`incomplete` match with no `ended_at`, not a guessed result.

## CI

`.github/workflows/ci.yml` runs two jobs on pull requests into `develop` or
`main`, by hand (`workflow_dispatch`), and on pushes to `develop` and `main`.
Two repositories hold this file. The private one never spends minutes on a
push: its Actions minutes are metered (2,000 a month on Free, and a Windows
minute counts twice), so each job carries
`if: github.event_name != 'push' || github.repository == 'sensei-top/sensei-top'`
and a push there shows a run whose jobs are skipped. The public repository,
`sensei-top/sensei-top`, runs every trigger, since its minutes are unmetered.

- **Linux:** `ruff check .`, `pytest -q`, then in `web/` `pnpm lint`, `test`
  and `build`, then the drift check: `pnpm gen:types` followed by
  `git diff --exit-code`, which fails if the tracked `web/src/types/api.ts` no
  longer matches the API (`openapi.json` is a gitignored intermediate).
- **Windows:** `pytest -q` only. No test reads the built dashboard
  (`test_dashboard.py` writes its own `web_dist`), so neither pnpm nor a
  build is needed there. `.gitattributes` marks `tests/fixtures/**` as `-text`
  so Git for Windows' CRLF conversion never touches the raw captures.

The privacy scan has its own gate, outside CI: the tracked hooks in
`scripts/git-hooks`, enabled in a clone with
`git config core.hooksPath scripts/git-hooks`. `pre-commit` runs
`privacy_scan.py` over the tracked tree, with the files being committed, and
refuses the commit on a hit; `pre-push` runs `privacy_scan.py --pre-push`
over the commits a push sends.

`verify.py --full` runs the same drift check after `pnpm build`, so a stale
`api.ts` fails locally before it fails in CI; the fix it names is
`cd web && pnpm gen:types` and commit the result.

Python is the 3.12 in `.python-version`; pnpm 11 and Node 24 (LTS).

Per-job minutes, from the first run (2026-10-06, cold caches): Linux 3 min
46 s, Windows 7 min 12 s, with pytest taking 3 min 4 s and 6 min 45 s of
them. GitHub rounds each job up to a whole minute and bills a Windows minute
twice, so one run costs 4 + 2 × 8 = 20 of the month's 2,000: about 100 runs
a month.

Windows skips about fifteen tests by design (a `:` or `?` in a file name,
POSIX permission bits, POSIX signals, the open-database race in the
install move, `/dev/shm`); each skip says why. What CI cannot reach is checked by hand on a Windows
machine, as plan 3 did on a Windows 10 VM: a kill that leaves no watcher
(`taskkill /F`, the Job Object), Ctrl+C, the log file beside a second
process. One trap there: a process started over `ssh` inherits "Ctrl+C
ignored" from the session, so a harness that tests Ctrl+C calls
`SetConsoleCtrlHandler(None, False)` (through `ctypes`) before it starts
`serve`.

`.github/workflows/desktop.yml` is the packaging workflow, separate from the
checks above: by hand (`workflow_dispatch`, which builds both packages as
artifacts kept one day, since the private repository's storage is metered,
and never publishes) and on a pushed tag `v*`. Every job is skipped for a tag
pushed anywhere but `sensei-top/sensei-top`, so tagging in the private
repository costs nothing. On a tag in the public one the two builds first
check that the tag is `v` plus `pyproject.toml`'s version, then a third job,
`release`, downloads both artifacts, writes the release notes with
`scripts/release_notes.py` (the tag's section of `CHANGELOG.md`; no section,
no release) and creates the GitHub Release with every file attached in one
`gh release create`, which uploads them before it publishes, so the updater
never sees a release without its `latest.yml`. When a `VIRUSTOTAL_API_KEY`
secret exists it uploads the installer and the AppImage first and adds the
analysis links to the notes; without the secret that step is skipped. The
Linux job runs on a pinned Ubuntu, not `ubuntu-latest`, because the frozen
server needs a glibc at least as new as the build host's. Minutes on the
public repository are unmetered. Its first real run is the first tag there;
until then only the build half has run, by hand.

## Green tests are not proof

The fixture is a subset and the real log is 4,595 entries. Before calling
anything done, run against reality with a scratch database and check
**structural invariants** — properties that must hold for any log, not counts
that depend on which session was captured:

- `COUNT(*) FROM turns` equals the count of distinct
  `(match_id, game_number, turn_number)`
- every `(match_id, game_number)` in `turns` exists in `games`
- `MAX(turns.turn_number)` per game equals `games.turn_count`
- turn numbers per game are contiguous from 1
- turn-1 life totals equal the format's starting life for both seats
- every match with a `MatchCompleted` event has a result in
  (`win`, `loss`, `draw`) — never `incomplete`
- `games_won + games_lost` equals the number of `games` rows for that match
- no `turns` rows for matches whose `self_seat` is `NULL`

Then re-run `project` and diff the tables: a second rebuild must produce
byte-identical rows.

**If an invariant fails, report it.** Do not relax the assertion to make it
pass. The `turn_count` mismatch that surfaced during M2 was a real bug in
trailing-turn handling, and weakening the check would have buried it.

## Verifying a claim you inherited

When told "X works this way", check it rather than assuming. The cheapest
verification is usually a throwaway script over the real log:

- Count how often the pattern actually occurs
- Mutate the code to break the property, watch the test fail, then revert

That mutation test is how the `source_file`-exclusion rule in the digest was
confirmed to be load-bearing rather than decorative.

## The docs' names

A doc that names a file, a function, a route or a flag goes on naming it
after a rename. `scripts/check_doc_refs.py` reads every backticked name in
the docs and fails on one the tree no longer has, and
`tests/test_doc_refs.py` runs it, so a rename that leaves a doc behind
fails the suite. `scripts/check_doc_links.py` does the same for links
between docs, and `tests/test_doc_links.py` runs it: a section a doc cites
has to be named by its whole heading. A name missing on purpose, like a
removed component a doc names as history or a name from another program,
goes in the script's `ALLOW` with its reason. Neither checks what a doc *says* about a name,
so a change of behaviour still needs its doc changed by hand.

The code's own prose gets the same check. `check_doc_refs.py` also reads
the comments and docstrings in `src/`, `tests/`, `scripts/` and `web/src`,
and tests the paths, `path::symbol` references and routes they name
against the code with its comments removed, so a comment can't vouch for
itself. It doesn't test a bare name, since most of those belong to another
library or to Arena. `scripts/check_prose.py`, run by `tests/test_prose.py`,
fails on a plan or phase label in code prose, on a `path:line` reference to
one of this repository's files anywhere but the fixtures and the changelog,
and on an AGENTS.md longer than its ceiling. A third check reads the
backlog: `scripts/check_backlog.py`, run by `tests/test_backlog.py`, fails on
a malformed or repeated item ID, a label line outside the vocabularies, a
`Next ID` that is not above every ID, and on any `BL-` reference in a tracked
text file (the changelog aside) that names no item, so closing an item that
code still cites fails the suite. Whether a comment copies a doc or a
measured number is still the reviewer's to catch.

## The metagame corpus

`test_metagame.py` follows `test_archetypes.py`'s own pattern: no network at
all. Every test builds a GitHub tree listing or a tournament event as an
in-memory dict, shaped like the three real event files the findings document
behind this feature verified against GitHub on 2026-08-18 — a Melee swiss
event, an MTGO challenge, and an MTGO league — rather than a committed JSON
fixture file. `metagame/source.py`'s own networked functions
(`resolve_commit_sha`, `list_tree`, `fetch_event`) are monkeypatched exactly
the way `archetypes.source.fetch_archive` already is.

Two things this suite checks that nothing else in the project needs to:

- **No player name survives parsing.** `test_parse_event_never_retains_a_player_name`
  dumps the parsed decks and round matches to JSON and asserts the fixture's
  synthetic handles are not in it — the privacy rule from `docs/metagame.md`,
  made mechanical rather than left to review.
- **A refresh is incremental.** `test_refresh_skips_files_whose_blob_sha_is_unchanged`
  proves a second refresh over the same window re-fetches nothing whose blob
  SHA has not moved, the same shape as `test_a_fresh_cache_opens_no_socket`
  for the archetype definitions.

`tests/test_classify.py`'s "complete decklists" section extends the same
synthetic-`Definition` style the rest of that file already uses (its own
docstring: "Definitions are synthetic so each rule is isolated") to
`evaluate(..., complete=True)` and `choose(..., complete=True)`, rather than
a committed real decklist — the assertions are about which *rule* fires, not
about any one archetype's real card list, so a synthetic one-condition
definition isolates the claim being tested exactly as it does everywhere
else in that file.

## Measuring the archetype classifier

`scripts/verify_archetypes.py` is deliberately **not** in `tests/`: it needs a
real database with real matches and a downloaded set of definitions, neither of
which belongs in a hermetic suite. The unit tests cover the rules with
synthetic definitions; this script answers "how accurate is it" with evidence.

Its headline is the **self-agreement** check, which works because of an
asymmetry. We never see the opponent's decklist, so there is no ground truth to
score their label against — but we know our *own* list exactly. So it
classifies our deck from all sixty cards, then again from only the cards we
happened to reveal in each match, and compares. That is the same
partial-information problem the opponent's label faces, against an answer we
can check.

Run it before believing any number on a deck's Matchups page.
