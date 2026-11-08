import type { ErrorEvent, Event, EventHint } from '@sentry/electron/main';
import { describe, expect, it } from 'vitest';
import type { Logger } from '../log';
import {
  fetchLogTail,
  LOG_ATTACHMENT_NAME,
  LOG_TAIL_LINES,
  PROBLEM_TEXT_MAX,
  sendProblemReport,
  type ReportOptions,
} from './report';
import {
  CLOSE_TIMEOUT_MS,
  CONSENT_ENV,
  DSN_ENV,
  ErrorReporter,
  USER_ENV,
  clientOptions,
  localApiSentryEnv,
  sentryFactory,
  type ClientOptions,
  type FeedbackAttachment,
  type FeedbackMeta,
  type SentryClient,
  type SentryFactory,
  type SentrySdk,
} from './sentry';

const DSN = 'https://public@sentry.example.invalid/1';
const USER = '00000000-0000-4000-8000-000000000001';
const OS = { name: 'Linux', version: '6.0.0-test' };

interface FakeClient extends SentryClient {
  readonly options: ClientOptions;
  readonly exceptions: Array<{ error: unknown; hint: EventHint | undefined }>;
  readonly feedback: Array<{ message: string; attachments: readonly FeedbackAttachment[]; meta?: FeedbackMeta }>;
  readonly closes: number[];
}

/** A factory that records every client it makes; none touches the SDK. */
function fakeFactory(closeResult = true): { factory: SentryFactory; clients: FakeClient[] } {
  const clients: FakeClient[] = [];
  const factory: SentryFactory = (options) => {
    const client: FakeClient = {
      options,
      exceptions: [],
      feedback: [],
      closes: [],
      captureException(error, hint) {
        client.exceptions.push({ error, hint });
        return 'event-id';
      },
      captureFeedback(message, attachments, meta) {
        client.feedback.push({ message, attachments, ...(meta ? { meta } : {}) });
        return 'event-id';
      },
      async close(timeoutMs) {
        client.closes.push(timeoutMs);
        return closeResult;
      },
    };
    clients.push(client);
    return client;
  };
  return { factory, clients };
}

function reporter(factory: SentryFactory, dsn: string | null = DSN, log?: Logger): ErrorReporter {
  return new ErrorReporter({ dsn, release: '1.3.0', factory, os: OS, home: null, names: () => ['Quuxling'], log });
}

function only(clients: FakeClient[]): FakeClient {
  expect(clients).toHaveLength(1);
  return clients[0]!;
}

describe('localApiSentryEnv', () => {
  it('passes the DSN, consent and user when consent is on', () => {
    expect(localApiSentryEnv(DSN, true, USER)).toEqual({ [DSN_ENV]: DSN, [CONSENT_ENV]: '1', [USER_ENV]: USER });
    expect(localApiSentryEnv(DSN, true, null)).toEqual({ [DSN_ENV]: DSN, [CONSENT_ENV]: '1', [USER_ENV]: '' });
  });

  it('blanks all three without consent or without a DSN, so nothing inherited reaches the server', () => {
    const off = { [DSN_ENV]: '', [CONSENT_ENV]: '0', [USER_ENV]: '' };
    expect(localApiSentryEnv(DSN, false, USER)).toEqual(off);
    expect(localApiSentryEnv(null, true, USER)).toEqual(off);
    expect(localApiSentryEnv('  ', true, USER)).toEqual(off);
  });
});

