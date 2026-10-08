import type { Menu, NativeImage, Tray } from 'electron';
import { afterEach, describe, expect, it } from 'vitest';
import type { Logger } from './log';
import {
  GAME_WINDOW_MS,
  ICONS,
  menuTemplate,
  NO_UPDATES,
  parseEventTime,
  StatusTray,
  trayState,
  WORDS,
  type TrayActions,
} from './tray';

const now = new Date(2026, 9, 7, 20, 0, 0).getTime();
/** `last_event_at` as `/api/live` sends it: naive local time. */
const localIso = (ms: number) => {
  const d = new Date(ms);
  const two = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}T${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
};

describe('the event time', () => {
  it('reads naive ISO as local time', () => {
    expect(parseEventTime('2026-10-07T20:00:00')).toBe(now);
    expect(parseEventTime('2026-10-07 20:00:00.250')).toBe(now + 250);
  });

  it('reads an explicit offset as written', () => {
    expect(parseEventTime('2026-10-07T20:00:00Z')).toBe(Date.UTC(2026, 9, 7, 20, 0, 0));
    expect(parseEventTime('2026-10-07T20:00:00+02:00')).toBe(Date.UTC(2026, 9, 7, 18, 0, 0));
  });

  it('is null for nothing or anything else', () => {
    for (const text of [null, undefined, '', '10/7/2026 8:00:00 PM', '2026-13-45']) {
      expect(parseEventTime(text)).toBeNull();
    }
  });
});

describe('the tray state (D14)', () => {
  it('follows the server until it is ready', () => {
    expect(trayState('failed', { watching: true }, now)).toBe('failed');
    expect(trayState('starting', { watching: true }, now)).toBe('starting');
    expect(trayState('stopped', null, now)).toBe('starting');
  });

  it('is down when /api/live does not answer', () => {
    expect(trayState('ready', null, now)).toBe('down');
  });

  it('puts a stopped watcher before a recent event', () => {
    expect(trayState('ready', { watching: false, watcher_stopped: true, last_event_at: localIso(now) }, now)).toBe('stopped');
  });

  it('calls an event within the last minute a match in progress', () => {
    expect(trayState('ready', { watching: true, last_event_at: localIso(now - GAME_WINDOW_MS) }, now)).toBe('game');
    expect(trayState('ready', { watching: true, last_event_at: localIso(now - GAME_WINDOW_MS - 1000) }, now)).toBe('watching');
  });

  it('is watching or not', () => {
    expect(trayState('ready', { watching: true, last_event_at: null }, now)).toBe('watching');
    expect(trayState('ready', { watching: false }, now)).toBe('idle');
    expect(trayState('ready', {}, now)).toBe('idle');
  });

  it('has words for every state', () => {
    for (const state of ['failed', 'starting', 'down', 'stopped', 'game', 'watching', 'idle'] as const) {
      expect(WORDS[state]).toBeTruthy();
    }
  });
});

