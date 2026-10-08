import type { ChildProcess, SpawnOptions } from 'node:child_process';
import { EventEmitter } from 'node:events';
import * as net from 'node:net';
import * as path from 'node:path';
import { PassThrough } from 'node:stream';
import { describe, expect, it } from 'vitest';
import type { Logger } from './log';
import {
  childEnv,
  choosePort,
  isPortFree,
  onLines,
  parseReadyLine,
  resolveDataDir,
  RestartBudget,
  RunError,
  serveArgs,
  serverCommand,
  ServerController,
  type ServerOptions,
  type ServerState,
  type SpawnFn,
  subcommandOf,
} from './server';

describe('the data directory (D8)', () => {
  it('is %LOCALAPPDATA%\\Sensei Top on Windows', () => {
    expect(
      resolveDataDir({ platform: 'win32', env: { LOCALAPPDATA: 'C:\\Users\\Sample\\AppData\\Local' }, home: 'C:\\Users\\Sample', packaged: true }),
    ).toEqual({ dir: 'C:\\Users\\Sample\\AppData\\Local\\Sensei Top', overridden: false });
  });

  it('falls back to the home AppData\\Local when LOCALAPPDATA is unset', () => {
    expect(resolveDataDir({ platform: 'win32', env: {}, home: 'C:\\Users\\Sample', packaged: true }).dir).toBe(
      'C:\\Users\\Sample\\AppData\\Local\\Sensei Top',
    );
  });

  it('is $XDG_DATA_HOME/sensei-top elsewhere', () => {
    expect(resolveDataDir({ platform: 'linux', env: { XDG_DATA_HOME: '/srv/xdg' }, home: '/home/sample', packaged: true }).dir).toBe(
      '/srv/xdg/sensei-top',
    );
  });

  it('is ~/.local/share/sensei-top with no XDG_DATA_HOME, or a relative one', () => {
    for (const env of [{}, { XDG_DATA_HOME: '' }, { XDG_DATA_HOME: 'relative/dir' }]) {
      expect(resolveDataDir({ platform: 'linux', env, home: '/home/sample', packaged: true }).dir).toBe(
        '/home/sample/.local/share/sensei-top',
      );
    }
  });

  it('honours SENSEI_TOP_DATA_DIR in development, resolved against the working directory', () => {
    expect(
      resolveDataDir({ platform: 'linux', env: { SENSEI_TOP_DATA_DIR: 'scratch' }, home: '/home/sample', packaged: false, cwd: '/tmp/work' }),
    ).toEqual({ dir: '/tmp/work/scratch', overridden: true });
  });

  it('ignores SENSEI_TOP_DATA_DIR in a packaged build', () => {
    expect(
      resolveDataDir({ platform: 'linux', env: { SENSEI_TOP_DATA_DIR: '/tmp/scratch' }, home: '/home/sample', packaged: true }),
    ).toEqual({ dir: '/home/sample/.local/share/sensei-top', overridden: false });
  });
});

describe('the server command', () => {
  it('is the frozen build under resources/server when packaged', () => {
    expect(serverCommand({ packaged: true, platform: 'win32', resourcesPath: 'C:\\App\\resources', appPath: 'x' })).toEqual({
      file: 'C:\\App\\resources\\server\\sensei-top.exe',
      prefix: [],
    });
    expect(serverCommand({ packaged: true, platform: 'linux', resourcesPath: '/opt/app/resources', appPath: 'x' })).toEqual({
      file: '/opt/app/resources/server/sensei-top',
      prefix: [],
    });
  });

  it('is uv run against the repository in development', () => {
    expect(serverCommand({ packaged: false, platform: 'linux', resourcesPath: '/x', appPath: '/repo/desktop' })).toEqual({
      file: 'uv',
      prefix: ['run', '--project', '/repo', 'sensei-top'],
    });
  });

  it("puts the CLI's own options before the subcommand", () => {
    expect(serveArgs('/d/sensei-top.db', 0, false)).toEqual([
      '--db', '/d/sensei-top.db', 'serve', '--watch', '--port', '0', '--ready-line', '--exit-on-stdin-close',
    ]);
    expect(serveArgs('/d/sensei-top.db', 41234, true).slice(0, 4)).toEqual(['--db', '/d/sensei-top.db', '--verbose', 'serve']);
  });

  it('hands the children the session id, and not ELECTRON_RUN_AS_NODE', () => {
    const base = { PATH: '/bin', ELECTRON_RUN_AS_NODE: '1' };
    const env = childEnv(base, 'abcd1234');
    expect(env.SENSEI_TOP_SESSION).toBe('abcd1234');
    expect(env.PATH).toBe('/bin');
    expect('ELECTRON_RUN_AS_NODE' in env).toBe(false);
    expect(base.ELECTRON_RUN_AS_NODE).toBe('1');
  });

  it('names a subcommand by its first non-option argument', () => {
    expect(subcommandOf(['config', '--set-key', '-'])).toBe('config');
    expect(subcommandOf(['--verbose', 'doctor', '--json'])).toBe('doctor');
    expect(subcommandOf([])).toBe('(none)');
  });
});

