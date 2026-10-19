// Updates (release plan 6, S14, decision D24). Electron-free: vitest imports
// it directly, and `main.ts` is the only main-process file that loads
// Electron. It hands `UpdateService` electron-updater's `autoUpdater` only when
// `updaterAvailability` says the updater can run, so electron-updater (whose
// `autoUpdater` getter loads Electron when it constructs the updater) is never
// imported otherwise.
//
// - Switch on: the first check 30 s after launch, then every 24 h; turning it
//   on mid-run checks at once. Switch off: no timer, no request, nothing
//   installs on quit, and the status reads `idle`.
// - One check at a time: a second caller gets the first one's result.
// - "Restart to update" works only in state `ready`. `quitAndInstall` spawns
//   the installer before it quits, so the caller's `beforeInstall` stops the
//   server first.
// - The shell log (`shell.updater`) gets one line per check started and one
//   per result. The logger scrubs the home path; the error is passed as text.

import { t } from './i18n';
import type { Logger } from './log';
import { silent } from './log';
import type { Saved } from './settings';

export type UpdateUnavailableReason = 'store' | 'development' | 'unsupported';

export type UpdateStatus =
  | { state: 'unavailable'; reason: 'store' | 'development' | 'unsupported' }
  | { state: 'idle' }
  | { state: 'checking' }
  | { state: 'current'; checkedAt: string } // ISO, UTC
  | { state: 'downloading'; version: string }
  | { state: 'ready'; version: string }
  | { state: 'failed'; checkedAt: string };

export type UpdateAvailability = { available: true } | { available: false; reason: UpdateUnavailableReason };

export interface AvailabilityInput {
  platform: NodeJS.Platform;
  packaged: boolean;
  /** `process.windowsStore`: set in the Microsoft Store (MSIX) build. */
  windowsStore: boolean;
  /** `$APPIMAGE`: set only when running from the AppImage. */
  appImage: string | undefined;
}

export const FIRST_CHECK_MS = 30_000;
export const CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000;

/** The rule for when the updater runs at all. Pure. */
export function updaterAvailability(input: AvailabilityInput): UpdateAvailability {
  if (input.windowsStore) return { available: false, reason: 'store' };
  if (!input.packaged) return { available: false, reason: 'development' };
  if (input.platform === 'win32') return { available: true };
  if (input.platform === 'linux' && input.appImage) return { available: true };
  return { available: false, reason: 'unsupported' };
}

/** The subset of electron-updater's `AppUpdater` the service uses. */
export interface UpdaterLogger {
  info(message?: unknown): void;
  warn(message?: unknown): void;
  error(message?: unknown): void;
  debug?(message: string): void;
}

export interface UpdateInfoLike {
  version: string;
}

export interface CheckResultLike {
  downloadPromise?: Promise<unknown> | null;
  cancellationToken?: { cancel(): void } | null;
}

export interface UpdaterLike {
  autoDownload: boolean;
  autoInstallOnAppQuit: boolean;
  allowPrerelease: boolean;
  allowDowngrade: boolean;
  disableWebInstaller: boolean;
  logger: UpdaterLogger | null;
  checkForUpdates(): Promise<CheckResultLike | null>;
  quitAndInstall(isSilent?: boolean, isForceRunAfter?: boolean): void;
  on(event: 'update-available' | 'update-not-available' | 'update-downloaded', listener: (info: UpdateInfoLike) => void): unknown;
  on(event: 'error', listener: (error: Error) => void): unknown;
}

export interface Timers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
  setInterval(fn: () => void, ms: number): unknown;
  clearInterval(handle: unknown): void;
}

export const realTimers: Timers = {
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
  setInterval: (fn, ms) => setInterval(fn, ms),
  clearInterval: (handle) => clearInterval(handle as ReturnType<typeof setInterval>),
};

export interface UpdateServiceDeps {
  updater: UpdaterLike;
  timers?: Timers;
  now?: () => Date;
  log?: Logger;
  onStatus?: (status: UpdateStatus) => void;
}

/** electron-updater's own logger, pointed at the shell log: its info lines at DEBUG. */
export function updaterLogger(log: Logger): UpdaterLogger {
  return {
    info: (message) => log.debug(String(message)),
    warn: (message) => log.warn(String(message)),
    error: (message) => log.error(String(message)),
    debug: (message) => log.debug(message),
  };
}

export class UpdateService {
  private readonly updater: UpdaterLike;
  private readonly timers: Timers;
  private readonly now: () => Date;
  private readonly log: Logger;
  private readonly onStatus: (status: UpdateStatus) => void;
  private current: UpdateStatus = { state: 'idle' };
  private enabled = false;
  private firstTimer: unknown = null;
  private repeatTimer: unknown = null;
  private inFlight: Promise<Saved> | null = null;
  private restarting: Promise<Saved> | null = null;
  private installing = false;
  /** `quitAndInstall` returned with no error: the app is on its way out. */
  private installed = false;
  private installError: unknown = null;
  private cancelToken: { cancel(): void } | null = null;

