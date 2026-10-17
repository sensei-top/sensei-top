// The bridge, shell side (release plan 6, S9; D2, D4, D12, D13, D16, D18, D19):
// what the dashboard's Settings page reads and writes, mapped to the CLI that
// owns `config.toml` and to `shell.json`.
//
// - **Read.** `config --json` (no secret in it: only whether a key is set)
//   plus `doctor --json` for whether Arena's log was found rather than chosen,
//   become `ShellSettings`; the shell's own preferences become the `app` part.
// - **Write.** A change becomes one `config --set-…` run. A key travels on
//   stdin alone (`--set-key -`), never argv: any process can read another's
//   argv (D4). Nothing here writes `config.toml` itself (D2).
// - **Restart.** The server reads the Arena log, the date order, MTGO's
//   settings and the backup settings only at start, so a change to one
//   restarts it (D12) and the page reconnects: this shell never sets
//   `Saved.restart`. Diagnostic mode restarts it too (D18).
// - **Restore.** Stop the server, run `restore FILE`, start it again, reload
//   the window. Exit status 3 means the restore stopped partway with files
//   still under `.replaced` names: starting the server would create a fresh
//   database in their place, so it stays stopped and the command's stderr,
//   which names each file, is what the person sees.
// - **Updates** (S14). `app.update` is `updater.ts`'s status, handed in by
//   the main process; a change of it sends the settings again with the new
//   `app` part alone. The "Check for updates" switch is handed to the updater.
//
// - **Onboarding** (S15). `doctor --json` also supplies Detailed Logs, the MTGO
//   folder it finds and the rules-text count; `recheck` reads everything
//   again, `firstData` streams `cards --scryfall --progress` (outside the
//   queue: a save must not wait minutes behind it), parsing its JSON lines
//   into `progress` and forwarding the other lines as `line`;
//   `finishOnboarding` writes `onboarded`.
//
// `bridge.ts` in the dashboard is the other half of the contract. The types
// are repeated here because `desktop/` cannot import from `web/`.
//
// Electron-free: vitest imports it directly. The main process hands in what
// needs Electron (the server, dialogs, the window) as `SettingsDeps`.

import { t } from './i18n';
import type { Logger } from './log';
import { silent } from './log';
import type { LanguageChoice, Play, ShellJson } from './store';
import type { UpdateStatus } from './updater';

export type DetailedLogs = 'enabled' | 'disabled' | 'unknown';
export type DateOrder = 'auto' | 'mdy' | 'dmy';
export type KeyName = 'claude' | 'topdeck';
export type Saved = { ok: true; restart?: boolean } | { ok: false; error: string };
export type Deleted = { ok: true; count: number } | { ok: false; error: string };

export type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends readonly unknown[] ? T[K] : T[K] extends object ? DeepPartial<T[K]> : T[K];
};

export type ShellSettings = {
  sources: {
    /** `detailedLogs` is `unknown` when doctor could not be read; read-only, as is `mtgoFound`. */
    arenaLog: { path: string | null; found: boolean; detailedLogs: DetailedLogs };
    dateOrder: DateOrder;
    mtgoHandle: string | null;
    mtgoDir: string | null;
    mtgoDeckDir: string | null;
    /** The folder doctor found MTGO writing to (Windows only), else `null`. */
    mtgoFound: string | null;
    dataDir: string;
  };
  writing: {
    claudeKey: boolean;
    topdeckKey: boolean;
    model: string;
    models: { value: string; label: string }[];
  };
  backup: {
    dir: string;
    keep: number;
    last: { at: string; ok: boolean; bytes: number | null } | null;
    inFolder: number;
  };
  /** Plan 10's; this shell offers none. */
  sharing: null;
};

/** One `cards --progress` event (S17b): bytes read of the total (null when
 *  unknown) while downloading, then the save stage. */
export type FirstDataProgress = { stage: 'download'; done: number; total: number | null } | { stage: 'save' };

/** Where `cards --scryfall` stands (S15, D21). */
export type FirstData =
  | { state: 'idle' }
  | { state: 'running'; line: string | null; progress?: FirstDataProgress }
  | { state: 'done'; line: string }
  | { state: 'failed'; error: string };

/** A `{"progress": {...}}` line from `cards --progress`, or null for any other line. */
export function parseProgress(line: string): FirstDataProgress | null {
  if (!line.startsWith('{')) return null;
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    return null;
  }
  const inner = (value as { progress?: unknown } | null)?.progress;
  if (typeof inner !== 'object' || inner === null) return null;
  const event = inner as { stage?: unknown; done?: unknown; total?: unknown };
  if (event.stage === 'save') return { stage: 'save' };
  if (event.stage !== 'download' || typeof event.done !== 'number') return null;
  return { stage: 'download', done: event.done, total: typeof event.total === 'number' ? event.total : null };
}

