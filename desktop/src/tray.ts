// The tray (release plan 6, S8; D14): the tracker's state at a glance and the
// app's menu. The main process reads `GET /api/live` every 5 s while the
// server is up; no process polling. The states, the first that holds:
//
//   failed    the server could not be (re)started (S8's restart budget)
//   starting  the server is starting or restarting, or is ready and its
//             first `/api/live` request has not come back yet
//   down      the server is up but `/api/live` did not answer
//   stopped   `watcher_stopped`: the watcher child exited on its own
//   game      `last_event_at` within 60 s of now
//   watching  `watching`
//   idle      none of these
//
// The words are the dashboard's own (`web/src/shell/LiveStatus.tsx`), with
// one change: `watching` is "Watching", not "Watching Arena", because the
// field is true for any running watcher, and one that has found no Arena log
// yet still watches the MTGO folder. `failed` and `starting` are the shell's
// own: the dashboard is not there to show them. The state is a tooltip, the
// menu's first (disabled) line, and the colour of the status dot on the logo
// (`assets/tray/`); GNOME draws no tray icon at all without the AppIndicator
// extension (spike F4), so nothing here is the only way to reach anything.
//
// Menu: Open, Settings, Check for updates, Show logs, Export diagnostics,
// Quit. "Check for updates" (S14) is enabled when the updater runs here and
// its switch is on; it opens Settings and starts a check, so the result shows
// in the App section. Once an update is downloaded, "Restart to update"
// appears above Quit. "Export diagnostics" runs the same function as
// Settings' button.
//
// Only `import type` from electron here: the constructors arrive in
// `TrayDeps`, so vitest loads this file without Electron.

import type {
  Menu as ElectronMenu,
  MenuItemConstructorOptions,
  NativeImage,
  Tray as ElectronTray,
} from 'electron';
import type { Logger } from './log';
import type { ServerState } from './server';

export const POLL_MS = 5000;
export const GAME_WINDOW_MS = 60_000;

export type TrayState = 'failed' | 'starting' | 'down' | 'stopped' | 'game' | 'watching' | 'idle';

export const WORDS: Record<TrayState, string> = {
  failed: 'Tracker could not start',
  starting: 'Starting the tracker',
  down: 'Tracker not running',
  stopped: 'Watcher stopped',
  game: 'Match in progress',
  watching: 'Watching',
  idle: 'Not watching',
};

/** The icon files in `assets/tray/`: the logo with a status dot of this colour. */
export type IconName = 'live' | 'warn' | 'muted';

export const ICONS: Record<TrayState, IconName> = {
  failed: 'warn',
  starting: 'muted',
  down: 'warn',
  stopped: 'warn',
  game: 'live',
  watching: 'live',
  idle: 'muted',
};

/** The fields of `/api/live` the tray reads. */
export interface LiveSnapshot {
  watching?: boolean;
  watcher_stopped?: boolean;
  last_event_at?: string | null;
}

/** `logged_at` is naive local time (`2026-10-06T14:37:04`, maybe with a
 *  fraction): read as local time. A string with its own offset is read as
 *  written. `null` for anything else. */
export function parseEventTime(text: string | null | undefined): number | null {
  if (!text) return null;
  const naive = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?$/.exec(text);
  if (naive) {
    const [, y, mo, d, h, mi, s, frac] = naive;
    const ms = frac ? Math.floor(Number(`0.${frac}`) * 1000) : 0;
    const when = new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s), ms);
    return Number.isNaN(when.getTime()) ? null : when.getTime();
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(text)) {
    const when = Date.parse(text);
    return Number.isNaN(when) ? null : when;
  }
  return null;
}

/** D14's state from the server's state and the last `/api/live` answer
 *  (`null`: the request failed). */
export function trayState(server: ServerState['kind'], live: LiveSnapshot | null, now: number): TrayState {
  if (server === 'failed') return 'failed';
  if (server !== 'ready') return 'starting';
  if (live === null) return 'down';
  if (live.watcher_stopped) return 'stopped';
  const event = parseEventTime(live.last_event_at);
  if (event !== null && Math.abs(now - event) <= GAME_WINDOW_MS) return 'game';
  return live.watching ? 'watching' : 'idle';
}

export interface TrayActions {
  open: () => void;
  settings: () => void;
  checkForUpdates: () => void;
  restartToUpdate: () => void;
  showLogs: () => void;
  exportDiagnostics: () => void;
  quit: () => void;
}

