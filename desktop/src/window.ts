// The main window (release plan 6, S8; D13, D20): one BrowserWindow, its
// bounds remembered in shell.json, a loading page while the server starts,
// then the dashboard at the server's own origin.
//
// - **Isolation.** `nodeIntegration: false`, `contextIsolation: true`,
//   `sandbox: true`. The preload script (phase 9) arrives as an option.
// - **Navigation.** The window shows only its own origin,
//   `http://127.0.0.1:<port>`, which `api/guard.py` accepts. Any other
//   http or https address, from a link or `window.open`, goes to the system
//   browser; anything else (mailto included) is refused and logged.
// - **The loading page** is a data URL whose own CSP forbids every request:
//   it makes no API call while there is no server to answer one.
// - **The application menu** (`appMenuTemplate`): Edit roles and the zoom
//   accelerators, never drawn. The bar stays hidden on Windows and Linux
//   (`setMenuBarVisibility(false)`, `autoHideMenuBar` false so Alt does not
//   reveal it); a hidden bar keeps its accelerators. Reload, Force Reload and
//   Toggle Developer Tools are there only when the app is not packaged.
//   Edit and View are keyed in `i18n.ts`; the role items keep Electron's
//   own labels.
// - **Language** (plan 18, D8). The loading page's sentences read through
//   `i18n.ts` when the page is built, and its `lang` is the current language.
// - **Closing** (D13). Windows: hide, tracking continues in the tray. Linux:
//   quit, unless "Keep running when the window is closed" is on. While the
//   app quits, the window simply closes.
//
// Only `import type` from electron here: the constructors arrive in
// `WindowDeps`, so vitest loads this file without Electron.

import type {
  BrowserWindow as ElectronBrowserWindow,
  BrowserWindowConstructorOptions,
  MenuItemConstructorOptions,
  Rectangle,
} from 'electron';
import { currentLanguage, t } from './i18n';
import type { Logger } from './log';
import type { Bounds, ShellStore } from './store';

export const DEFAULT_SIZE = { width: 1280, height: 820 };
export const MIN_SIZE = { width: 720, height: 480 };
/** How much of a remembered window must still be on a display to keep its place. */
const MIN_VISIBLE = 64;
const BACKGROUND = '#0b0c14';

export type CloseAction = 'hide' | 'quit' | 'close';

/** D13. `close` lets the window close (the app is quitting already). */
export function closeAction(platform: NodeJS.Platform, keepRunningOnClose: boolean, quitting: boolean): CloseAction {
  if (quitting) return 'close';
  if (platform === 'win32' || platform === 'darwin') return 'hide';
  return keepRunningOnClose ? 'hide' : 'quit';
}

/** The application menu: Edit, and View's zoom (Ctrl+0, Ctrl++, Ctrl+-). The
 *  bar is never shown; the menu exists for its accelerators. The developer
 *  items are for a development run only. */
export function appMenuTemplate(packaged: boolean): MenuItemConstructorOptions[] {
  return [
    {
      label: t('menu.edit'),
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' },
      ],
    },
    {
      label: t('menu.view'),
      submenu: [
        ...(packaged ? [] : ([{ role: 'reload' }, { role: 'forceReload' }, { role: 'toggleDevTools' }, { type: 'separator' }] as const)),
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
      ],
    },
  ];
}

export type NavigationKind = 'internal' | 'external' | 'blocked';

const EXTERNAL_SCHEMES = new Set(['http:', 'https:']);

/** Where `url` may go: in this window (`origin`'s own pages), to the system
 *  browser, or nowhere. With no server yet, `origin` is `null`. */
export function classifyNavigation(url: string, origin: string | null): NavigationKind {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return 'blocked';
  }
  if (origin !== null && parsed.origin === origin) return 'internal';
  return EXTERNAL_SCHEMES.has(parsed.protocol) ? 'external' : 'blocked';
}

