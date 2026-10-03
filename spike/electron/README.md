# Electron shell spike (release plan 6, phase 0)

Throwaway. It lives on `feature/electron-spike` and is never merged; what it
proves goes into `~/.claude/plans/release-6-desktop-app.md`, phase 0, and
into plan 7's Linux attempt.

## What it is

One Electron 44.5.1 main process (`main.js`, no build step) with:

- a **main window** on the tracker's own URL (`http://127.0.0.1:8765/`);
- an **overlay window**: frameless, transparent, always on top at the
  `screen-saver` level, click-through with `forward: true`, not focusable
  while click-through. It loads `/design/surfaces` with the page's own
  background removed, so the surfaces float and the gaps show what is
  behind. A pink dashed outline marks the window's edge;
- a **tray** icon (a pink square) with the menu below;
- **hotkeys**: `Ctrl+Alt+O` toggles click-through (interactive mode),
  `Ctrl+Alt+H` hides and shows the overlay;
- **single instance**: a second launch focuses the first;
- **diagnostics**: one log file (UTC, a session id per launch, home
  directory written as `~`) with versions, displays, GPU, every window
  event, every page load and console line, renderer and child-process
  exits, memory by process type every 30 s, and, on Linux, Arena's X
  window: its class, `_NET_WM_STATE` (fullscreen or not), whether it is
  focused and whether the overlay is above it in `_NET_CLIENT_LIST_STACKING`.