describe('the menu', () => {
  const actions: TrayActions = {
    open: () => {},
    settings: () => {},
    checkForUpdates: () => {},
    restartToUpdate: () => {},
    showLogs: () => {},
    exportDiagnostics: () => {},
    quit: () => {},
  };

  it('opens with the state, then the items in order', () => {
    const items = menuTemplate('watching', actions);
    expect(items.map((item) => item.label ?? item.type)).toEqual([
      'Watching', 'separator', 'Open', 'Settings', 'Check for updates', 'Show logs', 'Export diagnostics', 'separator', 'Quit',
    ]);
    expect(items[0]!.enabled).toBe(false);
  });

  it('leaves Check for updates disabled without the updater, and Settings until the dashboard is up', () => {
    const enabled = (state: Parameters<typeof menuTemplate>[0]) =>
      Object.fromEntries(menuTemplate(state, actions).filter((item) => item.label).map((item) => [item.label, item.enabled !== false]));
    expect(enabled('watching')).toMatchObject({ Open: true, Settings: true, 'Check for updates': false, 'Show logs': true, 'Export diagnostics': true, Quit: true });
    expect(enabled('starting')).toMatchObject({ Open: true, Settings: false, 'Show logs': true, Quit: true });
    expect(enabled('failed').Settings).toBe(false);
    expect(enabled('stopped').Settings).toBe(true);
  });

  it('enables Check for updates only when the updater runs and its switch is on', () => {
    const checkEnabled = (canCheck: boolean) =>
      menuTemplate('watching', actions, { canCheck, ready: false }).find((item) => item.label === 'Check for updates')!.enabled;
    expect(checkEnabled(true)).toBe(true);
    expect(checkEnabled(false)).toBe(false);
    const item = menuTemplate('watching', actions, { canCheck: true, ready: false }).find((i) => i.label === 'Check for updates')!;
    expect(item.click).toBe(actions.checkForUpdates);
  });

  it('puts Restart to update above Quit, after the separator, only when an update is ready', () => {
    const labels = (ready: boolean) => menuTemplate('watching', actions, { canCheck: true, ready }).map((item) => item.label ?? item.type);
    expect(labels(true).slice(-3)).toEqual(['separator', 'Restart to update', 'Quit']);
    expect(labels(false)).not.toContain('Restart to update');
    expect(menuTemplate('failed', actions, { canCheck: false, ready: true }).find((i) => i.label === 'Restart to update')?.click).toBe(
      actions.restartToUpdate,
    );
    expect(labels(false)).toEqual(menuTemplate('watching', actions, NO_UPDATES).map((item) => item.label ?? item.type));
  });
});

describe('the icon', () => {
  it('is the icon of the state’s colour group', () => {
    expect(ICONS).toEqual({
      failed: 'warn',
      down: 'warn',
      stopped: 'warn',
      game: 'live',
      watching: 'live',
      starting: 'muted',
      idle: 'muted',
    });
  });
});

class FakeTray {
  static last: FakeTray | null = null;
  readonly tooltips: string[] = [];
  readonly images: unknown[] = [];
  readonly menus: unknown[] = [];
  destroyed = false;
  constructor(image: unknown) {
    this.images.push(image);
    FakeTray.last = this;
  }
  on(): void {}
  setImage(image: unknown): void {
    this.images.push(image);
  }
  setToolTip(text: string): void {
    this.tooltips.push(text);
  }
  setContextMenu(menu: unknown): void {
    this.menus.push(menu);
  }
  destroy(): void {
    this.destroyed = true;
  }
}

interface PendingRequest {
  url: string;
  answer: (body: unknown) => void;
  fail: () => void;
}

function makeTray() {
  const requests: PendingRequest[] = [];
  const fetch = ((input: string | URL) =>
    new Promise<Response>((resolve, reject) => {
      requests.push({
        url: String(input),
        answer: (body) => resolve(new Response(JSON.stringify(body), { status: 200 })),
        fail: () => reject(new TypeError('fetch failed')),
      });
    })) as typeof globalThis.fetch;
  const silentLog: Logger = { debug: () => {}, info: () => {}, warn: () => {}, error: () => {} };
  const tray = new StatusTray(
    {
      Tray: FakeTray as unknown as typeof Tray,
      Menu: { buildFromTemplate: (template: unknown) => template } as unknown as typeof Menu,
      icon: (name) => name as unknown as NativeImage,
      fetch,
    },
    {
      open: () => {},
      settings: () => {},
      checkForUpdates: () => {},
      restartToUpdate: () => {},
      showLogs: () => {},
      exportDiagnostics: () => {},
      quit: () => {},
    },
    silentLog,
    'linux',
  );
  const fake = FakeTray.last!;
  const said = () => fake.tooltips.at(-1);
  return { tray, requests, said, fake };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 10));

