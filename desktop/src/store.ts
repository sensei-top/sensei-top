// `shell.json` (release plan 6, D2): the shell's own preferences, in Electron's
// userData directory. The server never reads it; `config.toml` stays the
// Python CLI's alone. Read once at launch, written whole and atomically (a
// temporary file, flushed, then renamed over the old one), so a crash or a
// SIGKILL mid-write leaves the previous file, never half of one.
//
// Parsing is lenient by key: a value of the wrong type is dropped with a
// warning and the rest kept, and keys this version does not know are carried
// through every write untouched, so a newer shell's settings survive an older
// one. A file that is not JSON at all is moved aside as `shell.json.bad`, and
// the shell starts from no preferences.
//
// Electron-free: vitest imports it directly.

import * as fs from 'node:fs';
import * as path from 'node:path';
import { silent, type Logger } from './log';

export const STORE_NAME = 'shell.json';

export interface Bounds {
  x?: number;
  y?: number;
  width: number;
  height: number;
  maximized?: boolean;
}

/** Every key the shell knows. All optional: absent means "not chosen yet". */
export interface ShellPrefs {
  /** D5: the port asked for at every launch, re-picked only when taken. */
  port?: number;
  /** The main window's last normal bounds. */
  bounds?: Bounds;
  /** D13, Linux: keep running in the background when the window closes. */
  keepRunningOnClose?: boolean;
  /** D25: start with the system (applied by `autostart.ts`, called from `main.ts`). */
  autostart?: boolean;
  /** D24: the daily update check (a later phase); default on. */
  checkForUpdates?: boolean;
  /** D18: `serve --verbose` and a DEBUG shell log. */
  diagnostic?: boolean;
  /** D20: onboarding finished; until then the window opens `/welcome`. */
  onboarded?: boolean;
}

/** What is on disk: the known keys plus whatever else was there. */
export type ShellJson = ShellPrefs & Record<string, unknown>;

const BOOLEAN_KEYS = ['keepRunningOnClose', 'autostart', 'checkForUpdates', 'diagnostic', 'onboarded'] as const;

function isInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

export function parseBounds(value: unknown): Bounds | undefined {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return undefined;
  const raw = value as Record<string, unknown>;
  if (!isInt(raw.width) || !isInt(raw.height) || raw.width <= 0 || raw.height <= 0) return undefined;
  const bounds: Bounds = { width: raw.width, height: raw.height };
  if (isInt(raw.x) && isInt(raw.y)) {
    bounds.x = raw.x;
    bounds.y = raw.y;
  }
  if (typeof raw.maximized === 'boolean') bounds.maximized = raw.maximized;
  return bounds;
}

/** The parsed file: known keys validated, unknown keys kept, and the name of
 *  every known key whose value was dropped. */
export function parseShellJson(text: string): { prefs: ShellJson; dropped: string[] } {
  const raw: unknown = JSON.parse(text);
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new SyntaxError('shell.json is not a JSON object');
  }
  const prefs: ShellJson = { ...(raw as Record<string, unknown>) };
  const dropped: string[] = [];
  if ('port' in prefs) {
    if (!(isInt(prefs.port) && prefs.port >= 1 && prefs.port <= 65535)) {
      delete prefs.port;
      dropped.push('port');
    }
  }
  if ('bounds' in prefs) {
    const bounds = parseBounds(prefs.bounds);
    if (bounds) prefs.bounds = bounds;
    else {
      delete prefs.bounds;
      dropped.push('bounds');
    }
  }
  for (const key of BOOLEAN_KEYS) {
    if (key in prefs && typeof prefs[key] !== 'boolean') {
      delete prefs[key];
      dropped.push(key);
    }
  }
  return { prefs, dropped };
}

/** `current` with `patch` laid over it, one level deep: `bounds` is replaced
 *  whole, and a key patched to `undefined` is removed. */
export function mergePrefs(current: ShellJson, patch: Partial<ShellJson>): ShellJson {
  const next: ShellJson = { ...current };
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) delete next[key];
    else next[key] = value;
  }
  return next;
}

/** Writes `data` to `file` through a temporary file beside it. */
export function writeAtomically(file: string, data: string): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.tmp`;
  const fd = fs.openSync(temp, 'w');
  try {
    fs.writeSync(fd, data);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  try {
    fs.renameSync(temp, file);
  } catch (error) {
    fs.rmSync(temp, { force: true });
    throw error;
  }
}

export class ShellStore {
  private prefs: ShellJson;

  private constructor(
    readonly file: string,
    prefs: ShellJson,
    private readonly log: Logger,
  ) {
    this.prefs = prefs;
  }

  /** Reads `<dir>/shell.json`. Missing is empty; unreadable is empty plus a warning. */
  static load(dir: string, log: Logger = silent): ShellStore {
    const file = path.join(dir, STORE_NAME);
    let text: string;
    try {
      text = fs.readFileSync(file, 'utf8');
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
        log.warn('shell.json could not be read; starting from no preferences', { error: String(error) });
      }
      return new ShellStore(file, {}, log);
    }
    try {
      const { prefs, dropped } = parseShellJson(text);
      if (dropped.length > 0) log.warn('shell.json: values of the wrong type were ignored', { keys: dropped });
      return new ShellStore(file, prefs, log);
    } catch (error) {
      const aside = `${file}.bad`;
      try {
        fs.renameSync(file, aside);
      } catch {
        // left where it is; the next write replaces it
      }
      log.warn('shell.json is not valid JSON; moved aside, starting from no preferences', {
        aside,
        error: String(error),
      });
      return new ShellStore(file, {}, log);
    }
  }

  get(): Readonly<ShellJson> {
    return this.prefs;
  }

  /** Merges `patch` and writes the file. `false` (and a warning) when the
   *  write failed; the merged values still apply for this launch. */
  update(patch: Partial<ShellJson>): boolean {
    this.prefs = mergePrefs(this.prefs, patch);
    try {
      writeAtomically(this.file, JSON.stringify(this.prefs, null, 2) + '\n');
      return true;
    } catch (error) {
      this.log.warn('shell.json could not be written', { error: String(error) });
      return false;
    }
  }
}
