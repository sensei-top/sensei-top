import { EventEmitter } from 'node:events';
import { createClient } from '@supabase/supabase-js';
import { describe, expect, it } from 'vitest';
import {
  afterFilter,
  BATCH_SIZE,
  changedPayloads,
  CLIENT_HEADER,
  CloudSync,
  cursorAfter,
  emptyState,
  jsonbTextBytes,
  localSyncApi,
  LocalApiError,
  MatchEndWatch,
  MAX_PAYLOAD_BYTES,
  overlapStart,
  parseState,
  PULL_OVERLAP_MS,
  readPayloads,
  RETRY_LIMIT,
  RETRY_MS,
  SERVER_NOW,
  supabaseSyncDb,
  timeMicros,
  waitForPort,
  type CloudMatchRow,
  type DeviceRow,
  type LocalPayload,
  type LocalSyncApi,
  type PullCursor,
  type PulledRow,
  type StateFile,
  type SyncDb,
  type SyncState,
} from './sync';

// Made-up identifiers only: no real account, project or match.
const USER = '00000000-0000-4000-8000-0000000000a1';
const OTHER = '00000000-0000-4000-8000-0000000000b2';
const INSTALL = '00000000-0000-4000-8000-0000000000c3';
const SUPABASE_URL = 'https://project.example.invalid';

function payload(n: number, digest = `d${n}`): LocalPayload {
  return {
    match_id: `m${String(n).padStart(4, '0')}`,
    source: n % 2 === 0 ? 'arena' : 'mtgo',
    played_at: '2026-01-02T03:04:05Z',
    digest,
    payload: { schema_version: 1, result: 'win', opp_cards: [] },
  };
}

function pulledRow(n: number, updatedAt: string): PulledRow {
  return {
    match_id: `p${String(n).padStart(4, '0')}`,
    source: 'arena',
    played_at: null,
    payload: { schema_version: 1 },
    schema_version: 1,
    updated_at: updatedAt,
    deleted_at: null,
  };
}

function memoryFile(initial: string | null = null): StateFile & { text: string | null; writes: number; failWrites: boolean } {
  const file = {
    text: initial,
    writes: 0,
    failWrites: false,
    read: () => file.text,
    write: (text: string) => {
      if (file.failWrites) throw new Error('disk full');
      file.writes++;
      file.text = text;
    },
    remove: () => {
      file.text = null;
    },
  };
  return file;
}

interface FakeDb extends SyncDb {
  batches: CloudMatchRow[][];
  devices: DeviceRow[];
  pulls: Array<PullCursor | null>;
  /** Rows the cloud holds, in `(updated_at, match_id)` order. */
  cloud: PulledRow[];
  /** Fails the upsert call with this number (1-based), once. */
  failUpsert: number | null;
}

function fakeDb(): FakeDb {
  let calls = 0;
  const db: FakeDb = {
    batches: [],
    devices: [],
    pulls: [],
    cloud: [],
    failUpsert: null,
    async upsertMatches(rows) {
      calls++;
      if (db.failUpsert === calls) {
        db.failUpsert = null;
        throw new Error('503');
      }
      db.batches.push([...rows]);
    },
    async upsertDevice(row) {
      db.devices.push(row);
    },
    async pullMatches(userId, after, limit) {
      expect(userId).toBe(USER);
      db.pulls.push(after);
      // Compared as instants, as Postgres does, whatever the text's offset form.
      const at = (text: string) => Date.parse(text);
      const later = db.cloud.filter(
        (row) =>
          !after ||
          at(row.updated_at) > at(after.updatedAt) ||
          (at(row.updated_at) === at(after.updatedAt) && row.match_id > after.matchId),
      );
      return later.slice(0, limit);
    },
  };
  return db;
}

/** `ServerController` as a run sees it: a port while ready, a `state` event. */
class FakeServer extends EventEmitter {
  port: number | null = null;
  ready(port: number): void {
    this.port = port;
    this.emit('state');
  }
}

