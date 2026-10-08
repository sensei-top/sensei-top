// The server child (release plan 6, S8; D5–D8, D12): finds `sensei-top`,
// runs `serve` with the data directory's database, keeps its stdin open as a
// lifeline, waits for its ready line, restarts it, and runs any other
// subcommand against the same database.
//
// - **Where the server is.** Packaged: the frozen build at
//   `<resources>/server/sensei-top[.exe]` (phase 12 puts PyInstaller's
//   `--onedir` folder there). Development: `uv run --project <repo>
//   sensei-top`, since the working directory is the data directory, not the
//   repository.
// - **Where the data is** (D8). Windows `%LOCALAPPDATA%\Sensei Top`, elsewhere
//   `$XDG_DATA_HOME/sensei-top` (`~/.local/share/sensei-top`). Every child gets
//   `--db <dir>/sensei-top.db` and the directory as its working directory. A
//   development run may point all of it elsewhere with SENSEI_TOP_DATA_DIR; a
//   packaged build ignores the variable.
// - **The port** (D5, D6). The remembered port is asked for again when it is
//   free. When it is taken (after a short wait: our own previous server may
//   still be shutting down) or there is none, `serve --port 0` lets the OS
//   choose, and the port the ready line reports is remembered. A remembered
//   port that is refused at bind time, a race the probe cannot close, is
//   retried once with `--port 0`. Never 8000, the developer's `serve`.
// - **Lifeline** (D7). `--exit-on-stdin-close`: stdin stays an open pipe the
//   shell never writes to, so the server shuts down in order however the
//   shell dies. Stopping closes it first and kills only after a grace period.
// - **Restarts.** On demand (D12) at any time, uncounted. After an unexpected
//   exit, or a start that fails or prints no ready line within 60 s, at most
//   3 restarts in any 5 minutes; past that the state is `failed` until a
//   `retry()`.
//
// Electron-free: vitest imports it directly. `electron` values the caller
// knows (packaged, resourcesPath, the app path) arrive as arguments.

import { spawn as nodeSpawn, type ChildProcess, type SpawnOptions } from 'node:child_process';
import { EventEmitter } from 'node:events';
import * as net from 'node:net';
import * as path from 'node:path';
import type { Readable } from 'node:stream';
import { silent, type Logger } from './log';

export const DB_NAME = 'sensei-top.db';
export const RESERVED_PORT = 8000;
export const READY_TIMEOUT_MS = 60_000;
export const RESTART_LIMIT = 3;
export const RESTART_WINDOW_MS = 5 * 60_000;
export const DATA_DIR_ENV = 'SENSEI_TOP_DATA_DIR';
export const SESSION_ENV = 'SENSEI_TOP_SESSION';

export interface DataDirInput {
  platform: NodeJS.Platform;
  env: NodeJS.ProcessEnv;
  home: string;
  packaged: boolean;
  cwd?: string;
}

/** D8's data directory, or SENSEI_TOP_DATA_DIR in a development run. */
export function resolveDataDir(input: DataDirInput): { dir: string; overridden: boolean } {
  const override = input.env[DATA_DIR_ENV];
  if (!input.packaged && override) {
    const lib = input.platform === 'win32' ? path.win32 : path.posix;
    return { dir: lib.resolve(input.cwd ?? process.cwd(), override), overridden: true };
  }
  if (input.platform === 'win32') {
    const local = input.env.LOCALAPPDATA || path.win32.join(input.home, 'AppData', 'Local');
    return { dir: path.win32.join(local, 'Sensei Top'), overridden: false };
  }
  // The XDG spec ignores a relative XDG_DATA_HOME.
  const xdg = input.env.XDG_DATA_HOME;
  const base = xdg && path.posix.isAbsolute(xdg) ? xdg : path.posix.join(input.home, '.local', 'share');
  return { dir: path.posix.join(base, 'sensei-top'), overridden: false };
}

export interface ServerCommand {
  file: string;
  /** Arguments before the CLI's own (`run --project <repo> sensei-top` for uv). */
  prefix: string[];
}

export interface CommandInput {
  packaged: boolean;
  platform: NodeJS.Platform;
  /** `process.resourcesPath` (packaged). */
  resourcesPath: string;
  /** `app.getAppPath()`: `desktop/` in development. */
  appPath: string;
}

