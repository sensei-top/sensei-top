import { describe, expect, it, vi } from 'vitest';
import { t } from './i18n';
import type { Logger } from './log';
import {
  CHECK_INTERVAL_MS,
  FIRST_CHECK_MS,
  UpdateService,
  updaterLogger,
  updaterAvailability,
  type AvailabilityInput,
  type CheckResultLike,
  type Timers,
  type UpdateInfoLike,
  type UpdaterLike,
  type UpdateStatus,
} from './updater';

describe('updaterAvailability', () => {
  const base: AvailabilityInput = { platform: 'win32', packaged: true, windowsStore: false, appImage: undefined };

  it('is unavailable in the Store build, before anything else', () => {
    expect(updaterAvailability({ ...base, windowsStore: true, packaged: false })).toEqual({ available: false, reason: 'store' });
  });

  it('is unavailable in a development run', () => {
    expect(updaterAvailability({ ...base, packaged: false })).toEqual({ available: false, reason: 'development' });
    expect(updaterAvailability({ ...base, platform: 'linux', packaged: false, appImage: '/x.AppImage' })).toEqual({
      available: false,
      reason: 'development',
    });
  });

  it('is unsupported on Linux without the AppImage, and on other platforms', () => {
    expect(updaterAvailability({ ...base, platform: 'linux' })).toEqual({ available: false, reason: 'unsupported' });
    expect(updaterAvailability({ ...base, platform: 'linux', appImage: '' })).toEqual({ available: false, reason: 'unsupported' });
    expect(updaterAvailability({ ...base, platform: 'darwin', appImage: '/x' })).toEqual({ available: false, reason: 'unsupported' });
  });

  it('is available for the installed Windows build and the AppImage', () => {
    expect(updaterAvailability(base)).toEqual({ available: true });
    expect(updaterAvailability({ ...base, platform: 'linux', appImage: '/x.AppImage' })).toEqual({ available: true });
  });
});

class FakeUpdater implements UpdaterLike {
  autoDownload = false;
  autoInstallOnAppQuit = true;
  allowPrerelease = true;
  allowDowngrade = true;
  disableWebInstaller = false;
  logger: UpdaterLike['logger'] = null;
  checks = 0;
  installs: Array<[boolean | undefined, boolean | undefined]> = [];
  onInstall: () => void = () => {};
  /** What the next checkForUpdates does. */
  behaviour: () => Promise<CheckResultLike | null> = () => Promise.resolve(null);
  private handlers = new Map<string, Array<(arg: never) => void>>();

  checkForUpdates(): Promise<CheckResultLike | null> {
    this.checks += 1;
    return this.behaviour();
  }
  quitAndInstall(silent?: boolean, run?: boolean): void {
    this.installs.push([silent, run]);
    this.onInstall();
  }
  on(event: string, listener: (arg: never) => void): this {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), listener]);
    return this;
  }
  emit(event: string, arg?: UpdateInfoLike | Error): void {
    for (const h of this.handlers.get(event) ?? []) (h as (a?: unknown) => void)(arg);
  }
}

class FakeTimers implements Timers {
  timeouts = new Map<number, { fn: () => void; ms: number }>();
  intervals = new Map<number, { fn: () => void; ms: number }>();
  private next = 1;
  setTimeout(fn: () => void, ms: number): number {
    this.timeouts.set(this.next, { fn, ms });
    return this.next++;
  }
  clearTimeout(handle: unknown): void {
    this.timeouts.delete(handle as number);
  }
  setInterval(fn: () => void, ms: number): number {
    this.intervals.set(this.next, { fn, ms });
    return this.next++;
  }
  clearInterval(handle: unknown): void {
    this.intervals.delete(handle as number);
  }
  fireTimeouts(): void {
    const all = [...this.timeouts.values()];
    this.timeouts.clear();
    for (const t of all) t.fn();
  }
  fireIntervals(): void {
    for (const t of [...this.intervals.values()]) t.fn();
  }
}

