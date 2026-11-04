// The cloud backup of the match history, from the shell's main process: the
// local API's payloads go up to the account's `matches` table, and rows the
// account's other installs wrote come down into `PUT /api/sync/pulled`.
//
// - **Push.** Every payload comes with a digest; `sync-state.json` in
//   `userData` keeps the `match_id → digest` last pushed, and a payload whose
//   digest differs from it goes up, in batches of `BATCH_SIZE`. The map is
//   written after each batch the cloud accepted and never before, so a
//   failed batch leaves the previous map and the next run pushes it again.
// - **Pull.** Rows changed after the pull cursor, oldest first, in pages of
//   `BATCH_SIZE`, each page handed to the local API before the cursor moves
//   past it. The cursor is the last row's `(updated_at, match_id)`: rows one
//   statement wrote share one `updated_at`, so the time alone would skip the
//   rest of a page that ends inside a tie. Each pull starts `PULL_OVERLAP_MS`
//   before the cursor (trap below), and the cursor never moves back. A
//   pulled row marked deleted drops its match's digest, so the next push
//   uploads it again: a history deleted from another install comes back
//   from this one once the backup is on again.
// - **Device.** After a run, the install's `devices` row: its random ID, the
//   app version, the operating system and when it synced, nothing else.
//
// Traps and contracts:
// - `updated_at` and `last_seen` are sent as the string `'now'`, which
//   Postgres's timestamp input reads as the transaction's time: the server's
//   clock, never this machine's, so a machine whose clock is behind cannot
//   write a row below another install's cursor.
// - The transaction's time is when it started, not when it committed: a
//   transaction that commits after a pull has moved the cursor can still
//   carry an earlier `updated_at`. Each pull therefore starts
//   `PULL_OVERLAP_MS` before the cursor and pulls that window again. That is
//   harmless because `PUT /api/sync/pulled` is idempotent (an upsert, a
//   delete, a pick applied only when strictly newer). A transaction open
//   longer than the overlap can still be missed.
// - A push sends `deleted_at: null`: pushing a match puts it back in the
//   backup, which is what turning the backup on again after "Delete my cloud
//   history" (`account.ts`) needs.
// - The state belongs to one account: a different user's sign-in starts from
//   an empty map and no cursor.
// - The cloud refuses a payload over 4 KB (as `jsonb` text, which adds a
//   space after every `:` and `,`); one is left out with a warning, never
//   sent, so it cannot fail the batch it would be in.
// - Every row and request carries only what the privacy policy lists for
//   the backup ("Cloud backup of your match history"). A new field is a
//   policy change first.
//
// Electron-free: the cloud, the local API and the file are arguments, so
// vitest runs it under Node with fakes.

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { SupabaseClient } from '@supabase/supabase-js';
import { silent, type Logger } from '../log';
import { writeAtomically } from '../store';
import { GAME_WINDOW_MS, parseEventTime, type LiveSnapshot } from '../tray';

export const BATCH_SIZE = 100;
export const SYNC_STATE_FILE = 'sync-state.json';
/** `public.matches`' check on `octet_length(payload::text)`. */
export const MAX_PAYLOAD_BYTES = 4096;
/** Postgres's timestamp input for "the transaction's time". */
export const SERVER_NOW = 'now';
export const LOCAL_API_TIMEOUT_MS = 60_000;
/** The local API refuses a non-GET request without it (`api/guard.py`). */
export const CLIENT_HEADER = 'X-Tracker-Client';
/** How far before the cursor each pull starts (the commit-order trap above). */
export const PULL_OVERLAP_MS = 5 * 60_000;
/** How long a run waits for the local API while the server (re)starts:
 *  longer than the server's own 60 s ready limit. */
export const SERVER_WAIT_MS = 90_000;

/** One `GET /api/sync/payloads` item. */
export interface LocalPayload {
  match_id: string;
  source: 'arena' | 'mtgo';
  played_at: string | null;
  digest: string;
  payload: Record<string, unknown>;
}

/** One row of `public.matches` as a push writes it. */
export interface CloudMatchRow {
  user_id: string;
  match_id: string;
  source: 'arena' | 'mtgo';
  payload: Record<string, unknown>;
  schema_version: number;
  played_at: string | null;
  updated_at: typeof SERVER_NOW;
  deleted_at: null;
}