describe('ErrorReporter', () => {
  it('makes no client while consent is off', async () => {
    const { factory, clients } = fakeFactory();
    const errors = reporter(factory);
    errors.captureException(new Error('boom'));
    await errors.setConsent(false);
    expect(errors.active).toBe(false);
    expect(clients).toHaveLength(0);
  });

  it('makes no client without a DSN, consent or not', async () => {
    const { factory, clients } = fakeFactory();
    const errors = reporter(factory, null);
    await errors.setConsent(true);
    expect(errors.active).toBe(false);
    expect(clients).toHaveLength(0);
  });

  it('starts a client when consent turns on and closes it when it turns off', async () => {
    const { factory, clients } = fakeFactory();
    const errors = reporter(factory);
    await errors.setConsent(true);
    await errors.setConsent(true);
    const first = only(clients);
    expect(errors.active).toBe(true);

    await errors.setConsent(false);
    expect(first.closes).toEqual([CLOSE_TIMEOUT_MS]);
    expect(errors.active).toBe(false);
    errors.captureException(new Error('after'));
    expect(first.exceptions).toHaveLength(0);

    await errors.setConsent(true);
    expect(clients).toHaveLength(2);
  });

  it('builds a client with no personal data, no breadcrumbs and no tracing', async () => {
    const { factory, clients } = fakeFactory();
    await reporter(factory).setConsent(true);
    const { options } = only(clients);
    expect(options.dsn).toBe(DSN);
    expect(options.dataCollection.userInfo).toBe(false);
    expect(options.dataCollection.httpHeaders).toEqual({ request: false, response: false });
    expect(options.dataCollection.stackFrameVariables).toBe(false);
    expect(options.maxBreadcrumbs).toBe(0);
    expect(options.beforeBreadcrumb()).toBeNull();
    expect(options.beforeSendTransaction()).toBeNull();
    expect(options.sendClientReports).toBe(false);
    for (const key of ['sendDefaultPii', 'tracesSampleRate', 'tracesSampler', 'profilesSampleRate', 'autoSessionTracking']) {
      expect(options).not.toHaveProperty(key);
    }
  });

  it('scrubs the message, the exception values and the frames, and drops the breadcrumbs', async () => {
    const { factory, clients } = fakeFactory();
    const errors = reporter(factory);
    errors.setUser(USER);
    await errors.setConsent(true);
    const { options } = only(clients);
    const event: ErrorEvent = {
      type: undefined,
      message: 'failed for C:\\Users\\zorblax because of a bug',
      server_name: 'zorblax-desktop',
      exception: {
        values: [
          {
            type: 'Error',
            value: 'mail zorblax.test@example.invalid about Quuxling',
            stacktrace: { frames: [{ filename: '/media/zorblax/app/main.js', lineno: 1 }] },
          },
        ],
      },
      breadcrumbs: [{ message: 'opened /media/zorblax/x' }],
      user: { id: 'other', email: 'zorblax.test@example.invalid' },
      contexts: { runtime: { name: 'node', version: 'v0' }, trace: { trace_id: 't', span_id: 's' } },
      modules: { anything: '1.0.0' },
    };
    const cleaned = options.beforeSend(event, {})!;
    expect(cleaned.message).toBe('failed for C:\\Users\\<user> because of a bug');
    const value = cleaned.exception!.values![0]!;
    expect(value.value).toBe('mail <email> about <name>');
    expect(value.stacktrace!.frames![0]!.filename).toBe('/media/<user>/app/main.js');
    expect(cleaned).not.toHaveProperty('breadcrumbs');
    expect(cleaned).not.toHaveProperty('server_name');
    expect(cleaned).not.toHaveProperty('modules');
    expect(cleaned.user).toEqual({ id: USER });
    expect(cleaned.contexts).toEqual({ os: OS });

    errors.setUser(null);
    expect(options.beforeSend(event, {})).not.toHaveProperty('user');
  });

  it('drops a renderer error while consent is off and captures it while on', async () => {
    const { factory, clients } = fakeFactory();
    const errors = reporter(factory);
    const payload = { name: 'TypeError', message: 'x is undefined', stack: 'TypeError: x is undefined\n    at f (app.js:1:2)' };
    expect(errors.captureRendererError(payload)).toBe(false);
    expect(clients).toHaveLength(0);

    await errors.setConsent(true);
    expect(errors.captureRendererError(payload)).toBe(true);
    expect(errors.captureRendererError({ message: 42 })).toBe(false);
    expect(errors.captureRendererError('boom')).toBe(false);
    const { exceptions } = only(clients);
    expect(exceptions).toHaveLength(1);
    const { error, hint } = exceptions[0]!;
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).name).toBe('TypeError');
    expect((error as Error).message).toBe('x is undefined');
    expect((error as Error).stack).toBe(payload.stack);
    expect(hint?.mechanism).toEqual({ type: 'renderer', handled: false });

    await errors.setConsent(false);
    expect(errors.captureRendererError(payload)).toBe(false);
  });

  it('stays without a client when the factory throws, and logs only the error class', async () => {
    const warnings: unknown[] = [];
    const log: Logger = { debug() {}, info() {}, warn: (...args) => warnings.push(args), error() {} };
    const errors = reporter(
      () => {
        throw new TypeError('bad dsn at /home/zorblax');
      },
      DSN,
      log,
    );
    await errors.setConsent(true);
    expect(errors.active).toBe(false);
    expect(warnings).toEqual([['error reports not started', { error: 'TypeError' }]]);
  });
});