/** The settings `ShellSettings` lacks (S9): the shell's own. */
export type AppSettings = {
  startWithSystem: boolean;
  /** Linux only (D13); the page hides it elsewhere. */
  keepRunningOnClose: boolean;
  checkForUpdates: boolean;
  diagnostic: boolean;
  /** shell.json's `language`; `'system'` when unset. */
  language: LanguageChoice;
  /** shell.json's `plays`; both when unset. */
  plays: Play[];
  /** Where the shell's own update stands (S14). */
  update: UpdateStatus;
  /** shell.json's `onboarded` (S15): the shell opens `/welcome` until it is true. */
  onboarded: boolean;
  /** Whether onboarding's last step asks about starting with the system (D25). */
  askAutostart: boolean;
  /** Cards with rules text, from doctor; `null` when unknown. */
  rulesText: number | null;
  firstData: FirstData;
  version: string;
  platform: string;
};

/** An app-setting change the page can send. */
export type AppChange = Partial<Pick<AppSettings, 'startWithSystem' | 'keepRunningOnClose' | 'checkForUpdates' | 'diagnostic' | 'language' | 'plays'>>;

/** What `window.senseiTopShell.initial` holds, and what a change sends. */
export type BridgeSettings = ShellSettings & { app: AppSettings };

/** The IPC channels. The preload script repeats them (a sandboxed preload
 *  cannot require this file); a test keeps the two lists equal. */
export const CHANNELS = {
  initial: 'sensei-top:initial',
  save: 'sensei-top:save',
  setKey: 'sensei-top:set-key',
  pickFolder: 'sensei-top:pick-folder',
  pickFile: 'sensei-top:pick-file',
  backUpNow: 'sensei-top:back-up-now',
  restoreFrom: 'sensei-top:restore-from',
  appSet: 'sensei-top:app-set',
  appCheckForUpdates: 'sensei-top:app-check-for-updates',
  appRestartToUpdate: 'sensei-top:app-restart-to-update',
  appShowLogs: 'sensei-top:app-show-logs',
  appShowDataFolder: 'sensei-top:app-show-data-folder',
  appExportDiagnostics: 'sensei-top:app-export-diagnostics',
  appRecheck: 'sensei-top:app-recheck',
  appFirstData: 'sensei-top:app-first-data',
  appFinishOnboarding: 'sensei-top:app-finish-onboarding',
  changed: 'sensei-top:changed',
} as const;

// ---- reading -------------------------------------------------------------

export interface ConfigJson {
  arena: { log: string | null; dateOrder: DateOrder };
  mtgo: { handle: string | null; dir: string | null; deckDir: string | null };
  backup: { dir: string; keep: number };
  claude: { keySet: boolean; model: string };
  topdeck: { keySet: boolean };
  models: { value: string; label: string }[];
}

function record(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`config --json: ${what} is not an object`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, what: string): string {
  if (typeof value !== 'string') throw new Error(`config --json: ${what} is not a string`);
  return value;
}

function textOrNull(value: unknown, what: string): string | null {
  if (value === null || value === undefined) return null;
  return text(value, what);
}

function flag(value: unknown, what: string): boolean {
  if (typeof value !== 'boolean') throw new Error(`config --json: ${what} is not a boolean`);
  return value;
}

/** `config --json`'s output as the fields the page shows. Throws on a shape
 *  it does not know: a guess would put a wrong value on a settings page. */
export function parseConfigJson(output: string): ConfigJson {
  const root = record(JSON.parse(output), 'the output');
  const arena = record(root.arena, 'arena');
  const mtgo = record(root.mtgo, 'mtgo');
  const backup = record(root.backup, 'backup');
  const claude = record(root.claude, 'claude');
  const topdeck = record(root.topdeck, 'topdeck');
  const dateOrder = text(arena.date_order, 'arena.date_order');
  if (dateOrder !== 'auto' && dateOrder !== 'mdy' && dateOrder !== 'dmy') {
    throw new Error('config --json: arena.date_order is not auto, mdy or dmy');
  }
  const keep = backup.keep;
  if (typeof keep !== 'number' || !Number.isInteger(keep)) throw new Error('config --json: backup.keep is not an integer');
  if (!Array.isArray(root.models)) throw new Error('config --json: models is not a list');
  return {
    arena: { log: textOrNull(arena.log, 'arena.log'), dateOrder },
    mtgo: { handle: textOrNull(mtgo.handle, 'mtgo.handle'), dir: textOrNull(mtgo.dir, 'mtgo.dir'), deckDir: textOrNull(mtgo.deck_dir, 'mtgo.deck_dir') },
    backup: { dir: text(backup.dir, 'backup.dir'), keep },
    claude: { keySet: flag(claude.key_set, 'claude.key_set'), model: text(claude.model, 'claude.model') },
    topdeck: { keySet: flag(topdeck.key_set, 'topdeck.key_set') },
    models: root.models.map((item, index) => {
      const model = record(item, `models[${index}]`);
      return { value: text(model.value, 'model value'), label: text(model.label, 'model label') };
    }),
  };
}