/** One row of `public.matches` as a pull reads it, and `PUT /api/sync/pulled` takes it. */
export interface PulledRow {
  match_id: string;
  source: string;
  played_at: string | null;
  payload: unknown;
  schema_version: number;
  updated_at: string;
  deleted_at: string | null;
}

export interface DeviceRow {
  user_id: string;
  install_id: string;
  app_version: string;
  os: string;
  last_seen: typeof SERVER_NOW;
}

export interface PullCursor {
  updatedAt: string;
  matchId: string;
}

/** The cloud's half: `public.matches` and `public.devices`. */
export interface SyncDb {
  upsertMatches(rows: readonly CloudMatchRow[]): Promise<void>;
  upsertDevice(row: DeviceRow): Promise<void>;
  /** The user's rows after `after` (all of them when `null`), oldest first. */
  pullMatches(userId: string, after: PullCursor | null, limit: number): Promise<PulledRow[]>;
}

/** The local API's half. */
export interface LocalSyncApi {
  payloads(): Promise<LocalPayload[]>;
  putPulled(rows: readonly PulledRow[]): Promise<void>;
}

/** Where `sync-state.json` lives. `read` is `null` when there is no file. */
export interface StateFile {
  read(): string | null;
  write(text: string): void;
  remove(): void;
}

export class CloudError extends Error {
  override readonly name = 'CloudError';
}

export class LocalApiError extends Error {
  override readonly name = 'LocalApiError';
}

// ---- the adapters ----------------------------------------------------------

/** A PostgREST logic-tree value in double quotes: a timestamp carries `.`
 *  and `:`, which the tree reserves. */
function quoted(value: string): string {
  return `"${value.replace(/[\\"]/g, (c) => `\\${c}`)}"`;
}

/** A timestamp as Postgres prints one (`2026-01-05 10:00:00.123456+00`, or
 *  ISO with `T` and `Z`), in microseconds; `null` for anything else. */
export function timeMicros(text: string): number | null {
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}(?::?\d{2})?)$/.exec(text);
  if (!match) return null;
  const [, date, time, fraction = '', zone = 'Z'] = match;
  const offset = zone === 'Z' ? 'Z' : zone.length === 3 ? `${zone}:00` : zone.length === 5 ? `${zone.slice(0, 3)}:${zone.slice(3)}` : zone;
  const ms = Date.parse(`${date}T${time}${offset}`);
  if (Number.isNaN(ms)) return null;
  return ms * 1000 + Number(fraction.padEnd(6, '0'));
}

/** Whether `a` is after `b` in `(updated_at, match_id)` order; `null` when a
 *  time cannot be read. */
export function cursorAfter(a: PullCursor, b: PullCursor): boolean | null {
  const at = timeMicros(a.updatedAt);
  const bt = timeMicros(b.updatedAt);
  if (at === null || bt === null) return null;
  return at !== bt ? at > bt : a.matchId > b.matchId;
}

/** Where a pull starts: `PULL_OVERLAP_MS` before `cursor`, every row at that
 *  time included (`match_id > ''`). `cursor` itself when its time cannot be read. */
export function overlapStart(cursor: PullCursor | null): PullCursor | null {
  if (!cursor) return null;
  const micros = timeMicros(cursor.updatedAt);
  if (micros === null) return cursor;
  return { updatedAt: new Date(Math.floor(micros / 1000) - PULL_OVERLAP_MS).toISOString(), matchId: '' };
}

/** The PostgREST filter for "after `cursor`" in `(updated_at, match_id)` order. */
export function afterFilter(cursor: PullCursor): string {
  const at = quoted(cursor.updatedAt);
  return `updated_at.gt.${at},and(updated_at.eq.${at},match_id.gt.${quoted(cursor.matchId)})`;
}

const PULLED_COLUMNS = 'match_id,source,played_at,payload,schema_version,updated_at,deleted_at';

function cloudFailure(what: string, error: { message?: string; code?: string } | null): CloudError {
  return new CloudError(`${what}: ${error?.code ?? ''} ${error?.message ?? 'no answer'}`.trim());
}

