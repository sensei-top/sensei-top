# Desktop shell

The design of the Electron shell in `desktop/`: its handshake with `serve`, the process tree, the frozen server and the support commands; cut from [architecture.md](architecture.md). The build and run steps are in `desktop/README.md`.

## The desktop shell

The desktop app (`desktop/`, an Electron shell) is a parent process that
runs the same `serve` a developer runs, so what it needs from `serve` is a
small handshake and nothing else.

**Start.** `serve --port 0` lets the OS choose the port. Whatever the port,
`cmd_serve` binds the socket itself (host already checked by
`_require_loopback`) and hands it to uvicorn, so the port it reports is the
one it listens on, and a connection made the moment the line prints is
never refused. With `--ready-line`, `serve` prints exactly one line,
`{"listening": <port>}`, to stdout once uvicorn's `started` flag is set.
Nothing else on stdout is a contract: the prose lines around it may change.

**Lifeline.** `--exit-on-stdin-close` starts a daemon thread that waits for
stdin to reach end of file. The shell holds `serve`'s stdin open, a pipe it never writes to; when the
shell dies by any means the pipe closes, and at end of file the thread sets
uvicorn's `should_exit`, which runs the lifespan's shutdown and stops the
watcher the way Ctrl+C does. On Linux and macOS the thread blocks in a read.
On Windows it must not: Windows serializes synchronous I/O on a handle, and
while a read was pending on the stdin pipe, the watcher child that
`serve --watch` spawns, which shares that handle, stalled at startup before
running any Python. It ingested nothing while `/api/live` still reported it
alive (measured on Windows 10, 2026-10-07). There the thread polls the pipe
with `PeekNamedPipe` every quarter second instead, and falls back to the
blocking read only when stdin is not a pipe. `procs.py` keeps covering
`serve`'s own children.

**The process tree.** The shell (the Electron main process) starts one
`serve --watch --port <n> --ready-line --exit-on-stdin-close` child per
start, with `--db <data dir>/sensei-top.db`, the data directory as its
working directory and a launch id in `SENSEI_TOP_SESSION`. `serve` starts
the watcher as a child process of its own and the refresh and backup jobs as
threads in itself (`procs.py`, trap 6). Every other subcommand the shell
needs (`config`, `doctor`, `diagnostics`, `cards --scryfall`, `restore`) is a short-lived
child of the shell against the same `--db`; a key is written to its stdin
and nothing else is. What kills what: on a stop the shell
closes `serve`'s stdin, which is the lifeline above; if `serve` is still
running 10 seconds later the shell sends SIGTERM, and 5 seconds after that
SIGKILL. When `serve` ends, the lifespan stops the watcher; when `serve`
is killed outright, the kernel mechanisms in `procs.py` do (the parent-death
signal on Linux, a Job Object on Windows). The shell supervises both. An
unexpected exit of `serve`, or a start that prints no ready line in 60
seconds, restarts it, at most 3 times in any 5 minutes, after which the state
is `failed` until the person retries; a restart the person asked for does not
count. A watcher that dies on its own while `serve` lives shows on the tray's
5-second `/api/live` poll as `watcher_stopped`; the shell then restarts
`serve` once per server generation, spending from the same budget, so a crash
loop of either kind is capped together. Past the budget the server keeps
running without a watcher (the dashboard is still useful), the shell logs one
ERROR and tries nothing more until the server restarts, and the tray shows
"Watcher stopped". The port is the one remembered in `shell.json` when it is free
(waiting up to 3 seconds for our own previous server to let go of it),
otherwise one the OS chooses and the shell then remembers; it is never 8000,
the developer's `serve`.

**The port, in detail.** A free remembered port is asked for again as
`serve --port <port>`; otherwise `serve --port 0` lets the OS choose, and the
port the ready line reports is remembered. A remembered port that `serve`
cannot bind after all (another program took it between the probe and the
bind) is retried once with `--port 0`. A remembered 8000 is ignored, and an
OS-chosen 8000 is given back and asked for again.

**Restarts, in detail.** A restart comes 1 second after the exit, and the
limit is a sliding window: a server that ran for a while earns its restarts
back. A server that printed no ready line is stopped, and the next one starts
only once it has exited, so two never share the database. Past the limit the
window names the log file, which says why, the tray says "Tracker could not
start", and launching the app again tries once more with a fresh budget.

