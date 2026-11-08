// Error reports from the shell's main process, sent only with the user's
// yes (S11, DB9), and the environment the local API's own reporter reads
// (DB8, `src/sensei_top/telemetry.py`).
//
// Traps and contracts:
// - No client exists unless `setConsent(true)` was called and the build has
//   a DSN. `setConsent(false)` drops the client at once, so nothing is
//   captured while it closes.
// - The SDK is never loaded here: `sentryFactory` takes `@sentry/electron/main`
//   from `main.ts`, the one module that loads Electron. Importing the SDK
//   reads `electron.app` at load time, which vitest does not have.
// - The SDK's `init` is not used: it registers a custom protocol, which
//   throws once the app is ready (consent can be given later), and IPC
//   handlers, which throw when registered twice (consent can be given
//   twice). A `NodeClient` on a scope of its own needs neither, and none of
//   the SDK's process-wide handlers: `main.ts` hands its own uncaught
//   errors to `captureException`.
// - In SDK 11 `sendDefaultPii` is gone; `dataCollection` with `userInfo:
//   false` replaces it, and the SDK's IP inference is set to `never`.
// - The SDK runs `beforeSend` on error events only; a feedback event goes
//   through `cleanFeedback` instead, as an event processor of the client.
//   Either hook throwing drops the event, so a scrub failure never sends
//   unscrubbed text.
// - A cleaned event keeps the `feedback` context and the OS; every other
//   context (the Node runtime the SDK adds, and `trace`, whose id pair would
//   link events) is removed, as are `server_name`, the breadcrumbs and
//   `modules`.
//
// Electron-free: vitest imports it directly.

import * as nodeOs from 'node:os';
import type { ErrorEvent, Event, EventHint, NodeOptions } from '@sentry/electron/main';
import { silent, type Logger } from '../log';
import { defaultHome, scrubDeep } from './scrub';

export const DSN_ENV = 'SENSEI_TOP_SENTRY_DSN';
export const CONSENT_ENV = 'SENSEI_TOP_SENTRY_CONSENT';
export const USER_ENV = 'SENSEI_TOP_SENTRY_USER';

/** How long closing a client waits for its queue to drain. */
export const CLOSE_TIMEOUT_MS = 2000;
/** The longest message and stack a renderer error keeps. */
export const RENDERER_MESSAGE_MAX = 4000;
export const RENDERER_STACK_MAX = 16000;

/** The three variables `telemetry.py` reads at the server's spawn. Always
 *  all three, so a value inherited from the shell's own environment never
 *  reaches the server; DSN and user are blank unless consent is on. */
export function localApiSentryEnv(
  dsn: string | null,
  consent: boolean,
  userId: string | null,
): Record<string, string> {
  const on = consent && !!dsn?.trim();
  return {
    [DSN_ENV]: on ? dsn!.trim() : '',
    [CONSENT_ENV]: on ? '1' : '0',
    [USER_ENV]: on ? (userId?.trim() ?? '') : '',
  };
}

export interface OsContext {
  readonly name: string;
  readonly version: string;
}

const OS_NAMES: Readonly<Record<string, string>> = { win32: 'Windows', linux: 'Linux', darwin: 'macOS' };

/** This machine's OS as a report names it: the system and its release. */
export function systemOs(): OsContext {
  return { name: OS_NAMES[process.platform] ?? process.platform, version: nodeOs.release() };
}

export type DataCollection = NonNullable<NodeOptions['dataCollection']>;

/** Every category the SDK could collect, off (`telemetry.py`'s `DATA_COLLECTION`). */
export const DATA_COLLECTION: Readonly<DataCollection> = {
  userInfo: false,
  cookies: false,
  httpHeaders: { request: false, response: false },
  httpBodies: [],
  urlQueryParams: false,
  graphQL: { document: false, variables: false },
  genAI: { inputs: false, outputs: false },
  databaseQueryData: false,
  queues: false,
  stackFrameVariables: false,
  frameContextLines: 0,
};

/** What a client is built from: no tracing option, no session option and
 *  no breadcrumbs, so none is ever recorded. */
export interface ClientOptions {
  readonly dsn: string;
  readonly release: string;
  readonly environment: string;
  readonly dataCollection: Readonly<DataCollection>;
  readonly maxBreadcrumbs: 0;
  readonly sendClientReports: false;
  readonly beforeBreadcrumb: () => null;
  readonly beforeSendTransaction: () => null;
  readonly beforeSend: (event: ErrorEvent, hint: EventHint) => ErrorEvent | null;
  /** The feedback event's counterpart of `beforeSend`. */
  readonly cleanFeedback: (event: Event) => Event | null;
}

/** What a report adds to its event: tags `kind` and `page`, and `match_id`
 *  in the `feedback` context. */