export function serverCommand(input: CommandInput): ServerCommand {
  const lib = input.platform === 'win32' ? path.win32 : path.posix;
  if (input.packaged) {
    const exe = input.platform === 'win32' ? 'sensei-top.exe' : 'sensei-top';
    return { file: lib.join(input.resourcesPath, 'server', exe), prefix: [] };
  }
  const repo = lib.resolve(input.appPath, '..');
  return { file: 'uv', prefix: ['run', '--project', repo, 'sensei-top'] };
}

/** The children's environment: this process's, plus the launch's session id
 *  (D17) and unbuffered output, so serve's prose lines reach the shell log
 *  in order with its stderr. ELECTRON_RUN_AS_NODE is no child's business. */
export function childEnv(base: NodeJS.ProcessEnv, session: string): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...base, [SESSION_ENV]: session, PYTHONUNBUFFERED: '1' };
  delete env.ELECTRON_RUN_AS_NODE;
  return env;
}

/** The arguments of the long-running server. `--db` and `--verbose` are the
 *  CLI's own options, so they come before the subcommand. */
export function serveArgs(db: string, port: number, verbose: boolean): string[] {
  return [
    '--db', db,
    ...(verbose ? ['--verbose'] : []),
    'serve', '--watch', '--port', String(port), '--ready-line', '--exit-on-stdin-close',
  ];
}

/** The subcommand's name, the only part of an argument list ever logged
 *  (`logs.py`'s trap 1: an argument can carry a credential). */
export function subcommandOf(args: readonly string[]): string {
  return args.find((arg) => !arg.startsWith('-')) ?? '(none)';
}

/** D6's `{"listening": <port>}`, or `null` for any other line. */
export function parseReadyLine(line: string): number | null {
  const text = line.trim();
  if (!text.startsWith('{')) return null;
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof value !== 'object' || value === null) return null;
  const port = (value as Record<string, unknown>).listening;
  return typeof port === 'number' && Number.isInteger(port) && port >= 1 && port <= 65535 ? port : null;
}

/** Calls `onLine` for each line of `stream`, `\r\n` or `\n`, the last one
 *  included even without its newline. */
export function onLines(stream: Readable | null | undefined, onLine: (line: string) => void): void {
  if (!stream) return;
  let pending = '';
  stream.setEncoding('utf8');
  stream.on('data', (chunk: string) => {
    pending += chunk;
    let index: number;
    while ((index = pending.indexOf('\n')) >= 0) {
      onLine(pending.slice(0, index).replace(/\r$/, ''));
      pending = pending.slice(index + 1);
    }
  });
  stream.on('end', () => {
    if (pending) onLine(pending.replace(/\r$/, ''));
    pending = '';
  });
  stream.on('error', () => {});
}

/** Whether `port` can be bound on loopback right now. */
export function isPortFree(port: number, host = '127.0.0.1'): Promise<boolean> {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.once('error', () => resolve(false));
    probe.listen({ port, host, exclusive: true }, () => probe.close(() => resolve(true)));
  });
}

export type PortReason = 'remembered' | 'none' | 'reserved' | 'taken';

export interface PortChoice {
  /** What to pass as `--port`; 0 lets the OS choose. */
  port: number;
  reason: PortReason;
}

export interface PortProbe {
  isFree: (port: number) => Promise<boolean>;
  sleep: (ms: number) => Promise<void>;
  /** How long a taken remembered port is waited for. */
  waitMs: number;
  stepMs: number;
}

export function validPort(port: unknown): port is number {
  return typeof port === 'number' && Number.isInteger(port) && port >= 1 && port <= 65535;
}

/** D5: the remembered port when it is (or within `waitMs` becomes) free,
 *  else 0. A remembered 8000 counts as none. */
export async function choosePort(remembered: number | undefined, probe: PortProbe): Promise<PortChoice> {
  if (!validPort(remembered)) return { port: 0, reason: 'none' };
  if (remembered === RESERVED_PORT) return { port: 0, reason: 'reserved' };
  const tries = Math.max(1, Math.floor(probe.waitMs / probe.stepMs) + 1);
  for (let attempt = 0; attempt < tries; attempt++) {
    if (await probe.isFree(remembered)) return { port: remembered, reason: 'remembered' };
    if (attempt < tries - 1) await probe.sleep(probe.stepMs);
  }
  return { port: 0, reason: 'taken' };
}

/** At most `limit` restarts in any `windowMs`: a sliding window, so a server
 *  that ran for a while earns its restarts back. */