/** `SyncDb` on the shell's one supabase-js client (`CloudAuth.client`). */
export function supabaseSyncDb(client: SupabaseClient): SyncDb {
  return {
    async upsertMatches(rows) {
      const { error } = await client.from('matches').upsert([...rows], { onConflict: 'user_id,match_id' });
      if (error) throw cloudFailure('matches upsert', error);
    },
    async upsertDevice(row) {
      const { error } = await client.from('devices').upsert(row, { onConflict: 'user_id,install_id' });
      if (error) throw cloudFailure('devices upsert', error);
    },
    async pullMatches(userId, after, limit) {
      let query = client
        .from('matches')
        .select(PULLED_COLUMNS)
        .eq('user_id', userId)
        .order('updated_at', { ascending: true })
        .order('match_id', { ascending: true })
        .limit(limit);
      if (after) query = query.or(afterFilter(after));
      const { data, error } = await query;
      if (error) throw cloudFailure('matches select', error);
      return (data ?? []) as unknown as PulledRow[];
    },
  };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The items of a payloads answer that have every field a push needs. */
export function readPayloads(body: unknown, log: Logger = silent): LocalPayload[] {
  if (!Array.isArray(body)) throw new LocalApiError('the payloads answer is not a list');
  const out: LocalPayload[] = [];
  let dropped = 0;
  for (const item of body) {
    if (
      isObject(item) &&
      typeof item.match_id === 'string' &&
      item.match_id !== '' &&
      (item.source === 'arena' || item.source === 'mtgo') &&
      (item.played_at === null || typeof item.played_at === 'string') &&
      typeof item.digest === 'string' &&
      item.digest !== '' &&
      isObject(item.payload) &&
      Number.isInteger(item.payload.schema_version)
    ) {
      out.push({
        match_id: item.match_id,
        source: item.source,
        played_at: item.played_at,
        digest: item.digest,
        payload: item.payload,
      });
    } else dropped++;
  }
  if (dropped > 0) log.warn('sync: payloads without a field a push needs were left out', { count: dropped });
  return out;
}

/** The local server as a run waits on it: `ServerController` in the shell.
 *  `port` is `null` unless it is ready; `state` fires on every change. */
export interface ServerPort {
  readonly port: number | null;
  on(event: 'state', listener: () => void): unknown;
  off(event: 'state', listener: () => void): unknown;
}

/** The server's port once it is ready, or `null` after `timeoutMs`. */
export function waitForPort(server: ServerPort, timeoutMs: number): Promise<number | null> {
  if (server.port !== null) return Promise.resolve(server.port);
  return new Promise((resolve) => {
    const done = (): void => {
      clearTimeout(timer);
      server.off('state', check);
      resolve(server.port);
    };
    const check = (): void => {
      if (server.port !== null) done();
    };
    const timer = setTimeout(done, timeoutMs);
    timer.unref?.();
    server.on('state', check);
  });
}

/** `LocalSyncApi` on the local server. A request made while the server is
 *  (re)starting, as it is right after a consent change, waits for it to be
 *  ready, up to `serverWaitMs`. */
export function localSyncApi(
  fetch: (url: string, init?: RequestInit) => Promise<Response>,
  server: ServerPort,
  log: Logger = silent,
  timeoutMs = LOCAL_API_TIMEOUT_MS,
  serverWaitMs = SERVER_WAIT_MS,
): LocalSyncApi {
  const base = async (): Promise<string> => {
    const current = await waitForPort(server, serverWaitMs);
    if (current === null) throw new LocalApiError('the server was not ready in time');
    return `http://127.0.0.1:${current}`;
  };
  const call = async (url: string, init: RequestInit): Promise<Response> => {
    let response: Response;
    try {
      response = await fetch(url, { ...init, signal: AbortSignal.timeout(timeoutMs) });
    } catch (error) {
      throw new LocalApiError(`${init.method ?? 'GET'} ${new URL(url).pathname}: ${String(error)}`);
    }
    if (!response.ok) throw new LocalApiError(`${init.method ?? 'GET'} ${new URL(url).pathname}: HTTP ${response.status}`);
    return response;
  };
  return {
    async payloads() {
      const response = await call(`${await base()}/api/sync/payloads`, { method: 'GET' });
      let body: unknown;
      try {
        body = await response.json();
      } catch (error) {
        throw new LocalApiError(`the payloads answer is not JSON: ${String(error)}`);
      }
      return readPayloads(body, log);
    },
    async putPulled(rows) {
      await call(`${await base()}/api/sync/pulled`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', [CLIENT_HEADER]: 'shell' },
        body: JSON.stringify({ items: rows }),
      });
    },
  };
}

