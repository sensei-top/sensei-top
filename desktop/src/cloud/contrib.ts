// Contributed games, from the shell's main process (plan 40b S13; DB12-DB14):
// when the user said yes, the finished games the local API lists and this
// install has not sent go to the hosted project as anonymous records.
//
// - **Queue.** `GET /api/contrib/games` lists every finished game's key; the
//   keys not in `contributed.json` (in `userData`) are fetched `BATCH_SIZE` at
//   a time and sent through `public.contribute_games`. A batch's keys are
//   written to `contributed.json` after the call succeeded and never before.
// - **Runs** at app start and when a match ends; a run asked for while one
//   runs is merged into the next.
//
// Traps and contracts:
// - The call carries the anon key and **no session**: the function is granted
//   to `anon` alone, so a signed-in client's call is refused (42501), and a
//   session header would also tie the record to an account. `anonContribSender`
//   is a plain `fetch`, never the signed-in client.
// - Each record gets a fresh `randomUUID()` for the call. The code is never
//   written anywhere (not to `contributed.json`, not to the log) and never
//   reused: a retry makes a new one.
// - `stop()` (the answer turned to no) aborts at once. A batch in flight has
//   its answer discarded and its keys are not marked: it was sent or it was
//   not, and either way nothing more goes.
// - One bad element refuses a whole call (22023 malformed, 54000 oversized);
//   such a batch is retried one record at a time, and a record refused alone
//   is left out of this run with a warning.
// - Nothing runs without `yes` and `ageConfirmed` together.
//
// Electron-free: the cloud, the local API and the file are arguments, so
// vitest runs it under Node with fakes.

import * as fs from 'node:fs';
import * as path from 'node:path';
import { silent, type Logger } from '../log';
import { writeAtomically, type Contribute } from '../store';
import {
  chunks,
  jsonbTextBytes,
  LOCAL_API_TIMEOUT_MS,
  LocalApiError,
  SERVER_WAIT_MS,
  waitForPort,
  type ServerPort,
  type StateFile,
} from './sync';

export const CONTRIB_BATCH_SIZE = 50;
export const CONTRIBUTED_FILE = 'contributed.json';
/** `contribute_games`' limit on `record::text`. */
export const MAX_RECORD_BYTES = 64 * 1024;
export const CONTRIB_SEND_TIMEOUT_MS = 60_000;

/** One element of `contribute_games`' argument. */
export interface WireRecord {
  id: string;
  schema_version: number;
  policy_version: string;
  record: Record<string, unknown>;
}

/** One `GET /api/contrib/records` item. */
export interface LocalRecord {
  key: string;
  record: Record<string, unknown>;
}

export interface LocalContribApi {
  keys(): Promise<string[]>;
  records(keys: readonly string[], policyVersion: string): Promise<LocalRecord[]>;
}

/** Sends one call; rejects when the project did not accept it. */
export type ContribSender = (records: readonly WireRecord[], signal: AbortSignal) => Promise<void>;

export class ContribSendError extends Error {
  override readonly name = 'ContribSendError';
  constructor(
    message: string,
    /** PostgREST's error code (`22023`, `54000`, `42501`...), `''` when none. */
    readonly code: string,
  ) {
    super(message);
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The anonymous call: `apikey` and `Authorization` both carry the anon key. */
export function anonContribSender(
  config: { url: string; anonKey: string },
  fetch: (url: string, init?: RequestInit) => Promise<Response>,
  timeoutMs = CONTRIB_SEND_TIMEOUT_MS,
): ContribSender {
  const url = `${config.url.replace(/\/+$/, '')}/rest/v1/rpc/contribute_games`;
  return async (records, signal) => {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        apikey: config.anonKey,
        Authorization: `Bearer ${config.anonKey}`,
      },
      body: JSON.stringify({ records }),
      signal: AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]),
    });
    if (response.ok) return;
    let code = '';
    try {
      const body: unknown = await response.json();
      if (isObject(body) && typeof body.code === 'string') code = body.code;
    } catch {
      // no readable body: the status says enough
    }
    throw new ContribSendError(`contribute_games: HTTP ${response.status} ${code}`.trim(), code);
  };
}