export interface DoctorArena {
  path: string | null;
  /** `flag`, `environment`, `config`, `autodetect` or `none` (D15). */
  source: string;
  detailedLogs: DetailedLogs;
  /** `mtgo.discovered`: the folder found, `null` when none or off Windows. */
  mtgoFound: string | null;
  /** `cards.rules_text`: `null` when the database could not say. */
  rulesText: number | null;
}

/** The parts of `doctor --json` the shell reads. The path and the source are
 *  required; a missing or unrecognised Detailed Logs, MTGO folder or count
 *  reads as `unknown`/`null`, never a guess (rule 4). `oddField` hears the
 *  name (never the value) of a field that is present, not null and wrong. */
export function parseDoctorArena(output: string, oddField?: (field: string) => void): DoctorArena {
  const root = record(JSON.parse(output), 'the output');
  const arena = record(root.arena_log, 'arena_log');
  const detailed = arena.detailed_logs;
  const mtgo = typeof root.mtgo === 'object' && root.mtgo !== null && !Array.isArray(root.mtgo) ? (root.mtgo as Record<string, unknown>) : {};
  const cards = typeof root.cards === 'object' && root.cards !== null && !Array.isArray(root.cards) ? (root.cards as Record<string, unknown>) : {};
  const rules = cards.rules_text;
  if (detailed !== undefined && detailed !== null && !['enabled', 'disabled', 'unknown'].includes(String(detailed))) oddField?.('arena_log.detailed_logs');
  else if (detailed !== undefined && detailed !== null && typeof detailed !== 'string') oddField?.('arena_log.detailed_logs');
  if (mtgo.discovered !== undefined && mtgo.discovered !== null && typeof mtgo.discovered !== 'string') oddField?.('mtgo.discovered');
  if (rules !== undefined && rules !== null && !(typeof rules === 'number' && Number.isInteger(rules))) oddField?.('cards.rules_text');
  return {
    path: textOrNull(arena.path, 'arena_log.path'),
    source: text(arena.source, 'arena_log.source'),
    detailedLogs: detailed === 'enabled' || detailed === 'disabled' ? detailed : 'unknown',
    mtgoFound: typeof mtgo.discovered === 'string' ? mtgo.discovered : null,
    rulesText: typeof rules === 'number' && Number.isInteger(rules) ? rules : null,
  };
}

export interface Extras {
  dataDir: string;
  backupInFolder: number;
  lastBackup: ShellSettings['backup']['last'];
}

/** `found` means the shell found the log where the game writes it and
 *  nobody chose the path. */
export function toShellSettings(config: ConfigJson, doctor: DoctorArena | null, extras: Extras): ShellSettings {
  return {
    sources: {
      // `found`: nobody chose the path, so a configured `[arena] log` is never "found".
      arenaLog: { path: doctor?.path ?? config.arena.log, found: config.arena.log === null && doctor?.source === 'autodetect', detailedLogs: doctor?.detailedLogs ?? 'unknown' },
      dateOrder: config.arena.dateOrder,
      mtgoHandle: config.mtgo.handle,
      mtgoDir: config.mtgo.dir,
      mtgoDeckDir: config.mtgo.deckDir,
      mtgoFound: doctor?.mtgoFound ?? null,
      dataDir: extras.dataDir,
    },
    writing: {
      claudeKey: config.claude.keySet,
      topdeckKey: config.topdeck.keySet,
      model: config.claude.model,
      models: config.models,
    },
    backup: {
      dir: config.backup.dir,
      keep: config.backup.keep,
      last: extras.lastBackup,
      inFolder: extras.backupInFolder,
    },
    sharing: null,
  };
}

/** D25: no install wizard asked, so onboarding asks: the AppImage and
 *  anything on Linux, and the Store build (`process.windowsStore`). */
export function asksAutostart(platform: string, windowsStore: boolean): boolean {
  return platform === 'linux' || windowsStore;
}

export function toAppSettings(
  prefs: Readonly<ShellJson>,
  info: {
    version: string;
    platform: string;
    update: UpdateStatus;
    askAutostart: boolean;
    rulesText: number | null;
    firstData: FirstData;
  },
): AppSettings {
  return {
    startWithSystem: prefs.autostart ?? false,
    keepRunningOnClose: prefs.keepRunningOnClose ?? false,
    checkForUpdates: prefs.checkForUpdates ?? true,
    diagnostic: prefs.diagnostic ?? false,
    language: prefs.language ?? 'system',
    plays: prefs.plays ?? ['arena', 'mtgo'],
    update: info.update,
    onboarded: prefs.onboarded ?? false,
    askAutostart: info.askAutostart,
    rulesText: info.rulesText,
    firstData: info.firstData,
    version: info.version,
    platform: info.platform,
  };
}