export interface FeedbackMeta {
  readonly kind: 'bug' | 'idea';
  readonly page: string | null;
  readonly matchId: string | null;
}

export interface FeedbackAttachment {
  readonly filename: string;
  readonly data: string;
  readonly contentType?: string;
}

/** One client, on a scope of its own. */
export interface SentryClient {
  captureException(error: unknown, hint?: EventHint): string;
  captureFeedback(message: string, attachments: readonly FeedbackAttachment[], meta?: FeedbackMeta): string;
  /** Sends what is queued, then disables the client; true when the queue
   *  drained within `timeoutMs`. */
  close(timeoutMs: number): Promise<boolean>;
}

export type SentryFactory = (options: ClientOptions) => SentryClient;

export interface CleanContext {
  /** The account's ID, or `null` signed out: read per event. */
  readonly userId: () => string | null;
  readonly names: () => Iterable<string>;
  readonly home: RegExp | null;
  readonly os: OsContext;
}

const NOT_SCRUBBED = new Set(['sdkProcessingMetadata']);
const KEPT_CONTEXTS = ['feedback'] as const;

/** `event` through `scrubDeep`, with the user set to the account's ID
 *  alone (or removed) and only the contexts kept that the module header
 *  lists. */
export function cleanEvent<T extends Event>(event: T, context: CleanContext): T {
  const cleaned = scrubDeep(event, [...context.names()], context.home, NOT_SCRUBBED) as T;
  delete cleaned.server_name;
  delete cleaned.breadcrumbs;
  delete cleaned.modules;
  const userId = context.userId();
  if (userId) cleaned.user = { id: userId };
  else delete cleaned.user;
  const contexts: Record<string, unknown> = {};
  for (const key of KEPT_CONTEXTS) {
    const kept = cleaned.contexts?.[key];
    if (kept !== undefined) contexts[key] = kept;
  }
  contexts.os = { name: context.os.name, version: context.os.version };
  cleaned.contexts = contexts as Event['contexts'];
  return cleaned;
}

export interface OptionsInput {
  readonly dsn: string;
  readonly release: string;
  readonly environment?: string;
}

/** A client's options, every event cleaned with `context`. */
export function clientOptions(input: OptionsInput, context: CleanContext): ClientOptions {
  return {
    dsn: input.dsn,
    release: input.release,
    environment: input.environment ?? 'production',
    dataCollection: DATA_COLLECTION,
    maxBreadcrumbs: 0,
    sendClientReports: false,
    beforeBreadcrumb: () => null,
    beforeSendTransaction: () => null,
    beforeSend: (event) => cleanEvent(event, context),
    cleanFeedback: (event) => (event.type === 'feedback' ? cleanEvent(event, context) : event),
  };
}

/** The part of `@sentry/electron/main` a client is built from. */
export type SentrySdk = Pick<
  typeof import('@sentry/electron/main'),
  | 'NodeClient'
  | 'Scope'
  | 'captureFeedback'
  | 'makeElectronTransport'
  | 'defaultStackParser'
  | 'linkedErrorsIntegration'
  | 'dedupeIntegration'
  | 'normalizePathsIntegration'
>;

function withMatchId(event: Event, matchId: string | null): Event {
  if (!matchId || event.type !== 'feedback') return event;
  return { ...event, contexts: { ...event.contexts, feedback: { ...event.contexts?.feedback, match_id: matchId } } };
}

/** The real factory, on the SDK `main.ts` hands over. Each client sends
 *  through Electron's `net` (DB5) and carries only the integrations that
 *  shape an error: linked causes, duplicates dropped, the app's paths
 *  written `app:///`. */
export function sentryFactory(sdk: SentrySdk): SentryFactory {
  return (options) => {
    // The SDK builds the `feedback` context from its own fields, so the
    // match ID is merged in by the processor; the tags ride the scope.
    // One feedback per client (a new client per report, as `sendProblemReport`
    // does): a second capture before the first is processed would take the
    // second's match ID.
    let matchId: string | null = null;
    const client = new sdk.NodeClient({
      dsn: options.dsn,
      release: options.release,
      environment: options.environment,
      dataCollection: options.dataCollection,
      maxBreadcrumbs: options.maxBreadcrumbs,
      sendClientReports: options.sendClientReports,
      beforeBreadcrumb: options.beforeBreadcrumb,
      beforeSendTransaction: options.beforeSendTransaction,
      beforeSend: options.beforeSend,
      includeServerName: false,
      enableRuntimeChannelInjection: false,
      _metadata: { sdk: { settings: { infer_ip: 'never' } } },
      transport: sdk.makeElectronTransport,
      stackParser: sdk.defaultStackParser,
      integrations: [
        sdk.linkedErrorsIntegration(),
        sdk.dedupeIntegration(),
        sdk.normalizePathsIntegration(),
        { name: 'SenseiTopFeedback', processEvent: (event) => options.cleanFeedback(withMatchId(event, matchId)) },
      ],
    });
    const scope = new sdk.Scope();
    scope.setClient(client);
    client.init();
    return {
      captureException: (error, hint) => scope.captureException(error, hint),
      captureFeedback: (message, attachments, meta) => {
        matchId = meta?.matchId ?? null;
        if (meta) scope.setTags({ kind: meta.kind, ...(meta.page ? { page: meta.page } : {}) });
        return sdk.captureFeedback({ message }, { attachments: attachments.map((a) => ({ ...a })) }, scope);
      },
      close: async (timeoutMs) => client.close(timeoutMs),
    };
  };
}

