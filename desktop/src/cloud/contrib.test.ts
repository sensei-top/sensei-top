import { EventEmitter } from 'node:events';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import type { Contribute } from '../store';
import {
  anonContribSender,
  CONTRIB_BATCH_SIZE,
  contribAnswer,
  contributedFile,
  Contributor,
  ContribSendError,
  localContribApi,
  parseContributed,
  type LocalContribApi,
  type LocalRecord,
  type WireRecord,
} from './contrib';
import type { StateFile } from './sync';

// Made-up values only: no real project, key or game.
const URL_BASE = 'https://project.example.invalid';
const ANON = 'anon-key-stand-in';
const YES: Contribute = { yes: true, policyVersion: '2026-11-01', answeredAt: '2026-11-02T00:00:00.000Z', ageConfirmed: true };

function keysFor(n: number): string[] {
  return Array.from({ length: n }, (_, i) => `m${String(i).padStart(3, '0')}:1`);
}

function localWith(keys: string[], calls: string[][] = []): LocalContribApi {
  return {
    async keys() {
      return keys;
    },
    async records(asked) {
      calls.push([...asked]);
      return asked.map((key): LocalRecord => ({ key, record: { schema_version: 1, client: 'arena', result: 'win' } }));
    },
  };
}

function memoryFile(initial: string | null = null): StateFile & { text: string | null; writes: string[] } {
  const file = {
    text: initial,
    writes: [] as string[],
    read() {
      return file.text;
    },
    write(text: string) {
      file.writes.push(text);
      file.text = text;
    },
    remove() {
      file.text = null;
    },
  };
  return file;
}

function markedKeys(file: { text: string | null }): string[] {
  return file.text === null ? [] : [...parseContributed(file.text)];
}

