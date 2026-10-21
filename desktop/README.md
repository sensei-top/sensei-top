# The desktop shell

An Electron main process that runs the tracker's own `serve` as a child and
shows the dashboard in a window, with a tray icon. It adds no feature of its
own: everything the window shows is the dashboard `serve` already serves.
The design (the handshake with `serve`, the process tree, the two settings
files, the shell's log, the frozen server and the support commands) is in
[docs/desktop.md](../docs/desktop.md); this file is how to build and run it.

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

Where the data directory is on each system: `docs/desktop.md`, "The desktop shell".
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
belongs to that origin, so the port is kept steady: `docs/desktop.md`, "The desktop shell".

### Restarts

How `serve` is stopped and restarted: `docs/desktop.md`, "The desktop shell".

### Closing the window

Windows hides the window and keeps tracking in the tray. Linux quits, unless
`keepRunningOnClose` is set in `shell.json`: GNOME draws no tray icon without
the AppIndicator extension, so a hidden window could be unreachable. The tray's
Quit always quits.

## The log

`<data dir>/logs/shell.log`, beside the server's `sensei-top.log`; its format,
rotation and session id are in `docs/desktop.md`, "The desktop shell".
`diagnostic: true` in `shell.json` adds the DEBUG lines and starts the server
with `--verbose`.

## Files

| File | What it does |
|---|---|
| `src/main.ts` | The main process, and the only main-process file that loads Electron: single instance, signals, quitting in order, wiring the rest together |
| `src/server.ts` | Finds `sensei-top`, picks the data directory and the port, runs `serve` and any other subcommand, restarts |
| `src/window.ts` | The window: isolation, bounds, the loading and error page, navigation, the close rule |
| `src/tray.ts` | The tray: the tracker's state from `GET /api/live` every 5 s, and the menu |
| `src/autostart.ts` | Start with the system: the login item on Windows and Linux, and the installer's `first-run.json` choice |
| `src/log.ts` | `shell.log` |
| `src/store.ts` | `shell.json`, the shell's own preferences, in Electron's `userData` |
| `src/preload.ts` | The preload script: `window.senseiTopShell`, the bridge the dashboard reads, over `ipcRenderer`. It runs in the renderer and imports `electron` itself |
| `src/settings.ts` | The Settings bridge, shell side: what the dashboard's Settings page reads and writes, mapped to `config --json` and `config --set-…` and to `shell.json` |
| `src/updater.ts` | Updates: a check 30 s after launch and every 24 h while the switch is on, and "Restart to update" |
| `src/i18n.ts` | The shell's own catalogue, `src/locales/<language>.json`: the tray, the app menu, the loading page and every sentence a dialog or the page shows, in `shell.json`'s language |
| `scripts/notices.ts` | The third-party notices for the shell's npm packages, written to `dist/notices/` before packaging; fails when a package names no licence |
| `build/appx-extensions.xml` | The Store package's startup task (Windows' Startup list, off), spliced into the appx manifest by electron-builder |
| `server/` | The PyInstaller build of the server (`uv run python scripts/build_server.py`) |

Everything but `main.ts` and `preload.ts` takes Electron's classes as
arguments, so the tests run under plain Node. `preload.ts` has no test.

## The Store build

`win.target` is `[nsis, appx]`, so `pnpm dist:win` also writes
`release/Sensei-Top-<version>.appx`. Its `appx:` block in
`electron-builder.yml` carries the identity reserved in Partner Center
(`identityName` and `publisher`, which the Store checks against the
reservation; neither is a secret) and the two languages. The package declares
one startup task, off, from `build/appx-extensions.xml`. The release job
attaches the appx, and it is submitted to Partner Center by hand from the
release's assets; the Store signs it, so nothing here holds a certificate.

## Checks

    pnpm --dir desktop test        # vitest, over src/ and scripts/
    pnpm --dir desktop typecheck   # tsc over src/ and scripts/ with the tests, no output
    pnpm --dir desktop build       # tsc, to dist/, tests left out
    pnpm --dir desktop exec electron-builder --win nsis --publish never   # the Windows installer, compiled here with wine: proves installer.nsh

The installer line needs wine and the frozen server (`server/dist/`); it runs
makensis, so an error in `build/installer.nsh` shows here before the Windows VM
is asked. The Linux server is inside the output, so the .exe is for compiling,
not running.