describe('sendProblemReport', () => {
  function options(factory: SentryFactory, overrides: Partial<ReportOptions> = {}): ReportOptions {
    return {
      dsn: DSN,
      release: '1.3.0',
      factory,
      userId: null,
      logTail: async () => 'line one at /media/zorblax/x\nline two by Quuxling\n',
      os: OS,
      home: null,
      names: () => ['Quuxling'],
      ...overrides,
    };
  }

  const feedbackEvent = (): Event => ({
    type: 'feedback',
    user: { id: 'scope-user' },
    server_name: 'zorblax-desktop',
    contexts: { feedback: { message: 'it broke at C:\\Users\\zorblax' }, runtime: { name: 'node' } },
  });

  it('sends one feedback event through a client of its own, then closes it', async () => {
    const { factory, clients } = fakeFactory();
    const outcome = await sendProblemReport({ text: '  It broke.  ', attachLog: false }, options(factory));
    expect(outcome).toBe('sent');
    const client = only(clients);
    expect(client.feedback).toEqual([
      { message: 'It broke.', attachments: [], meta: { kind: 'bug', page: null, matchId: null } },
    ]);
    expect(client.closes).toHaveLength(1);
    expect(client.options.dataCollection.userInfo).toBe(false);
  });

  it('carries kind, page and matchId, defaulting to a bug, and drops a malformed page', async () => {
    const { factory, clients } = fakeFactory();
    await sendProblemReport(
      { text: 'Add X.', attachLog: false, kind: 'idea', page: '/matches/m-1', matchId: 'm-1' },
      options(factory),
    );
    await sendProblemReport({ text: 'Odd.', attachLog: false, page: '/matches?x=1', matchId: 'a b' }, options(factory));
    expect(clients[0]!.feedback[0]!.meta).toEqual({ kind: 'idea', page: '/matches/m-1', matchId: 'm-1' });
    expect(clients[1]!.feedback[0]!.meta).toEqual({ kind: 'bug', page: null, matchId: null });
    expect(await sendProblemReport({ text: 'x', attachLog: false, kind: 'other' }, options(factory))).toBe('invalid');
  });

  it('never attaches the log to an idea', async () => {
    let reads = 0;
    const { factory, clients } = fakeFactory();
    const logTail = async () => {
      reads += 1;
      return 'line';
    };
    const outcome = await sendProblemReport({ text: 'Add X.', attachLog: true, kind: 'idea' }, options(factory, { logTail }));
    expect(outcome).toBe('sent');
    expect(reads).toBe(0);
    expect(only(clients).feedback[0]!.attachments).toEqual([]);
  });

  it('scrubs the text before it is captured', async () => {
    const { factory, clients } = fakeFactory();
    await sendProblemReport({ text: 'Quuxling saw C:\\Users\\zorblax\\x fail', attachLog: false }, options(factory));
    expect(only(clients).feedback[0]!.message).toBe('<name> saw C:\\Users\\<user>\\x fail');
  });

  it('reads and attaches the log only when asked', async () => {
    let reads = 0;
    const logTail = async () => {
      reads += 1;
      return 'line one at /media/zorblax/x\nline two by Quuxling\n';
    };
    const without = fakeFactory();
    await sendProblemReport({ text: 'It broke.', attachLog: false }, options(without.factory, { logTail }));
    expect(reads).toBe(0);

    const withLog = fakeFactory();
    const outcome = await sendProblemReport({ text: 'It broke.', attachLog: true }, options(withLog.factory, { logTail }));
    expect(outcome).toBe('sent');
    expect(reads).toBe(1);
    expect(only(withLog.clients).feedback[0]!.attachments).toEqual([
      { filename: LOG_ATTACHMENT_NAME, data: 'line one at /media/<user>/x\nline two by <name>\n', contentType: 'text/plain' },
    ]);
  });

  it('still sends when the log cannot be read, and says so', async () => {
    const { factory, clients } = fakeFactory();
    const outcome = await sendProblemReport(
      { text: 'It broke.', attachLog: true },
      options(factory, { logTail: async () => null }),
    );
    expect(outcome).toBe('sent-without-log');
    expect(only(clients).feedback[0]!.attachments).toEqual([]);
  });

  it('carries no user signed out, and the account ID alone signed in', async () => {
    const out = fakeFactory();
    await sendProblemReport({ text: 'It broke.', attachLog: false }, options(out.factory));
    const signedOut = only(out.clients).options.cleanFeedback(feedbackEvent())!;
    expect(signedOut).not.toHaveProperty('user');
    expect(signedOut).not.toHaveProperty('server_name');
    expect(signedOut.contexts).toEqual({ feedback: { message: 'it broke at C:\\Users\\<user>' }, os: OS });

    const signedIn = fakeFactory();
    await sendProblemReport({ text: 'It broke.', attachLog: false }, options(signedIn.factory, { userId: USER }));
    expect(only(signedIn.clients).options.cleanFeedback(feedbackEvent())!.user).toEqual({ id: USER });
  });

  it('leaves an error event to beforeSend', async () => {
    const { factory, clients } = fakeFactory();
    await sendProblemReport({ text: 'It broke.', attachLog: false }, options(factory));
    const error: Event = { message: 'C:\\Users\\zorblax' };
    expect(only(clients).options.cleanFeedback(error)).toBe(error);
  });

  it('refuses what is not a report, and sends nothing from a build without a DSN', async () => {
    const { factory, clients } = fakeFactory();
    expect(await sendProblemReport({ text: '   ', attachLog: false }, options(factory))).toBe('invalid');
    expect(await sendProblemReport({ text: 'x'.repeat(PROBLEM_TEXT_MAX + 1), attachLog: false }, options(factory))).toBe(
      'invalid',
    );
    expect(await sendProblemReport({ text: 'It broke.' }, options(factory))).toBe('invalid');
    expect(await sendProblemReport(null, options(factory))).toBe('invalid');
    expect(await sendProblemReport({ text: 'It broke.', attachLog: false }, options(factory, { dsn: null }))).toBe(
      'unavailable',
    );
    expect(clients).toHaveLength(0);
  });

  it('fails when the client cannot be made or its queue does not drain', async () => {
    const throwing: SentryFactory = () => {
      throw new Error('no');
    };
    expect(await sendProblemReport({ text: 'It broke.', attachLog: false }, options(throwing))).toBe('failed');
    const { factory } = fakeFactory(false);
    expect(await sendProblemReport({ text: 'It broke.', attachLog: false }, options(factory))).toBe('failed');
  });
});

