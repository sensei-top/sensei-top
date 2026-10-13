# The desktop shell

An Electron main process that runs the tracker's own `serve` as a child and
shows the dashboard in a window, with a tray icon. It adds no feature of its
own: everything the window shows is the dashboard `serve` already serves.

## Running it in development

    pnpm --dir desktop install
    pnpm --dir desktop dev

`dev` compiles `src/` to `dist/` and starts Electron with
`ELECTRON_RUN_AS_NODE` unset: an editor or terminal that exports it would
otherwise make Electron run as plain Node, where `require('electron')` is a
path string (the shell refuses to start and says so). `env -u` is POSIX, so
`dev` runs on Linux; on Windows unset the variable and run
`pnpm --dir desktop build && pnpm --dir desktop exec electron .`.

pnpm may skip Electron's `postinstall`, which is what downloads its binary.
If `electron .` reports that Electron failed to install correctly, fetch the
binary once:

    cd desktop && node node_modules/electron/install.js

In development the server is `uv run --project <repo> sensei-top`, the
repository's own code; a packaged build runs the frozen server under
`resources/server/` instead (`server/`, phase 12 puts it there).

On a Wayland session where the window misbehaves, pass Electron's own flag
through: `pnpm --dir desktop build && pnpm --dir desktop exec electron . --ozone-platform=x11`.

### Where the data goes

The shell keeps the database, its `logs/` and its working directory in one
data directory:

- Windows: `%LOCALAPPDATA%\Sensei Top`
- elsewhere: `$XDG_DATA_HOME/sensei-top`, which is `~/.local/share/sensei-top`
  when the variable is unset

Every child gets `--db <dir>/sensei-top.db` and runs in that directory.
**A development run starts against that real directory** unless you point it
elsewhere:

    SENSEI_TOP_DATA_DIR=/tmp/shell-dev pnpm --dir desktop dev

`SENSEI_TOP_DATA_DIR` moves the database, the server's log, the shell's log,
and Electron's own profile (`shell.json`, the page's local storage, the
single-instance lock, under `<dir>/userData`). A packaged build ignores the
variable. The server still reads the user's config file and keyring, which
the variable does not move: set `XDG_CONFIG_HOME` to a temporary directory as
well for a run that touches nothing of yours.

### The port

The window loads `http://127.0.0.1:<port>`, and the page's local storage
belongs to that origin, so the port is kept steady:

1. The port the last server reported is in `shell.json`. If it is free, it is
   asked for again (`serve --port <port>`). If it is taken, the shell waits up
   to 3 s for it, since its own previous server may still be shutting down.
2. Otherwise `serve --port 0` lets the OS choose, and the port the ready line
   (`{"listening": <port>}`) reports is remembered.
3. A remembered port that `serve` cannot bind after all (another program took
   it between the probe and the bind) is retried once with `--port 0`.
4. Never 8000, the developer's `serve`: a remembered 8000 is ignored, and an
   OS-chosen 8000 is given back and asked for again.

### Restarts

`serve` runs with `--exit-on-stdin-close`: its stdin is a pipe the shell
holds open and never writes to, so the server shuts down in order however the
shell ends. Quitting closes the pipe, waits 10 s, then sends SIGTERM, then
SIGKILL.

An unexpected exit, a start that fails, or a start that prints no ready line
within 60 s is restarted after 1 s, at most 3 times in any 5 minutes (a
sliding window: a server that ran for a while earns its restarts back). A
server that printed no ready line is stopped, and the next one starts only
once it has exited, so two never share the database. Past the limit the
window names the log file, which says why, the tray says "Tracker could not
start", and launching the app again tries once more with a fresh budget.
A restart the shell asks for itself (a setting changed) is never counted. A
restart because the watcher stopped on its own is, and past the limit the
server keeps running without a watcher, the tray says "Watcher stopped", and the
next restart of any kind tries again.

### Closing the window

Windows hides the window and keeps tracking in the tray. Linux quits, unless
`keepRunningOnClose` is set in `shell.json`: GNOME draws no tray icon without
the AppIndicator extension, so a hidden window could be unreachable. The tray's
Quit always quits.

## The log

`<data dir>/logs/shell.log`, beside the server's `sensei-top.log`, in the same
line format (`src/sensei_top/logs.py`), rotated the same way (5 × 2 MB), with
the home directory written as `~`. Each launch has an 8-hex session id, handed
to the server as `SENSEI_TOP_SESSION`. `diagnostic: true` in `shell.json` adds
the DEBUG lines and starts the server with `--verbose`.

## Files

| File | What it does |
|---|---|
| `src/main.ts` | The main process, and the only file that loads Electron: single instance, signals, quitting in order, wiring the rest together |
| `src/server.ts` | Finds `sensei-top`, picks the data directory and the port, runs `serve` and any other subcommand, restarts |
| `src/window.ts` | The window: isolation, bounds, the loading and error page, navigation, the close rule |
| `src/tray.ts` | The tray: the tracker's state from `GET /api/live` every 5 s, and the menu |
| `src/autostart.ts` | Start with the system: the login item on Windows and Linux, and the installer's `first-run.json` choice |
| `src/log.ts` | `shell.log` |
| `src/store.ts` | `shell.json`, the shell's own preferences, in Electron's `userData` |
| `src/i18n.ts` | The shell's own catalogue, `src/locales/<language>.json`: the tray, the app menu, the loading page and every sentence a dialog or the page shows, in `shell.json`'s language |
| `scripts/notices.ts` | The third-party notices for the shell's npm packages, written to `dist/notices/` before packaging; fails when a package names no licence |
| `server/` | The PyInstaller build of the server (`uv run python scripts/build_server.py`) |

Everything but `main.ts` takes Electron's classes as arguments, so the tests
run under plain Node.

## Checks

    pnpm --dir desktop test        # vitest, over src/ and scripts/
    pnpm --dir desktop typecheck   # tsc over src/ and scripts/ with the tests, no output
    pnpm --dir desktop build       # tsc, to dist/, tests left out
    pnpm --dir desktop exec electron-builder --win nsis --publish never   # the Windows installer, compiled here with wine: proves installer.nsh

The installer line needs wine and the frozen server (`server/dist/`); it runs
makensis, so an error in `build/installer.nsh` shows here before the Windows VM
is asked. The Linux server is inside the output, so the .exe is for compiling,
not running.
