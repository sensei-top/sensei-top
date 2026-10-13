import { EventEmitter } from 'node:events';
import type { BrowserWindow, Rectangle } from 'electron';
import { afterEach, describe, expect, it } from 'vitest';
import { setLanguage } from './i18n';
import type { Logger } from './log';
import type { LanguageChoice, ShellPrefs, ShellStore } from './store';
import {
  appMenuTemplate,
  classifyNavigation,
  closeAction,
  DEFAULT_SIZE,
  describe as describeUrl,
  fitBounds,
  loadingPage,
  MainWindow,
  MIN_SIZE,
  startPath,
  targetUrl,
  type StartMode,
} from './window';

describe('closing the window (D13)', () => {
  it.each([
    ['win32', false, 'hide'],
    ['win32', true, 'hide'],
    ['darwin', false, 'hide'],
    ['linux', false, 'quit'],
    ['linux', true, 'hide'],
  ] as const)('%s, keep running %s: %s', (platform, keep, action) => {
    expect(closeAction(platform, keep, false)).toBe(action);
  });

  it('just closes while the app is quitting', () => {
    expect(closeAction('win32', false, true)).toBe('close');
    expect(closeAction('linux', true, true)).toBe('close');
  });
});

describe('navigation', () => {
  const origin = 'http://127.0.0.1:41234';

  it('keeps the dashboard’s own pages in the window', () => {
    expect(classifyNavigation('http://127.0.0.1:41234/decks?x=1#y', origin)).toBe('internal');
  });

  it('sends other web addresses to the system browser', () => {
    expect(classifyNavigation('https://scryfall.com/card/x', origin)).toBe('external');
    expect(classifyNavigation('http://127.0.0.1:8000/', origin)).toBe('external');
    expect(classifyNavigation('http://localhost:41234/', origin)).toBe('external');
  });

  it('refuses every other scheme, and anything before the server is up', () => {
    expect(classifyNavigation('mailto:someone@example.org', origin)).toBe('blocked');
    expect(classifyNavigation('file:///etc/passwd', origin)).toBe('blocked');
    expect(classifyNavigation('javascript:alert(1)', origin)).toBe('blocked');
    expect(classifyNavigation('not a url', origin)).toBe('blocked');
    expect(classifyNavigation('data:text/html,x', null)).toBe('blocked');
    expect(classifyNavigation('http://127.0.0.1:41234/', null)).toBe('external');
  });
});

describe('where the window goes (D20)', () => {
  it('opens onboarding until shell.json says it is done', () => {
    expect(startPath(undefined)).toBe('/welcome');
    expect(startPath(false)).toBe('/welcome');
    expect(startPath(true)).toBe('/');
  });

  it('leaves a page on the same origin alone: it reconnects by itself', () => {
    expect(targetUrl('http://127.0.0.1:41234/decks/3', 41234, '/')).toBeNull();
  });

  it('keeps the page when the port moved', () => {
    expect(targetUrl('http://127.0.0.1:41234/decks/3?tab=guide#top', 45678, '/')).toBe(
      'http://127.0.0.1:45678/decks/3?tab=guide#top',
    );
  });

  it('goes to the start page from the loading page', () => {
    expect(targetUrl(loadingPage({ kind: 'starting' }), 41234, '/welcome')).toBe('http://127.0.0.1:41234/welcome');
    expect(targetUrl('', 41234, '/')).toBe('http://127.0.0.1:41234/');
  });
});

describe('the remembered bounds', () => {
  const screen: Rectangle = { x: 0, y: 0, width: 1920, height: 1040 };
  const right: Rectangle = { x: 1920, y: 0, width: 1280, height: 1000 };

  it('is the default size the first time', () => {
    expect(fitBounds(undefined, [screen])).toEqual(DEFAULT_SIZE);
  });

  it('keeps a window that is on a display where it was', () => {
    expect(fitBounds({ x: 100, y: 50, width: 1200, height: 800 }, [screen])).toEqual({ x: 100, y: 50, width: 1200, height: 800 });
    expect(fitBounds({ x: 2000, y: 10, width: 1000, height: 700 }, [screen, right])).toEqual({ x: 2000, y: 10, width: 1000, height: 700 });
  });

  it('keeps a window mostly off screen if 64 px of it still show', () => {
    expect(fitBounds({ x: 1856, y: 976, width: 1000, height: 700 }, [screen])).toEqual({ x: 1856, y: 976, width: 1000, height: 700 });
  });

  it('drops the position of a window on a display that is gone, keeping its size', () => {
    expect(fitBounds({ x: 2000, y: 10, width: 1000, height: 700 }, [screen])).toEqual({ width: 1000, height: 700 });
    expect(fitBounds({ x: 1857, y: 10, width: 1000, height: 700 }, [screen])).toEqual({ width: 1000, height: 700 });
  });

  it('shrinks to the largest display, and never below the minimum', () => {
    expect(fitBounds({ width: 4000, height: 3000 }, [screen, right])).toEqual({ width: 1920, height: 1040 });
    expect(fitBounds({ width: 100, height: 100 }, [screen])).toEqual(MIN_SIZE);
  });
});