export class RestartBudget {
  private times: number[] = [];

  constructor(
    readonly limit = RESTART_LIMIT,
    readonly windowMs = RESTART_WINDOW_MS,
  ) {}

  /** Spends one restart at `now`; `false` when none is left. */
  take(now: number): boolean {
    this.times = this.times.filter((time) => now - time < this.windowMs);
    if (this.times.length >= this.limit) return false;
    this.times.push(now);
    return true;
  }

  used(now: number): number {
    return this.times.filter((time) => now - time < this.windowMs).length;
  }

  reset(): void {
    this.times = [];
  }
}

export type ServerState =
  | { kind: 'stopped' }
  | { kind: 'starting' }
  | { kind: 'ready'; port: number }
  | { kind: 'failed'; reason: string };

export type SpawnFn = (file: string, args: readonly string[], options: SpawnOptions) => ChildProcess;

export interface ServerOptions {
  command: ServerCommand;
  dataDir: string;
  session: string;
  /** The shell's own environment; `childEnv` is applied to it. */
  env: NodeJS.ProcessEnv;
  /** D18: `--verbose`, read at each start. */
  verbose: () => boolean;
  rememberedPort: () => number | undefined;
  rememberPort: (port: number) => void;
  log?: Logger;
  spawn?: SpawnFn;
  isFree?: (port: number) => Promise<boolean>;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  readyTimeoutMs?: number;
  /** How long a stop waits after closing stdin before it kills. */
  stopGraceMs?: number;
  restartDelayMs?: number;
  portWaitMs?: number;
  budget?: RestartBudget;
}

type Attempt =
  | { kind: 'ready'; port: number; child: ChildProcess }
  | { kind: 'exited'; reason: string }
  | { kind: 'timeout'; reason: string };

export class RunError extends Error {
  constructor(
    readonly command: string,
    readonly code: number | null,
    readonly stderr: string,
  ) {
    super(`sensei-top ${command} exited with ${code ?? 'no status'}`);
    this.name = 'RunError';
  }
}

export interface RunOptions {
  /** Written to the child's stdin, which is then closed (D4: keys travel here). */
  stdin?: string;
  timeoutMs?: number;
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Emits `state` with each `ServerState`. */
export class ServerController extends EventEmitter {
  readonly db: string;
  private readonly log: Logger;
  private readonly spawnFn: SpawnFn;
  private readonly isFree: (port: number) => Promise<boolean>;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly now: () => number;
  private readonly budget: RestartBudget;
  private current: ServerState = { kind: 'stopped' };
  private wanted = false;
  private generation = 0;
  /** Every `serve` started and not yet exited: a stop ends them all. */
  private readonly children = new Set<ChildProcess>();
  private readyChild: ChildProcess | null = null;
  private retryTimer: NodeJS.Timeout | null = null;
  private starts = 0;

  constructor(private readonly options: ServerOptions) {
    super();
    this.db = path.join(options.dataDir, DB_NAME);
    this.log = options.log ?? silent;
    this.spawnFn = options.spawn ?? nodeSpawn;
    this.isFree = options.isFree ?? ((port) => isPortFree(port));
    this.sleep = options.sleep ?? defaultSleep;
    this.now = options.now ?? Date.now;
    this.budget = options.budget ?? new RestartBudget();
  }

  get state(): ServerState {
    return this.current;
  }

  /** The port while ready, else `null`. */
  get port(): number | null {
    return this.current.kind === 'ready' ? this.current.port : null;
  }

  /** Starts the server unless it is already starting or running. */
  start(): void {
    if (this.wanted) return;
    this.wanted = true;
    const generation = ++this.generation;
    void this.launch(generation);
  }

  /** From `failed`: a fresh budget and a new start. */
  retry(): void {
    if (this.current.kind !== 'failed') return;
    this.budget.reset();
    this.start();
  }

  /** D12: stop, then start again. Never counted against the budget. */
  async restart(reason: string): Promise<void> {
    this.log.info('server restart requested', { reason });
    await this.stop();
    this.start();
  }

  /** Closes every server's lifeline, waits, then kills. Resolves once all
   *  of them are gone, one still being stopped after a failed start included. */
  async stop(): Promise<void> {
    this.wanted = false;
    this.generation++;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.readyChild = null;
    await Promise.all([...this.children].map((child) => this.terminate(child)));
    this.setState({ kind: 'stopped' });
  }

