// The shell's log file (release plan 6, D17): `<data dir>/logs/shell.log`,
// beside the server's `sensei-top.log`, in the same line format as
// `src/sensei_top/logs.py`, so the two files merge by time and session id:
//
//   2026-10-06T14:03:22.418Z 3f9a1c2e WARNING shell.server: message {"field":1}
//
// UTC with milliseconds, the launch's 8-hex session id (also handed to `serve`
// in SENSEI_TOP_SESSION), the level by Python's name, the logger, the message.
// Structured detail, where there is any, follows as one JSON object. The home
// directory is written as `~` on the formatted line, by the same rule as
// `logs.py`'s `home_as_tilde` (its trap 2). Rotation is 5 files of 2 MB, done
// by this small writer, renaming the current file first (`logs.py`'s trap 3).
//
// Electron-free: vitest imports it directly.

import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

export const LOG_DIR = 'logs';
export const LOG_NAME = 'shell.log';
export const MAX_BYTES = 2 * 1024 * 1024;
export const BACKUP_COUNT = 5;

export type Level = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';

const RANK: Record<Level, number> = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40 };

export type Fields = Record<string, unknown> | unknown[];

export interface Logger {
  debug(message: string, fields?: Fields): void;
  info(message: string, fields?: Fields): void;
  warn(message: string, fields?: Fields): void;
  error(message: string, fields?: Fields): void;
}

/** A new launch's session id: 8 hex digits, as `logs.py`'s `token_hex(4)`. */
export function newSessionId(): string {
  return crypto.randomBytes(4).toString('hex');
}

/** The shell log's path inside a data directory. */
export function logPath(dataDir: string): string {
  return path.join(dataDir, LOG_DIR, LOG_NAME);
}

function escapeRegExp(text: string): string {
  // Only the syntax characters: under the `u` flag any other escape is an error.
  return text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
}

/** `home` as it may appear in a line, with no letter, digit or underscore
 *  after it to continue the name. On Windows any case and either separator,
 *  or a doubled backslash (how a JSON string or Python's `repr` writes one).
 *  `null` for a home that is a filesystem root: nothing is substituted. */
export function homePattern(home: string, windows: boolean): RegExp | null {
  if (!home) return null;
  const root = (windows ? path.win32 : path.posix).parse(home).root;
  const trimmed = home.replace(windows ? /[\\/]+$/ : /\/+$/, '');
  if (!trimmed || home === root || trimmed + (windows ? '\\' : '/') === root) return null;
  const body = windows
    ? trimmed.split(/[\\/]+/).map(escapeRegExp).join('[\\\\/]+')
    : escapeRegExp(trimmed);
  // Python's `\w` on a str pattern is Unicode: letters, numbers, underscore.
  return new RegExp(`${body}(?![\\p{L}\\p{N}_])`, windows ? 'giu' : 'gu');
}

export function homeAsTilde(text: string, pattern: RegExp | null): string {
  return pattern ? text.replace(pattern, '~') : text;
}

function pad(value: number, width: number): string {
  return String(value).padStart(width, '0');
}

/** `logs.py`'s `%(asctime)s.%(msecs)03dZ` with `%Y-%m-%dT%H:%M:%S`, in UTC. */
export function formatTime(when: Date): string {
  return (
    `${pad(when.getUTCFullYear(), 4)}-${pad(when.getUTCMonth() + 1, 2)}-${pad(when.getUTCDate(), 2)}` +
    `T${pad(when.getUTCHours(), 2)}:${pad(when.getUTCMinutes(), 2)}:${pad(when.getUTCSeconds(), 2)}` +
    `.${pad(when.getUTCMilliseconds(), 3)}Z`
  );
}

function renderFields(fields: Fields | undefined): string {
  if (fields === undefined) return '';
  try {
    return ' ' + JSON.stringify(fields, (_key, value: unknown) =>
      value instanceof Error ? { name: value.name, message: value.message, stack: value.stack } : value,
    );
  } catch {
    return ' {"fields":"unserializable"}';
  }
}

/** One log line, newline excluded, home not yet substituted. */
export function formatLine(
  when: Date,
  session: string,
  level: Level,
  name: string,
  message: string,
  fields?: Fields,
): string {
  return `${formatTime(when)} ${session} ${level} ${name}: ${message}${renderFields(fields)}`;
}