describe('the ready line (D6)', () => {
  it('reads {"listening": PORT}', () => {
    expect(parseReadyLine('{"listening": 41234}')).toBe(41234);
    expect(parseReadyLine('  {"listening": 41234}\r')).toBe(41234);
  });

  it.each([
    'Serving /d/sensei-top.db on http://127.0.0.1:41234  (Ctrl-C to stop)',
    '{"listening": 0}',
    '{"listening": 65536}',
    '{"listening": "41234"}',
    '{"port": 41234}',
    '{"listening": 41',
    '',
  ])('ignores %j', (line) => {
    expect(parseReadyLine(line)).toBeNull();
  });

  it('splits a stream into lines across chunks and line endings', () => {
    const stream = new PassThrough();
    const lines: string[] = [];
    onLines(stream, (line) => lines.push(line));
    stream.write('first\r\nsec');
    stream.write('ond\n{"listen');
    stream.end('ing": 1}');
    return new Promise<void>((resolve) => {
      stream.on('end', () => {
        expect(lines).toEqual(['first', 'second', '{"listening": 1}']);
        resolve();
      });
    });
  });
});

describe('the port (D5)', () => {
  const probe = (free: (port: number, call: number) => boolean) => {
    let calls = 0;
    const sleeps: number[] = [];
    return {
      sleeps,
      calls: () => calls,
      probe: {
        isFree: async (port: number) => free(port, calls++),
        sleep: async (ms: number) => {
          sleeps.push(ms);
        },
        waitMs: 1000,
        stepMs: 250,
      },
    };
  };

  it('lets the OS choose on a first launch', async () => {
    const p = probe(() => true);
    expect(await choosePort(undefined, p.probe)).toEqual({ port: 0, reason: 'none' });
    expect(p.calls()).toBe(0);
  });

  it('never asks for 8000, the developer server', async () => {
    expect(await choosePort(8000, probe(() => true).probe)).toEqual({ port: 0, reason: 'reserved' });
  });

  it('asks for the remembered port when it is free', async () => {
    expect(await choosePort(41234, probe(() => true).probe)).toEqual({ port: 41234, reason: 'remembered' });
  });

  it('waits for a taken port, then lets the OS choose', async () => {
    const p = probe(() => false);
    expect(await choosePort(41234, p.probe)).toEqual({ port: 0, reason: 'taken' });
    // 1000 ms in 250 ms steps: five looks, four waits between them.
    expect(p.calls()).toBe(5);
    expect(p.sleeps).toEqual([250, 250, 250, 250]);
  });

  it('keeps the remembered port when it frees up while waiting', async () => {
    const p = probe((_port, call) => call >= 2);
    expect(await choosePort(41234, p.probe)).toEqual({ port: 41234, reason: 'remembered' });
  });

  it('probes a real loopback port', async () => {
    const holder = net.createServer();
    await new Promise<void>((resolve) => holder.listen({ port: 0, host: '127.0.0.1' }, resolve));
    const port = (holder.address() as net.AddressInfo).port;
    expect(await isPortFree(port)).toBe(false);
    await new Promise<void>((resolve) => holder.close(() => resolve()));
    expect(await isPortFree(port)).toBe(true);
  });
});

describe('the restart budget', () => {
  it('allows three restarts in five minutes, then none', () => {
    const budget = new RestartBudget();
    expect([budget.take(0), budget.take(1000), budget.take(2000), budget.take(3000)]).toEqual([true, true, true, false]);
  });

  it('is a sliding window: a restart five minutes old is earned back', () => {
    const budget = new RestartBudget(3, 300_000);
    budget.take(0);
    budget.take(100_000);
    budget.take(200_000);
    expect(budget.take(299_999)).toBe(false);
    expect(budget.take(300_000)).toBe(true);
    expect(budget.used(300_000)).toBe(3);
  });

  it('starts over on reset', () => {
    const budget = new RestartBudget(1, 300_000);
    budget.take(0);
    budget.reset();
    expect(budget.take(1)).toBe(true);
  });
});