The log is `~/.config/sensei-top-shell-spike/logs/shell-spike.log`
(Electron's `logs` path; the start line prints it).

## Running it

    ./run-server.sh      # dashboard on :8765 from a snapshot of the real DB
    pnpm start           # forced to XWayland (--ozone-platform=x11)
    pnpm start:wayland   # the native-Wayland comparison

`pnpm start` clears `ELECTRON_RUN_AS_NODE`: VS Code's terminal sets it,
and with it Electron runs as plain Node.

## Flags

- `--overlay-focusable=1`: see finding F1. Default `0`.
- `--main=0`: keep the dashboard window hidden, so launching takes no focus from Arena.
- `--overlay-level=<level>`: the `setAlwaysOnTop` level, `none` to skip it. Default `screen-saver`.
- `--overlay-opts=<json>`: merged into the overlay's `BrowserWindow` options last.
- `--overlay-route=/path`, `--url=http://127.0.0.1:<port>`, `--auto-quit=<seconds>`.

## Findings (2026-09-30, Linux)

- **F1. `focusable: false` makes the overlay override-redirect under X11.**
  Chromium then never hands the window to Mutter: no `_NET_WM_STATE`, no
  `ABOVE`, absent from `_NET_CLIENT_LIST_STACKING`. With `focusable: true`
  (and `skipTaskbar: true`) it is managed, keeps its 32-bit visual, and
  carries `_NET_WM_STATE_ABOVE`. Read with `xprop` and `XGetWindowAttributes`.
  Both stay above Arena; see "Results over Arena" for which to keep.
- **F2. Transparency works** on the NVIDIA driver under XWayland with no
  flags: 32-bit visual, and the author's screenshot shows the desktop through
  the page with the surfaces opaque. The page's scrollbar was drawn opaque;
  the overlay CSS now hides it.
- **F3. X11 window handles are 4 bytes** (`getNativeWindowHandle()`), not 8.
- **F4. GNOME shows no tray icon** without the AppIndicator extension; none
  is enabled on the author's desktop. `new Tray()` succeeds silently.
- **F5. Cold start** to the main window's `ready-to-show`: 404–408 ms
  (warm disk cache). **Memory** with both windows: 871 MB working set in
  total (browser 200, GPU 271, utility 90, two renderers 309); working set
  counts shared pages in every process, so this overstates.
- **F6.** `ELECTRON_RUN_AS_NODE=1` leaks from VS Code's terminal and turns
  Electron into Node; a shell launched from an editor must clear it.
- **F7.** Single instance works: a second launch focuses the first.
- **F8.** Both renderers print Electron's "Insecure Content-Security-Policy"
  warning: the dashboard sends no CSP. Worth a header in plan 6.
- **F9. Arena under Proton reports `_NET_WM_STATE_FULLSCREEN` when windowed
  at the monitor's own size** (3840×2160): Mutter's legacy-fullscreen rule,
  since Wine draws its title bar inside the client area. The state is not
  a reliable "is Arena fullscreen" signal; the window's size against the
  monitor's is. At 2560×1440 windowed the state carries no FULLSCREEN.
- **F10. SIGTERM leaves no `quitting` line**: Electron's `will-quit` does not
  run on a signal, so the log cannot tell a kill from a crash. Plan 6's
  diagnostics should log `SIGTERM`/`SIGINT` before exiting.
- **F11. Interactive mode selected page text** on drag. The overlay CSS now
  sets `user-select: none`.
- **F12. A hidden overlay leaves the stacking list**, so `overlayIndex: -1`
  right after `Ctrl+Alt+H` is expected, not a stacking failure.

## Results over Arena (2026-09-30, a bot match, primary 4K monitor)

Arena: `steam_app_2141910`, Proton, on the primary (right) monitor. Both
variants launched with `--main=0`.

| # | A: `--overlay-focusable=0` (override-redirect) | B: `--overlay-focusable=1` (managed, `ABOVE`) |
|---|---|---|
| L1 | pass | pass |
| L4 windowed 3840×2160 (reads FULLSCREEN, F9) | pass, eyes | pass, log only |
| L4 windowed 2560×1440, window dragged under the overlay | not run | pass, eyes and log |
| L5 fullscreen | pass, eyes (log cannot see it: absent from the list) | pass, log (`overlayAboveArena: true` with Arena focused) |
| L6 clicks pass through | pass | pass |
| L7 hotkeys while Arena focused | pass, log | pass, log |
| L8 interactive mode | scrolls; **never takes keyboard focus** | scrolls; **takes focus**, gives it back to Arena on `Ctrl+Alt+O` |
| L9 memory beside Arena | 798–837 MB | 797–819 MB |
| L10 cold start (`ready-to-show`) | — | 356 ms |

**Recommendation: B**, managed with `_NET_WM_STATE_ABOVE`. It passed at
every size tried, the window manager knows it exists (workspaces, and the
log can verify its stacking), and interactive mode can take typing, which
any search or note field in the overlay will need. It is also the shape the
Windows overlay will have (a focusable topmost window). A stays the
fallback if some compositor puts a managed window below fullscreen Arena.

**Open: the overlay does not follow Arena's window.** It is placed in the
primary monitor's top-right corner, so with Arena windowed at 2560×1440 it
hangs over the Steam client beside Arena, not inside it (the author's
screenshot). Following needs Arena's geometry, which XWayland exposes
(Arena is an X client: `XGetWindowAttributes` read 2566×1472 at
4476,344 physical), polled or watched with `ConfigureNotify`, then
`setBounds` in DIPs. Under native Wayland there is no way to read another
client's position. On Windows, `GetWindowRect` on `MTGA.exe`'s window.

Not tested: L2 (no AppIndicator extension, F4), L11.

## Linux checklist (the author's desktop: GNOME, Wayland, NVIDIA)

Never during a match that counts. A casual queue or the bot match is
enough.

| # | Check | How it is read |
|---|---|---|
| L1 | Both windows render; the overlay is transparent between surfaces | eyes; log `page loaded` for both |
| L2 | Tray icon appears and its menu works on GNOME | eyes (GNOME shows tray icons only with the AppIndicator extension) |
| L3 | A second `pnpm start` focuses the first | log `second launch` |
| L4 | Overlay stays above Arena, **windowed** | log `overlayAboveArena: true` with Arena's state lacking `_NET_WM_STATE_FULLSCREEN`; eyes |
| L5 | Overlay stays above Arena, **fullscreen** | the same with `_NET_WM_STATE_FULLSCREEN`; eyes |
| L6 | Clicks pass through the overlay to Arena | eyes: click a card under a surface |
| L7 | `Ctrl+Alt+O` and `Ctrl+Alt+H` fire while Arena has focus | log `hotkey fired` with `arenaActive: true` just before |
| L8 | Interactive mode: the overlay takes the mouse and scrolls, then hands it back | eyes; log `click-through set` |
| L9 | Memory with both windows open, beside Arena | log `memory MB by process type` |
| L10 | Cold start to the main window's first paint | log `ready-to-show` `msSinceProcessStart` |
| L11 | The same under `pnpm start:wayland` (expected to fail L4/L5: Wayland gives no stacking control) | as above |

## Windows checklist (the author's Win11 VM, next)

First: does Arena run in the VM at all without GPU passthrough. Then the
Linux list, plus following `MTGA.exe`'s window (a Win32 helper this spike
does not have yet), DPI and a second monitor, the installer without admin,
and an update from N to N+1.