describe('fetchLogTail', () => {
  it('reads the route on the server port, and null when it fails or is empty', async () => {
    const urls: string[] = [];
    const answer = (body: string, status = 200) => async (url: string) => {
      urls.push(url);
      return new Response(body, { status });
    };
    expect(await fetchLogTail(answer('a line\n'), 8123)).toBe('a line\n');
    expect(urls).toEqual([`http://127.0.0.1:8123/api/diagnostics/log-tail?lines=${LOG_TAIL_LINES}`]);
    expect(await fetchLogTail(answer(''), 8123)).toBeNull();
    expect(await fetchLogTail(answer('oops', 503), 8123)).toBeNull();
    expect(
      await fetchLogTail(async () => {
        throw new TypeError('refused');
      }, 8123),
    ).toBeNull();
  });
});

describe('sentryFactory', () => {
  interface Integration {
    name: string;
    processEvent?: (event: Event) => Event | null;
  }

  /** A stand-in for `@sentry/electron/main`, recording what the factory hands it. */
  function fakeSdk() {
    const made: Array<{ options: Record<string, unknown>; inits: number }> = [];
    const feedback: Array<{ params: unknown; hint: unknown; scope: unknown }> = [];
    const scopes: FakeScope[] = [];
    class FakeNodeClient {
      readonly record: { options: Record<string, unknown>; inits: number };
      constructor(options: Record<string, unknown>) {
        this.record = { options, inits: 0 };
        made.push(this.record);
      }
      init(): void {
        this.record.inits += 1;
      }
      async close(): Promise<boolean> {
        return true;
      }
    }
    class FakeScope {
      client: unknown = null;
      constructor() {
        scopes.push(this);
      }
      setClient(client: unknown): void {
        this.client = client;
      }
      tags: Record<string, unknown> = {};
      setTags(tags: Record<string, unknown>): void {
        Object.assign(this.tags, tags);
      }
      captureException(): string {
        return 'event-id';
      }
    }
    const transport = () => ({});
    const stackParser = () => [];
    const sdk = {
      NodeClient: FakeNodeClient,
      Scope: FakeScope,
      captureFeedback: (params: unknown, hint: unknown, scope: unknown) => {
        feedback.push({ params, hint, scope });
        return 'event-id';
      },
      makeElectronTransport: transport,
      defaultStackParser: stackParser,
      linkedErrorsIntegration: () => ({ name: 'LinkedErrors' }),
      dedupeIntegration: () => ({ name: 'Dedupe' }),
      normalizePathsIntegration: () => ({ name: 'NormalizePaths' }),
    } as unknown as SentrySdk;
    return { sdk, made, feedback, scopes, transport, stackParser };
  }

  const context = (userId: string | null) => ({ userId: () => userId, names: () => ['Quuxling'], home: null, os: OS });

  it('builds a NodeClient that sends through Electron, names no server and infers no IP', () => {
    const fake = fakeSdk();
    sentryFactory(fake.sdk)(clientOptions({ dsn: DSN, release: '1.3.0' }, context(null)));
    expect(fake.made).toHaveLength(1);
    const { options, inits } = fake.made[0]!;
    expect(inits).toBe(1);
    expect(options.transport).toBe(fake.transport);
    expect(options.stackParser).toBe(fake.stackParser);
    expect(options.includeServerName).toBe(false);
    expect(options._metadata).toEqual({ sdk: { settings: { infer_ip: 'never' } } });
    expect((options.dataCollection as { userInfo: boolean }).userInfo).toBe(false);
    expect((options.integrations as Integration[]).map((i) => i.name)).toEqual([
      'LinkedErrors',
      'Dedupe',
      'NormalizePaths',
      'SenseiTopFeedback',
    ]);
  });

  it("cleans a feedback event in its processor, the user only when signed in", () => {
    const feedbackEvent = (): Event => ({
      type: 'feedback',
      user: { id: 'scope-user' },
      contexts: { feedback: { message: 'Quuxling at C:\\Users\\zorblax' } },
    });
    const processor = (userId: string | null) => {
      const fake = fakeSdk();
      sentryFactory(fake.sdk)(clientOptions({ dsn: DSN, release: '1.3.0' }, context(userId)));
      return (fake.made[0]!.options.integrations as Integration[]).at(-1)!.processEvent!;
    };
    const signedOut = processor(null)(feedbackEvent())!;
    expect(signedOut.contexts).toEqual({ feedback: { message: '<name> at C:\\Users\\<user>' }, os: OS });
    expect(signedOut).not.toHaveProperty('user');
    expect(processor(USER)(feedbackEvent())!.user).toEqual({ id: USER });
  });

  it("sends feedback on the client's own scope", () => {
    const fake = fakeSdk();
    const client = sentryFactory(fake.sdk)(clientOptions({ dsn: DSN, release: '1.3.0' }, context(null)));
    const attachment = { filename: 'sensei-top.log', data: 'x', contentType: 'text/plain' };
    client.captureFeedback('It broke.', [attachment]);
    expect(fake.scopes).toHaveLength(1);
    const scope = fake.scopes[0]!;
    expect(scope.client).not.toBeNull();
    expect(fake.feedback).toEqual([{ params: { message: 'It broke.' }, hint: { attachments: [attachment] }, scope }]);
  });
});