function harness(
  options: { payloads?: LocalPayload[]; file?: ReturnType<typeof memoryFile>; user?: string | null; localApi?: LocalSyncApi } = {},
) {
  const db = fakeDb();
  const file = options.file ?? memoryFile();
  const local = {
    payloads: options.payloads ?? [],
    puts: [] as PulledRow[][],
    failPayloads: false,
  };
  let user: string | null = options.user === undefined ? USER : options.user;
  let enabled = true;
  let statusCalls = 0;
  const timers: { fn: () => void; ms: number; cancelled: boolean }[] = [];
  const sync = new CloudSync({
    db,
    local: options.localApi ?? {
      payloads: async () => {
        if (local.failPayloads) throw new LocalApiError('down');
        return local.payloads;
      },
      putPulled: async (rows) => void local.puts.push([...rows]),
    },
    file,
    currentUser: () => user,
    enabled: () => enabled,
    installId: () => INSTALL,
    appVersion: '9.9.9',
    os: 'Linux 6.0',
    now: () => new Date('2026-02-03T04:05:06.000Z'),
    onStatus: () => void statusCalls++,
    after: (fn, ms) => {
      const timer = { fn, ms, cancelled: false };
      timers.push(timer);
      return () => (timer.cancelled = true);
    },
  });
  const state = (): SyncState => parseState(file.text ?? '');
  return {
    sync,
    db,
    file,
    local,
    state,
    setUser: (next: string | null) => (user = next),
    setEnabled: (on: boolean) => (enabled = on),
    statusCalls: () => statusCalls,
    /** Timers set, not cancelled and not yet fired. */
    waiting: () => timers.filter((t) => !t.cancelled),
    /** Fires the first waiting timer and waits for the run it starts. */
    fire: async () => {
      const timer = timers.find((t) => !t.cancelled);
      if (!timer) throw new Error('no timer is waiting');
      timer.cancelled = true;
      timer.fn();
      await sync.idle();
    },
  };
}

describe('the digest diff', () => {
  it('keeps the payloads whose digest differs from the one last pushed', () => {
    const items = [payload(1), payload(2), payload(3, 'new')];
    expect(changedPayloads(items, { m0001: 'd1', m0003: 'd3' }).map((p) => p.match_id)).toEqual(['m0002', 'm0003']);
  });

  it('pushes only what changed since the last run, and nothing on a second run', async () => {
    const h = harness({ payloads: [payload(1), payload(2)] });
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.db.batches.flat().map((r) => r.match_id)).toEqual(['m0001', 'm0002']);
    expect(h.state().digests).toEqual({ m0001: 'd1', m0002: 'd2' });

    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.db.batches).toHaveLength(1);

    h.local.payloads = [payload(1, 'd1-picked'), payload(2), payload(3)];
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.db.batches[1]!.map((r) => r.match_id)).toEqual(['m0001', 'm0003']);
    expect(h.state().digests).toEqual({ m0001: 'd1-picked', m0002: 'd2', m0003: 'd3' });
    expect(h.sync.status()).toMatchObject({ backedUp: 3, lastError: null, running: false, lastSyncAt: '2026-02-03T04:05:06.000Z' });
  });

  it('sends each row with the policy fields only, and the server-side time', async () => {
    const h = harness({ payloads: [payload(2)] });
    await h.sync.run({ userId: USER, pull: 'never' });
    const row = h.db.batches[0]![0]!;
    expect(row).toEqual({
      user_id: USER,
      match_id: 'm0002',
      source: 'arena',
      payload: { schema_version: 1, result: 'win', opp_cards: [] },
      schema_version: 1,
      played_at: '2026-01-02T03:04:05Z',
      updated_at: SERVER_NOW,
      deleted_at: null,
    });
    expect(h.db.devices).toEqual([{ user_id: USER, install_id: INSTALL, app_version: '9.9.9', os: 'Linux 6.0', last_seen: SERVER_NOW }]);
  });

  it('starts from an empty map for another account', async () => {
    const file = memoryFile(JSON.stringify({ ...emptyState(OTHER), digests: { m0001: 'd1' }, pulledAt: '2026-01-01T00:00:00Z' }));
    const h = harness({ payloads: [payload(1)], file });
    expect(h.sync.status().backedUp).toBe(0);
    await h.sync.run({ userId: USER, pull: 'ifNever' });
    expect(h.db.batches.flat().map((r) => r.match_id)).toEqual(['m0001']);
    expect(h.db.pulls).toEqual([null]);
    expect(h.state().userId).toBe(USER);
  });

  it('leaves out a payload over the cloud limit, so it fails no batch', async () => {
    const big = payload(5);
    big.payload = { schema_version: 1, opp_cards: Array.from({ length: 400 }, (_, i) => `Card ${i}`) };
    expect(jsonbTextBytes(big.payload)).toBeGreaterThan(MAX_PAYLOAD_BYTES);
    const h = harness({ payloads: [payload(1), big] });
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.db.batches.flat().map((r) => r.match_id)).toEqual(['m0001']);
    expect(h.state().digests).toEqual({ m0001: 'd1' });
  });
});