// ---- writing -------------------------------------------------------------

export interface PlannedChange {
  /** One `config` run's arguments, `config` first; `null` when nothing goes to the CLI. */
  args: string[] | null;
  /** Whether the server must start again for the change to apply (D12). */
  restart: boolean;
}

const DATE_ORDERS: readonly string[] = ['auto', 'mdy', 'dmy'];

/** A `ShellSettings` change as the `config` flags that write it. An empty
 *  value clears a setting, so `null` becomes `""`. Keys have no path here:
 *  `writing.claudeKey` and `topdeckKey` are read-only, a key is set by
 *  `keyCommand` alone; `dataDir` cannot be changed (D9). Throws on a value
 *  the CLI would refuse anyway, naming nothing the person typed. */
export function planChange(change: DeepPartial<ShellSettings>): PlannedChange {
  const args: string[] = ['config'];
  let restart = false;
  const sources = change.sources;
  if (sources) {
    if (sources.arenaLog && sources.arenaLog.path !== undefined) {
      args.push('--set-arena-log', sources.arenaLog.path ?? '');
      restart = true;
    }
    if (sources.dateOrder !== undefined) {
      if (!DATE_ORDERS.includes(sources.dateOrder)) throw new Error(t('settings.dateOrder'));
      args.push('--set-date-order', sources.dateOrder);
      restart = true;
    }
    if (sources.mtgoHandle !== undefined) {
      args.push('--set-mtgo-handle', sources.mtgoHandle ?? '');
      restart = true;
    }
    if (sources.mtgoDir !== undefined) {
      args.push('--set-mtgo-dir', sources.mtgoDir ?? '');
      restart = true;
    }
    if (sources.mtgoDeckDir !== undefined) {
      args.push('--set-mtgo-deck-dir', sources.mtgoDeckDir ?? '');
      restart = true;
    }
  }
  if (change.writing?.model !== undefined) args.push('--set-model', change.writing.model);
  const backup = change.backup;
  if (backup) {
    if (backup.dir !== undefined) {
      args.push('--set-backup-dir', backup.dir);
      restart = true;
    }
    if (backup.keep !== undefined) {
      if (!Number.isInteger(backup.keep) || backup.keep < 1) throw new Error(t('settings.backupKeep'));
      args.push('--set-backup-keep', String(backup.keep));
      restart = true;
    }
  }
  return { args: args.length > 1 ? args : null, restart };
}

export interface KeyCommand {
  args: string[];
  /** The key, for the child's stdin; absent when clearing. */
  stdin?: string;
}

/** D4: a key goes in on stdin (`-`), so it is never in any argv. */
export function keyCommand(which: KeyName, key: string | null): KeyCommand {
  const flagName = which === 'claude' ? 'key' : 'topdeck-key';
  if (key === null) return { args: ['config', `--clear-${flagName}`] };
  const trimmed = key.trim();
  if (trimmed === '' || /[\r\n]/.test(trimmed)) throw new Error(t('settings.notAKey'));
  return { args: ['config', `--set-${flagName}`, '-'], stdin: trimmed + '\n' };
}

/** Which of an app-setting change reach `shell.json`, and whether the server
 *  restarts (only diagnostic mode, D18), when its value changed. */
export function planAppChange(
  current: AppSettings,
  change: AppChange,
): { patch: Partial<ShellJson>; restart: boolean } {
  const patch: Partial<ShellJson> = {};
  if (change.startWithSystem !== undefined) patch.autostart = change.startWithSystem;
  if (change.keepRunningOnClose !== undefined) patch.keepRunningOnClose = change.keepRunningOnClose;
  if (change.checkForUpdates !== undefined) patch.checkForUpdates = change.checkForUpdates;
  if (change.diagnostic !== undefined) patch.diagnostic = change.diagnostic;
  if (change.language !== undefined) patch.language = change.language;
  if (change.plays !== undefined) patch.plays = change.plays;
  return { patch, restart: change.diagnostic !== undefined && change.diagnostic !== current.diagnostic };
}

export interface RestoreOutcome {
  restartServer: boolean;
  saved: Saved;
}

/** What `restore FILE` ending with `code` means for the server and the
 *  page. 0: done. 1: a refusal, nothing changed, the server may start.
 *  3: stopped partway, files still under `.replaced` names; the server must
 *  stay stopped. Any other status is unknown, so the server stays stopped
 *  too. `code` is `null` when the command could not be run at all, which
 *  changed nothing. */