/** `sync-state.json` in `dir`, replaced through a temporary file. */
export function stateFile(dir: string): StateFile {
  const file = path.join(dir, SYNC_STATE_FILE);
  return {
    read() {
      try {
        return fs.readFileSync(file, 'utf8');
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
        throw error;
      }
    },
    write(text) {
      writeAtomically(file, text);
    },
    remove() {
      fs.rmSync(file, { force: true });
    },
  };
}

// ---- the state ---------------------------------------------------------------

export interface SyncState {
  version: 1;
  /** The account the map and the cursor belong to. */
  userId: string | null;
  /** `match_id → digest`, as last accepted by the cloud. */
  digests: Record<string, string>;
  cursor: PullCursor | null;
  /** When a pull last reached the end; `null`: this install never pulled for this account. */
  pulledAt: string | null;
  /** When a run last finished without an error. */
  lastSyncAt: string | null;
}

export function emptyState(userId: string | null): SyncState {
  return { version: 1, userId, digests: {}, cursor: null, pulledAt: null, lastSyncAt: null };
}

function stringOrNull(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null;
}

/** The state `text` holds; an unreadable part is dropped, never guessed. */
export function parseState(text: string): SyncState {
  const raw: unknown = JSON.parse(text);
  if (!isObject(raw) || raw.version !== 1) throw new SyntaxError('not a version 1 sync state');
  const digests: Record<string, string> = {};
  if (isObject(raw.digests)) {
    for (const [id, digest] of Object.entries(raw.digests)) {
      if (typeof digest === 'string' && digest !== '') digests[id] = digest;
    }
  }
  const cursor =
    isObject(raw.cursor) && stringOrNull(raw.cursor.updatedAt) && stringOrNull(raw.cursor.matchId)
      ? { updatedAt: raw.cursor.updatedAt as string, matchId: raw.cursor.matchId as string }
      : null;
  return {
    version: 1,
    userId: stringOrNull(raw.userId),
    digests,
    cursor,
    pulledAt: stringOrNull(raw.pulledAt),
    lastSyncAt: stringOrNull(raw.lastSyncAt),
  };
}

/** The payloads whose digest differs from the one last pushed. */
export function changedPayloads(payloads: readonly LocalPayload[], digests: Readonly<Record<string, string>>): LocalPayload[] {
  return payloads.filter((item) => digests[item.match_id] !== item.digest);
}

/** Bytes of `value` as Postgres writes `jsonb` as text: JSON with `", "` and
 *  `": "` between items. */
export function jsonbTextBytes(value: unknown): number {
  if (Array.isArray(value)) {
    if (value.length === 0) return 2;
    return 2 + value.reduce<number>((sum, item) => sum + jsonbTextBytes(item), 0) + 2 * (value.length - 1);
  }
  if (isObject(value)) {
    const entries = Object.entries(value).filter(([, item]) => item !== undefined);
    if (entries.length === 0) return 2;
    let sum = 2 + 2 * (entries.length - 1);
    for (const [key, item] of entries) sum += Buffer.byteLength(JSON.stringify(key)) + 2 + jsonbTextBytes(item);
    return sum;
  }
  return Buffer.byteLength(JSON.stringify(value) ?? 'null');
}

