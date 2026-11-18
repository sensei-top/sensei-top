import { describe, expect, it } from 'vitest';
import type { Logger } from '../log';
import { CoachClient, type CoachClientDeps } from './coach';
import { parseBuildConfig } from './config';

const ANSWER = {
  outcome: 'answered',
  verdict: 'yes',
  explanation: 'Because.',
  citations: [{ type: 'rule', ref: '100.1', quote: 'A player may concede.' }],
  confidence: 'high',
  out_of_scope: false,
  rules_version: '2026-11-01',
};

type Reply = { status: number; body: unknown } | 'throw';

function setup(replies: (question: string) => Reply, options: Partial<CoachClientDeps> = {}) {
  const calls: { url: string; headers: Record<string, string>; question: string }[] = [];
  const logged: unknown[] = [];
  let inFlight = 0;
  let peak = 0;
  const log: Logger = {
    debug: (...a) => void logged.push(a),
    info: (...a) => void logged.push(a),
    warn: (...a) => void logged.push(a),
    error: (...a) => void logged.push(a),
  };
  const client = new CoachClient({
    url: 'https://coach.test',
    accessToken: async () => 'tok-1',
    fetch: async (url, init) => {
      const question = (JSON.parse(init.body) as { question: string }).question;
      calls.push({ url, headers: init.headers, question });
      inFlight++;
      peak = Math.max(peak, inFlight);
      await new Promise((r) => setTimeout(r, 5));
      inFlight--;
      const reply = replies(question);
      if (reply === 'throw') throw new Error('network');
      return { ok: reply.status < 400, status: reply.status, json: async () => reply.body };
    },
    log,
    ...options,
  });
  return { client, calls, logged, peak: () => peak };
}

const ok = (): Reply => ({ status: 200, body: ANSWER });

describe('CoachClient.ask', () => {
  it('posts each question with the bearer token and returns the answer', async () => {
    const { client, calls } = setup(ok);
    const [r] = await client.ask(['q1']);
    expect(calls[0]?.url).toBe('https://coach.test/v1/ask');
    expect(calls[0]?.headers.Authorization).toBe('Bearer tok-1');
    expect(r).toEqual({ question: 'q1', ok: true, ...ANSWER });
  });

  it('passes a null rules_version through', async () => {
    const { client } = setup(() => ({ status: 200, body: { ...ANSWER, rules_version: null, out_of_scope: true } }));
    const [r] = await client.ask(['q']);
    expect(r).toMatchObject({ ok: true, rules_version: null, out_of_scope: true });
  });

  it('has no coach in this build: unavailable, no call', async () => {
    const { client, calls } = setup(ok, { url: null });
    expect(await client.ask(['q'])).toEqual([{ question: 'q', ok: false, reason: 'unavailable' }]);
    expect(calls).toHaveLength(0);
  });

  it('signed out: no token, no call', async () => {
    const { client, calls } = setup(ok, { accessToken: async () => null });
    expect(await client.ask(['q'])).toEqual([{ question: 'q', ok: false, reason: 'signedOut' }]);
    expect(calls).toHaveLength(0);
  });

  it.each([
    ['not_enabled', 403, 'notEnabled'],
    ['notes_off', 403, 'notesOff'],
    ['limit', 429, 'limit'],
    ['busy', 429, 'busy'],
    ['budget', 429, 'budget'],
    ['paused', 503, 'paused'],
    ['unauthorized', 401, 'signedOut'],
  ] as const)('reads code %s (%i) as %s', async (code, status, reason) => {
    const { client } = setup(() => ({ status, body: { code } }));
    expect(await client.ask(['q'])).toEqual([{ question: 'q', ok: false, reason }]);
  });

  it.each([
    [401, 'signedOut'],
    [429, 'failed'],
    [503, 'failed'],
    [500, 'failed'],
  ] as const)('reads status %i as %s when the body has no known code', async (status, reason) => {
    const { client } = setup(() => ({ status, body: { code: 'something_else' } }));
    expect(await client.ask(['q'])).toEqual([{ question: 'q', ok: false, reason }]);
  });

  it('passes a try_again 200 with null fields through as an answer', async () => {
    const nulls = { outcome: 'try_again', verdict: null, explanation: null, citations: null, confidence: null, out_of_scope: null, rules_version: null };
    const { client } = setup(() => ({ status: 200, body: nulls }));
    expect(await client.ask(['q'])).toEqual([{ question: 'q', ok: true, ...nulls }]);
  });

  it('a network error is offline; a malformed 200 is failed', async () => {
    expect((await setup(() => 'throw').client.ask(['q']))[0]).toMatchObject({ reason: 'offline' });
    expect((await setup(() => ({ status: 200, body: { nope: 1 } })).client.ask(['q']))[0]).toMatchObject({ reason: 'failed' });
  });

  it('aborts a call after the timeout', async () => {
    const client = new CoachClient({
      url: 'https://coach.test',
      accessToken: async () => 't',
      fetch: (_url, init) =>
        new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => reject(new Error('aborted')));
        }),
      timeoutMs: 10,
    });
    expect(await client.ask(['q'])).toEqual([{ question: 'q', ok: false, reason: 'offline' }]);
  });

  it('stops the questions not yet sent after the first limit', async () => {
    const { client, calls } = setup((q) => (q === 'q1' ? { status: 429, body: { code: 'limit' } } : ok()));
    const results = await client.ask(['q1', 'q2', 'q3', 'q4']);
    // q1 and q2 start together; q3 and q4 are never sent
    expect(calls.map((c) => c.question).sort()).toEqual(['q1', 'q2']);
    expect(results.map((r) => (r.ok ? 'ok' : r.reason))).toEqual(['limit', 'ok', 'limit', 'limit']);
  });

  it('does not stop for busy', async () => {
    const { client, calls } = setup((q) => (q === 'q1' ? { status: 429, body: { code: 'busy' } } : ok()));
    const results = await client.ask(['q1', 'q2', 'q3']);
    expect(calls).toHaveLength(3);
    expect(results.map((r) => (r.ok ? 'ok' : r.reason))).toEqual(['busy', 'ok', 'ok']);
  });

  it('runs two at a time at most', async () => {
    const s = setup(ok);
    await s.client.ask(['a', 'b', 'c', 'd']);
    expect(s.peak()).toBe(2);
  });

  it.each([
    ['five questions', ['a', 'b', 'c', 'd', 'e']],
    ['a 501-character one', ['x'.repeat(501)]],
    ['none', []],
    ['a blank one', ['  ']],
  ])('refuses %s before any call, one result per element', async (_, questions) => {
    const { client, calls } = setup(ok);
    const results = await client.ask(questions);
    expect(calls).toHaveLength(0);
    expect(results).toHaveLength(questions.length);
    expect(results.every((r) => !r.ok && r.reason === 'failed')).toBe(true);
  });

  it('accepts 500 characters', async () => {
    const { client, calls } = setup(ok);
    await client.ask(['x'.repeat(500)]);
    expect(calls).toHaveLength(1);
  });

  it('never logs a question', async () => {
    const secret = 'SECRET-QUESTION-TEXT';
    for (const reply of [ok, () => ({ status: 429, body: { code: 'limit' } }) as Reply, () => 'throw' as Reply]) {
      const { client, logged } = setup(reply);
      await client.ask([secret, `${secret} 2`]);
      await client.ask(['x'.repeat(501), secret]);
      expect(logged.length).toBeGreaterThan(0);
      expect(JSON.stringify(logged)).not.toContain('SECRET');
    }
  });
});