export function interpretRestore(code: number | null | 'not-run', stderr: string): RestoreOutcome {
  const message = stderr.trim();
  if (code === 0) return { restartServer: true, saved: { ok: true } };
  if (code === 1) return { restartServer: true, saved: { ok: false, error: message || t('restore.refused') } };
  if (code === 'not-run') return { restartServer: true, saved: { ok: false, error: t('restore.notStarted') } };
  if (code === 3) return { restartServer: false, saved: { ok: false, error: message || t('restore.partway') } };
  return {
    restartServer: false,
    saved: { ok: false, error: message || (code === null ? t('restore.noStatus') : t('restore.status', { code })) },
  };
}

/** The size of a backup, from `backup`'s `  Backup:    N bytes…` line. */
export function parseBackupBytes(output: string): number | null {
  const match = /^\s*Backup:\s+([\d,]+) bytes/m.exec(output);
  if (!match || !match[1]) return null;
  return Number(match[1].replace(/,/g, ''));
}

/** The whole of a failed run's message, as `interpretRestore` shows it. */
export function wholeMessage(stderr: string, fallback: string): string {
  return stderr.trim() || fallback;
}

/** A sentence for a failed run: the last non-empty line of stderr. */
export function failureSentence(stderr: string, fallback: string): string {
  const lines = stderr.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return lines[lines.length - 1] ?? fallback;
}

/** An IPC message is answered only when it comes from the dashboard's own
 *  origin on the running server's port. */
export function trustedSender(url: string, port: number | null): boolean {
  if (port === null) return false;
  try {
    return new URL(url).origin === `http://127.0.0.1:${port}`;
  } catch {
    return false;
  }
}

// ---- diagnostics (D16) ---------------------------------------------------

/** The arguments of the run that writes the zip. `Player.log` goes in only
 *  when its box was ticked. */
export function diagnosticsArgs(options: { out: string; shellLog: string; withPlayerLog: boolean }): string[] {
  return [
    'diagnostics',
    '--out', options.out,
    '--shell-log', options.shellLog,
    ...(options.withPlayerLog ? ['--with-player-log'] : []),
  ];
}

/** `diagnostics --list`'s `name<TAB>bytes` lines as lines for a dialog. */
export function formatListing(output: string): string {
  return output
    .split(/\r?\n/)
    .filter((line) => line.trim() !== '')
    .map((line) => {
      const [name, size] = line.split('\t');
      return size === undefined ? line : `${name} (${size} bytes)`;
    })
    .join('\n');
}

// ---- a restore that stopped partway (D19) --------------------------------

/** The files a restore left under `.replaced` names when the live database
 *  is gone: starting the server then would create a fresh database in its
 *  place. Empty when the database is there (a finished restore keeps
 *  `<db>.replaced` beside it, which blocks nothing). `entries` are the names
 *  in the database's folder.
 *
 *  Earlier, finished restores leave their own sets, so only the newest is
 *  returned: `restore.py` picks the first of `.replaced`, `.replaced.1`,
 *  `.replaced.2`... that no sidecar has, so the stopped restore's set carries
 *  the highest suffix. Each entry reads `<file> → <original name>`. */
export function restoreLeftovers(dbName: string, dbExists: boolean, entries: readonly string[]): string[] {
  if (dbExists) return [];
  const escaped = dbName.replace(/[.*+?^$|()[\]{}\\]/g, '\\$&');
  const pattern = new RegExp(`^(${escaped}(?:-wal|-shm)?)\\.replaced(?:\\.(\\d+))?$`);
  const found: Array<{ name: string; original: string; n: number }> = [];
  for (const name of entries) {
    const match = pattern.exec(name);
    if (match?.[1]) found.push({ name, original: match[1], n: match[2] ? Number(match[2]) : 0 });
  }
  if (found.length === 0) return [];
  const newest = Math.max(...found.map((item) => item.n));
  return found
    .filter((item) => item.n === newest)
    .map((item) => `${item.name} \u2192 ${item.original}`)
    .sort();
}

export function restoreLeftoversMessage(files: readonly string[]): string {
  return t('restore.leftovers', { files: files.join(', ') });
}

/** The `name -> name` lines of `restore`'s stderr, and only those: they hold
 *  file names, where other lines can carry a full path. */
export function filePairLines(stderr: string): string[] {
  return stderr
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => /^[^\s/\\]+ -> [^\s/\\]+$/.test(line));
}

// ---- the service ---------------------------------------------------------