describe('jsonb text size', () => {
  it('counts the space Postgres writes after each colon and comma', () => {
    // {"a": 1, "b": [1, 2]} is 21 bytes; a non-ASCII letter is two.
    expect(jsonbTextBytes({ a: 1, b: [1, 2] })).toBe(21);
    expect(jsonbTextBytes({})).toBe(2);
    expect(jsonbTextBytes([])).toBe(2);
    expect(jsonbTextBytes({ n: null, s: 'é' })).toBe('{"n": null, "s": "é"}'.length + 1);
  });
});

describe('batching', () => {
  it(`upserts in batches of ${BATCH_SIZE}`, async () => {
    const items = Array.from({ length: 250 }, (_, i) => payload(i));
    const h = harness({ payloads: items });
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.db.batches.map((b) => b.length)).toEqual([100, 100, 50]);
    expect(h.db.batches.flat().map((r) => r.match_id)).toEqual(items.map((p) => p.match_id));
    expect(Object.keys(h.state().digests)).toHaveLength(250);
  });
});

describe('a failed push', () => {
  it('keeps every accepted digest and pushes the rest on the next trigger', async () => {
    const items = Array.from({ length: 250 }, (_, i) => payload(i));
    const file = memoryFile(JSON.stringify({ ...emptyState(USER), digests: { old: 'x' } }));
    const h = harness({ payloads: items, file });
    h.db.failUpsert = 2;
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.sync.status().lastError).toBe('cloud');
    const kept = h.state().digests;
    expect(kept.old).toBe('x');
    expect(Object.keys(kept)).toHaveLength(101);
    expect(h.state().lastSyncAt).toBeNull();
    expect(h.db.devices).toEqual([]);

    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.sync.status().lastError).toBeNull();
    const second = h.db.batches.slice(1).flat().map((r) => r.match_id);
    expect(second).toEqual(items.slice(100).map((p) => p.match_id));
    expect(Object.keys(h.state().digests)).toHaveLength(251);
  });

  it('keeps the map on disk when the local API is down', async () => {
    const before = JSON.stringify({ ...emptyState(USER), digests: { m0001: 'd1' } });
    const h = harness({ payloads: [payload(2)], file: memoryFile(before) });
    h.local.failPayloads = true;
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.sync.status().lastError).toBe('localApi');
    expect(h.file.text).toBe(before);
    expect(h.db.batches).toEqual([]);
  });

  it('keeps the previous map when the state cannot be written', async () => {
    const before = JSON.stringify({ ...emptyState(USER), digests: { m0001: 'd1' } });
    const h = harness({ payloads: [payload(2)], file: memoryFile(before) });
    h.file.failWrites = true;
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.sync.status().lastError).toBe('disk');
    expect(h.file.text).toBe(before);
    h.file.failWrites = false;
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.state().digests).toEqual({ m0001: 'd1', m0002: 'd2' });
  });

  it('stops at the next step when the account changes or the backup is turned off', async () => {
    const items = Array.from({ length: 150 }, (_, i) => payload(i));
    const h = harness({ payloads: items });
    h.db.upsertMatches = async (rows) => {
      h.db.batches.push([...rows]);
      h.setUser(OTHER);
    };
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.db.batches).toHaveLength(1);
    expect(h.sync.status().lastError).toBeNull();

    const off = harness({ payloads: [payload(1)] });
    off.setEnabled(false);
    await off.sync.run({ userId: USER, pull: 'never' });
    expect(off.db.batches).toEqual([]);
  });
});