  constructor(deps: UpdateServiceDeps) {
    this.updater = deps.updater;
    this.timers = deps.timers ?? realTimers;
    this.now = deps.now ?? (() => new Date());
    this.log = deps.log ?? silent;
    this.onStatus = deps.onStatus ?? (() => {});
    const u = this.updater;
    u.autoDownload = false;
    // electron-updater turns prereleases on when the running version is one
    // (`0.7.0-beta.1`): beta testers get ordinary releases.
    u.allowPrerelease = false;
    u.allowDowngrade = false;
    // The NSIS build is a full installer; left false, every update found logs a warning.
    u.disableWebInstaller = true;
    u.autoInstallOnAppQuit = false;
    u.logger = updaterLogger(this.log);
    u.on('update-available', (info) => {
      if (!this.enabled) return;
      this.log.info('update found', { version: info.version });
      this.set({ state: 'downloading', version: info.version });
    });
    u.on('update-not-available', () => {
      if (!this.enabled) return;
      this.log.info('no update available');
      this.set({ state: 'current', checkedAt: this.now().toISOString() });
    });
    u.on('update-downloaded', (info) => {
      if (!this.enabled) return;
      this.log.info('update downloaded', { version: info.version });
      this.set({ state: 'ready', version: info.version });
    });
    u.on('error', (error) => {
      if (this.installing) {
        // quitAndInstall never throws: a failed install arrives as this event.
        this.installError = error;
        this.log.error('update install failed', { error: String(error) });
        return;
      }
      if (!this.enabled) return;
      this.fail(error);
    });
  }

  get status(): UpdateStatus {
    return this.current;
  }

  /** At launch: with the switch on, the first check comes 30 s later. */
  start(enabled: boolean): void {
    this.apply(enabled, false);
  }

  /** The switch changed mid-run: on checks at once, off clears everything. */
  setEnabled(on: boolean): void {
    this.apply(on, true);
  }

  /** `{ok: true}` once the check has finished with no error. */
  checkNow(): Promise<Saved> {
    if (!this.enabled) return Promise.resolve({ ok: false, error: t('update.off') });
    if (this.inFlight) return this.inFlight;
    // A downloaded or downloading update is not looked for again.
    if (this.current.state === 'ready' || this.current.state === 'downloading') {
      return Promise.resolve({ ok: true });
    }
    const run = this.runCheck().finally(() => {
      this.inFlight = null;
    });
    this.inFlight = run;
    return run;
  }

  /** Only in state `ready`. `beforeInstall` stops the server: the installer is
   *  spawned before electron-updater quits the app. Once an install has gone
   *  through, a later call answers `{ok: true}` and installs nothing: a second
   *  `quitAndInstall` resets electron-updater's guard, and install-on-quit
   *  would then install a second time. */
  restartToUpdate(beforeInstall: () => Promise<void>): Promise<Saved> {
    if (this.restarting) return this.restarting;
    if (this.installed) return Promise.resolve({ ok: true });
    if (this.current.state !== 'ready') return Promise.resolve({ ok: false, error: t('update.nothingReady') });
    const run = this.install(beforeInstall).finally(() => {
      this.restarting = null;
    });
    this.restarting = run;
    return run;
  }

  private async install(beforeInstall: () => Promise<void>): Promise<Saved> {
    try {
      await beforeInstall();
    } catch (error) {
      this.log.error('update install failed', { error: String(error) });
      return { ok: false, error: t('update.installFailed') };
    }
    this.installing = true;
    this.installError = null;
    try {
      this.updater.quitAndInstall(true, true);
    } catch (error) {
      this.installError = error;
      this.log.error('update install failed', { error: String(error) });
    } finally {
      this.installing = false;
    }
    if (this.installError !== null) return { ok: false, error: t('update.installFailed') };
    this.installed = true;
    return { ok: true };
  }

  /** Clears the timers; the status is left as it is. */
  dispose(): void {
    this.clearTimers();
  }

  private apply(on: boolean, immediate: boolean): void {
    if (on === this.enabled) return;
    this.enabled = on;
    this.updater.autoInstallOnAppQuit = on;
    this.updater.autoDownload = on;
    this.clearTimers();
    if (!on) {
      this.cancelDownload();
      this.set({ state: 'idle' });
      return;
    }
    const tick = () => void this.checkNow();
    this.repeatTimer = this.timers.setInterval(tick, CHECK_INTERVAL_MS);
    if (immediate) tick();
    else this.firstTimer = this.timers.setTimeout(tick, FIRST_CHECK_MS);
  }

  private cancelDownload(): void {
    const token = this.cancelToken;
    this.cancelToken = null;
    try {
      token?.cancel();
    } catch (error) {
      this.log.warn('could not cancel the download', { error: String(error) });
    }
  }

  private clearTimers(): void {
    if (this.firstTimer !== null) this.timers.clearTimeout(this.firstTimer);
    if (this.repeatTimer !== null) this.timers.clearInterval(this.repeatTimer);
    this.firstTimer = null;
    this.repeatTimer = null;
  }

  private async runCheck(): Promise<Saved> {
    this.log.info('update check started');
    this.set({ state: 'checking' });
    try {
      const result = await this.updater.checkForUpdates();
      this.cancelToken = result?.cancellationToken ?? null;
      // the `error` event already reports a failed download
      result?.downloadPromise?.catch(() => {});
    } catch (error) {
      if (this.enabled && this.current.state !== 'failed') this.fail(error);
      return { ok: false, error: this.enabled ? t('update.checkFailed') : t('update.off') };
    }
    return this.current.state === 'failed' ? { ok: false, error: t('update.checkFailed') } : { ok: true };
  }

  private fail(error: unknown): void {
    this.log.warn('update check failed', { error: String(error) });
    this.set({ state: 'failed', checkedAt: this.now().toISOString() });
  }

  private set(status: UpdateStatus): void {
    this.current = status;
    this.onStatus(status);
  }
}