function pageHtml(url: string): string {
  const prefix = 'data:text/html;charset=utf-8,';
  expect(url.startsWith(prefix)).toBe(true);
  return decodeURIComponent(url.slice(prefix.length));
}

describe('the loading page', () => {
  it('can make no request: a CSP of default-src none, and no script', () => {
    const html = pageHtml(loadingPage({ kind: 'starting' }));
    expect(html).toContain(`content="default-src 'none'; style-src 'unsafe-inline'"`);
    expect(html).not.toMatch(/<script|src=|href=|url\(/i);
    expect(html).toContain('Starting the tracker');
  });

  it('names the log file, escaped, and leaves the reason to the log', () => {
    const html = pageHtml(loadingPage({ kind: 'failed', logPath: '~/odd <b>&/logs/shell.log' }));
    expect(html).toContain(
      '<p>The tracker stopped and could not be restarted.</p>' +
        '<p>Quit Sensei Top and open it again to try once more.</p>' +
        '<p class="detail">What went wrong is written to the log file: ~/odd &#60;b&#62;&#38;/logs/shell.log</p>',
    );
    expect(html).not.toContain('<b>');
  });

  it('is in English, and says so, before any language is chosen', () => {
    expect(pageHtml(loadingPage({ kind: 'starting' }))).toContain('<html lang="en">');
  });
});

describe('the shell in another language', () => {
  afterEach(() => setLanguage('en'));

  it('writes the loading page and its lang in the current language', () => {
    setLanguage('pt-BR');
    const html = pageHtml(loadingPage({ kind: 'failed', logPath: '/logs/shell.log' }));
    expect(html).toContain('<html lang="pt-BR">');
    expect(html).toContain('<p>O tracker parou e não pôde ser reiniciado.</p>');
    expect(html).toContain('<p class="detail">O que deu errado está escrito no arquivo de log: /logs/shell.log</p>');
  });

  it('keeps lang at en when an unexpected value reaches the language', () => {
    setLanguage('x" a="' as LanguageChoice);
    expect(pageHtml(loadingPage({ kind: 'starting' }))).toContain('<html lang="en">');
  });

  it('names the app menu in the current language', () => {
    setLanguage('pt-BR');
    expect(appMenuTemplate(true).map((item) => item.label)).toEqual(['Editar', 'Exibir']);
  });
});

describe('the error page with a message', () => {
  it('replaces the fixed paragraphs with the message, escaped, and still names the log file', () => {
    const html = pageHtml(loadingPage({ kind: 'failed', logPath: '/logs/shell.log', message: 'Put <i>a.db</i> back & try.' }));
    const message = html.indexOf('Put &#60;i&#62;a.db&#60;/i&#62; back &#38; try.');
    expect(message).toBeGreaterThan(-1);
    expect(html).not.toContain('could not be restarted');
    expect(html).not.toContain('open it again');
    expect(html).toContain('the log file: /logs/shell.log');
    expect(html).not.toContain('<i>');
    expect(html).toContain(`content="default-src 'none'; style-src 'unsafe-inline'"`);
  });
});

describe('a URL as logged', () => {
  it('is the path on the dashboard, a label for the loading page, and short otherwise', () => {
    expect(describeUrl('http://127.0.0.1:41234/decks/3?tab=guide')).toBe('/decks/3?tab=guide');
    expect(describeUrl(loadingPage({ kind: 'starting' }))).toBe('data:(loading page)');
    expect(describeUrl(`https://example.org/${'x'.repeat(300)}`)).toHaveLength(200);
  });
});

class FakeContents extends EventEmitter {
  url = '';
  openHandler: ((details: { url: string }) => { action: string }) | null = null;
  getURL(): string {
    return this.url;
  }
  setWindowOpenHandler(handler: (details: { url: string }) => { action: string }): void {
    this.openHandler = handler;
  }
}

class FakeWindow extends EventEmitter {
  static last: FakeWindow | null = null;
  readonly webContents = new FakeContents();
  readonly loads: string[] = [];
  readonly calls: string[] = [];
  menuBarVisible: boolean | null = null;
  constructor(readonly options: Record<string, unknown>) {
    super();
    FakeWindow.last = this;
  }
  loadURL(url: string): Promise<void> {
    this.loads.push(url);
    this.webContents.url = url;
    return Promise.resolve();
  }
  hide(): void {
    this.calls.push('hide');
  }
  show(): void {
    this.calls.push('show');
  }
  focus(): void {}
  setMenuBarVisibility(visible: boolean): void {
    this.menuBarVisible = visible;
  }
  maximize(): void {
    this.calls.push('maximize');
  }
  minimize(): void {
    this.calls.push('minimize');
  }
  restore(): void {}
  isMinimized(): boolean {
    return false;
  }
  isMaximized(): boolean {
    return false;
  }
  isDestroyed(): boolean {
    return false;
  }
  getNormalBounds(): Rectangle {
    return { x: 10, y: 20, width: 1000, height: 700 };
  }
}

function makeWindow(platform: NodeJS.Platform, prefs: ShellPrefs = {}, start: StartMode = 'show') {
  let current: ShellPrefs = { ...prefs };
  const store = {
    get: () => current,
    update: (patch: ShellPrefs) => {
      current = { ...current, ...patch };
      return true;
    },
  } as unknown as ShellStore;
  const lines: string[] = [];
  const log: Logger = { debug: (m) => lines.push(m), info: (m) => lines.push(m), warn: (m) => lines.push(m), error: (m) => lines.push(m) };
  const external: string[] = [];
  let quits = 0;
  const window = new MainWindow(
    {
      BrowserWindow: FakeWindow as unknown as typeof BrowserWindow,
      openExternal: async (url) => {
        external.push(url);
      },
      workAreas: () => [{ x: 0, y: 0, width: 1920, height: 1040 }],
    },
    { store, log, pageLog: log, platform, start, sinceStart: () => 0, quit: () => quits++ },
  );
  const fake = FakeWindow.last!;
  return { window, fake, external, lines, prefs: () => current, quits: () => quits };
}

function closeEvent() {
  let prevented = false;
  return {
    event: { preventDefault: () => (prevented = true) },
    prevented: () => prevented,
  };
}

describe('the application menu', () => {
  const roles = (packaged: boolean) =>
    appMenuTemplate(packaged).flatMap((top) => (Array.isArray(top.submenu) ? top.submenu : [])).map((item) => item.role);

  it('keeps the zoom accelerators and leaves out the developer items when packaged', () => {
    const packaged = roles(true);
    expect(packaged).toEqual(expect.arrayContaining(['resetZoom', 'zoomIn', 'zoomOut']));
    for (const role of ['reload', 'forceReload', 'toggleDevTools']) expect(packaged).not.toContain(role);
  });

  it('adds reload and the developer tools in a development run', () => {
    const development = roles(false);
    expect(development).toEqual(expect.arrayContaining(['resetZoom', 'zoomIn', 'zoomOut', 'reload', 'forceReload', 'toggleDevTools']));
  });
});

describe('the main window', () => {
  it('never draws the menu bar, and Alt does not reveal it', () => {
    const { fake } = makeWindow('win32');
    expect(fake.options.autoHideMenuBar).toBe(false);
    expect(fake.menuBarVisible).toBe(false);
  });

  it('isolates the page from Node', () => {
    const { fake } = makeWindow('linux');
    expect(fake.options.webPreferences).toEqual({ nodeIntegration: false, contextIsolation: true, sandbox: true });
    expect(fake.options.show).toBe(false);
  });

  it('shows the loading page first, then the start page once the server is ready', () => {
    const { window, fake } = makeWindow('linux');
    expect(fake.loads).toHaveLength(1);
    expect(fake.loads[0]!.startsWith('data:text/html')).toBe(true);
    window.serverReady(41234);
    expect(fake.loads[1]).toBe('http://127.0.0.1:41234/welcome');
    window.serverReady(41234);
    expect(fake.loads).toHaveLength(2);
  });

  it('shows the error page when the server gives up, and the loading page when it starts again', () => {
    const { window, fake } = makeWindow('linux', { onboarded: true });
    window.serverReady(41234);
    window.showError('~/logs/shell.log');
    expect(pageHtml(fake.loads.at(-1)!)).toContain('could not be restarted');
    window.showLoading();
    expect(pageHtml(fake.loads.at(-1)!)).toContain('Starting the tracker');
    window.serverReady(41234);
    expect(fake.loads.at(-1)).toBe('http://127.0.0.1:41234/');
  });

  it('stays hidden when started with the system, and maximizes when it was', () => {
    const hidden = makeWindow('win32', { bounds: { width: 900, height: 600, maximized: true } }, 'hidden');
    hidden.fake.emit('ready-to-show');
    expect(hidden.fake.calls).toEqual([]);
    const shown = makeWindow('win32', { bounds: { width: 900, height: 600, maximized: true } });
    shown.fake.emit('ready-to-show');
    expect(shown.fake.calls).toEqual(['maximize', 'show']);
  });

  it('starts minimized: restores a saved maximized state, then minimizes', () => {
    const minimized = makeWindow('linux', { bounds: { width: 900, height: 600, maximized: true } }, 'minimized');
    minimized.fake.emit('ready-to-show');
    expect(minimized.fake.calls).toEqual(['maximize', 'show', 'minimize']);
    const plain = makeWindow('linux', {}, 'minimized');
    plain.fake.emit('ready-to-show');
    expect(plain.fake.calls).toEqual(['show', 'minimize']);
  });

  it('maximizes on an open() before the first paint of a hidden start', () => {
    const early = makeWindow('win32', { bounds: { width: 900, height: 600, maximized: true } }, 'hidden');
    early.window.open();
    expect(early.fake.calls).toEqual(['maximize', 'show']);
  });

  it('maximizes on the first open after a hidden start, and a close before then keeps the flag', () => {
    const bounds = { width: 900, height: 600, maximized: true };
    const early = makeWindow('win32', { bounds }, 'hidden');
    early.fake.emit('ready-to-show');
    early.fake.emit('close', closeEvent().event);
    expect(early.prefs().bounds?.maximized).toBe(true);
    const later = makeWindow('win32', { bounds }, 'hidden');
    later.fake.emit('ready-to-show');
    later.window.open();
    later.window.open();
    expect(later.fake.calls).toEqual(['maximize', 'show', 'show']);
    const normal = makeWindow('win32', {}, 'hidden');
    normal.fake.emit('ready-to-show');
    normal.window.open();
    expect(normal.fake.calls).toEqual(['show']);
  });

  it('hides on close on Windows, and saves its bounds', () => {
    const { fake, prefs, quits } = makeWindow('win32');
    const close = closeEvent();
    fake.emit('close', close.event);
    expect(close.prevented()).toBe(true);
    expect(fake.calls).toContain('hide');
    expect(quits()).toBe(0);
    expect(prefs().bounds).toEqual({ x: 10, y: 20, width: 1000, height: 700, maximized: false });
  });

  it('quits on close on Linux, unless asked to keep running', () => {
    const plain = makeWindow('linux');
    const close = closeEvent();
    plain.fake.emit('close', close.event);
    expect(close.prevented()).toBe(true);
    expect(plain.quits()).toBe(1);

    const kept = makeWindow('linux', { keepRunningOnClose: true });
    kept.fake.emit('close', closeEvent().event);
    expect(kept.quits()).toBe(0);
    expect(kept.fake.calls).toContain('hide');
  });

  it('lets the window close while quitting', () => {
    const { window, fake, quits } = makeWindow('win32');
    window.setQuitting();
    const close = closeEvent();
    fake.emit('close', close.event);
    expect(close.prevented()).toBe(false);
    expect(quits()).toBe(0);
  });

  it('quits when the window is destroyed without a close, but not while quitting', () => {
    const plain = makeWindow('win32');
    plain.fake.emit('closed');
    expect(plain.quits()).toBe(1);

    const quitting = makeWindow('linux');
    quitting.window.setQuitting();
    quitting.fake.emit('closed');
    expect(quitting.quits()).toBe(0);
  });

  it('decides for itself again once a quit is called off', () => {
    const { window, fake, quits } = makeWindow('win32');
    window.setQuitting();
    window.cancelQuitting();
    const close = closeEvent();
    fake.emit('close', close.event);
    expect(close.prevented()).toBe(true);
    expect(fake.calls).toContain('hide');
    expect(quits()).toBe(0);
  });

  it('sends an outside link to the system browser and refuses a file', () => {
    const { window, fake, external } = makeWindow('linux');
    window.serverReady(41234);
    const inside = closeEvent();
    fake.webContents.emit('will-navigate', inside.event, 'http://127.0.0.1:41234/decks');
    expect(inside.prevented()).toBe(false);
    const outside = closeEvent();
    fake.webContents.emit('will-navigate', outside.event, 'https://example.org/');
    expect(outside.prevented()).toBe(true);
    const file = closeEvent();
    fake.webContents.emit('will-navigate', file.event, 'file:///etc/hosts');
    expect(file.prevented()).toBe(true);
    expect(external).toEqual(['https://example.org/']);
  });

  it('never opens a second window', () => {
    const { window, fake, external } = makeWindow('linux');
    window.serverReady(41234);
    expect(fake.webContents.openHandler?.({ url: 'https://example.org/' })).toEqual({ action: 'deny' });
    expect(fake.webContents.openHandler?.({ url: 'http://127.0.0.1:41234/coach' })).toEqual({ action: 'deny' });
    expect(external).toEqual(['https://example.org/']);
    expect(fake.loads.at(-1)).toBe('http://127.0.0.1:41234/coach');
  });
});
