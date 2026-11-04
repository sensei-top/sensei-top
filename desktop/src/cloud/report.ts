// Report a problem (S11, DB15): one feedback event, sent through a client
// made for it and closed after, whatever the error-reports toggle says.
// The caller has already asked the transfer consent for this press.
//
// Traps and contracts:
// - The user ID goes only when signed in; a report works signed out.
// - The log tail is `GET /api/diagnostics/log-tail`, already scrubbed by the
//   server with the names its database holds; it is scrubbed again here
//   with the shell's, and goes as an attachment, only when `attachLog`. A
//   tail that cannot be read leaves the report without it, never unsent.
// - The text is scrubbed here before it is captured, and again by the
//   client's `cleanFeedback` with every other string in the event.
// - `close` resolving true means the queue drained in time, not that
//   Sentry accepted the event: the SDK reports no answer to its caller.
//
// Electron-free: vitest imports it directly.

import { silent, type Logger } from '../log';
import { defaultHome, scrubText } from './scrub';
import {
  clientOptions,
  errorName,
  systemOs,
  type FeedbackAttachment,
  type OsContext,
  type SentryFactory,
} from './sentry';

/** The longest text a report carries; a longer one is refused. */
export const PROBLEM_TEXT_MAX = 4000;
/** How many log lines a report attaches (the route's default). */
export const LOG_TAIL_LINES = 500;
export const LOG_TAIL_TIMEOUT_MS = 5000;
/** How long a report waits for its event to leave. */
export const REPORT_TIMEOUT_MS = 10000;
export const LOG_ATTACHMENT_NAME = 'sensei-top.log';

export interface ProblemReport {
  readonly text: string;
  readonly attachLog: boolean;
}

/** `payload` as a `ProblemReport`, or `null`: a non-blank string `text` of
 *  at most `PROBLEM_TEXT_MAX` characters and a boolean `attachLog`. */
export function problemReport(payload: unknown): ProblemReport | null {
  if (payload === null || typeof payload !== 'object') return null;
  const { text, attachLog } = payload as Record<string, unknown>;
  if (typeof text !== 'string' || typeof attachLog !== 'boolean') return null;
  const trimmed = text.trim();
  if (!trimmed || trimmed.length > PROBLEM_TEXT_MAX) return null;
  return { text: trimmed, attachLog };
}

export type LogTailFetch = (url: string, init: { signal: AbortSignal }) => Promise<Response>;

/** The server's scrubbed log tail on `port`, or `null` when it cannot be
 *  read or is empty. */
export async function fetchLogTail(
  fetch: LogTailFetch,
  port: number,
  lines: number = LOG_TAIL_LINES,
): Promise<string | null> {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/api/diagnostics/log-tail?lines=${lines}`, {
      signal: AbortSignal.timeout(LOG_TAIL_TIMEOUT_MS),
    });
    if (!response.ok) return null;
    const body = await response.text();
    return body.trim() ? body : null;
  } catch {
    return null;
  }
}

export type ReportOutcome =
  /** Sent, with the log when it was asked for. */
  | 'sent'
  /** Sent, but the log was asked for and could not be read. */
  | 'sent-without-log'
  /** This build has no DSN. */
  | 'unavailable'
  /** The payload is not a `ProblemReport`. */
  | 'invalid'
  /** The client could not be made, or its queue did not drain in time. */
  | 'failed';

export interface ReportOptions {
  /** The build's desktop DSN. */
  readonly dsn: string | null;
  readonly release: string;
  readonly environment?: string;
  readonly factory: SentryFactory;
  /** The account's ID, `null` signed out. */
  readonly userId: string | null;
  /** The log tail, read only when the report asks for it. */
  readonly logTail: () => Promise<string | null>;
  readonly os?: OsContext;
  readonly names?: () => Iterable<string>;
  readonly home?: RegExp | null;
  readonly log?: Logger;
}

/** Sends `payload` as one feedback event (see the module header). */
export async function sendProblemReport(payload: unknown, options: ReportOptions): Promise<ReportOutcome> {
  const log = options.log ?? silent;
  const report = problemReport(payload);
  if (!report) return 'invalid';
  const dsn = options.dsn?.trim();
  if (!dsn) return 'unavailable';

  const names = options.names ?? (() => []);
  const home = options.home === undefined ? defaultHome() : options.home;
  const userId = options.userId?.trim() || null;

  const attachments: FeedbackAttachment[] = [];
  let logMissing = false;
  if (report.attachLog) {
    const tail = await options.logTail();
    if (tail === null) logMissing = true;
    else {
      attachments.push({
        filename: LOG_ATTACHMENT_NAME,
        data: scrubText(tail, [...names()], home),
        contentType: 'text/plain',
      });
    }
  }

  let sent: boolean;
  try {
    const client = options.factory(
      clientOptions(
        { dsn, release: options.release, environment: options.environment },
        { userId: () => userId, names, home, os: options.os ?? systemOs() },
      ),
    );
    client.captureFeedback(scrubText(report.text, [...names()], home), attachments);
    sent = await client.close(REPORT_TIMEOUT_MS);
  } catch (error) {
    log.warn('problem report not sent', { error: errorName(error) });
    return 'failed';
  }
  if (!sent) {
    log.warn('problem report not sent', { error: 'timeout' });
    return 'failed';
  }
  return logMissing ? 'sent-without-log' : 'sent';
}
