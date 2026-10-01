# Sensei Top

Fully local Magic: The Gathering match analytics for Arena and MTGO. Reads
the logs both clients already write — Arena's `Player.log`, MTGO's
`Match_GameLog_*.dat` files — stores raw events in SQLite, projects them into
matches, games and turn-by-turn board state, and serves a dashboard on
loopback. No account, no upload, no network egress of game data, read-only
with respect to both clients.

The dashboard has seven places and Settings, each at an address of its own,
so a page can be bookmarked, linked to and reloaded as it is:

- **Home** — the last session, three things worth a look, the recent matches
  beside the win rate by week, your decks and the field.
- **Live** (Arena only) — the match in progress: a replay of what's been
  revealed, a keep guide, a read of the opponent's likely hand, your remaining
  library and a between-games sideboard plan.
- **Matches** — every match, filtered by client or deck, each with a report
  and a turn-by-turn replay of its games.
- **Decks** — a page for each of your decks: its record over every version
  or one, its record against each opponent archetype with the matchup brief
  once one is written, and a guide that sets your list and results against
  the field.
- **Field** — the metagame from real MTGO and paper tournament results
  (never Arena).
- **Coach** — a dated report across every deck, each one kept and measured
  against the one before it.
- **Settings** — whether a Claude key is set and which model writes with it,
  the density of the display, and the credits.

Turn numbers are **player-turns**, matching Arena's own counter: a game where
each player took 12 turns counts as 24.

## Requirements

- Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/)
- Node with [pnpm](https://pnpm.io/) (dashboard only)
- In Arena: **Detailed Logs (Plugin Support)** enabled (Options → Account).
  Without it the log contains nothing to read.

## Setup

    uv sync
    cd web && pnpm install && cd ..

The log path is autodetected for Steam/Proton installs. Anywhere else, point
`MTGA_LOG` at the file (quote it — the path contains spaces):

    export MTGA_LOG="/path/to/SteamLibrary/steamapps/compatdata/2141910/pfx/drive_c/users/steamuser/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"

## Run

    cd web && pnpm start

Builds the dashboard and starts live mode: the log is followed while you play,
matches appear as they finish, and the page refreshes itself. Always at
**http://127.0.0.1:8000** — both ports are fixed (API 8000, dev server 5173),
so the URL is bookmarkable.

The same thing without the build step, from the repo root:

    uv run sensei-top serve --watch

`--interval` sets how often the log is read (default 1 s), `--project-every`
how often derived tables are rebuilt (default 5 s).

`serve` binds loopback only and refuses any other `--host`. It also refuses
requests made on behalf of another website, so a page open in your browser
can't read your match data or act on it, such as starting a paid Claude call.

## Other commands

    uv run sensei-top ingest                # read Player-prev.log then Player.log once
    uv run sensei-top project               # rebuild matches/games/turns from raw events
    uv run sensei-top report                # the three metrics, in the terminal
    uv run sensei-top serve                 # dashboard without watching (read-only)
    uv run sensei-top ingest --watch --project   # headless live mode, no server
    uv run sensei-top cards                 # card names, from the installed Arena client
    uv run sensei-top archetypes            # deck definitions, for naming opponents' decks
    uv run sensei-top meta                  # real MTGO/paper tournament results, for the Field page
    uv run sensei-top meta --reclassify     # re-run the classifier over what's stored, no network
    uv run sensei-top backup                # verified daily snapshot of the whole database
    uv run sensei-top ingest-mtgo           # read MTGO game logs by hand
    uv run sensei-top mtgo-status           # why aren't my MTGO matches showing up?
    uv run sensei-top guide                 # deck guides in the terminal (list, prompt, import)
    uv run sensei-top brief                 # matchup briefs (list, prompt, import)
    uv run sensei-top config                # optional Claude key, TopDeck.gg key, MTGO handle and log directory, backups

### Card names and opponent decks

The log names cards only by number, so run `cards` once to get names — it reads
the card database your Arena install already ships, and falls back to
downloading Scryfall's if Arena is not installed here.

Arena never tells you what deck your opponent is playing, so the tracker works
it out from the cards they reveal — typically eight to fifteen a match, which
is usually enough. `archetypes` downloads the deck definitions that makes
possible, and `serve` refreshes them in the background when they are over a day
old. Both commands only ever download; nothing about your games is uploaded,
and both work from cache when you are offline. When the guess is uncertain the
dashboard says so and lets you name the deck yourself.

The database lives at `data/sensei-top.db` (override with `--db`, before the
subcommand). Raw events are kept verbatim and deduplicated, so re-reading a
log is a no-op (`ingest --from-start` proves it) and `project` is always a
full rebuild — a parser fix applies retroactively to every match ever
recorded. Arena wipes `Player.log` on every launch; running `ingest` (or live
mode) regularly is what preserves history, since the previous session survives
only in `Player-prev.log` and only until the next launch — `backup` (below)
is what protects it from anything happening to the database file itself.

The API is documented at `/docs` while the server runs. Every connection opens
with `PRAGMA query_only=ON`, except the few routes that store something only
you can author: naming an opponent's deck yourself, and saving a written deck
guide, matchup brief, match or leak narrative, or coach report.

### MTGO

MTGO's game logs are read once when `serve --watch` (or `ingest --watch`)
starts, and never followed live — a match you play afterwards comes in with
`ingest-mtgo`, or at the next restart. Two things aren't autodetected, so
tell it both once:

    uv run sensei-top config --set-mtgo-handle YOURHANDLE
    uv run sensei-top config --set-mtgo-dir DIR

MTGO's log never says which player is you, hence the handle. `DIR` above is
the directory holding MTGO's `Match_GameLog_*.dat` files. It resolves in
this order — first match wins: an explicit `--dir`/`--mtgo-dir` on the
command that needs it, then a `MTGO_LOG_DIR` environment variable, then the
`config --set-mtgo-dir` value above. With none of the three set, MTGO logs
are never read at all.

MTGO matches show up on Home, in Matches and in the coach. They never appear
on Live, which needs Arena's board-state stream, and they aren't under Decks
yet, since MTGO's log doesn't name the deck you played. `mtgo-status`
diagnoses a missing match.

### Written guides, briefs and reports

The deck guide, matchup briefs, match reports and coach each come with a
prompt: copy it into an assistant you already use and import the answer, or
set an Anthropic API key with `config --set-key` and press the dashboard's
generate button instead. Nothing calls out without that key and that button
press. See [docs/llm.md](docs/llm.md).

### Backups

`serve` takes one verified `VACUUM INTO` snapshot of the database a day on a
background thread — pass `--no-backup` to skip it — and `sensei-top backup`
takes or checks on one by hand. By default the copy lands in a `backups`
folder beside the database, keeping just the current slot; both are
configurable, and either persists across restarts:

    uv run sensei-top config --set-backup-dir /path/to/somewhere
    uv run sensei-top config --set-backup-keep 3

**To restore one, stop the watcher first** (Ctrl-C any `serve --watch` /
`ingest --watch`) — see `docs/architecture.md`'s "Backups" section for the
full step-by-step, including the one trap (a stale `-wal` file left beside a
restored database) that a plain `cp` back into place does not warn you about.

## Development

    uv run pytest
    uv run ruff check .

    cd web
    pnpm dev            # Vite on :5173, proxies /api to :8000 (run `serve` too)
    pnpm build          # typecheck + production build into web/dist
    pnpm lint
    pnpm test           # vitest, the pure functions under src/lib
    pnpm gen:types      # regenerate src/types/api.ts after changing the API

Frontend types are generated from the API's OpenAPI schema and committed, so
the build fails on a renamed field instead of rendering `undefined`. Tests run
against an anonymized real Bo3 session fixture in `tests/fixtures/`.

Before changing anything, read [AGENTS.md](AGENTS.md) — the rules of the
codebase — and [`docs/`](docs/) for the detail behind them, including
[what Arena's log actually does](docs/arena-log.md).

## Licence

Copyright (C) 2026 The Sensei Top maintainer. All rights reserved.

Sensei Top is proprietary software. Official builds are free to install and
use; the source is not licensed for copying, modification or
redistribution. It comes with no warranty. The full notice is in
[LICENSE](LICENSE).

The name and logo are covered by [TRADEMARK.md](TRADEMARK.md). To report a
vulnerability, read [SECURITY.md](SECURITY.md).

## Credits

Sensei Top is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.

Card data and images come from [Scryfall](https://scryfall.com), tournament
results from [MTG_decklistcache](https://github.com/fbettega/MTG_decklistcache) and
[TopDeck.gg](https://topdeck.gg), and archetype definitions from
[MTGOFormatData](https://github.com/Badaro/MTGOFormatData). None of them
produces or endorses Sensei Top. What is taken from each, and on what terms, is
in [docs/attribution.md](docs/attribution.md).