class FakeChild extends EventEmitter {
  readonly stdin = new PassThrough();
  readonly stdout = new PassThrough();
  readonly stderr = new PassThrough();
  exitCode: number | null = null;
  signalCode: NodeJS.Signals | null = null;
  stdinEnded = false;
  stdinText = '';
  readonly signals: string[] = [];
  /** What the child does when its stdin ends: serve's lifeline is an orderly exit. */
  onStdinEnd: () => void = () => setImmediate(() => this.exit(0));

  constructor(
    readonly file: string,
    readonly args: string[],
    readonly options: SpawnOptions,
  ) {
    super();
    this.stdin.setEncoding('utf8');
    this.stdin.on('data', (chunk: string) => (this.stdinText += chunk));
    this.stdin.on('end', () => {
      this.stdinEnded = true;
      this.onStdinEnd();
    });
  }

  get port(): string | undefined {
    return this.args[this.args.indexOf('--port') + 1];
  }

  ready(port: number): void {
    this.stdout.write(`Serving x on http://127.0.0.1:${port}\n{"listening": ${port}}\n`);
  }

  exit(code: number | null, signal: NodeJS.Signals | null = null): void {
    if (this.exitCode !== null || this.signalCode !== null) return;
    this.exitCode = code;
    this.signalCode = signal;
    this.stdout.end();
    this.stderr.end();
    this.emit('exit', code, signal);
    // As a real child: 'close' follows once its output has been read.
    setImmediate(() => setImmediate(() => this.emit('close', code, signal)));
  }

  kill(signal: NodeJS.Signals = 'SIGTERM'): boolean {
    this.signals.push(signal);
    setImmediate(() => this.exit(null, signal));
    return true;
  }
}

interface HarnessOptions extends Partial<ServerOptions> {
  remembered?: number;
  /** Called as the child is spawned, before anyone listens to it. */
  configure?: (child: FakeChild) => void;
  /** Called on the next turn, once the controller listens. */
  onSpawn?: (child: FakeChild) => void;
}

function harness(overrides: HarnessOptions = {}) {
  const children: FakeChild[] = [];
  const waiting: Array<(child: FakeChild) => void> = [];
  let taken = 0;
  const spawn: SpawnFn = (file, args, options) => {
    const child = new FakeChild(file, [...args], options);
    children.push(child);
    overrides.configure?.(child);
    if (overrides.onSpawn) setImmediate(() => overrides.onSpawn?.(child));
    const waiter = waiting.shift();
    if (waiter) waiter(children[taken++]!);
    return child as unknown as ChildProcess;
  };
  const nextChild = (): Promise<FakeChild> =>
    taken < children.length ? Promise.resolve(children[taken++]!) : new Promise((resolve) => waiting.push(resolve));

  let remembered = overrides.remembered;
  const remembers: number[] = [];
  const lines: string[] = [];
  const push = (message: string, fields?: unknown) => lines.push(fields ? `${message} ${JSON.stringify(fields)}` : message);
  const log: Logger = { debug: push, info: push, warn: push, error: push };
  const states: ServerState[] = [];
  const budget = overrides.budget ?? new RestartBudget();
  const server = new ServerController({
    command: { file: 'sensei-top', prefix: [] },
    dataDir: path.join('/data'),
    session: 'abcd1234',
    env: { PATH: '/bin', ELECTRON_RUN_AS_NODE: '1' },
    verbose: () => false,
    rememberedPort: () => remembered,
    rememberPort: (port) => {
      remembered = port;
      remembers.push(port);
    },
    log,
    spawn,
    isFree: async () => true,
    sleep: async () => {},
    restartDelayMs: 0,
    readyTimeoutMs: 5000,
    stopGraceMs: 20,
    ...overrides,
    budget,
  });
  server.on('state', (state: ServerState) => states.push(state));
  const reach = (kind: ServerState['kind']): Promise<ServerState> =>
    server.state.kind === kind
      ? Promise.resolve(server.state)
      : new Promise((resolve) => {
          const on = (state: ServerState) => {
            if (state.kind !== kind) return;
            server.off('state', on);
            resolve(state);
          };
          server.on('state', on);
        });
  return { server, children, nextChild, remembers, lines, states, budget, reach };
}