/** Appends lines to `file`, rotating it at `maxBytes` into `file.1` …
 *  `file.<backups>`. Every line is written synchronously, so a SIGKILL loses
 *  nothing already logged. A failure to open or rotate never throws: the
 *  writer goes quiet (open) or keeps appending to the current file (rotate). */
export class RotatingFile {
  private fd: number | null = null;
  private size = 0;

  constructor(
    readonly file: string,
    readonly maxBytes = MAX_BYTES,
    readonly backups = BACKUP_COUNT,
  ) {}

  /** `false` when the file cannot be opened; the caller says so once. */
  open(): boolean {
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      this.fd = fs.openSync(this.file, 'a');
      this.size = fs.fstatSync(this.fd).size;
      return true;
    } catch {
      this.fd = null;
      return false;
    }
  }

  write(line: string): void {
    if (this.fd === null) return;
    const data = Buffer.from(line + '\n', 'utf8');
    // RotatingFileHandler's test: roll over before a write that would reach the limit.
    if (this.size > 0 && this.size + data.length >= this.maxBytes) this.rotate();
    if (this.fd === null) return;
    try {
      fs.writeSync(this.fd, data);
      this.size += data.length;
    } catch {
      // A full disk or a vanished directory: the shell runs on without its log.
    }
  }

  close(): void {
    if (this.fd === null) return;
    try {
      fs.closeSync(this.fd);
    } catch {
      // already closed
    }
    this.fd = null;
  }

  /** The current file is renamed aside first, then the backups shift; a
   *  refused rename (Windows: another process holds the file) puts the
   *  current file back and appending carries on there. */
  private rotate(): void {
    this.close();
    const moving = `${this.file}.rotating`;
    try {
      fs.renameSync(this.file, moving);
      for (let index = this.backups - 1; index >= 1; index--) {
        const older = `${this.file}.${index}`;
        if (fs.existsSync(older)) fs.renameSync(older, `${this.file}.${index + 1}`);
      }
      fs.renameSync(moving, `${this.file}.1`);
    } catch {
      if (fs.existsSync(moving)) {
        try {
          fs.renameSync(moving, this.file);
        } catch {
          // left aside; the reopen below starts a fresh current file
        }
      }
    }
    this.open();
  }
}

export interface ShellLogOptions {
  session: string;
  level?: Level;
  maxBytes?: number;
  backups?: number;
  home?: string;
  windows?: boolean;
  /** Also print each line to stdout (a development run's terminal). */
  echo?: boolean;
  now?: () => Date;
}

/** The shell's one log. `child(name)` hands out a named `Logger`. */
export class ShellLog {
  readonly session: string;
  private level: Level;
  private readonly out: RotatingFile;
  private readonly home: RegExp | null;
  private readonly echo: boolean;
  private readonly now: () => Date;
  readonly opened: boolean;

  constructor(
    readonly file: string,
    options: ShellLogOptions,
  ) {
    this.session = options.session;
    this.level = options.level ?? 'INFO';
    this.out = new RotatingFile(file, options.maxBytes ?? MAX_BYTES, options.backups ?? BACKUP_COUNT);
    this.home = homePattern(options.home ?? os.homedir(), options.windows ?? process.platform === 'win32');
    this.echo = options.echo ?? false;
    this.now = options.now ?? (() => new Date());
    this.opened = this.out.open();
    if (!this.opened) {
      process.stderr.write(`WARNING not writing a log file: cannot open ${this.scrub(file)}\n`);
    }
  }

  setLevel(level: Level): void {
    this.level = level;
  }

  scrub(text: string): string {
    return homeAsTilde(text, this.home);
  }

  write(level: Level, name: string, message: string, fields?: Fields): void {
    if (RANK[level] < RANK[this.level]) return;
    const line = this.scrub(formatLine(this.now(), this.session, level, name, message, fields));
    this.out.write(line);
    if (this.echo) {
      try {
        process.stdout.write(line + '\n');
      } catch {
        // no terminal
      }
    }
  }

  child(name: string): Logger {
    return {
      debug: (message, fields) => this.write('DEBUG', name, message, fields),
      info: (message, fields) => this.write('INFO', name, message, fields),
      warn: (message, fields) => this.write('WARNING', name, message, fields),
      error: (message, fields) => this.write('ERROR', name, message, fields),
    };
  }

  close(): void {
    this.out.close();
  }
}

/** A logger that drops everything, for tests and for code run before the log opens. */
export const silent: Logger = { debug() {}, info() {}, warn() {}, error() {} };