describe('the pull cursor', () => {
  it('pages after the last row of each page, ties included, and keeps the cursor', async () => {
    const h = harness();
    // 150 rows written by one statement share one time; 30 later ones.
    const tied = Array.from({ length: 150 }, (_, i) => pulledRow(i, '2026-01-05T10:00:00.123456+00:00'));
    const later = Array.from({ length: 30 }, (_, i) => pulledRow(200 + i, '2026-01-06T10:00:00.5+00:00'));
    h.db.cloud = [...tied, ...later];
    await h.sync.run({ userId: USER, pull: 'ifNever' });
    expect(h.local.puts.map((p) => p.length)).toEqual([100, 80]);
    expect(h.local.puts.flat().map((r) => r.match_id)).toEqual(h.db.cloud.map((r) => r.match_id));
    expect(h.db.pulls).toEqual([null, { updatedAt: '2026-01-05T10:00:00.123456+00:00', matchId: 'p0099' }]);
    expect(h.state().cursor).toEqual({ updatedAt: '2026-01-06T10:00:00.5+00:00', matchId: 'p0229' });
    expect(h.state().pulledAt).toBe('2026-02-03T04:05:06.000Z');
  });

  it('pulls at a sign-in only on an install that never pulled, and at every start from the cursor', async () => {
    const h = harness();
    h.db.cloud = [pulledRow(1, '2026-01-05T10:00:00+00:00')];
    await h.sync.run({ userId: USER, pull: 'ifNever' });
    expect(h.db.pulls).toEqual([null]);

    await h.sync.run({ userId: USER, pull: 'ifNever' });
    expect(h.db.pulls).toHaveLength(1);

    h.db.cloud.push({ ...pulledRow(2, '2026-01-07T10:00:00+00:00'), deleted_at: '2026-01-07T10:00:00+00:00' });
    await h.sync.run({ userId: USER, pull: 'always' });
    // Five minutes before the cursor, so the cursor's own row comes again.
    expect(h.db.pulls[1]).toEqual({ updatedAt: '2026-01-05T09:55:00.000Z', matchId: '' });
    expect(h.local.puts.at(-1)?.map((r) => [r.match_id, r.deleted_at])).toEqual([
      ['p0001', null],
      ['p0002', '2026-01-07T10:00:00+00:00'],
    ]);
    expect(h.state().cursor).toEqual({ updatedAt: '2026-01-07T10:00:00+00:00', matchId: 'p0002' });
  });

  it('counts an empty pull as a pull', async () => {
    const h = harness();
    await h.sync.run({ userId: USER, pull: 'ifNever' });
    expect(h.state().pulledAt).not.toBeNull();
    expect(h.state().cursor).toBeNull();
    expect(h.local.puts).toEqual([]);
  });

  it('keeps the cursor of each page handed over when a later page fails', async () => {
    const h = harness();
    h.db.cloud = Array.from({ length: 120 }, (_, i) => pulledRow(i, `2026-01-05T10:00:${String(i % 60).padStart(2, '0')}+00:00`));
    h.db.cloud.sort((a, b) => (a.updated_at === b.updated_at ? (a.match_id < b.match_id ? -1 : 1) : a.updated_at < b.updated_at ? -1 : 1));
    let calls = 0;
    const pull = h.db.pullMatches.bind(h.db);
    h.db.pullMatches = async (...args) => {
      if (++calls === 2) throw new Error('timeout');
      return pull(...args);
    };
    await h.sync.run({ userId: USER, pull: 'always' });
    expect(h.sync.status().lastError).toBe('cloud');
    const last = h.db.cloud[99]!;
    expect(h.state().cursor).toEqual({ updatedAt: last.updated_at, matchId: last.match_id });
    expect(h.state().pulledAt).toBeNull();
  });

  it('pulls again the five minutes before the cursor, catching a row that committed late', async () => {
    const file = memoryFile(
      JSON.stringify({ ...emptyState(USER), cursor: { updatedAt: '2026-01-05T10:00:00+00:00', matchId: 'p0005' }, pulledAt: '2026-01-05T10:00:01Z' }),
    );
    const h = harness({ file });
    h.db.cloud = [
      pulledRow(1, '2026-01-05T09:50:00+00:00'), // before the window: not pulled again
      pulledRow(7, '2026-01-05T09:58:00+00:00'), // committed after the cursor moved past its time
      pulledRow(5, '2026-01-05T10:00:00+00:00'), // the cursor's row, pulled again
      pulledRow(9, '2026-01-05T10:03:00+00:00'),
    ];
    await h.sync.run({ userId: USER, pull: 'always' });
    expect(h.db.pulls).toEqual([{ updatedAt: '2026-01-05T09:55:00.000Z', matchId: '' }]);
    expect(h.local.puts.flat().map((r) => r.match_id)).toEqual(['p0007', 'p0005', 'p0009']);
    expect(h.state().cursor).toEqual({ updatedAt: '2026-01-05T10:03:00+00:00', matchId: 'p0009' });
  });

  it('never moves the cursor back over a window with nothing new', async () => {
    const cursor = { updatedAt: '2026-01-05T10:00:00+00:00', matchId: 'p0005' };
    const h = harness({ file: memoryFile(JSON.stringify({ ...emptyState(USER), cursor, pulledAt: '2026-01-05T10:00:01Z' })) });
    h.db.cloud = [pulledRow(3, '2026-01-05T09:57:00+00:00'), pulledRow(5, '2026-01-05T10:00:00+00:00')];
    await h.sync.run({ userId: USER, pull: 'always' });
    expect(h.local.puts.flat().map((r) => r.match_id)).toEqual(['p0003', 'p0005']);
    expect(h.state().cursor).toEqual(cursor);
  });

  it('uploads again a match the pull finds deleted, and only that one', async () => {
    const state = { ...emptyState(USER), digests: { m0001: 'd1', m0002: 'd2' }, cursor: null, pulledAt: '2026-01-05T10:00:01Z' };
    const h = harness({ payloads: [payload(1), payload(2)], file: memoryFile(JSON.stringify(state)) });
    h.db.cloud = [
      { ...pulledRow(1, '2026-01-06T10:00:00+00:00'), match_id: 'm0001', deleted_at: '2026-01-06T10:00:00+00:00' },
      { ...pulledRow(2, '2026-01-06T10:00:00+00:00'), match_id: 'm0002' },
    ];
    await h.sync.run({ userId: USER, pull: 'always' });
    expect(h.db.batches.flat().map((r) => r.match_id)).toEqual(['m0001']);
    expect(h.state().digests).toEqual({ m0001: 'd1', m0002: 'd2' });
  });

  it('is idle once the run and the one merged into it are done', async () => {
    const h = harness({ payloads: [payload(1)] });
    let idle = false;
    const run = h.sync.run({ userId: USER, pull: 'never' });
    void h.sync.run({ userId: USER, pull: 'never' });
    const waiting = h.sync.idle().then(() => (idle = true));
    expect(idle).toBe(false);
    await run;
    await waiting;
    expect(h.sync.status().running).toBe(false);
    expect(await h.sync.idle()).toBeUndefined();
  });

  it('reads the times Postgres prints, to the microsecond', () => {
    const base = Date.parse('2026-01-05T10:00:00Z') * 1000;
    expect(timeMicros('2026-01-05T10:00:00+00:00')).toBe(base);
    expect(timeMicros('2026-01-05 10:00:00.123456+00')).toBe(base + 123_456);
    expect(timeMicros('2026-01-05T10:00:00.5Z')).toBe(base + 500_000);
    expect(timeMicros('2026-01-05T07:00:00-03:00')).toBe(base);
    expect(timeMicros('2026-01-05T10:00:00')).toBeNull();
    expect(timeMicros('yesterday')).toBeNull();
    expect(cursorAfter({ updatedAt: '2026-01-05T10:00:00.000001+00:00', matchId: 'a' }, { updatedAt: '2026-01-05T10:00:00+00:00', matchId: 'z' })).toBe(true);
    expect(cursorAfter({ updatedAt: '2026-01-05T10:00:00Z', matchId: 'b' }, { updatedAt: '2026-01-05T10:00:00+00:00', matchId: 'a' })).toBe(true);
    expect(cursorAfter({ updatedAt: 'x', matchId: 'b' }, { updatedAt: '2026-01-05T10:00:00+00:00', matchId: 'a' })).toBeNull();
    expect(PULL_OVERLAP_MS).toBe(300_000);
    expect(overlapStart({ updatedAt: 'not a time', matchId: 'm' })).toEqual({ updatedAt: 'not a time', matchId: 'm' });
  });

  it('builds the filter for rows after the cursor, values quoted', () => {
    expect(afterFilter({ updatedAt: '2026-01-05T10:00:00.1+00:00', matchId: 'a"b' })).toBe(
      'updated_at.gt."2026-01-05T10:00:00.1+00:00",and(updated_at.eq."2026-01-05T10:00:00.1+00:00",match_id.gt."a\\"b")',
    );
  });
});