  /** Runs `sensei-top --db <db> ...args` and returns its stdout; a non-zero
   *  exit rejects with a `RunError` carrying stderr. Only the subcommand's
   *  name is logged, never its arguments or its stdin. */
  run(args: readonly string[], options: RunOptions = {}): Promise<string> {
    const name = subcommandOf(args);
    const began = this.now();
    const { file, prefix } = this.options.command;
    return new Promise((resolve, reject) => {
      let child: ChildProcess;
      try {
        child = this.spawnFn(file, [...prefix, '--db', this.db, ...args], this.spawnOptions());
      } catch (error) {
        this.log.error(`could not run ${name}`, { error: String(error) });
        reject(error instanceof Error ? error : new Error(String(error)));
        return;
      }
      let stdout = '';
      let stderr = '';
      let settled = false;
      let timer: NodeJS.Timeout | null = null;
      const settle = (fn: () => void) => {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        fn();
      };
      child.stdout?.setEncoding('utf8');
      child.stderr?.setEncoding('utf8');
      child.stdout?.on('data', (chunk: string) => (stdout += chunk));
      child.stderr?.on('data', (chunk: string) => (stderr += chunk));
      child.stdout?.on('error', () => {});
      child.stderr?.on('error', () => {});
      child.stdin?.on('error', () => {});
      child.once('error', (error) => {
        this.log.error(`could not run ${name}`, { error: String(error) });
        settle(() => reject(error));
      });
      child.once('close', (code: number | null, signal: NodeJS.Signals | null) => {
        const ms = this.now() - began;
        if (code === 0) {
          this.log.info(`ran ${name}`, { exit: 0, ms });
          settle(() => resolve(stdout));
        } else {
          this.log.warn(`ran ${name}`, { exit: code, signal, ms });
          settle(() => reject(new RunError(name, code, stderr)));
        }
      });
      if (options.timeoutMs !== undefined) {
        timer = setTimeout(() => {
          this.log.warn(`${name} timed out; killing it`, { ms: options.timeoutMs });
          child.kill();
        }, options.timeoutMs);
      }
      if (options.stdin !== undefined) child.stdin?.end(options.stdin);
      else child.stdin?.end();
    });
  }

  private spawnOptions(): SpawnOptions {
    return {
      cwd: this.options.dataDir,
      env: childEnv(this.options.env, this.options.session),
      stdio: ['pipe', 'pipe', 'pipe'],
      // The frozen server is a console executable; without this Windows
      // opens a console window for it.
      windowsHide: true,
    };
  }

  private setState(state: ServerState): void {
    this.current = state;
    this.emit('state', state);
  }

  private live(generation: number): boolean {
    return this.wanted && generation === this.generation;
  }

  private async launch(generation: number): Promise<void> {
    this.setState({ kind: 'starting' });
    const choice = await choosePort(this.options.rememberedPort(), {
      isFree: this.isFree,
      sleep: this.sleep,
      waitMs: this.options.portWaitMs ?? 3000,
      stepMs: 250,
    });
    if (choice.reason === 'taken') this.log.info('the remembered port is taken; letting the OS choose');
    if (choice.reason === 'reserved') this.log.info('ignoring a remembered port of 8000, the developer server\'s');
    let port = choice.port;
    let fellBack = choice.port === 0;
    let refusedReserved = false;
    for (;;) {
      if (!this.live(generation)) return;
      const result = await this.attempt(port);
      if (!this.live(generation)) {
        if (result.kind === 'ready') await this.terminate(result.child);
        return;
      }
      if (result.kind === 'ready') {
        if (result.port === RESERVED_PORT) {
          // Only `--port 0` can land here: 8000 is never asked for.
          await this.terminate(result.child);
          if (!refusedReserved) {
            this.log.warn('the OS chose port 8000, the developer server\'s; starting again');
            refusedReserved = true;
            port = 0;
            continue;
          }
          return this.unexpected(generation, 'the server was given port 8000 twice');
        }
        this.readyChild = result.child;
        if (result.port !== this.options.rememberedPort()) this.options.rememberPort(result.port);
        this.log.info('server ready', { port: result.port });
        this.setState({ kind: 'ready', port: result.port });
        return;
      }
      if (port !== 0 && !fellBack && !(await this.isFree(port))) {
        // Lost the race between the probe and serve's own bind.
        this.log.info('the remembered port was taken at bind time; letting the OS choose', { port });
        fellBack = true;
        port = 0;
        continue;
      }
      return this.unexpected(generation, result.reason);
    }
  }