describe('the server controller', () => {
  it('starts serve on --port 0 the first time, and remembers the reported port', async () => {
    const h = harness();
    h.server.start();
    const child = await h.nextChild();
    expect(child.file).toBe('sensei-top');
    expect(child.args).toEqual(serveArgs(path.join('/data', 'sensei-top.db'), 0, false));
    expect(child.options.cwd).toBe(path.join('/data'));
    expect(child.options.windowsHide).toBe(true);
    expect((child.options.env as NodeJS.ProcessEnv).SENSEI_TOP_SESSION).toBe('abcd1234');
    child.ready(41234);
    expect(await h.reach('ready')).toEqual({ kind: 'ready', port: 41234 });
    expect(h.remembers).toEqual([41234]);
    expect(h.server.port).toBe(41234);
  });

  it('asks for the remembered port again, and holds stdin open while it runs', async () => {
    const h = harness({ remembered: 41234 });
    h.server.start();
    const child = await h.nextChild();
    expect(child.port).toBe('41234');
    child.ready(41234);
    await h.reach('ready');
    expect(h.remembers).toEqual([]);
    expect(child.stdinEnded).toBe(false);
    expect(child.stdinText).toBe('');
  });

  it('stops by closing stdin, without a signal when serve exits on its own', async () => {
    const h = harness();
    h.server.start();
    const child = await h.nextChild();
    child.ready(41234);
    await h.reach('ready');
    await h.server.stop();
    expect(child.stdinEnded).toBe(true);
    expect(child.signals).toEqual([]);
    expect(h.server.state).toEqual({ kind: 'stopped' });
  });

  it('terminates a server that ignores its stdin closing', async () => {
    const h = harness();
    h.server.start();
    const child = await h.nextChild();
    child.onStdinEnd = () => {};
    child.ready(41234);
    await h.reach('ready');
    await h.server.stop();
    expect(child.signals).toEqual(['SIGTERM']);
  });

  it('restarts after an unexpected exit, and comes back ready', async () => {
    const h = harness({ remembered: 41234 });
    h.server.start();
    const first = await h.nextChild();
    first.ready(41234);
    await h.reach('ready');
    first.exit(1);
    const second = await h.nextChild();
    expect(second.port).toBe('41234');
    second.ready(41234);
    await h.reach('ready');
    expect(h.budget.used(Date.now())).toBe(1);
  });

  it('gives up after three restarts in five minutes', async () => {
    const h = harness({ onSpawn: (child) => child.exit(1) });
    h.server.start();
    const failed = await h.reach('failed');
    expect(h.children).toHaveLength(4);
    expect(failed.kind === 'failed' && failed.reason).toMatch(/exited with 1 before it was ready/);
    expect(h.lines.some((line) => line.startsWith('server stopped unexpectedly too often'))).toBe(true);
  });

  it('starts over from failed on retry, with a fresh budget', async () => {
    let fail = true;
    const h = harness({ budget: new RestartBudget(1, 300_000), onSpawn: (child) => (fail ? child.exit(1) : child.ready(41234)) });
    h.server.start();
    await h.reach('failed');
    expect(h.children).toHaveLength(2);
    fail = false;
    h.server.retry();
    await h.reach('ready');
    expect(h.children).toHaveLength(3);
  });

  it('counts a start with no ready line in time as a failure, and stops that server', async () => {
    const h = harness({ readyTimeoutMs: 30, budget: new RestartBudget(0, 300_000) });
    h.server.start();
    const child = await h.nextChild();
    const failed = await h.reach('failed');
    expect(failed.kind === 'failed' && failed.reason).toBe('no ready line within 0.03 s');
    expect(child.stdinEnded).toBe(true);
  });

  it('waits for a server with no ready line to exit before starting the next', async () => {
    const running = (child: FakeChild) => child.exitCode === null && child.signalCode === null;
    const overlapped: boolean[] = [];
    const h = harness({
      readyTimeoutMs: 30,
      stopGraceMs: 50,
      configure: (child) => {
        // Ignores its stdin closing: only the signal after the grace ends it.
        child.onStdinEnd = () => {};
        overlapped.push(h.children.some((other) => other !== child && running(other)));
      },
    });
    h.server.start();
    const first = await h.nextChild();
    const second = await h.nextChild();
    expect(first.signals).toEqual(['SIGTERM']);
    expect(running(first)).toBe(false);
    expect(overlapped).toEqual([false, false]);
    await h.server.stop();
    expect(running(second)).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(h.children).toHaveLength(2);
    expect(h.server.state).toEqual({ kind: 'stopped' });
  });

  it('ends a server still being stopped after its failed start', async () => {
    const h = harness({ readyTimeoutMs: 30, stopGraceMs: 200, configure: (child) => (child.onStdinEnd = () => {}) });
    h.server.start();
    const first = await h.nextChild();
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(first.stdinEnded).toBe(true);
    expect(first.signalCode).toBeNull();
    await h.server.stop();
    expect(first.signalCode).toBe('SIGTERM');
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(h.children).toHaveLength(1);
    expect(h.server.state).toEqual({ kind: 'stopped' });
  });

  it('restarts on demand without spending the budget', async () => {
    const h = harness({ onSpawn: (child) => child.ready(41234) });
    h.server.start();
    await h.reach('ready');
    await h.server.restart('a setting changed');
    await h.reach('ready');
    expect(h.children).toHaveLength(2);
    expect(h.children[0]!.stdinEnded).toBe(true);
    expect(h.budget.used(Date.now())).toBe(0);
  });

  it('falls back to --port 0 when the remembered port is taken at bind time', async () => {
    let probes = 0;
    const h = harness({
      remembered: 41234,
      isFree: async () => probes++ === 0,
      onSpawn: (child) => (child.port === '41234' ? child.exit(1) : child.ready(45678)),
    });
    h.server.start();
    await h.reach('ready');
    expect(h.children.map((child) => child.port)).toEqual(['41234', '0']);
    expect(h.remembers).toEqual([45678]);
    expect(h.budget.used(Date.now())).toBe(0);
  });

  it('refuses port 8000 even when the OS hands it out', async () => {
    const ports = [8000, 45678];
    const h = harness({ onSpawn: (child) => child.ready(ports.shift()!) });
    h.server.start();
    expect(await h.reach('ready')).toEqual({ kind: 'ready', port: 45678 });
    expect(h.children[0]!.stdinEnded).toBe(true);
    expect(h.children.map((child) => child.port)).toEqual(['0', '0']);
    expect(h.remembers).toEqual([45678]);
    expect(h.budget.used(Date.now())).toBe(0);
  });

  it('logs serve’s prose and stderr, but never takes them for the ready line', async () => {
    const h = harness();
    h.server.start();
    const child = await h.nextChild();
    child.stderr.write('Traceback (most recent call last):\n');
    child.ready(41234);
    await h.reach('ready');
    expect(h.lines).toContain('serve stderr: Traceback (most recent call last):');
    expect(h.lines).toContain('serve: Serving x on http://127.0.0.1:41234');
  });
});