describe('the log at every level (build point 18)', () => {
  it('never records a question or an answer, Diagnostic mode (debug) included', async () => {
    const secretAnswer = { ...ANSWER, explanation: 'SECRET-EXPLANATION', citations: [{ type: 'rule', ref: '1.1', quote: 'SECRET-QUOTE' }] };
    const replies: ((q: string) => Reply)[] = [
      () => ({ status: 200, body: secretAnswer }),
      () => ({ status: 200, body: { ...secretAnswer, outcome: 'try_again' } }),
      () => ({ status: 429, body: { code: 'limit', message: 'SECRET-QUESTION-TEXT' } }),
      () => ({ status: 403, body: { code: 'notes_off', message: 'SECRET-QUESTION-TEXT' } }),
      () => ({ status: 500, body: { error: 'SECRET-QUESTION-TEXT' } }),
      () => 'throw',
    ];
    const seen = new Set<string>();
    for (const reply of replies) {
      const lines: unknown[] = [];
      const log: Logger = {
        debug: (...a) => void (seen.add('debug'), lines.push(a)),
        info: (...a) => void (seen.add('info'), lines.push(a)),
        warn: (...a) => void (seen.add('warn'), lines.push(a)),
        error: (...a) => void (seen.add('error'), lines.push(a)),
      };
      const { client } = setup(reply, { log });
      await client.ask(['SECRET-QUESTION-TEXT one', 'SECRET-QUESTION-TEXT two']);
      await client.ask(['SECRET-QUESTION-TEXT'.padEnd(501, 'x')]);
      expect(lines.length).toBeGreaterThan(0);
      expect(JSON.stringify(lines)).not.toContain('SECRET');
    }
    // Diagnostic mode is debug: the lines it adds were drawn too.
    expect([...seen].sort()).toEqual(expect.arrayContaining(['debug', 'info', 'warn']));
  });
});

describe('parseBuildConfig coach', () => {
  it('keeps an https URL without trailing slash', () => {
    expect(parseBuildConfig({ coachUrl: ' https://coach.test/ ' }).coach).toBe('https://coach.test');
  });
  it.each(['http://coach.test', 'coach.test', ''])('drops %j', (coachUrl) => {
    expect(parseBuildConfig({ coachUrl }).coach).toBeNull();
  });
  it('is null when unset', () => {
    expect(parseBuildConfig({}).coach).toBeNull();
  });
});