describe('feedback tags and match context', () => {
  it('tags the scope and merges match_id into the feedback context, kept and scrubbed', () => {
    const tags: Array<Record<string, unknown>> = [];
    let processor: ((event: Event) => Event | null) | undefined;
    const sdk = {
      NodeClient: class {
        constructor(options: { integrations: Array<{ processEvent?: (event: Event) => Event | null }> }) {
          processor = options.integrations.at(-1)!.processEvent;
        }
        init(): void {}
        async close(): Promise<boolean> {
          return true;
        }
      },
      Scope: class {
        setClient(): void {}
        setTags(t: Record<string, unknown>): void {
          tags.push(t);
        }
      },
      captureFeedback: () => 'event-id',
      makeElectronTransport: () => ({}),
      defaultStackParser: () => [],
      linkedErrorsIntegration: () => ({ name: 'L' }),
      dedupeIntegration: () => ({ name: 'D' }),
      normalizePathsIntegration: () => ({ name: 'N' }),
    } as unknown as SentrySdk;
    const ctx = { userId: () => null, names: () => ['Quuxling'], home: null, os: OS };
    const client = sentryFactory(sdk)(clientOptions({ dsn: DSN, release: '1.3.0' }, ctx));
    client.captureFeedback('x', [], { kind: 'idea', page: '/decks/Quuxling', matchId: 'Quuxling-1' });
    expect(tags).toEqual([{ kind: 'idea', page: '/decks/Quuxling' }]);
    const out = processor!({ type: 'feedback', tags: { kind: 'idea', page: '/decks/Quuxling' }, contexts: { feedback: { message: 'hi' } } })!;
    expect(out.contexts).toEqual({ feedback: { message: 'hi', match_id: '<name>-1' }, os: OS });
    expect(out.tags).toEqual({ kind: 'idea', page: '/decks/<name>' });
  });
});