export interface SettingsDeps {
  /** `sensei-top --db <db> ...args`; rejects with a `RunError` (`code`, `stderr`) on a non-zero exit. */
  run(args: readonly string[], options?: { stdin?: string; onLine?: (line: string) => void; signal?: AbortSignal }): Promise<string>;
  stopServer(): Promise<void>;
  /** Starts the server and resolves once it is ready or has failed. */
  startServer(): Promise<void>;
  reloadWindow(): void;
  store: { get(): Readonly<ShellJson>; update(patch: Partial<ShellJson>): boolean };
  dataDir: string;
  version: string;
  platform: string;
  /** `asksAutostart(process.platform, process.windowsStore === true)`. */
  askAutostart: boolean;
  /** How many backups the folder holds. */
  countBackups(dir: string): number;
  /** The newest `<db>.backup` slot in `dir`: its modification time (ISO) and size. */
  newestBackup(dir: string): { at: string; bytes: number } | null;
  now(): Date;
  applyAutostart?(on: boolean): void;
  setDiagnostic?(on: boolean): void;
  /** The language choice changed: the shell's own text follows it. */
  setLanguage?(choice: LanguageChoice): void;
  /** Where the shell's own update stands now. */
  updateStatus(): UpdateStatus;
  /** The "Check for updates" switch changed: the updater follows it. */
  setUpdateChecks?(on: boolean): void;
  pickFolder(): Promise<string | null>;
  pickFile(): Promise<string | null>;
  showLogs(): void;
  /** `shell.openPath` on the data folder: its error string, `''` when it opened. */
  openDataFolder(): Promise<string>;
  /** Sent whenever the settings changed. */
  changed(settings: BridgeSettings): void;
  log?: Logger;
}

/** Everything the page can ask of the shell. One operation at a time. */
export class SettingsService {
  private readonly log: Logger;
  private cache: BridgeSettings | null = null;
  private lastBackup: ShellSettings['backup']['last'] = null;
  private queue: Promise<unknown> = Promise.resolve();
  private doctor: DoctorArena | null = null;
  private firstDataState: FirstData = { state: 'idle' };
  private firstDataAbort: AbortController | null = null;
  private firstDataRun: Promise<Saved> | null = null;
  /** The abort in flight is a restore's, not the user's. */
  private quietAbort = false;
  /** Restores asked for and not yet finished; no download starts while any is. */
  private pendingRestores = 0;

  constructor(private readonly deps: SettingsDeps) {
    this.log = deps.log ?? silent;
  }

  /** The last settings read, `null` before the first read or when it failed. */
  get current(): BridgeSettings | null {
    return this.cache;
  }

  /** Reads `config --json` and `doctor --json` again. `null` (and a warning)
   *  when the config could not be read: the page then draws what the API
   *  alone can say. A failed doctor only costs `found`. */
  async refresh(): Promise<BridgeSettings | null> {
    try {
      const config = parseConfigJson(await this.deps.run(['config', '--json']));
      let doctor: DoctorArena | null = null;
      try {
        doctor = parseDoctorArena(await this.deps.run(['doctor', '--json']), (field) =>
          this.log.warn('doctor --json has an unexpected value', { field }),
        );
      } catch (error) {
        this.log.warn('doctor --json could not be read', { error: String(error) });
      }
      this.doctor = doctor;
      const settings = toShellSettings(config, doctor, {
        dataDir: this.deps.dataDir,
        backupInFolder: this.deps.countBackups(config.backup.dir),
        lastBackup: this.lastTried(config.backup.dir),
      });
      this.cache = { ...settings, app: this.appSettings() };
    } catch (error) {
      this.log.warn('settings could not be read', { error: String(error) });
      this.cache = null;
      // A count from before this read describes a database that may be gone.
      this.doctor = null;
    }
    return this.cache;
  }

  /** A backup tried this session wins when it is newer than the newest slot
   *  on disk; a slot only appears after a verified copy, so it counts as ok. */
  private lastTried(dir: string): ShellSettings['backup']['last'] {
    const slot = this.deps.newestBackup(dir);
    const onDisk = slot ? { at: slot.at, ok: true, bytes: slot.bytes } : null;
    if (!this.lastBackup) return onDisk;
    if (!onDisk) return this.lastBackup;
    return this.lastBackup.at >= onDisk.at ? this.lastBackup : onDisk;
  }

  private appSettings(): AppSettings {
    return toAppSettings(this.deps.store.get(), {
      version: this.deps.version,
      platform: this.deps.platform,
      update: this.deps.updateStatus(),
      askAutostart: this.deps.askAutostart,
      rulesText: this.doctor?.rulesText ?? null,
      firstData: this.firstDataState,
    });
  }

  /** The update status changed: the page gets the settings it has with the
   *  new `app` part. Nothing is read again, and nothing is sent before the
   *  first read succeeded. */
  updateChanged(): void {
    if (!this.cache) return;
    this.cache = { ...this.cache, app: this.appSettings() };
    this.deps.changed(this.cache);
  }

  private serial<T>(work: () => Promise<T>): Promise<T> {
    const next = this.queue.then(work, work);
    this.queue = next.catch(() => undefined);
    return next;
  }

  private async publish(): Promise<void> {
    const settings = await this.refresh();
    if (settings) this.deps.changed(settings);
  }

