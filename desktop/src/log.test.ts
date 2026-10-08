import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  formatLine,
  formatTime,
  homeAsTilde,
  homePattern,
  logPath,
  newSessionId,
  RotatingFile,
  ShellLog,
} from './log';

// The server's own format, read from logs.py rather than copied, so a change
// there fails here instead of silently splitting the two files apart.
const LOGS_PY = path.resolve(__dirname, '..', '..', 'src', 'sensei_top', 'logs.py');

function pythonConstant(source: string, name: string): string {
  const match = new RegExp(`^${name} = "([^"]*)"$`, 'm').exec(source);
  if (!match?.[1]) throw new Error(`${name} not found in logs.py`);
  return match[1];
}

/** `logging.Formatter(fmt, datefmt)` with `converter = time.gmtime`, for
 *  exactly the directives the two constants use; anything else fails. */
function renderPython(fmt: string, datefmt: string, when: Date, record: Record<string, string>): string {
  const two = (n: number) => String(n).padStart(2, '0');
  const strftime: Record<string, string> = {
    Y: String(when.getUTCFullYear()),
    m: two(when.getUTCMonth() + 1),
    d: two(when.getUTCDate()),
    H: two(when.getUTCHours()),
    M: two(when.getUTCMinutes()),
    S: two(when.getUTCSeconds()),
  };
  const asctime = datefmt.replace(/%(.)/g, (_all, code: string) => {
    const value = strftime[code];
    if (value === undefined) throw new Error(`unhandled strftime directive %${code}`);
    return value;
  });
  const fields: Record<string, string> = {
    ...record,
    asctime,
    msecs: String(when.getUTCMilliseconds()).padStart(3, '0'),
  };
  return fmt.replace(/%\((\w+)\)(03d|s)/g, (_all, key: string) => {
    const value = fields[key];
    if (value === undefined) throw new Error(`unhandled record field ${key}`);
    return value;
  });
}

describe('the line format', () => {
  const when = new Date(Date.UTC(2026, 9, 6, 14, 3, 22, 418));

  it("is logs.py's LINE_FORMAT and DATE_FORMAT, in UTC", () => {
    const source = fs.readFileSync(LOGS_PY, 'utf8');
    const expected = renderPython(pythonConstant(source, 'LINE_FORMAT'), pythonConstant(source, 'DATE_FORMAT'), when, {
      session: '3f9a1c2e',
      levelname: 'WARNING',
      name: 'shell.server',
      message: 'server stopped',
    });
    expect(formatLine(when, '3f9a1c2e', 'WARNING', 'shell.server', 'server stopped')).toBe(expected);
  });

  it("matches the example line logs.py's docstring gives", () => {
    expect(formatLine(when, '3f9a1c2e', 'WARNING', 'sensei_top.live', '…')).toBe(
      '2026-10-06T14:03:22.418Z 3f9a1c2e WARNING sensei_top.live: …',
    );
  });

  it('pads every field, milliseconds to three digits', () => {
    expect(formatTime(new Date(Date.UTC(2026, 0, 2, 3, 4, 5, 7)))).toBe('2026-01-02T03:04:05.007Z');
  });

  it('appends structured fields as one JSON object', () => {
    expect(formatLine(when, '3f9a1c2e', 'INFO', 'shell.server', 'server ready', { port: 41234 })).toBe(
      '2026-10-06T14:03:22.418Z 3f9a1c2e INFO shell.server: server ready {"port":41234}',
    );
  });

  it('gives each launch an 8-hex session id', () => {
    expect(newSessionId()).toMatch(/^[0-9a-f]{8}$/);
  });

  it('puts the file beside the server log', () => {
    expect(logPath(path.join('data', 'dir'))).toBe(path.join('data', 'dir', 'logs', 'shell.log'));
  });
});