let counter = 0;
const makeId = (): string => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`;

const dirs: string[] = [];
afterEach(() => {
  for (const dir of dirs.splice(0)) fs.rmSync(dir, { recursive: true, force: true });
});

describe('anonContribSender', () => {
  it('posts the records with the anon key and no session', async () => {
    let seen: { url: string; init: RequestInit } | null = null;
    const send = anonContribSender({ url: `${URL_BASE}/`, anonKey: ANON }, async (url, init) => {
      seen = { url, init: init ?? {} };
      return new Response(null, { status: 200 });
    });
    const record: WireRecord = { id: makeId(), schema_version: 1, policy_version: '2026-11-01', record: { schema_version: 1 } };
    await send([record], new AbortController().signal);
    const headers = (seen!.init.headers ?? {}) as Record<string, string>;
    expect(seen!.url).toBe(`${URL_BASE}/rest/v1/rpc/contribute_games`);
    expect(seen!.init.method).toBe('POST');
    expect(headers.apikey).toBe(ANON);
    // the only bearer is the anon key itself: a session would be refused (42501)
    expect(headers.Authorization).toBe(`Bearer ${ANON}`);
    expect(Object.keys(headers).map((k) => k.toLowerCase()).filter((k) => k === 'authorization')).toHaveLength(1);
    expect(JSON.parse(seen!.init.body as string)).toEqual({ records: [record] });
  });

  it('turns a refusal into an error carrying the code', async () => {
    const send = anonContribSender({ url: URL_BASE, anonKey: ANON }, async () => new Response(JSON.stringify({ code: '22023', message: 'x' }), { status: 400 }));
    await expect(send([], new AbortController().signal)).rejects.toMatchObject({ code: '22023' });
  });
});

describe('Contributor', () => {
  it('sends the unsent games in batches of 50 and marks them after success', async () => {
    const calls: string[][] = [];
    const sent: WireRecord[][] = [];
    const file = memoryFile();
    const keys = keysFor(120);
    const c = new Contributor({
      local: localWith(keys, calls),
      send: async (records) => {
        sent.push([...records]);
      },
      file,
      answer: () => YES,
      makeId,
    });
    await c.run();
    expect(calls.map((batch) => batch.length)).toEqual([CONTRIB_BATCH_SIZE, CONTRIB_BATCH_SIZE, 20]);
    expect(sent.map((batch) => batch.length)).toEqual([50, 50, 20]);
    expect(markedKeys(file).sort()).toEqual([...keys].sort());
    expect(sent.flat().every((r) => r.policy_version === '2026-11-01' && r.schema_version === 1)).toBe(true);
    // every code is different
    expect(new Set(sent.flat().map((r) => r.id)).size).toBe(120);
  });

  it('skips the keys already marked', async () => {
    const calls: string[][] = [];
    const file = memoryFile(JSON.stringify({ version: 1, keys: ['m000:1', 'm001:1'] }));
    const c = new Contributor({ local: localWith(keysFor(3), calls), send: async () => {}, file, answer: () => YES, makeId });
    await c.run();
    expect(calls).toEqual([['m002:1']]);
  });

  it('marks no key when the call fails, and the next run sends them again', async () => {
    const file = memoryFile();
    let fail = true;
    let attempts = 0;
    const c = new Contributor({
      local: localWith(keysFor(2)),
      send: async () => {
        attempts++;
        if (fail) throw new ContribSendError('down', '');
      },
      file,
      answer: () => YES,
      makeId,
    });
    await c.run();
    expect(file.writes).toEqual([]);
    fail = false;
    await c.run();
    expect(attempts).toBe(2);
    expect(markedKeys(file)).toHaveLength(2);
  });

  it('sends nothing without a yes, or a yes without the age confirmation', async () => {
    let sends = 0;
    let keyReads = 0;
    const local: LocalContribApi = { ...localWith(keysFor(2)), keys: async () => (keyReads++, keysFor(2)) };
    for (const answer of [null, undefined, { ...YES, yes: false }, { ...YES, ageConfirmed: false }]) {
      const c = new Contributor({ local, send: async () => void sends++, file: memoryFile(), answer: () => answer, makeId });
      await c.run();
    }
    expect(sends).toBe(0);
    expect(keyReads).toBe(0);
  });

  it('aborts at once when turned off: the in-flight answer is discarded and its keys not marked', async () => {
    const file = memoryFile();
    let answer: Contribute = YES;
    let release!: () => void;
    let aborted = false;
    let sends = 0;
    const c = new Contributor({
      local: localWith(keysFor(120)),
      send: (_records, signal) => {
        sends++;
        signal.addEventListener('abort', () => (aborted = true));
        // the response arrives only after the user turned it off
        return new Promise<void>((resolve) => {
          release = resolve;
        });
      },
      file,
      answer: () => answer,
      makeId,
    });
    const run = c.run();
    await new Promise((r) => setTimeout(r, 5));
    expect(sends).toBe(1);
    answer = { ...YES, yes: false };
    c.stop();
    expect(aborted).toBe(true);
    release();
    await run;
    expect(sends).toBe(1);
    expect(file.writes).toEqual([]);
  });

  it('retries a refused batch one record at a time with fresh codes and leaves out the one refused alone', async () => {
    const file = memoryFile();
    const keys = keysFor(3);
    const badKey = keys[1]!;
    const local: LocalContribApi = {
      keys: async () => keys,
      records: async (asked) => asked.map((key): LocalRecord => ({ key, record: { schema_version: 1, game: key } })),
    };
    const calls: WireRecord[][] = [];
    const c = new Contributor({
      local,
      send: async (records) => {
        calls.push([...records]);
        if (records.length > 1 || records[0]?.record.game === badKey) throw new ContribSendError('bad', '22023');
      },
      file,
      answer: () => YES,
      makeId,
    });
    await c.run();
    expect(calls.map((call) => call.length)).toEqual([3, 1, 1, 1]);
    const ids = calls.flat().map((r) => r.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(markedKeys(file).sort()).toEqual([keys[0], keys[2]].sort());
  });

  it('merges a run asked for during a run into the next one', async () => {
    let keyReads = 0;
    const local: LocalContribApi = { ...localWith(keysFor(1)), keys: async () => (keyReads++, keysFor(1)) };
    const c = new Contributor({ local, send: async () => {}, file: memoryFile(), answer: () => YES, makeId });
    const first = c.run();
    void c.run();
    void c.run();
    await first;
    await c.idle();
    expect(keyReads).toBe(2);
  });

  it('never writes a code to disk', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'contrib-test-'));
    dirs.push(dir);
    const sent: WireRecord[] = [];
    const c = new Contributor({
      local: localWith(keysFor(7)),
      send: async (records) => void sent.push(...records),
      file: contributedFile(dir),
      answer: () => YES,
      makeId: () => crypto.randomUUID(),
    });
    await c.run();
    expect(sent).toHaveLength(7);
    const files = fs.readdirSync(dir, { recursive: true, withFileTypes: true }).filter((e) => e.isFile());
    expect(files.map((e) => e.name)).toEqual(['contributed.json']);
    for (const entry of files) {
      const text = fs.readFileSync(path.join(entry.parentPath, entry.name), 'utf8');
      for (const record of sent) expect(text).not.toContain(record.id);
    }
    expect(parseContributed(fs.readFileSync(path.join(dir, 'contributed.json'), 'utf8')).size).toBe(7);
  });
});

describe('localContribApi', () => {
  it('reads the keys and asks for records with the policy version', async () => {
    const urls: string[] = [];
    const server = Object.assign(new EventEmitter(), { port: 4100 });
    const api = localContribApi(async (url) => {
      urls.push(url);
      return new Response(
        JSON.stringify(url.includes('/records') ? [{ key: 'a:1', record: { schema_version: 1 } }, { key: 3 }] : ['a:1', 7, 'b:2']),
        { status: 200 },
      );
    }, server);
    expect(await api.keys()).toEqual(['a:1', 'b:2']);
    expect(await api.records(['a:1', 'b:2'], '2026-11-01')).toEqual([{ key: 'a:1', record: { schema_version: 1 } }]);
    expect(urls[1]).toBe('http://127.0.0.1:4100/api/contrib/records?keys=a%3A1&keys=b%3A2&policy_version=2026-11-01');
  });
});

describe('contribAnswer', () => {
  const now = new Date('2026-11-04T00:00:00.000Z');
  it('accepts a well-formed answer and stamps the time', () => {
    expect(contribAnswer({ yes: true, policyVersion: '2026-11-01', ageConfirmed: true }, now)).toEqual({
      yes: true,
      policyVersion: '2026-11-01',
      answeredAt: now.toISOString(),
      ageConfirmed: true,
    });
    expect(contribAnswer({ yes: false, policyVersion: '2026-11-01', ageConfirmed: false }, now)?.yes).toBe(false);
  });
  it('refuses a yes without the age confirmation and any malformed input', () => {
    expect(contribAnswer({ yes: true, policyVersion: '2026-11-01', ageConfirmed: false }, now)).toBeNull();
    expect(contribAnswer({ yes: 'yes', policyVersion: '2026-11-01', ageConfirmed: true }, now)).toBeNull();
    expect(contribAnswer({ yes: true, policyVersion: '../x', ageConfirmed: true }, now)).toBeNull();
    expect(contribAnswer({ yes: true, policyVersion: '1.0', ageConfirmed: true }, now)).toBeNull();
    expect(contribAnswer(null, now)).toBeNull();
  });
});