  private async restartServer(reason: string): Promise<void> {
    this.log.info('restarting the server for a setting', { reason });
    await this.deps.stopServer();
    await this.deps.startServer();
  }

  save(change: DeepPartial<ShellSettings>): Promise<Saved> {
    return this.serial(async () => {
      let plan: PlannedChange;
      try {
        plan = planChange(change);
      } catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : t('settings.cannotSave') };
      }
      if (plan.args) {
        try {
          await this.deps.run(plan.args);
        } catch (error) {
          return { ok: false, error: failureSentence(errorStderr(error), t('settings.notSaved')) };
        }
        if (plan.restart) await this.restartServer('a setting the server reads at start');
      }
      await this.publish();
      return { ok: true };
    });
  }

  setKey(which: KeyName, key: string | null): Promise<Saved> {
    return this.serial(async () => {
      let command: KeyCommand;
      try {
        command = keyCommand(which, key);
      } catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : t('settings.notAKey') };
      }
      try {
        await this.deps.run(command.args, command.stdin === undefined ? {} : { stdin: command.stdin });
      } catch (error) {
        return { ok: false, error: failureSentence(errorStderr(error), t('settings.keyNotSaved')) };
      }
      await this.publish();
      return { ok: true };
    });
  }

  setApp(change: AppChange): Promise<Saved> {
    return this.serial(async () => {
      const { patch, restart } = planAppChange(this.appSettings(), change);
      if (!this.deps.store.update(patch)) {
        return { ok: false, error: t('settings.notSaved') };
      }
      if (patch.autostart !== undefined) this.deps.applyAutostart?.(patch.autostart);
      if (patch.diagnostic !== undefined) this.deps.setDiagnostic?.(patch.diagnostic);
      if (patch.language !== undefined) this.deps.setLanguage?.(patch.language);
      if (patch.checkForUpdates !== undefined) this.deps.setUpdateChecks?.(patch.checkForUpdates);
      if (restart) await this.restartServer('diagnostic mode changed');
      await this.publish();
      return { ok: true };
    });
  }

  backUpNow(): Promise<Saved> {
    return this.serial(async () => {
      const at = this.deps.now().toISOString();
      let output: string;
      try {
        output = await this.deps.run(['backup', '--force']);
      } catch (error) {
        this.lastBackup = { at, ok: false, bytes: null };
        await this.publish();
        return { ok: false, error: wholeMessage(errorStderr(error), t('backup.failed')) };
      }
      const bytes = parseBackupBytes(output);
      if (bytes === null) {
        // Exit 0 without a copy: another backup is running. Nothing was made.
        return { ok: false, error: failureSentence(output, t('backup.none')) };
      }
      this.lastBackup = { at, ok: true, bytes };
      await this.publish();
      return { ok: true };
    });
  }

  async restoreFrom(file: string): Promise<Saved> {
    // D5: no download runs while a restore does. Counted before any await, so
    // nothing queued ahead of this restore starts a download behind its back.
    this.pendingRestores += 1;
    let restarted = false;
    try {
      await this.stopDownloadForRestore();
      return await this.serial(async () => {
        await this.deps.stopServer();
        let code: number | null | 'not-run' = 0;
        let stderr = '';
        try {
          await this.deps.run(['restore', file]);
        } catch (error) {
          const shaped = errorShape(error);
          if (shaped) ({ code, stderr } = shaped);
          else code = 'not-run';
        }
        const outcome = interpretRestore(code, stderr);
        if (!outcome.restartServer) {
          this.log.error('restore ended partway; the server stays stopped', { code, files: filePairLines(stderr) });
          return outcome.saved;
        }
        await this.deps.startServer();
        restarted = true;
        // A finished or failed download described the database just replaced.
        if (outcome.saved.ok && this.firstDataState.state !== 'idle' && this.firstDataState.state !== 'running') {
          this.setFirstData({ state: 'idle' });
        }
        await this.publish();
        if (outcome.saved.ok) this.deps.reloadWindow();
        return outcome.saved;
      });
    } finally {
      this.pendingRestores -= 1;
      // D5 again, against the restored database; the publish above has just read it.
      if (restarted) this.startIfNoCards();
    }
  }

  private async stopDownloadForRestore(): Promise<void> {
    if (!this.firstDataRun) return;
    this.quietAbort = true;
    this.firstDataAbort?.abort();
    await this.firstDataRun;
    this.quietAbort = false;
  }

  /** Reads the config and doctor again and sends the result (the Arena
   *  step's "Check again"). */
  recheck(): Promise<Saved> {
    return this.serial(async () => {
      const settings = await this.refresh();
      if (!settings) return { ok: false, error: t('settings.notRead') };
      this.deps.changed(settings);
      return { ok: true };
    });
  }

  /** Runs `cards --scryfall --progress`, sending each progress line as it arrives, except
   *  one naming the database (the data folder, where `--db` points). Outside the queue:
   *  it takes minutes and a save must not wait behind it. A second call
   *  while one runs is refused. No timeout; the state is the shell's, so
   *  leaving the page does not stop it. */
  async firstData(): Promise<Saved> {
    if (this.firstDataState.state === 'running') return { ok: false, error: t('cards.alreadyRunning') };
    if (this.pendingRestores > 0) return { ok: false, error: t('cards.restoreRunning') };
    const run = this.runFirstData();
    this.firstDataRun = run;
    try {
      return await run;
    } finally {
      if (this.firstDataRun === run) this.firstDataRun = null;
    }
  }

  private async runFirstData(): Promise<Saved> {
    this.setFirstData({ state: 'running', line: null });
    const controller = new AbortController();
    this.firstDataAbort = controller;
    let last = '';
    let progress: FirstDataProgress | undefined;
    try {
      await this.deps.run(['cards', '--scryfall', '--progress'], {
        signal: controller.signal,
        onLine: (line) => {
          if (controller.signal.aborted) return;
          const trimmed = line.trim();
          if (!trimmed) return;
          const event = parseProgress(trimmed);
          if (event) {
            progress = event;
            const shown = this.firstDataState;
            this.setFirstData({
              state: 'running',
              line: shown.state === 'running' ? shown.line : null,
              progress: event,
            });
            return;
          }
          last = trimmed;
          // The CLI's closing line names the database's full path (in the data folder).
          if (trimmed.includes(this.deps.dataDir)) return;
          this.setFirstData({ state: 'running', line: trimmed, ...(progress && { progress }) });
        },
      });
    } catch (error) {
      if (controller.signal.aborted && this.quietAbort) {
        // Stopped for a restore: the page shows no error.
        this.quietAbort = false;
        this.firstDataAbort = null;
        this.setFirstData({ state: 'idle' });
        return { ok: false, error: t('cards.stopped') };
      }
      const message = controller.signal.aborted
        ? t('cards.stopped')
        : failureSentence(errorStderr(error), t('cards.noReason'));
      this.firstDataAbort = null;
      this.log.warn('the first-data download failed', { error: String(error) });
      this.setFirstData({ state: 'failed', error: message });
      return { ok: false, error: message };
    }
    this.firstDataAbort = null;
    this.setFirstData({ state: 'done', line: last });
    // The refresh sends the settings, with the new rules-text count.
    await this.serial(() => this.publish());
    return { ok: true };
  }

  /** D5: starts the card-data download when doctor counted zero cards with rules
   *  text (`null` is unknown, not zero) and none is running or finished. */
  async startFirstDataIfMissing(): Promise<void> {
    // The launch's first doctor run starts before `serve` creates the database,
    // so an unknown count is read again before deciding.
    if (this.doctor?.rulesText == null) await this.serial(() => this.publish());
    this.startIfNoCards();
  }

  private startIfNoCards(): void {
    if (this.pendingRestores > 0) return;
    if (this.doctor?.rulesText !== 0 || this.firstDataState.state !== 'idle') return;
    this.log.info('no card data yet; starting the download on its own');
    void this.firstData();
  }

  /** The app is quitting: a running download ends as `failed`. */
  stopFirstData(): void {
    this.firstDataAbort?.abort();
  }

  private setFirstData(state: FirstData): void {
    this.firstDataState = state;
    this.updateChanged();
  }

  finishOnboarding(): Promise<Saved> {
    return this.serial(async () => {
      if (!this.deps.store.update({ onboarded: true })) return { ok: false, error: t('settings.notSaved') };
      await this.publish();
      return { ok: true };
    });
  }

  pickFolder(): Promise<string | null> {
    return this.deps.pickFolder();
  }

  pickFile(): Promise<string | null> {
    return this.deps.pickFile();
  }

  showLogs(): void {
    this.deps.showLogs();
  }

  /** Opens the data folder in the system's file manager. The error itself
   *  goes to the log; the page gets a sentence. */
  async showDataFolder(): Promise<Saved> {
    let error: string;
    try {
      error = await this.deps.openDataFolder();
    } catch (thrown) {
      error = String(thrown);
    }
    if (!error) return { ok: true };
    this.log.warn('could not open the data folder', { error });
    return { ok: false, error: t('settings.folderNotOpened') };
  }
}

/** `server.ts`'s `RunError`: a non-zero exit, with its status and stderr. */
function errorShape(error: unknown): { code: number | null; stderr: string } | null {
  if (typeof error !== 'object' || error === null) return null;
  const { code, stderr } = error as { code?: unknown; stderr?: unknown };
  if (typeof stderr !== 'string') return null;
  if (code !== null && typeof code !== 'number') return null;
  return { code: code ?? null, stderr };
}

function errorStderr(error: unknown): string {
  return errorShape(error)?.stderr ?? '';
}