/** `LocalContribApi` on the local server; waits for it as `localSyncApi` does. */
export function localContribApi(
  fetch: (url: string, init?: RequestInit) => Promise<Response>,
  server: ServerPort,
  timeoutMs = LOCAL_API_TIMEOUT_MS,
  serverWaitMs = SERVER_WAIT_MS,
): LocalContribApi {
  const get = async (pathAndQuery: string): Promise<unknown> => {
    const port = await waitForPort(server, serverWaitMs);
    if (port === null) throw new LocalApiError('the server was not ready in time');
    const route = pathAndQuery.split('?')[0];
    let response: Response;
    try {
      response = await fetch(`http://127.0.0.1:${port}${pathAndQuery}`, { method: 'GET', signal: AbortSignal.timeout(timeoutMs) });
    } catch (error) {
      throw new LocalApiError(`GET ${route}: ${String(error)}`);
    }
    if (!response.ok) throw new LocalApiError(`GET ${route}: HTTP ${response.status}`);
    try {
      return await response.json();
    } catch (error) {
      throw new LocalApiError(`GET ${route}: not JSON: ${String(error)}`);
    }
  };
  return {
    async keys() {
      const body = await get('/api/contrib/games');
      if (!Array.isArray(body)) throw new LocalApiError('the games answer is not a list');
      return body.filter((key): key is string => typeof key === 'string' && key !== '');
    },
    async records(keys, policyVersion) {
      const query = new URLSearchParams();
      for (const key of keys) query.append('keys', key);
      query.set('policy_version', policyVersion);
      const body = await get(`/api/contrib/records?${query.toString()}`);
      if (!Array.isArray(body)) throw new LocalApiError('the records answer is not a list');
      const out: LocalRecord[] = [];
      for (const item of body) {
        if (isObject(item) && typeof item.key === 'string' && isObject(item.record)) out.push({ key: item.key, record: item.record });
      }
      return out;
    },
  };
}