describe('running another subcommand', () => {
  it('passes --db first, writes stdin then closes it, and returns stdout', async () => {
    const h = harness({
      configure: (child) => {
        child.onStdinEnd = () => {
          child.stdout.write('{"ok": true}\n');
          child.exit(0);
        };
      },
    });
    const out = await h.server.run(['config', '--set-key', '-'], { stdin: 'sk-not-a-real-key' });
    const child = h.children[0]!;
    expect(child.args).toEqual(['--db', path.join('/data', 'sensei-top.db'), 'config', '--set-key', '-']);
    expect(child.stdinText).toBe('sk-not-a-real-key');
    expect(child.stdinEnded).toBe(true);
    expect(out).toBe('{"ok": true}\n');
    // Only the subcommand's name is logged: never an argument or stdin.
    expect(h.lines.join('\n')).not.toContain('sk-not-a-real-key');
    expect(h.lines.join('\n')).not.toContain('--set-key');
  });

  it('closes stdin at once when there is nothing to write', async () => {
    const h = harness();
    await h.server.run(['doctor', '--json']);
    expect(h.children[0]!.stdinEnded).toBe(true);
  });

  it('rejects a non-zero exit with its status and stderr', async () => {
    const h = harness({
      configure: (child) => {
        child.onStdinEnd = () => {
          child.stderr.write('refused: schema is newer\n');
          child.exit(3);
        };
      },
    });
    const error = await h.server.run(['restore', 'x.db']).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(RunError);
    expect(error).toMatchObject({ command: 'restore', code: 3, stderr: 'refused: schema is newer\n' });
  });
});