**Where the files are.** The data directory (the database, `logs/`,
backups) is `%LOCALAPPDATA%\Sensei Top` on Windows and
`$XDG_DATA_HOME/sensei-top`, by default `~/.local/share/sensei-top`,
elsewhere; a development run (not packaged) may move it with
`SENSEI_TOP_DATA_DIR`, and a packaged build ignores the variable. The
config file the Python CLI writes is `config.toml` under
`%APPDATA%\sensei-top` on Windows and `~/.config/sensei-top` elsewhere
(`XDG_CONFIG_HOME` moves it); `INSTALL.md`, "Where your data lives", is the
table a person reads. `shell.json` is in Electron's own `userData`
directory, not in either.

**`shell.json` versus `config.toml`.** The Python CLI alone writes
`config.toml`: the Arena log path, the date order, the MTGO handle, game-log
folder and deck folder, the backup directory and count, the model and, when
no system keyring exists, the keys. The shell reads it only by running
`config --json` (which never carries a key, only whether one is set) and
changes it only by running a `config --set-…` command; a key travels on that
command's stdin, never in its arguments. The shell alone writes
`shell.json`: the remembered port, the window's bounds, "keep running when
the window is closed", start with the system, the daily update check,
diagnostic mode, the language, which clients the user plays (`plays`,
`arena` and/or `mtgo`; missing means both, so an install from before it
behaves as before) and whether onboarding is finished. The server never
reads it. It is read once at launch and written whole through a temporary
file and a rename, a key it does not know is carried through every write,
and a file that is not JSON is moved aside as `shell.json.bad`.

**Which saves restart the server.** The server reads the Arena log path, the
date order, the MTGO handle, game-log folder and deck folder, and the backup
directory and count only at its start, so saving any of them restarts it and
the page reconnects. So does turning diagnostic mode on or off, which adds
`--verbose` to `serve` and a DEBUG level to the shell log, and a restore
(the server is stopped while `restore` runs, and stays stopped when the
restore stops partway with files under `.replaced` names). The model, the
keys and every other `shell.json` preference do not restart it.

**The shell log.** `logs/shell.log` in the data directory, beside the
server's `sensei-top.log`, in the same line format (`src/sensei_top/logs.py`) so the two merge by time:
a UTC timestamp with milliseconds, the launch's 8-hex session id (the same
id the server's lines carry), the level, the logger name and the message,
then one JSON object when there is detail. The home directory is written as
`~`. It rotates at 2 MB and keeps 5 files. It holds the shell's own lines
(start, window, tray, updates, settings) and everything `serve` prints or
writes to stderr, prefixed `serve:` and `serve stderr:`. Of a subcommand it
records the name, the exit status and the duration, never its arguments or
its stdin, since an argument can carry a credential. Diagnostic mode adds
DEBUG lines.

**Updates and onboarding.** The packaged app checks for a newer version 30
seconds after it starts and then every 24 hours, unless "Check for updates"
is off, in which case it makes no request at all; it reads `latest.yml` on
the project's latest GitHub release, which the release job publishes with
the installer (`docs/testing.md`, "CI"). Where the updater cannot
run (the Microsoft Store build, a development run, an unsupported platform)
the status says so. "Restart to update" stops the server before the installer
starts. Until `onboarded` is true in `shell.json` the window opens at
`/welcome`; its steps read `doctor --json`, "Which do you play?"
writes `plays`, and finishing them writes the flag.

**Card data starts on its own** (`settings.ts`'s
`startFirstDataIfMissing`). Once per launch, after the server first
reports `ready`, so `serve` has migrated the database before `cards`
opens it, the shell runs `cards --scryfall --progress` when doctor
counts zero cards with rules text and no download is running or
finished. `null` is unknown, not zero: the launch's first doctor run
starts before `serve` creates the database, so a `null` count is read
again after `ready` before deciding, and a count still unknown starts
nothing. There is no retry within a launch; Ready and Settings' Card
data card show a failure with Try again. The download prints JSON
lines for its bytes and its save stage, parsed into
`FirstData.progress`. **A restore stops a running download** rather
than being refused, since it replaces the database the download fills,
and no download starts while a restore runs (a Download pressed then
is refused). After a restore that succeeded, a `done` or `failed`
state goes back to `idle`, since it described the replaced database,
and the check runs again against the restored one.

Pinned by `tests/test_cli.py`, "serve's handshake with a parent process",
and, for the shell's side, `desktop/src/server.test.ts` (port choice,
restart budget, stop order), `store.test.ts`, `log.test.ts`,
`settings.test.ts` (which saves restart, when card data starts on its
own, a restore stopping a download) and `updater.test.ts`.

### The frozen server