/** `contributed.json` in `dir`. */
export function contributedFile(dir: string): StateFile {
  const file = path.join(dir, CONTRIBUTED_FILE);
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

/** The keys `text` holds; throws on anything that is not a version 1 file. */
export function parseContributed(text: string): Set<string> {
  const raw: unknown = JSON.parse(text);
  if (!isObject(raw) || raw.version !== 1 || !Array.isArray(raw.keys)) throw new SyntaxError('not a version 1 contributed file');
  return new Set(raw.keys.filter((key): key is string => typeof key === 'string' && key !== ''));
}

/** The `Contribute` a page's answer becomes, `null` when it is not a well-formed answer. */
export function contribAnswer(input: unknown, now: Date): Contribute | null {
  if (!isObject(input)) return null;
  const { yes, policyVersion, ageConfirmed } = input;
  if (typeof yes !== 'boolean' || typeof ageConfirmed !== 'boolean') return null;
  // The local records route's pattern, which fits inside `contribute_games`'.
  if (typeof policyVersion !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(policyVersion)) return null;
  // A yes needs the age confirmation it was given with.
  if (yes && !ageConfirmed) return null;
  return { yes, policyVersion, answeredAt: now.toISOString(), ageConfirmed };
}

export interface ContributorDeps {
  local: LocalContribApi;
  send: ContribSender;
  file: StateFile;
  /** The stored answer now. */
  answer(): Contribute | null | undefined;
  makeId(): string;
  log?: Logger;
}

export class Contributor {
  private readonly log: Logger;
  private done: Set<string> | null = null;
  private running: Promise<void> | null = null;
  private again = false;
  private abort: AbortController | null = null;

  constructor(private readonly deps: ContributorDeps) {
    this.log = deps.log ?? silent;
  }

  /** The policy version to send under, `null` unless the answer is a full yes. */
  private active(): string | null {
    const answer = this.deps.answer();
    return answer?.yes === true && answer.ageConfirmed === true ? answer.policyVersion : null;
  }

  /** Runs the queue; one asked for while one runs is merged into the next.
   *  Resolves when no run is left; never rejects. */
  run(): Promise<void> {
    if (this.active() === null) return this.running ?? Promise.resolve();
    if (this.running) {
      this.again = true;
      return this.running;
    }
    this.running = this.drain();
    return this.running;
  }

  /** Resolves once no run is going or waiting; never rejects. */
  async idle(): Promise<void> {
    await this.running;
  }

  /** The answer is no (or not a yes any more): nothing more goes, at once. */
  stop(): void {
    this.again = false;
    this.abort?.abort();
  }

  private async drain(): Promise<void> {
    try {
      do {
        this.again = false;
        await this.once();
      } while (this.again && this.active() !== null);
    } finally {
      this.running = null;
    }
  }

  private load(): Set<string> {
    if (this.done) return this.done;
    let text: string | null = null;
    try {
      text = this.deps.file.read();
    } catch (error) {
      this.log.warn('contrib: the sent-games file could not be read; starting from none', { error: String(error) });
    }
    if (text === null) this.done = new Set();
    else {
      try {
        this.done = parseContributed(text);
      } catch (error) {
        this.log.warn('contrib: the sent-games file could not be parsed; starting from none', { error: String(error) });
        this.done = new Set();
      }
    }
    return this.done;
  }

  /** Writes the keys and only then adds them to memory. `false` on a failed write. */
  private mark(keys: readonly string[]): boolean {
    const next = new Set(this.load());
    for (const key of keys) next.add(key);
    try {
      this.deps.file.write(`${JSON.stringify({ version: 1, keys: [...next] })}\n`);
    } catch (error) {
      this.log.warn('contrib: the sent-games file could not be written', { error: String(error) });
      return false;
    }
    this.done = next;
    return true;
  }

  private async once(): Promise<void> {
    const control = new AbortController();
    this.abort = control;
    const live = (): boolean => !control.signal.aborted && this.active() !== null;
    try {
      const policy = this.active();
      if (policy === null) return;
      const known = this.load();
      const keys = await this.deps.local.keys();
      if (!live()) return;
      const todo = keys.filter((key) => !known.has(key));
      let sent = 0;
      for (const batch of chunks(todo, CONTRIB_BATCH_SIZE)) {
        if (!live()) return;
        const items = await this.deps.local.records(batch, policy);
        if (!live()) return;
        const wire: Array<{ key: string; item: WireRecord }> = [];
        for (const { key, record } of items) {
          if (!batch.includes(key)) continue;
          if (!Number.isInteger(record.schema_version) || jsonbTextBytes(record) > MAX_RECORD_BYTES) {
            this.log.warn('contrib: a record is not sendable and was left out');
            continue;
          }
          wire.push({
            key,
            item: { id: this.deps.makeId(), schema_version: record.schema_version as number, policy_version: policy, record },
          });
        }
        if (wire.length === 0) continue;
        const accepted = await this.sendBatch(wire, control.signal, live);
        if (accepted === null) return;
        sent += accepted;
      }
      this.log.info('contrib: run finished', { sent });
    } catch (error) {
      if (control.signal.aborted) return;
      this.log.warn('contrib: the run stopped', {
        error: error instanceof ContribSendError || error instanceof LocalApiError ? error.message : String(error),
      });
    } finally {
      if (this.abort === control) this.abort = null;
    }
  }

  /** How many records the project took; `null` when the run must end (turned
   *  off, or a write failed). A response that arrives after `live()` went
   *  false is dropped and its keys are not marked. */
  private async sendBatch(
    wire: ReadonlyArray<{ key: string; item: WireRecord }>,
    signal: AbortSignal,
    live: () => boolean,
  ): Promise<number | null> {
    try {
      await this.deps.send(wire.map((entry) => entry.item), signal);
    } catch (error) {
      if (!live()) return null;
      const refused = error instanceof ContribSendError && (error.code === '22023' || error.code === '54000');
      if (!refused) throw error;
      if (wire.length === 1) {
        this.log.warn('contrib: a record was refused and left out', { code: (error as ContribSendError).code });
        return 0;
      }
      let accepted = 0;
      for (const entry of wire) {
        if (!live()) return null;
        // A fresh code for the retry: no code is in two calls.
        const one = await this.sendBatch([{ key: entry.key, item: { ...entry.item, id: this.deps.makeId() } }], signal, live);
        if (one === null) return null;
        accepted += one;
      }
      return accepted;
    }
    if (!live()) return null;
    return this.mark(wire.map((entry) => entry.key)) ? wire.length : null;
  }
}