function setup() {
  const updater = new FakeUpdater();
  const timers = new FakeTimers();
  const statuses: UpdateStatus[] = [];
  const lines: string[] = [];
  const records: Array<{ level: string; message: string; fields?: unknown }> = [];
  const rec = (level: string) => (message: string, fields?: unknown) => {
    lines.push(message);
    records.push({ level, message, fields });
  };
  const log: Logger = { debug: rec('DEBUG'), info: rec('INFO'), warn: rec('WARNING'), error: rec('ERROR') };
  const service = new UpdateService({
    updater,
    timers,
    log,
    now: () => new Date('2026-10-08T12:00:00.000Z'),
    onStatus: (s) => statuses.push(s),
  });
  return { updater, timers, statuses, lines, records, service };
}

const flush = () => new Promise<void>((resolve) => setImmediate(resolve));

describe('UpdateService', () => {
  it('sets the updater up: autoDownload stays off until the switch turns it on, prereleases, downgrades and the web installer off, nothing on quit yet', () => {
    const { updater, records } = setup();
    expect(updater.autoDownload).toBe(false);
    expect(updater.allowPrerelease).toBe(false);
    expect(updater.allowDowngrade).toBe(false);
    expect(updater.disableWebInstaller).toBe(true);
    expect(updater.autoInstallOnAppQuit).toBe(false);
    updater.logger?.info('x');
    updater.logger?.warn('y');
    updater.logger?.error('z');
    expect(records).toEqual([
      { level: 'DEBUG', message: 'x', fields: undefined },
      { level: 'WARNING', message: 'y', fields: undefined },
      { level: 'ERROR', message: 'z', fields: undefined },
    ]);
  });

  it('with the switch off never checks, installs nothing on quit and reads idle', async () => {
    const { updater, timers, service } = setup();
    service.start(false);
    expect(updater.autoInstallOnAppQuit).toBe(false);
    expect(timers.timeouts.size + timers.intervals.size).toBe(0);
    expect(service.status).toEqual({ state: 'idle' });
    expect(await service.checkNow()).toEqual({ ok: false, error: t('update.off') });
    expect(updater.checks).toBe(0);
  });

  it('with the switch on checks 30 s after launch, then every 24 h', async () => {
    const { updater, timers, service } = setup();
    service.start(true);
    expect(updater.autoInstallOnAppQuit).toBe(true);
    expect(updater.autoDownload).toBe(true);
    expect([...timers.timeouts.values()].map((t) => t.ms)).toEqual([FIRST_CHECK_MS]);
    expect([...timers.intervals.values()].map((t) => t.ms)).toEqual([CHECK_INTERVAL_MS]);
    expect(FIRST_CHECK_MS).toBe(30_000);
    expect(CHECK_INTERVAL_MS).toBe(86_400_000);
    expect(updater.checks).toBe(0);
    timers.fireTimeouts();
    await flush();
    expect(updater.checks).toBe(1);
    timers.fireIntervals();
    await flush();
    expect(updater.checks).toBe(2);
  });

  it('switching on mid-run checks at once and starts the timer; off clears it', async () => {
    const { updater, timers, service } = setup();
    service.start(false);
    service.setEnabled(true);
    expect(updater.checks).toBe(1);
    expect(timers.intervals.size).toBe(1);
    expect(timers.timeouts.size).toBe(0);
    await flush();
    service.setEnabled(false);
    expect(timers.intervals.size).toBe(0);
    expect(updater.autoInstallOnAppQuit).toBe(false);
    expect(service.status).toEqual({ state: 'idle' });
  });

  it('maps each updater event to a status', async () => {
    const { updater, statuses, service } = setup();
    service.start(true);
    updater.behaviour = () => {
      updater.emit('update-not-available', { version: '0.6.0' });
      return Promise.resolve(null);
    };
    expect(await service.checkNow()).toEqual({ ok: true });
    expect(service.status).toEqual({ state: 'current', checkedAt: '2026-10-08T12:00:00.000Z' });

    updater.behaviour = () => {
      updater.emit('update-available', { version: '0.6.1' });
      return Promise.resolve(null);
    };
    await service.checkNow();
    expect(service.status).toEqual({ state: 'downloading', version: '0.6.1' });

    updater.emit('update-downloaded', { version: '0.6.1' });
    expect(service.status).toEqual({ state: 'ready', version: '0.6.1' });
    expect(statuses.map((s) => s.state)).toEqual(['checking', 'current', 'checking', 'downloading', 'ready']);
  });

  it('answers a failed check with the shell sentence and logs the error once', async () => {
    const { updater, lines, service } = setup();
    service.start(true);
    updater.behaviour = () => {
      const error = new Error('404 Not Found');
      updater.emit('error', error);
      return Promise.reject(error);
    };
    expect(await service.checkNow()).toEqual({ ok: false, error: t('update.checkFailed') });
    expect(service.status).toEqual({ state: 'failed', checkedAt: '2026-10-08T12:00:00.000Z' });
    expect(lines.filter((l) => l === 'update check failed')).toHaveLength(1);
  });

  it('fails a rejected check even when no error event came', async () => {
    const { updater, service } = setup();
    service.start(true);
    updater.behaviour = () => Promise.reject(new Error('offline'));
    expect(await service.checkNow()).toEqual({ ok: false, error: t('update.checkFailed') });
    expect(service.status.state).toBe('failed');
  });

  it('does not start a second check while one runs; both callers get the same result', async () => {
    const { updater, service } = setup();
    service.start(true);
    let finish: () => void = () => {};
    updater.behaviour = () => new Promise((resolve) => (finish = () => resolve(null)));
    const first = service.checkNow();
    const second = service.checkNow();
    expect(updater.checks).toBe(1);
    finish();
    expect(await first).toEqual({ ok: true });
    expect(await second).toEqual({ ok: true });
    updater.behaviour = () => Promise.resolve(null);
    await service.checkNow();
    expect(updater.checks).toBe(2);
  });

  it('ignores updater events while the switch is off', () => {
    const { updater, service } = setup();
    service.start(false);
    updater.emit('update-downloaded', { version: '0.6.1' });
    expect(service.status).toEqual({ state: 'idle' });
  });

  it('refuses restartToUpdate outside ready, without running beforeInstall', async () => {
    const { updater, service } = setup();
    service.start(true);
    const before = vi.fn(() => Promise.resolve());
    expect(await service.restartToUpdate(before)).toEqual({ ok: false, error: t('update.nothingReady') });
    expect(before).not.toHaveBeenCalled();
    expect(updater.installs).toEqual([]);
  });

  it('restartToUpdate runs beforeInstall, then installs silently and restarts', async () => {
    const { updater, service } = setup();
    service.start(true);
    updater.emit('update-downloaded', { version: '0.6.1' });
    const order: string[] = [];
    const before = () => {
      order.push('before');
      expect(updater.installs).toEqual([]);
      return Promise.resolve();
    };
    expect(await service.restartToUpdate(before)).toEqual({ ok: true });
    expect(order).toEqual(['before']);
    expect(updater.installs).toEqual([[true, true]]);
  });

  it('does not install when beforeInstall fails', async () => {
    const { updater, service } = setup();
    service.start(true);
    updater.emit('update-downloaded', { version: '0.6.1' });
    const result = await service.restartToUpdate(() => Promise.reject(new Error('server stuck')));
    expect(result.ok).toBe(false);
    expect(updater.installs).toEqual([]);
  });

  it('does not look again once an update is ready', async () => {
    const { updater, service } = setup();
    service.start(true);
    updater.emit('update-downloaded', { version: '0.6.1' });
    expect(await service.checkNow()).toEqual({ ok: true });
    expect(updater.checks).toBe(0);
    expect(service.status).toEqual({ state: 'ready', version: '0.6.1' });
  });

  it('logs the error text, and answers the install-failed sentence when beforeInstall rejects', async () => {
    const { updater, records, service } = setup();
    service.start(true);
    updater.behaviour = () => Promise.reject(new Error('boom-text'));
    await service.checkNow();
    const failed = records.find((r) => r.message === 'update check failed');
    expect(failed?.level).toBe('WARNING');
    expect(JSON.stringify(failed?.fields)).toContain('boom-text');

    updater.emit('update-downloaded', { version: '0.6.1' });
    expect(await service.restartToUpdate(() => Promise.reject(new Error('x')))).toEqual({ ok: false, error: t('update.installFailed') });
  });

  it('answers the install-failed sentence when quitAndInstall emits error and returns', async () => {
    const { updater, records, service } = setup();
    service.start(true);
    updater.emit('update-downloaded', { version: '0.6.1' });
    updater.onInstall = () => updater.emit('error', new Error('installer refused'));
    expect(await service.restartToUpdate(() => Promise.resolve())).toEqual({ ok: false, error: t('update.installFailed') });
    const line = records.find((r) => r.message === 'update install failed');
    expect(line?.level).toBe('ERROR');
    expect(JSON.stringify(line?.fields)).toContain('installer refused');
    // the failed install did not turn the status into a failed check
    expect(service.status).toEqual({ state: 'ready', version: '0.6.1' });
  });

  it('a second restartToUpdate while the first waits shares it', async () => {
    const { updater, service } = setup();
    service.start(true);
    updater.emit('update-downloaded', { version: '0.6.1' });
    let release: () => void = () => {};
    const before = vi.fn(() => new Promise<void>((resolve) => (release = resolve)));
    const first = service.restartToUpdate(before);
    const second = service.restartToUpdate(before);
    release();
    expect(await first).toEqual({ ok: true });
    expect(await second).toEqual({ ok: true });
    expect(before).toHaveBeenCalledTimes(1);
    expect(updater.installs).toHaveLength(1);
  });

  it('installs once: a later restartToUpdate answers ok and calls quitAndInstall no more', async () => {
    const { updater, service } = setup();
    service.start(true);
    updater.emit('update-downloaded', { version: '0.6.1' });
    const before = vi.fn(() => Promise.resolve());
    expect(await service.restartToUpdate(before)).toEqual({ ok: true });
    expect(await service.restartToUpdate(before)).toEqual({ ok: true });
    expect(updater.installs).toHaveLength(1);
    expect(before).toHaveBeenCalledTimes(1);
  });

  it('may try again after an install that failed', async () => {
    const { updater, service } = setup();
    service.start(true);
    updater.emit('update-downloaded', { version: '0.6.1' });
    updater.onInstall = () => updater.emit('error', new Error('installer refused'));
    expect(await service.restartToUpdate(() => Promise.resolve())).toEqual({ ok: false, error: t('update.installFailed') });
    updater.onInstall = () => {};
    expect(await service.restartToUpdate(() => Promise.resolve())).toEqual({ ok: true });
    expect(updater.installs).toHaveLength(2);
  });

  it('swallows a rejected downloadPromise: the error event reports it', async () => {
    const { updater, service } = setup();
    service.start(true);
    const rejected = Promise.reject(new Error('download broke'));
    updater.behaviour = () => Promise.resolve({ downloadPromise: rejected });
    expect(await service.checkNow()).toEqual({ ok: true });
    await flush();
  });

  it('switching off turns autoDownload off and cancels a running download', async () => {
    const { updater, service } = setup();
    service.start(true);
    expect(updater.autoDownload).toBe(true);
    const cancel = vi.fn();
    updater.behaviour = () => Promise.resolve({ cancellationToken: { cancel } });
    await service.checkNow();
    service.setEnabled(false);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(updater.autoDownload).toBe(false);
  });
});

describe('updaterLogger', () => {
  it('sends info to DEBUG, warn to WARNING, error to ERROR', () => {
    const records: Array<[string, string]> = [];
    const log: Logger = {
      debug: (m) => void records.push(['DEBUG', m]),
      info: (m) => void records.push(['INFO', m]),
      warn: (m) => void records.push(['WARNING', m]),
      error: (m) => void records.push(['ERROR', m]),
    };
    const adapter = updaterLogger(log);
    adapter.info('a');
    adapter.warn('b');
    adapter.error('c');
    expect(records).toEqual([
      ['DEBUG', 'a'],
      ['WARNING', 'b'],
      ['ERROR', 'c'],
    ]);
  });
});