// The same cases tests/test_logs.py pins for logs.py's home rule (its trap 2).
describe('the home directory written as ~', () => {
  const windows = homePattern('C:\\Users\\Sample', true);
  it.each([
    ['database C:\\Users\\Sample\\AppData\\Local\\sensei-top\\sensei-top.db', 'database ~\\AppData\\Local\\sensei-top\\sensei-top.db'],
    ['database c:/users/SAMPLE/AppData', 'database ~/AppData'],
    ["No such file: 'C:\\\\Users\\\\Sample\\\\Player.log'", "No such file: '~\\\\Player.log'"],
    ['cd C:\\Users\\Sample', 'cd ~'],
    ['C:\\Users\\Sampler\\x.db', 'C:\\Users\\Sampler\\x.db'],
    ['C:\\Users\\Sample.old\\x.db', '~.old\\x.db'],
    ['written to C:\\Users\\Sample.', 'written to ~.'],
  ])('Windows: %s', (line, written) => {
    expect(homeAsTilde(line, windows)).toBe(written);
  });

  const posix = homePattern('/home/sample', false);
  it.each([
    ['database /home/sample/.local/share/sensei-top.db', 'database ~/.local/share/sensei-top.db'],
    ['cd /home/sample', 'cd ~'],
    ['/home/Sample/x.db', '/home/Sample/x.db'],
    ['/home/sampler/x.db', '/home/sampler/x.db'],
    ['/home/sample-old/x.db', '~-old/x.db'],
    ['written to /home/sample.', 'written to ~.'],
  ])('POSIX: %s', (line, written) => {
    expect(homeAsTilde(line, posix)).toBe(written);
  });

  it('replaces every occurrence, a JSON-escaped Windows path included', () => {
    const line = JSON.stringify({ a: 'C:\\Users\\Sample\\x', b: 'C:\\Users\\Sample' });
    expect(homeAsTilde(line, windows)).toBe('{"a":"~\\\\x","b":"~"}');
  });

  it('leaves a name continued by a non-ASCII letter alone', () => {
    expect(homeAsTilde('/home/sampleé/x', posix)).toBe('/home/sampleé/x');
  });

  it('substitutes nothing for a home that is a filesystem root', () => {
    expect(homePattern('/', false)).toBeNull();
    expect(homePattern('C:\\', true)).toBeNull();
  });
});

describe('the rotating file', () => {
  let dir: string;
  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shell-log-'));
  });
  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('rolls over before a write that would reach the limit, keeping `backups` old files', () => {
    // Each line is 60 bytes plus its newline. RotatingFileHandler's rule
    // (size + next >= max rolls over) puts three in a 200-byte file, so ten
    // lines are 1–3, 4–6, 7–9 and 10, and two backups keep 4–9.
    const file = path.join(dir, 'logs', 'shell.log');
    const out = new RotatingFile(file, 200, 2);
    expect(out.open()).toBe(true);
    const line = (n: number) => `line ${String(n).padStart(2, '0')} ${'x'.repeat(52)}`;
    for (let n = 1; n <= 10; n++) out.write(line(n));
    out.close();
    const read = (name: string) => fs.readFileSync(path.join(dir, 'logs', name), 'utf8').trimEnd().split('\n');
    expect(read('shell.log')).toEqual([line(10)]);
    expect(read('shell.log.1')).toEqual([line(7), line(8), line(9)]);
    expect(read('shell.log.2')).toEqual([line(4), line(5), line(6)]);
    expect(fs.existsSync(path.join(dir, 'logs', 'shell.log.3'))).toBe(false);
    expect(fs.existsSync(path.join(dir, 'logs', 'shell.log.rotating'))).toBe(false);
  });

  it('appends to what an earlier launch wrote', () => {
    const file = path.join(dir, 'shell.log');
    fs.writeFileSync(file, 'earlier\n');
    const out = new RotatingFile(file);
    out.open();
    out.write('later');
    out.close();
    expect(fs.readFileSync(file, 'utf8')).toBe('earlier\nlater\n');
  });

  it('reports a file it cannot open instead of throwing', () => {
    const blocker = path.join(dir, 'not-a-dir');
    fs.writeFileSync(blocker, '');
    const out = new RotatingFile(path.join(blocker, 'shell.log'));
    expect(out.open()).toBe(false);
    expect(() => out.write('dropped')).not.toThrow();
  });
});

describe('the shell log', () => {
  let dir: string;
  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shell-log-'));
  });
  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  function open(level?: 'DEBUG' | 'INFO') {
    const file = path.join(dir, 'shell.log');
    const log = new ShellLog(file, {
      session: 'abcdef01',
      home: '/home/sample',
      windows: false,
      now: () => new Date(Date.UTC(2026, 9, 7, 12, 0, 0, 5)),
      ...(level ? { level } : {}),
    });
    return { file, log };
  }

  it('drops DEBUG at its default level, and keeps it once raised', () => {
    const { file, log } = open();
    const server = log.child('shell.server');
    server.debug('hidden');
    server.info('shown');
    log.setLevel('DEBUG');
    server.debug('now shown');
    log.close();
    expect(fs.readFileSync(file, 'utf8')).toBe(
      '2026-10-07T12:00:00.005Z abcdef01 INFO shell.server: shown\n' +
        '2026-10-07T12:00:00.005Z abcdef01 DEBUG shell.server: now shown\n',
    );
  });

  it('writes the home as ~ in the message and in the fields', () => {
    const { file, log } = open();
    log.child('shell.main').warn('reading /home/sample/x', { dir: '/home/sample/.local/share/sensei-top' });
    log.close();
    const text = fs.readFileSync(file, 'utf8');
    expect(text).toContain('reading ~/x {"dir":"~/.local/share/sensei-top"}');
    expect(text).not.toContain('/home/sample');
  });
});