describe('runs', () => {
  it('merges a run asked for while one runs into one more run', async () => {
    const h = harness({ payloads: [payload(1)] });
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const upsert = h.db.upsertMatches.bind(h.db);
    h.db.upsertMatches = async (rows) => {
      await gate;
      return upsert(rows);
    };
    const first = h.sync.run({ userId: USER, pull: 'never' });
    expect(h.sync.status().running).toBe(true);
    void h.sync.run({ userId: USER, pull: 'never' });
    void h.sync.run({ userId: USER, pull: 'ifNever' });
    release();
    await first;
    expect(h.sync.status().running).toBe(false);
    expect(h.db.devices).toHaveLength(2);
    expect(h.db.pulls).toEqual([null]);
  });

  it('forgets the map and the cursor on clear', async () => {
    const h = harness({ payloads: [payload(1)] });
    await h.sync.run({ userId: USER, pull: 'ifNever' });
    await h.sync.clear();
    expect(h.file.text).toBeNull();
    expect(h.sync.status().backedUp).toBe(0);
  });
});

describe('a run the local API failed', () => {
  it('is tried again later, and a retry that succeeds clears the error', async () => {
    const h = harness({ payloads: [payload(1)] });
    h.local.failPayloads = true;
    await h.sync.run({ userId: USER, pull: 'ifNever' });
    expect(h.sync.status().lastError).toBe('localApi');
    expect(h.waiting().map((t) => t.ms)).toEqual([RETRY_MS]);

    h.local.failPayloads = false;
    await h.fire();
    expect(h.sync.status().lastError).toBeNull();
    expect(h.sync.status().backedUp).toBe(1);
    expect(h.waiting()).toHaveLength(0);
  });

  it('stops retrying after RETRY_LIMIT failures in a row', async () => {
    const h = harness({ payloads: [payload(1)] });
    h.local.failPayloads = true;
    await h.sync.run({ userId: USER, pull: 'never' });
    for (let i = 0; i < RETRY_LIMIT; i++) {
      await h.fire();
    }
    expect(h.waiting()).toHaveLength(0);
    expect(h.sync.status().lastError).toBe('localApi');
  });

  it('is dropped when another run starts first', async () => {
    const h = harness({ payloads: [payload(1)] });
    h.local.failPayloads = true;
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.waiting()).toHaveLength(1);
    h.local.failPayloads = false;
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.waiting()).toHaveLength(0);
  });

  it('is not tried again when the cloud failed', async () => {
    const h = harness({ payloads: [payload(1)] });
    h.db.failUpsert = 1;
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.sync.status().lastError).toBe('cloud');
    expect(h.waiting()).toHaveLength(0);
  });
});