/** What the menu shows of the updater. `canCheck`: the updater runs here and
 *  its switch is on. `ready`: an update is downloaded. */
export interface UpdateMenu {
  canCheck: boolean;
  ready: boolean;
}

export const NO_UPDATES: UpdateMenu = { canCheck: false, ready: false };

/** The menu for `state`. Settings needs the dashboard, so it waits for the server. */
export function menuTemplate(state: TrayState, actions: TrayActions, update: UpdateMenu = NO_UPDATES): MenuItemConstructorOptions[] {
  const serving = state !== 'failed' && state !== 'starting' && state !== 'down';
  return [
    { label: WORDS[state], enabled: false },
    { type: 'separator' },
    { label: 'Open', click: actions.open },
    { label: 'Settings', enabled: serving, click: actions.settings },
    { label: 'Check for updates', enabled: update.canCheck, click: actions.checkForUpdates },
    { label: 'Show logs', click: actions.showLogs },
    { label: 'Export diagnostics', click: actions.exportDiagnostics },
    { type: 'separator' },
    ...(update.ready ? [{ label: 'Restart to update', click: actions.restartToUpdate }] : []),
    { label: 'Quit', click: actions.quit },
  ];
}

export interface TrayDeps {
  Tray: typeof ElectronTray;
  Menu: typeof ElectronMenu;
  icon: (name: IconName) => NativeImage;
  fetch: typeof fetch;
}

export class StatusTray {
  private readonly tray: ElectronTray;
  private server: ServerState = { kind: 'stopped' };
  private live: LiveSnapshot | null = null;
  /** Whether a request for the current server has come back, answered or not. */
  private settled = false;
  private state: TrayState | null = null;
  private update: UpdateMenu = NO_UPDATES;
  private timer: NodeJS.Timeout | null = null;
  /** One per `setServer`: a request for an earlier server is discarded, and
   *  does not hold up the current server's. */
  private generation = 0;
  private inFlight: number | null = null;

  constructor(
    private readonly deps: TrayDeps,
    private readonly actions: TrayActions,
    private readonly log: Logger,
    private readonly platform: NodeJS.Platform,
  ) {
    this.tray = new deps.Tray(this.iconFor('starting'));
    if (platform === 'win32') this.tray.on('click', () => actions.open());
    this.render();
  }

  /** The server's state changed: render, and poll `/api/live` while it is ready. */
  setServer(state: ServerState): void {
    this.server = state;
    this.live = null;
    this.settled = false;
    const generation = ++this.generation;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (state.kind === 'ready') {
      const port = state.port;
      void this.poll(port, generation);
      this.timer = setInterval(() => void this.poll(port, generation), POLL_MS);
      this.timer.unref();
    }
    this.render();
  }

  /** The updater's part of the menu changed: the menu is built again. */
  setUpdate(update: UpdateMenu): void {
    if (update.canCheck === this.update.canCheck && update.ready === this.update.ready) return;
    this.update = { ...update };
    if (this.state !== null) this.buildMenu(this.state);
  }

  destroy(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.tray.destroy();
  }

  private async poll(port: number, generation: number): Promise<void> {
    if (this.inFlight === generation) return;
    this.inFlight = generation;
    let live: LiveSnapshot | null;
    try {
      const response = await this.deps.fetch(`http://127.0.0.1:${port}/api/live`, {
        signal: AbortSignal.timeout(POLL_MS - 1000),
      });
      live = response.ok ? ((await response.json()) as LiveSnapshot) : null;
    } catch {
      live = null;
    } finally {
      if (this.inFlight === generation) this.inFlight = null;
    }
    if (generation !== this.generation) return;
    this.live = live;
    this.settled = true;
    this.render();
  }

  private iconFor(state: TrayState): NativeImage {
    return this.deps.icon(ICONS[state]);
  }

  private render(): void {
    const server = this.server.kind === 'ready' && !this.settled ? 'starting' : this.server.kind;
    const state = trayState(server, this.live, Date.now());
    if (state === this.state) return;
    if (this.state !== null) this.log.info('tray state', { from: this.state, to: state });
    this.state = state;
    this.tray.setImage(this.iconFor(state));
    this.tray.setToolTip(`Sensei Top: ${WORDS[state]}`);
    this.buildMenu(state);
  }

  private buildMenu(state: TrayState): void {
    this.tray.setContextMenu(this.deps.Menu.buildFromTemplate(menuTemplate(state, this.actions, this.update)));
  }
}
