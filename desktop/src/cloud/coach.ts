// The rules coach's client, in the shell's main process (release plan 40e,
// S11): each question goes to the hosted `POST {coachUrl}/v1/ask` with the
// signed-in person's access token, and the answer goes back to the page.
//
// Traps and contracts:
// - `ask` never throws and never sends a question that breaks the bounds
//   (1-4 questions, each 1-500 characters): the whole batch is refused with
//   `failed` before any call.
// - Two calls at most are in flight. The first `notEnabled`, `notesOff`,
//   `limit`, `budget` or `paused` stops the questions not yet sent; they come
//   back with that same reason, so a stopped batch costs no more calls.
// - The log records counts and reasons, never a question and never the
//   server's text: a question can name the person's deck.
// - A refusal is `{code}`: `not_enabled`, `notes_off`, `limit`, `busy`,
//   `budget`, `paused` and `unauthorized` (`signedOut`). The code is read
//   first; only a body with no known code falls back to the status (401
//   `signedOut`, anything else `failed`), because one status carries several
//   reasons. A 200 with a string `outcome` is an answer, its other fields
//   (null on `try_again` or a pre-retrieval refusal) passed through unchanged.
//
// Electron-free: the fetch and the session are arguments, so vitest runs it
// under Node with fakes.

import { silent, type Logger } from '../log';

export const MAX_QUESTIONS = 4;
export const MAX_QUESTION_CHARS = 500;
export const COACH_TIMEOUT_MS = 35_000;
const IN_FLIGHT = 2;

export type CoachReason =
  | 'unavailable'
  | 'signedOut'
  | 'notEnabled'
  | 'notesOff'
  | 'limit'
  | 'busy'
  | 'budget'
  | 'paused'
  | 'offline'
  | 'failed';

const STOPPING: readonly CoachReason[] = ['notEnabled', 'notesOff', 'limit', 'budget', 'paused'];

export interface CoachAnswer {
  question: string;
  ok: true;
  outcome: string;
  verdict: string | null;
  explanation: string | null;
  citations: unknown[] | null;
  confidence: string | null;
  out_of_scope: boolean | null;
  rules_version: string | null;
}

export interface CoachRefusal {
  question: string;
  ok: false;
  reason: CoachReason;
}

export type CoachResult = CoachAnswer | CoachRefusal;

export interface CoachClientDeps {
  /** The coach's base URL, or `null` when this build has none. */
  url: string | null;
  /** The signed-in person's access token, or `null` when signed out. */
  accessToken(): Promise<string | null>;
  fetch(url: string, init: { method: string; headers: Record<string, string>; body: string; signal: AbortSignal }): Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;
  log?: Logger;
  timeoutMs?: number;
}

/** The questions in `value`, or `null` when it is not 1-4 strings of 1-500 characters. */
export function parseQuestions(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > MAX_QUESTIONS) return null;
  for (const item of value) {
    if (typeof item !== 'string' || item.trim() === '' || item.length > MAX_QUESTION_CHARS) return null;
  }
  return value as string[];
}

const CODES: Record<string, CoachReason> = {
  not_enabled: 'notEnabled',
  notes_off: 'notesOff',
  limit: 'limit',
  busy: 'busy',
  budget: 'budget',
  paused: 'paused',
  unauthorized: 'signedOut',
};

function fromStatus(status: number): CoachReason {
  return status === 401 ? 'signedOut' : 'failed';
}

export class CoachClient {
  private readonly log: Logger;

  constructor(private readonly deps: CoachClientDeps) {
    this.log = deps.log ?? silent;
  }

  async ask(value: unknown): Promise<CoachResult[]> {
    const questions = parseQuestions(value);
    if (!questions) {
      const list = Array.isArray(value) ? value : [];
      this.log.warn('coach: the questions were refused before any call', { count: list.length });
      return list.map((q) => ({ question: typeof q === 'string' ? q : '', ok: false as const, reason: 'failed' as const }));
    }
    const results: (CoachResult | undefined)[] = new Array(questions.length).fill(undefined);
    let stop: CoachReason | null = null;
    let next = 0;
    const worker = async (): Promise<void> => {
      for (;;) {
        const index = next++;
        if (index >= questions.length) return;
        const question = questions[index] as string;
        if (stop !== null) {
          results[index] = { question, ok: false, reason: stop };
          continue;
        }
        const result = await this.askOne(question);
        results[index] = result;
        if (!result.ok && STOPPING.includes(result.reason) && stop === null) stop = result.reason;
      }
    };
    await Promise.all(Array.from({ length: Math.min(IN_FLIGHT, questions.length) }, worker));
    const done = results as CoachResult[];
    const reasons: Record<string, number> = {};
    for (const r of done) if (!r.ok) reasons[r.reason] = (reasons[r.reason] ?? 0) + 1;
    this.log.info('coach: asked', { questions: done.length, answered: done.filter((r) => r.ok).length, reasons });
    return done;
  }

  private async askOne(question: string): Promise<CoachResult> {
    const refuse = (reason: CoachReason): CoachRefusal => ({ question, ok: false, reason });
    if (!this.deps.url) return refuse('unavailable');
    let token: string | null;
    try {
      token = await this.deps.accessToken();
    } catch {
      return refuse('failed');
    }
    if (!token) return refuse('signedOut');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.deps.timeoutMs ?? COACH_TIMEOUT_MS);
    try {
      const response = await this.deps.fetch(`${this.deps.url}/v1/ask`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
        signal: controller.signal,
      });
      let body: unknown = null;
      try {
        body = await response.json();
      } catch {
        // a body that is not JSON: judged by the status alone
      }
      const record = typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : {};
      if (!response.ok) {
        const named = typeof record.code === 'string' && Object.hasOwn(CODES, record.code) ? CODES[record.code] : null;
        return refuse(named ?? fromStatus(response.status));
      }
      if (typeof record.outcome !== 'string') return refuse('failed');
      return {
        question,
        ok: true,
        outcome: record.outcome,
        verdict: typeof record.verdict === 'string' ? record.verdict : null,
        explanation: typeof record.explanation === 'string' ? record.explanation : null,
        citations: Array.isArray(record.citations) ? record.citations : null,
        confidence: typeof record.confidence === 'string' ? record.confidence : null,
        out_of_scope: typeof record.out_of_scope === 'boolean' ? record.out_of_scope : null,
        rules_version: typeof record.rules_version === 'string' ? record.rules_version : null,
      };
    } catch (error) {
      // an abort is a timeout: the same word as a network that is gone
      this.log.debug('coach: a call did not complete', { name: error instanceof Error ? error.name : 'unknown' });
      return refuse('offline');
    } finally {
      clearTimeout(timer);
    }
  }
}