describe('the state file', () => {
  it('drops what it cannot read, never guessing', () => {
    expect(parseState(JSON.stringify({ version: 1, userId: USER, digests: { a: 'x', b: 3 }, cursor: { updatedAt: 'x' } }))).toEqual({
      ...emptyState(USER),
      digests: { a: 'x' },
    });
    expect(() => parseState('{"version":2}')).toThrow();
  });

  it('starts from none when the file is not JSON', async () => {
    const h = harness({ payloads: [payload(1)], file: memoryFile('not json') });
    await h.sync.run({ userId: USER, pull: 'never' });
    expect(h.state().digests).toEqual({ m0001: 'd1' });
  });
});

describe('the local API', () => {
  it('reads the payloads and leaves out an item missing a field', () => {
    const good = payload(1);
    expect(readPayloads([good, { ...good, digest: '' }, { ...good, payload: { result: 'win' } }, 'x'])).toEqual([good]);
    expect(() => readPayloads({})).toThrow(LocalApiError);
  });

  it('puts the pulled rows with the client header, and refuses without a server', async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const server = new FakeServer();
    server.port = 4100;
    const api = localSyncApi(
      async (url, init) => {
        calls.push({ url, init });
        return new Response(url.endsWith('/payloads') ? JSON.stringify([payload(1)]) : '{}', { status: 200 });
      },
      server,
      undefined,
      undefined,
      20,
    );
    expect(await api.payloads()).toEqual([payload(1)]);
    await api.putPulled([pulledRow(1, '2026-01-05T10:00:00+00:00')]);
    expect(calls[0]!.url).toBe('http://127.0.0.1:4100/api/sync/payloads');
    expect(calls[1]!.url).toBe('http://127.0.0.1:4100/api/sync/pulled');
    expect(calls[1]!.init?.method).toBe('PUT');
    expect((calls[1]!.init?.headers as Record<string, string>)[CLIENT_HEADER]).toBeTruthy();
    expect(JSON.parse(String(calls[1]!.init?.body))).toEqual({ items: [pulledRow(1, '2026-01-05T10:00:00+00:00')] });
    server.port = null;
    await expect(api.payloads()).rejects.toThrow(LocalApiError);
    expect(server.listenerCount('state')).toBe(0);
  });

  it('turns a refused request into a local API error', async () => {
    const server = new FakeServer();
    server.port = 4100;
    const api = localSyncApi(async () => new Response('{}', { status: 403 }), server);
    await expect(api.putPulled([])).rejects.toThrow(LocalApiError);
  });
});