`uv run python scripts/build_server.py` builds the dashboard if `web_dist/`
is older than its sources, freezes the server with PyInstaller
(`desktop/server/sensei-top.spec`, `--onedir`, into the gitignored
`desktop/server/dist/sensei-top/`), then smoke-tests the result:
`--version` equals the pyproject version, `doctor --json` parses, the
frozen executable ingests and projects a fixture, and `serve --port 0
--ready-line --exit-on-stdin-close` answers `/api/health`, reports the
version and serves the dashboard, then exits when its stdin closes.
`--smoke-only` skips both builds and tests an existing dist (`--dist` moves
it). It is not part of `pytest -q`: it takes minutes with a cold web build.
The smoke test runs on Linux and Windows; it writes only inside a
temporary directory, reads a fixture, runs its children with a failing
keyring backend, a temporary config home and no API keys, and starts `serve`
with every refresh job off. On Windows alone, one `doctor --json` run names
`WinVaultKeyring` to prove that backend imports (it reads no credential). On
Linux it checks that no frozen process outlives `serve`.

Each spec line is there for a reason:

- **A console executable, no UPX.** The shell reads stdout, which a windowed
  executable does not have; UPX-packed binaries are what antivirus
  products flag.
- **`copy_metadata("sensei-top")`.** `api/app.py` and `logs.py` read the
  version through `importlib.metadata` (`api/app.py` raises without
  `sensei_top-*.dist-info`; `logs.py` falls back to "unknown"). The spec drops
  `direct_url.json` from the copied metadata: an editable install's names the
  builder's directory. `copy_metadata("keyring")` is needed because keyring
  finds its backends through entry points.
- **`collect_data_files("sensei_top")`.** `migrations/` and `web_dist/` are
  read through `importlib.resources`, so they must sit in the bundle.
- **Hidden imports for `uvicorn` and `keyring.backends`.** uvicorn imports
  its loop, protocol and lifespan modules from strings, and keyring imports
  a backend by name; the analysis sees neither.
- **`multiprocessing.freeze_support()` first in `cli.main`.** The only child
  `serve` starts is `--watch`'s watcher, forked on Linux and spawned on
  Windows. In a frozen build a spawned child is the same executable, and
  without the call it would run the CLI again instead of its target. The
  smoke test starts `serve --watch` and checks that the watcher child
  ingested the fixture (`/api/live` reports events).
- **A generated entry script** (`desktop/server/build/entry.py`), since the
  `sensei-top` console script is made by the installer, which PyInstaller
  does not run.

`sensei-top --version` exists for this smoke test and for the shell.

### Support commands

Two read-only commands answer "what can the app find" and "what do I attach
to a bug report"; the desktop shell drives both.

- **`sensei-top doctor [--json] [--file PATH]`** (`doctor.py`). Reports the
  Arena log's path and source (`flag`, `environment`, `config`, `autodetect`
  or `none`); under `autodetect`, `arena_log.found` lists every
  `Player.log` discovery found, the one in use first, and the text form
  adds an "Also found" line for each other one, so a support report shows
  a second prefix without a back-and-forth (`docs/architecture.md`,
  "Finding the clients' files"); Detailed Logs, the MTGO directories and
  whether a handle is set, the card counts, the schema version beside the
  code's, the config path and the keyring backend. It never creates, migrates or writes the
  database: that is opened through a `?mode=ro` URI (`connect()` sets
  `journal_mode=WAL`, which writes; a read-only open can still leave an empty
  `-wal` and a 32 KB `-shm` beside a WAL database nothing else has open,
  never touching the main file), and a missing file or table reads as
  `null`, not zero. Detailed Logs is `enabled` when the log's
  first 200 lines carry `DETAILED LOGS: ENABLED`, `disabled` only on a
  `DISABLED` line (never seen in a capture, so untested), `unknown`
  otherwise. The `--json` keys are a contract the shell reads.
- **`sensei-top diagnostics --out FILE.zip [--shell-log PATH]
  [--with-player-log] [--list]`** (`diagnostics.py`). The zip holds
  `doctor.json`, `config.toml` with every `api_key` and `[mtgo] handle` removed (rebuilt
  from the parsed tables, never by text substitution), `row_counts.json`, the app's
  log files and, on request, the shell's log and `Player.log`. Paths inside
  it are written with `~` for the home directory, as `logs.py` writes them.
  No log line names a player: the MTGO projector's warnings carry counts,
  game numbers and card names instead (`ParsedMatch.warnings`), and the ones
  0.7.0 and earlier wrote with a handle in them are masked as the logs are
  copied in (`_LEGACY_MTGO`), since a log keeps them until it rotates.
  The database never goes in. `--list` prints each entry and its size and
  writes nothing; an existing `--out` file is refused.

Pinned by `tests/test_doctor.py`.