export function originFor(port: number): string {
  return `http://127.0.0.1:${port}`;
}

/** D20: the onboarding page until shell.json has `onboarded`. */
export function startPath(onboarded: boolean | undefined): string {
  return onboarded ? '/' : '/welcome';
}

/** Where the window should go once the server is ready on `port`: nowhere
 *  if it already shows that origin (the page reconnects by itself, D12); the
 *  same page on the new origin if the port moved; else `startPath`. */
export function targetUrl(currentUrl: string, port: number, start: string): string | null {
  const origin = originFor(port);
  let current: URL | null = null;
  try {
    current = new URL(currentUrl);
  } catch {
    current = null;
  }
  if (current && current.origin === origin) return null;
  if (current && current.protocol === 'http:' && current.hostname === '127.0.0.1') {
    return origin + current.pathname + current.search + current.hash;
  }
  return origin + start;
}

function overlap(a: Rectangle, b: Rectangle): { width: number; height: number } {
  return {
    width: Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x),
    height: Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y),
  };
}

/** The remembered bounds, kept where at least a corner of the window is
 *  still on some display's work area, and no larger than the largest one;
 *  otherwise the size alone (Electron centres it). */
export function fitBounds(saved: Bounds | undefined, workAreas: readonly Rectangle[]): Partial<Rectangle> {
  if (!saved) return { ...DEFAULT_SIZE };
  const maxWidth = Math.max(0, ...workAreas.map((area) => area.width));
  const maxHeight = Math.max(0, ...workAreas.map((area) => area.height));
  const width = Math.max(MIN_SIZE.width, maxWidth > 0 ? Math.min(saved.width, maxWidth) : saved.width);
  const height = Math.max(MIN_SIZE.height, maxHeight > 0 ? Math.min(saved.height, maxHeight) : saved.height);
  if (saved.x === undefined || saved.y === undefined) return { width, height };
  const rect = { x: saved.x, y: saved.y, width, height };
  const visible = workAreas.some((area) => {
    const shared = overlap(rect, area);
    return shared.width >= MIN_VISIBLE && shared.height >= MIN_VISIBLE;
  });
  return visible ? rect : { width, height };
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export type LoadingState = { kind: 'starting' } | { kind: 'failed'; logPath: string; message?: string };

/** The loading or error page, as a data URL that can make no request. The
 *  error page names the log file; the reason is for the log. It shows a
 *  message only when the user must act on it (a restore that stopped partway). */
export function loadingPage(state: LoadingState): string {
  const body =
    state.kind === 'starting'
      ? `<p>${escapeHtml(t('page.starting'))}</p>`
      : (state.message
          ? `<p>${escapeHtml(state.message)}</p>`
          : `<p>${escapeHtml(t('page.failed'))}</p>` + `<p>${escapeHtml(t('page.tryAgain'))}</p>`) +
        `<p class="detail">${escapeHtml(t('page.logFile', { path: state.logPath }))}</p>`;
  const html =
    `<!doctype html><html lang="${currentLanguage()}"><head><meta charset="utf-8">` +
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">` +
    '<title>Sensei Top</title><style>' +
    `html{color-scheme:dark;background:${BACKGROUND};color:#f2f3f8;font:16px/1.5 system-ui,sans-serif}` +
    'body{margin:0;min-height:100vh;display:grid;place-items:center}' +
    'main{max-width:36rem;padding:2rem}h1{font-size:1.25rem;margin:0 0 .5rem}' +
    '.detail{color:#989db5;font-size:.875rem;overflow-wrap:anywhere}' +
    `</style></head><body><main><h1>Sensei Top</h1>${body}</main></body></html>`;
  return 'data:text/html;charset=utf-8,' + encodeURIComponent(html);
}

export interface WindowDeps {
  BrowserWindow: typeof ElectronBrowserWindow;
  openExternal: (url: string) => Promise<void>;
  workAreas: () => Rectangle[];
}

/** How the window begins: shown, kept out of sight, or minimized (D25). */
export type StartMode = 'show' | 'hidden' | 'minimized';

export interface MainWindowOptions {
  store: ShellStore;
  log: Logger;
  /** The page's own console lines go here. */
  pageLog: Logger;
  platform: NodeJS.Platform;
  /** D25: `hidden` stays in the tray, `minimized` shows in the taskbar. */
  start: StartMode;
  /** `performance.now()`-style ms since the process began, for F5's cold start. */
  sinceStart: () => number;
  /** Asked when closing means quitting (D13, Linux). */
  quit: () => void;
  /** Phase 9's preload script. */
  preload?: string;
}

const CONSOLE_LEVEL = { debug: 'debug', info: 'info', warning: 'warn', error: 'error' } as const;

export class MainWindow {
  readonly win: ElectronBrowserWindow;
  private origin: string | null = null;
  private quitting = false;
  private pendingMaximize = false;
  private saveTimer: NodeJS.Timeout | null = null;

  constructor(
    private readonly deps: WindowDeps,
    private readonly options: MainWindowOptions,
  ) {
    const saved = options.store.get().bounds;
    const browserOptions: BrowserWindowConstructorOptions = {
      ...fitBounds(saved, deps.workAreas()),
      minWidth: MIN_SIZE.width,
      minHeight: MIN_SIZE.height,
      show: false,
      title: 'Sensei Top',
      autoHideMenuBar: false,
      backgroundColor: BACKGROUND,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
        ...(options.preload ? { preload: options.preload } : {}),
      },
    };
    this.win = new deps.BrowserWindow(browserOptions);
    this.win.setMenuBarVisibility(false);
    // Hidden: the first open() maximizes, and a close before then keeps the saved flag.
    this.pendingMaximize = options.start === 'hidden' && Boolean(saved?.maximized);
    this.watch();
    this.win.once('ready-to-show', () => {
      options.log.info('ready-to-show', { msSinceProcessStart: Math.round(options.sinceStart()) });
      if (options.start === 'hidden') {
        return;
      }
      if (options.start === 'minimized') {
        if (saved?.maximized) this.win.maximize();
        this.win.show();
        this.win.minimize();
        return;
      }
      // maximize() also shows the window, so it waits for the same moment.
      if (saved?.maximized) this.win.maximize();
      this.win.show();
    });
    this.showLoading();
  }

  showLoading(): void {
    void this.load(loadingPage({ kind: 'starting' }));
  }

  showError(logPath: string, message?: string): void {
    this.origin = null;
    void this.load(loadingPage({ kind: 'failed', logPath, ...(message ? { message } : {}) }));
  }

  /** The server is ready on `port`: go to the dashboard unless already there. */
  serverReady(port: number): void {
    this.origin = originFor(port);
    const target = targetUrl(this.win.webContents.getURL(), port, startPath(this.options.store.get().onboarded));
    if (target) void this.load(target);
  }

  /** Shows and focuses the window, and opens `path` on the dashboard if given. */
  open(path?: string): void {
    if (this.win.isMinimized()) this.win.restore();
    if (this.pendingMaximize) {
      this.pendingMaximize = false;
      this.win.maximize();
    }
    this.win.show();
    this.win.focus();
    if (path && this.origin) void this.load(this.origin + path);
  }

  /** From here on, closing the window closes it (D13's `close`). */
  setQuitting(): void {
    this.quitting = true;
  }

  /** The quit did not happen (an update that could not be installed):
   *  closing the window decides for itself again. */
  cancelQuitting(): void {
    this.quitting = false;
  }

  private async load(url: string): Promise<void> {
    try {
      await this.win.loadURL(url);
    } catch {
      // did-fail-load has already logged it
    }
  }

  private saveBounds(): void {
    if (this.win.isDestroyed() || this.win.isMinimized()) return;
    const { x, y, width, height } = this.win.getNormalBounds();
    this.options.store.update({ bounds: { x, y, width, height, maximized: this.pendingMaximize || this.win.isMaximized() } });
  }

  private scheduleSave(): void {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => {
      this.saveTimer = null;
      this.saveBounds();
    }, 500);
  }

  private routeAway(url: string, how: string): void {
    const kind = classifyNavigation(url, this.origin);
    if (kind === 'external') {
      this.options.log.info('opening in the system browser', { how, scheme: new URL(url).protocol });
      this.deps.openExternal(url).catch((error: unknown) =>
        this.options.log.warn('the system browser refused an address', { error: String(error) }),
      );
    } else if (kind === 'blocked') {
      this.options.log.warn('refused a navigation', { how, url: url.slice(0, 200) });
    }
  }

  private watch(): void {
    const { log, pageLog } = this.options;
    const win = this.win;
    const contents = win.webContents;

    win.on('close', (event) => {
      const action = closeAction(this.options.platform, Boolean(this.options.store.get().keepRunningOnClose), this.quitting);
      if (this.saveTimer) clearTimeout(this.saveTimer);
      this.saveBounds();
      if (action === 'hide') {
        event.preventDefault();
        win.hide();
        log.info('window closed: hidden, tracking continues');
      } else if (action === 'quit') {
        event.preventDefault();
        log.info('window closed: quitting');
        this.options.quit();
      }
    });
    // A page's `window.close()` destroys the window without a `close` event.
    // A destroyed window cannot be shown again, so the app quits rather than
    // run on with nothing to open (no tray on GNOME without the extension).
    win.on('closed', () => {
      if (this.quitting) return;
      log.warn('window destroyed without a close: quitting');
      this.options.quit();
    });
    win.on('resize', () => this.scheduleSave());
    win.on('move', () => this.scheduleSave());
    win.on('show', () => log.debug('window shown'));
    win.on('hide', () => log.debug('window hidden'));

    contents.on('will-navigate', (event, url) => {
      if (classifyNavigation(url, this.origin) === 'internal') return;
      event.preventDefault();
      this.routeAway(url, 'navigation');
    });
    contents.setWindowOpenHandler(({ url }) => {
      if (classifyNavigation(url, this.origin) === 'internal') void this.load(url);
      else this.routeAway(url, 'new window');
      return { action: 'deny' };
    });

    const started = new Map<string, number>();
    contents.on('did-start-navigation', (details) => {
      if (details.isMainFrame && !details.isSameDocument) started.set(details.url, Date.now());
    });
    contents.on('did-finish-load', () => {
      const url = contents.getURL();
      const began = started.get(url);
      started.clear();
      log.info('page loaded', { page: describe(url), ms: began === undefined ? null : Date.now() - began });
    });
    contents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
      // -3 is ERR_ABORTED: a navigation replaced by the next one.
      const fields = { code, description, page: describe(url), isMainFrame };
      if (code === -3) log.debug('load aborted', fields);
      else log.error('load failed', fields);
    });
    contents.on('console-message', (event) => {
      const level = CONSOLE_LEVEL[event.level] ?? 'info';
      pageLog[level](event.message, { source: describe(event.sourceId), line: event.lineNumber });
    });
    contents.on('render-process-gone', (_event, details) => log.error('renderer gone', { ...details }));
    contents.on('unresponsive', () => log.warn('renderer unresponsive'));
    contents.on('responsive', () => log.info('renderer responsive again'));
  }
}

/** A URL as logged: the path on the dashboard's origin, the scheme alone for
 *  a data URL (the loading page), else the URL cut short. */
export function describe(url: string): string {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === 'data:') return 'data:(loading page)';
    if (parsed.hostname === '127.0.0.1') return parsed.pathname + parsed.search;
    return url.slice(0, 200);
  } catch {
    return url.slice(0, 200);
  }
}