  private unexpected(generation: number, reason: string): void {
    if (!this.live(generation)) return;
    if (this.budget.take(this.now())) {
      this.log.warn('server stopped unexpectedly; restarting', {
        reason,
        restartsInWindow: this.budget.used(this.now()),
        limit: this.budget.limit,
      });
      this.setState({ kind: 'starting' });
      this.retryTimer = setTimeout(() => {
        this.retryTimer = null;
        if (this.live(generation)) void this.launch(generation);
      }, this.options.restartDelayMs ?? 1000);
      return;
    }
    this.log.error('server stopped unexpectedly too often; giving up', {
      reason,
      limit: this.budget.limit,
      windowMinutes: this.budget.windowMs / 60_000,
    });
    this.wanted = false;
    this.setState({ kind: 'failed', reason });
  }

  private attempt(port: number): Promise<Attempt> {
    const { file, prefix } = this.options.command;
    const args = [...prefix, ...serveArgs(this.db, port, this.options.verbose())];
    this.starts++;
    this.log.info('server starting', { port: port === 0 ? 'any' : port, start: this.starts });
    return new Promise((resolve) => {
      let child: ChildProcess;
      try {
        child = this.spawnFn(file, args, this.spawnOptions());
      } catch (error) {
        this.log.error('server could not be started', { error: String(error) });
        resolve({ kind: 'exited', reason: `could not be started: ${String(error)}` });
        return;
      }
      this.children.add(child);
      let done = false;
      let timedOut = false;
      const finish = (result: Attempt) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve(result);
      };
      const timeoutMs = this.options.readyTimeoutMs ?? READY_TIMEOUT_MS;
      // The attempt ends only once this server has exited, so the next one
      // never shares the database with it.
      const timer = setTimeout(() => {
        timedOut = true;
        this.log.error('no ready line; stopping the server', { seconds: timeoutMs / 1000 });
        void this.terminate(child).then(() =>
          finish({ kind: 'timeout', reason: `no ready line within ${timeoutMs / 1000} s` }),
        );
      }, timeoutMs);
      child.stdin?.on('error', () => {});
      onLines(child.stdout, (line) => {
        const ready = parseReadyLine(line);
        if (ready !== null && !done && !timedOut) finish({ kind: 'ready', port: ready, child });
        else if (line.trim()) this.log.info(`serve: ${line}`);
      });
      onLines(child.stderr, (line) => {
        if (line.trim()) this.log.warn(`serve stderr: ${line}`);
      });
      child.once('error', (error) => {
        this.log.error('server could not be started', { error: String(error) });
        this.children.delete(child);
        if (!timedOut) finish({ kind: 'exited', reason: `could not be started: ${String(error)}` });
      });
      child.once('exit', (code: number | null, signal: NodeJS.Signals | null) => {
        this.log.info('server exited', { code, signal });
        this.children.delete(child);
        if (timedOut) return;
        if (!done) {
          finish({ kind: 'exited', reason: `exited with ${code ?? signal ?? 'no status'} before it was ready` });
          return;
        }
        if (child === this.readyChild) {
          this.readyChild = null;
          this.unexpected(this.generation, `exited with ${code ?? signal ?? 'no status'}`);
        }
      });
    });
  }

  /** Closes stdin (the orderly path), then SIGTERM after the grace period,
   *  then SIGKILL. Resolves on exit, or once the last signal is sent. */
  private terminate(child: ChildProcess): Promise<void> {
    if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
    return new Promise((resolve) => {
      const grace = this.options.stopGraceMs ?? 10_000;
      const timers: NodeJS.Timeout[] = [];
      const done = () => {
        for (const timer of timers) clearTimeout(timer);
        resolve();
      };
      child.once('exit', done);
      child.once('error', done);
      try {
        if (child.stdin && !child.stdin.writableEnded) child.stdin.end();
      } catch {
        // already closed
      }
      timers.push(
        setTimeout(() => {
          this.log.warn('server still running after its stdin closed; terminating it');
          child.kill('SIGTERM');
        }, grace),
        setTimeout(() => {
          this.log.error('server still running; killing it');
          child.kill('SIGKILL');
        }, grace + 5000),
        setTimeout(done, grace + 10_000),
      );
    });
  }
}