export function chunks<T>(items: readonly T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

// ---- the loop ------------------------------------------------------------------

/** `localApi`: the local server did not answer; `cloud`: the account's
 *  project did not; `disk`: `sync-state.json` could not be written. */
export type SyncError = 'localApi' | 'cloud' | 'disk';

/** What the page is shown of the backup. */
export interface SyncStatus {
  running: boolean;
  lastSyncAt: string | null;
  /** Matches this install has backed up for the signed-in account. */
  backedUp: number;
  /** Why the last run stopped; `null` after one that finished. */
  lastError: SyncError | null;
}

/** `always`: at an app start. `ifNever`: at a sign-in, only on an install that
 *  never pulled for this account. */
export type PullWhen = 'always' | 'ifNever' | 'never';

export interface SyncRunOptions {
  userId: string;
  pull: PullWhen;
}

export interface CloudSyncDeps {
  db: SyncDb;
  local: LocalSyncApi;
  file: StateFile;
  /** The signed-in account now: a run for another one stops at its next step. */
  currentUser(): string | null;
  /** Whether the backup is on (`consent_sync`): a run stops at its next step once it is off. */
  enabled(): boolean;
  installId(): string | null;
  appVersion: string;
  os: string;
  now(): Date;
  /** Called whenever `status()` may have changed. */
  onStatus(): void;
  log?: Logger;
}

const PULL_RANK: Record<PullWhen, number> = { never: 0, ifNever: 1, always: 2 };

class Stopped extends Error {}

class StateWriteError extends Error {}

export class CloudSync {
  private readonly log: Logger;
  private state: SyncState | null = null;
  private running: Promise<void> | null = null;
  private pending: SyncRunOptions | null = null;
  private lastError: SyncError | null = null;

  constructor(private readonly deps: CloudSyncDeps) {
    this.log = deps.log ?? silent;
  }

  status(): SyncStatus {
    const state = this.load();
    const user = this.deps.currentUser();
    const mine = user !== null && state.userId === user;
    return {
      running: this.running !== null,
      lastSyncAt: mine ? state.lastSyncAt : null,
      backedUp: mine ? Object.keys(state.digests).length : 0,
      lastError: this.lastError,
    };
  }

  /** Runs a sync; one asked for while one runs is merged into the next run.
   *  Resolves when no run is left; never rejects. */
  run(options: SyncRunOptions): Promise<void> {
    if (this.pending && this.pending.userId === options.userId) {
      this.pending = { userId: options.userId, pull: PULL_RANK[options.pull] > PULL_RANK[this.pending.pull] ? options.pull : this.pending.pull };
    } else this.pending = { ...options };
    this.running ??= this.drain();
    this.deps.onStatus();
    return this.running;
  }

  /** Resolves once no run is going or waiting; never rejects. */
  async idle(): Promise<void> {
    await this.running;
  }

  /** Forgets the map and the cursor (the account was deleted). */
  async clear(): Promise<void> {
    await this.running;
    this.pending = null;
    this.state = emptyState(null);
    this.lastError = null;
    try {
      this.deps.file.remove();
    } catch (error) {
      this.log.warn('sync: the sync state could not be removed', { error: String(error) });
    }
    this.deps.onStatus();
  }

  /** Trap: `running` is cleared in the same step that finds nothing pending,
   *  so a run asked for in between cannot be left waiting. */
  private async drain(): Promise<void> {
    try {
      while (this.pending) {
        const options = this.pending;
        this.pending = null;
        await this.once(options);
      }
    } finally {
      this.running = null;
      this.deps.onStatus();
    }
  }

  private load(): SyncState {
    if (this.state) return this.state;
    let text: string | null = null;
    try {
      text = this.deps.file.read();
    } catch (error) {
      this.log.warn('sync: the sync state could not be read; starting from none', { error: String(error) });
    }
    if (text === null) this.state = emptyState(null);
    else {
      try {
        this.state = parseState(text);
      } catch (error) {
        this.log.warn('sync: the sync state could not be parsed; starting from none', { error: String(error) });
        this.state = emptyState(null);
      }
    }
    return this.state;
  }

  /** Writes `next` and only then makes it the state; a failed write keeps the old one. */
  private commit(next: SyncState): void {
    try {
      this.deps.file.write(`${JSON.stringify(next)}\n`);
    } catch (error) {
      throw new StateWriteError(String(error));
    }
    this.state = next;
  }

  private checkUser(userId: string): void {
    if (this.deps.currentUser() !== userId) throw new Stopped('the account changed');
    if (!this.deps.enabled()) throw new Stopped('the backup was turned off');
  }

  private async once({ userId, pull }: SyncRunOptions): Promise<void> {
    try {
      this.checkUser(userId);
      let state = this.load();
      if (state.userId !== userId) {
        state = emptyState(userId);
        this.commit(state);
      }
      if (pull === 'always' || (pull === 'ifNever' && state.pulledAt === null)) await this.pull(userId);
      await this.push(userId);
      await this.device(userId);
      this.commit({ ...this.load(), lastSyncAt: this.deps.now().toISOString() });
      this.lastError = null;
    } catch (error) {
      if (error instanceof Stopped) {
        this.log.info('sync: stopped', { reason: error.message });
        return;
      }
      this.lastError = error instanceof LocalApiError ? 'localApi' : error instanceof StateWriteError ? 'disk' : 'cloud';
      this.log.warn('sync: the run stopped', { error: String(error), kind: this.lastError });
    }
  }

  private async pull(userId: string): Promise<void> {
    let pages = 0;
    let rows = 0;
    let after = overlapStart(this.load().cursor);
    for (;;) {
      this.checkUser(userId);
      const page = await this.deps.db.pullMatches(userId, after, BATCH_SIZE);
      const last = page.at(-1);
      if (last) {
        this.checkUser(userId);
        await this.deps.local.putPulled(page);
        after = { updatedAt: last.updated_at, matchId: last.match_id };
        const state = this.load();
        const digests = { ...state.digests };
        let dropped = false;
        for (const row of page) {
          if (row.deleted_at !== null && Object.hasOwn(digests, row.match_id)) {
            delete digests[row.match_id];
            dropped = true;
          }
        }
        // Inside the overlap a page can end before the stored cursor.
        const moves = !state.cursor || cursorAfter(after, state.cursor) !== false;
        if (moves || dropped) this.commit({ ...state, digests, cursor: moves ? after : state.cursor });
        pages++;
        rows += page.length;
      }
      if (page.length < BATCH_SIZE) break;
    }
    this.commit({ ...this.load(), pulledAt: this.deps.now().toISOString() });
    this.log.info('sync: pulled', { rows, pages });
  }

  private async push(userId: string): Promise<void> {
    const payloads = await this.deps.local.payloads();
    const changed = changedPayloads(payloads, this.load().digests);
    const sendable: LocalPayload[] = [];
    for (const item of changed) {
      if (jsonbTextBytes(item.payload) > MAX_PAYLOAD_BYTES) {
        this.log.warn('sync: a payload is over the cloud size limit and was not sent', { match: item.match_id });
      } else sendable.push(item);
    }
    let pushed = 0;
    for (const batch of chunks(sendable, BATCH_SIZE)) {
      this.checkUser(userId);
      await this.deps.db.upsertMatches(
        batch.map((item) => ({
          user_id: userId,
          match_id: item.match_id,
          source: item.source,
          payload: item.payload,
          schema_version: item.payload.schema_version as number,
          played_at: item.played_at,
          updated_at: SERVER_NOW,
          deleted_at: null,
        })),
      );
      const state = this.load();
      const digests = { ...state.digests };
      for (const item of batch) digests[item.match_id] = item.digest;
      this.commit({ ...state, digests });
      pushed += batch.length;
      this.deps.onStatus();
    }
    this.log.info('sync: pushed', { matches: pushed, of: payloads.length });
  }

  private async device(userId: string): Promise<void> {
    const installId = this.deps.installId();
    if (!installId) {
      this.log.warn('sync: no install ID, so no device row');
      return;
    }
    this.checkUser(userId);
    await this.deps.db.upsertDevice({
      user_id: userId,
      install_id: installId,
      app_version: this.deps.appVersion,
      os: this.deps.os,
      last_seen: SERVER_NOW,
    });
  }
}

/** The push trigger "a match ended" (DB6), from the tray's `/api/live`
 *  answers: the tray's `game` state (an event within `GAME_WINDOW_MS`) ending. */
export class MatchEndWatch {
  private inGame = false;

  /** `true` once, on the first answer after a game that is no longer one. A
   *  failed request (`null`) changes nothing. */
  note(live: LiveSnapshot | null, now: number): boolean {
    if (live === null) return false;
    const event = parseEventTime(live.last_event_at);
    const inGame = event !== null && Math.abs(now - event) <= GAME_WINDOW_MS;
    const ended = this.inGame && !inGame;
    this.inGame = inGame;
    return ended;
  }
}