describe('waiting for the server', () => {
  it('answers at once while ready, else at its next ready state, else null after the limit', async () => {
    const server = new FakeServer();
    server.port = 4100;
    expect(await waitForPort(server, 10)).toBe(4100);
    server.port = null;
    const waiting = waitForPort(server, 60_000);
    server.emit('state');
    server.ready(4200);
    expect(await waiting).toBe(4200);
    server.port = null;
    expect(await waitForPort(server, 10)).toBeNull();
    expect(server.listenerCount('state')).toBe(0);
  });

  it('pushes a run started during a restart once the server is up', async () => {
    const server = new FakeServer();
    const urls: string[] = [];
    const api = localSyncApi(async (url) => {
      urls.push(url);
      return new Response(JSON.stringify([payload(1)]), { status: 200 });
    }, server);
    const h = harness({ localApi: api });
    const run = h.sync.run({ userId: USER, pull: 'never' });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(urls).toEqual([]);
    server.ready(4300);
    await run;
    expect(urls).toEqual(['http://127.0.0.1:4300/api/sync/payloads']);
    expect(h.db.batches.flat().map((r) => r.match_id)).toEqual(['m0001']);
    expect(h.sync.status().lastError).toBeNull();
  });
});

describe('the cloud adapter', () => {
  function client(answer: (url: URL) => Response = () => new Response(null, { status: 201 })) {
    const requests: Array<{ url: URL; method: string; headers: Headers; body: string | null }> = [];
    const supabase = createClient(SUPABASE_URL, 'anon-key-for-tests', {
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
      global: {
        fetch: async (input: string | URL | Request, init?: RequestInit) => {
          const url = new URL(input instanceof Request ? input.url : String(input));
          requests.push({ url, method: init?.method ?? 'GET', headers: new Headers(init?.headers), body: (init?.body as string | undefined) ?? null });
          return answer(url);
        },
      },
    });
    return { db: supabaseSyncDb(supabase), requests };
  }

  it('upserts matches on their key, the rows as given', async () => {
    const { db, requests } = client();
    const row: CloudMatchRow = {
      user_id: USER,
      match_id: 'm1',
      source: 'arena',
      payload: { schema_version: 1 },
      schema_version: 1,
      played_at: null,
      updated_at: SERVER_NOW,
      deleted_at: null,
    };
    await db.upsertMatches([row]);
    expect(requests).toHaveLength(1);
    const request = requests[0]!;
    expect(request.method).toBe('POST');
    expect(request.url.origin + request.url.pathname).toBe(`${SUPABASE_URL}/rest/v1/matches`);
    expect(request.url.searchParams.get('on_conflict')).toBe('user_id,match_id');
    expect(request.headers.get('Prefer')).toContain('resolution=merge-duplicates');
    expect(JSON.parse(request.body ?? '')).toEqual([row]);
  });

  it('upserts the device row on its key', async () => {
    const { db, requests } = client();
    await db.upsertDevice({ user_id: USER, install_id: INSTALL, app_version: '1', os: 'Linux 6', last_seen: SERVER_NOW });
    expect(requests[0]!.url.pathname).toBe('/rest/v1/devices');
    expect(requests[0]!.url.searchParams.get('on_conflict')).toBe('user_id,install_id');
  });

  it('pulls in key order after the cursor', async () => {
    const { db, requests } = client(() => new Response(JSON.stringify([pulledRow(1, 't')]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    expect(await db.pullMatches(USER, null, 100)).toEqual([pulledRow(1, 't')]);
    await db.pullMatches(USER, { updatedAt: '2026-01-05T10:00:00+00:00', matchId: 'm1' }, 100);
    const [first, second] = requests.map((r) => r.url.searchParams) as [URLSearchParams, URLSearchParams];
    expect(first.get('select')).toBe('match_id,source,played_at,payload,schema_version,updated_at,deleted_at');
    expect(first.get('user_id')).toBe(`eq.${USER}`);
    expect(first.get('order')).toBe('updated_at.asc,match_id.asc');
    expect(first.get('limit')).toBe('100');
    expect(first.get('or')).toBeNull();
    expect(second.get('or')).toBe(`(${afterFilter({ updatedAt: '2026-01-05T10:00:00+00:00', matchId: 'm1' })})`);
  });

  it('throws on an error answer', async () => {
    const { db } = client(() => new Response(JSON.stringify({ message: 'no', code: '42501' }), { status: 403, headers: { 'Content-Type': 'application/json' } }));
    await expect(db.upsertMatches([])).rejects.toThrow(/42501/);
  });
});

describe('the match-end trigger', () => {
  it('fires once when the tray leaves its game state', () => {
    const watch = new MatchEndWatch();
    const now = Date.parse('2026-01-05T10:00:00Z');
    const at = (ms: number) => ({ last_event_at: new Date(ms).toISOString() });
    expect(watch.note(at(now - 120_000), now)).toBe(false);
    expect(watch.note(at(now - 1_000), now)).toBe(false);
    expect(watch.note(null, now)).toBe(false);
    expect(watch.note(at(now - 1_000), now + 30_000)).toBe(false);
    expect(watch.note(at(now - 1_000), now + 70_000)).toBe(true);
    expect(watch.note(at(now - 1_000), now + 75_000)).toBe(false);
  });
});