/** A renderer error as the page forwards it (DB9). */
export interface RendererError {
  readonly name: string;
  readonly message: string;
  readonly stack: string | null;
}

/** `payload` as a `RendererError`, or `null` when it is not one: an object
 *  with a string `message`, an optional string `name` and `stack`. Long
 *  texts are cut at `RENDERER_MESSAGE_MAX` and `RENDERER_STACK_MAX`. */
export function rendererError(payload: unknown): RendererError | null {
  if (payload === null || typeof payload !== 'object') return null;
  const { name, message, stack } = payload as Record<string, unknown>;
  if (typeof message !== 'string') return null;
  if (name !== undefined && typeof name !== 'string') return null;
  if (stack !== undefined && stack !== null && typeof stack !== 'string') return null;
  return {
    name: name?.trim() ? name.trim().slice(0, 200) : 'Error',
    message: message.slice(0, RENDERER_MESSAGE_MAX),
    stack: typeof stack === 'string' ? stack.slice(0, RENDERER_STACK_MAX) : null,
  };
}

export interface ErrorReporterOptions {
  /** The build's desktop DSN; `null` means no client ever exists. */
  readonly dsn: string | null;
  readonly release: string;
  readonly environment?: string;
  readonly factory: SentryFactory;
  readonly os?: OsContext;
  /** Names to scrub besides the rules, read per event. */
  readonly names?: () => Iterable<string>;
  readonly home?: RegExp | null;
  readonly log?: Logger;
}

/** The main process's error reports: one client while consent is on. */
export class ErrorReporter {
  private client: SentryClient | null = null;
  private userId: string | null = null;
  private readonly context: CleanContext;

  constructor(private readonly options: ErrorReporterOptions) {
    this.context = {
      userId: () => this.userId,
      names: options.names ?? (() => []),
      home: options.home === undefined ? defaultHome() : options.home,
      os: options.os ?? systemOs(),
    };
  }

  /** True while a client exists. */
  get active(): boolean {
    return this.client !== null;
  }

  /** The account's ID for every later event, `null` signed out. */
  setUser(userId: string | null): void {
    this.userId = userId?.trim() || null;
  }

  /** On: a client now, when the build has a DSN and none exists. Off: the
   *  client is dropped at once and closed. */
  async setConsent(on: boolean): Promise<void> {
    if (!on) {
      const client = this.client;
      this.client = null;
      if (client) await this.closeQuietly(client);
      return;
    }
    const dsn = this.options.dsn?.trim();
    if (this.client || !dsn) return;
    try {
      this.client = this.options.factory(
        clientOptions({ dsn, release: this.options.release, environment: this.options.environment }, this.context),
      );
    } catch (error) {
      this.client = null;
      (this.options.log ?? silent).warn('error reports not started', { error: errorName(error) });
    }
  }

  /** An error from the main process; nothing without a client. */
  captureException(error: unknown): void {
    this.client?.captureException(error, { mechanism: { type: 'main', handled: false } });
  }

  /** A renderer error the page forwarded; dropped without a client or when
   *  `payload` is not a `RendererError`. True when it was captured. */
  captureRendererError(payload: unknown): boolean {
    const client = this.client;
    if (!client) return false;
    const parsed = rendererError(payload);
    if (!parsed) return false;
    const error = new Error(parsed.message);
    error.name = parsed.name;
    error.stack = parsed.stack ?? `${parsed.name}: ${parsed.message}`;
    client.captureException(error, {
      mechanism: { type: 'renderer', handled: false },
      captureContext: { tags: { process: 'renderer' } },
    });
    return true;
  }

  /** Sends what is queued and drops the client, at quit. Consent is not
   *  changed: a later `setConsent(true)` starts a new client. */
  async shutdown(): Promise<void> {
    await this.setConsent(false);
  }

  private async closeQuietly(client: SentryClient): Promise<void> {
    try {
      await client.close(CLOSE_TIMEOUT_MS);
    } catch (error) {
      (this.options.log ?? silent).warn('error reports did not close', { error: errorName(error) });
    }
  }
}

/** An error's class name, never its message (which may carry a path). */
export function errorName(error: unknown): string {
  return error instanceof Error ? error.name : typeof error;
}