describe('the status tray', () => {
  let current: StatusTray | null = null;
  afterEach(() => {
    current?.destroy();
    current = null;
  });

  it('stays at starting until the first /api/live answer, never passing through down', async () => {
    const { tray, requests, said, fake } = makeTray();
    current = tray;
    expect(said()).toBe('Sensei Top: Starting the tracker');
    tray.setServer({ kind: 'starting' });
    tray.setServer({ kind: 'ready', port: 41234 });
    expect(said()).toBe('Sensei Top: Starting the tracker');
    expect(requests.map((r) => r.url)).toEqual(['http://127.0.0.1:41234/api/live']);
    requests[0]!.answer({ watching: true, watcher_stopped: false, last_event_at: null });
    await settle();
    expect(said()).toBe('Sensei Top: Watching');
    expect(fake.tooltips).not.toContain('Sensei Top: Tracker not running');
  });

  it('says the tracker is not running when the first request fails', async () => {
    const { tray, requests, said } = makeTray();
    current = tray;
    tray.setServer({ kind: 'ready', port: 41234 });
    requests[0]!.fail();
    await settle();
    expect(said()).toBe('Sensei Top: Tracker not running');
  });

  it('discards an old port’s answer, and does not let it hold up the new port’s request', async () => {
    const { tray, requests, said } = makeTray();
    current = tray;
    tray.setServer({ kind: 'ready', port: 41234 });
    tray.setServer({ kind: 'starting' });
    tray.setServer({ kind: 'ready', port: 45678 });
    expect(requests.map((r) => r.url)).toEqual(['http://127.0.0.1:41234/api/live', 'http://127.0.0.1:45678/api/live']);
    requests[0]!.answer({ watching: true });
    await settle();
    expect(said()).toBe('Sensei Top: Starting the tracker');
    requests[1]!.answer({ watching: false });
    await settle();
    expect(said()).toBe('Sensei Top: Not watching');
  });

  it('drops back to starting while the server restarts', async () => {
    const { tray, requests, said } = makeTray();
    current = tray;
    tray.setServer({ kind: 'ready', port: 41234 });
    requests[0]!.answer({ watching: true });
    await settle();
    tray.setServer({ kind: 'starting' });
    expect(said()).toBe('Sensei Top: Starting the tracker');
  });

  it('hands the icon dep the name of the state’s colour group', async () => {
    const { tray, requests, fake } = makeTray();
    current = tray;
    expect(fake.images[0]).toBe('muted');
    tray.setServer({ kind: 'ready', port: 41234 });
    requests[0]!.answer({ watching: true });
    await settle();
    expect(fake.images.at(-1)).toBe('live');
    tray.setServer({ kind: 'ready', port: 41234 });
    requests[1]!.fail();
    await settle();
    expect(fake.images.at(-1)).toBe('warn');
    tray.setServer({ kind: 'failed', reason: 'test' });
    expect(fake.images.at(-1)).toBe('warn');
  });

  it('builds the menu again when the updater’s part changes, and only then', () => {
    const { tray, fake } = makeTray();
    current = tray;
    const lastMenu = () => fake.menus.at(-1) as Array<{ label?: string; enabled?: boolean }>;
    const built = fake.menus.length;
    tray.setUpdate({ canCheck: false, ready: false });
    expect(fake.menus).toHaveLength(built);
    tray.setUpdate({ canCheck: true, ready: false });
    expect(fake.menus).toHaveLength(built + 1);
    expect(lastMenu().find((item) => item.label === 'Check for updates')?.enabled).toBe(true);
    tray.setUpdate({ canCheck: true, ready: true });
    expect(lastMenu().map((item) => item.label).slice(-2)).toEqual(['Restart to update', 'Quit']);
  });

  it('keeps the updater’s items when the state changes', async () => {
    const { tray, requests, fake } = makeTray();
    current = tray;
    tray.setUpdate({ canCheck: true, ready: true });
    tray.setServer({ kind: 'ready', port: 41234 });
    requests[0]!.answer({ watching: true });
    await settle();
    const menu = fake.menus.at(-1) as Array<{ label?: string }>;
    expect(menu[0]?.label).toBe('Watching');
    expect(menu.map((item) => item.label)).toContain('Restart to update');
  });
});
