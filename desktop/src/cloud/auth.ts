// Signing in to the account from the shell: a supabase-js client in main,
// on the PKCE flow, every request through the `fetch` it is handed
// (Electron's `net.fetch`), the session in a `SessionStore`.
//
// A sign-in listens on the first free loopback port of `CALLBACK_PORTS`,
// opens the provider's page in the system browser (never in an Electron
// window), waits for Supabase's redirect to `/auth/callback`, exchanges its
// `code` for a session and closes the listener. The browser tab gets a
// small page in the shell's language.
//
// Traps and contracts:
// - Supabase's PKCE redirect carries no `state` of ours. What binds a code
//   to this sign-in is the verifier supabase-js stored for the flow
//   `signInWithOAuth` started, selected by its `flowId`: a code from any
//   other flow fails the exchange. One callback is taken per sign-in; any
//   later one is answered with the failed page and changes nothing.
// - The redirect's `redirect_to` is matched exactly against the project's
//   allow-list, so it carries no query of its own (no `sb_flow_id`).
// - GoTrue puts a redirect error in the query and repeats it in the
//   fragment, which a browser never sends. A callback with nothing in its
//   query is answered with a page whose script sends the fragment back as
//   a query (`FRAGMENT_PARAM` marks it); with no script it fails after
//   `FRAGMENT_GRACE_MS`.
// - The raw error (its code and description) goes to the log only, never
//   to the page or the result's text; the code's value and tokens are never
//   logged.
//
// Electron-free: `fetch`, `openExternal` and the storage are arguments, so
// vitest runs it under Node.

import * as http from 'node:http';
import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js';
import { currentLanguage, translate, type Key, type Language } from '../i18n';
import { silent, type Logger } from '../log';
import type { SupabaseConfig } from './config';
import type { Persistence, SessionStore } from './sessionStore';

export const CALLBACK_PORTS: readonly number[] = [53682, 53683, 53684];
export const CALLBACK_HOST = '127.0.0.1';
export const CALLBACK_PATH = '/auth/callback';
export const SIGN_IN_TIMEOUT_MS = 5 * 60 * 1000;
export const FRAGMENT_GRACE_MS = 10 * 1000;
export const FRAGMENT_PARAM = 'from_fragment';

/** The coach project's sign-up hook refuses an unverified address with this
 *  text as the redirect's `error_description`. */
export const UNVERIFIED_EMAIL_TEXT = 'An account needs a verified email address.';

export const PROVIDERS = ['google', 'discord'] as const;
export type Provider = (typeof PROVIDERS)[number];

export const PROVIDER_SCOPES: Readonly<Record<Provider, string>> = {
  google: 'openid email profile',
  discord: 'identify email',
};

export type SignInError =
  | 'auth.error.unverifiedEmail'
  | 'auth.error.cancelled'
  | 'auth.error.timeout'
  | 'auth.error.noPort'
  | 'auth.error.failed';

export interface AccountStatus {
  signedIn: boolean;
  userId: string | null;
  email: string | null;
  /** The provider the session was signed in with, as Supabase names it. */
  provider: string | null;
  /** Whether the session outlives this launch (`SessionStore`). */
  persistence: Persistence;
}

export type SignInResult =
  | { ok: true; account: AccountStatus }
  | { ok: false; error: SignInError; message: string };

/** Electron's `net.fetch` takes no `URL`; supabase-js is handed an adapter. */
export type NetFetch = (input: string | Request, init?: RequestInit) => Promise<Response>;

export interface CloudAuthOptions {
  supabase: SupabaseConfig;
  fetch: NetFetch;
  storage: SessionStore;
  openExternal: (url: string) => Promise<void>;
  log?: Logger;
  /** The language the callback page and the result's text are in. */
  language?: () => Language;
  ports?: readonly number[];
  timeoutMs?: number;
  fragmentGraceMs?: number;
}

/** The key a redirect error maps to: the hook's refusal by its text (the
 *  status alone is any 403), the provider's `access_denied` without it as
 *  cancelled, anything else as failed. */
export function redirectErrorKey(error: string | null, description: string | null): SignInError {
  if (description?.includes(UNVERIFIED_EMAIL_TEXT)) return 'auth.error.unverifiedEmail';
  if (error === 'access_denied') return 'auth.error.cancelled';
  return 'auth.error.failed';
}

/** Text in an element or a double-quoted attribute; an apostrophe stays. */
function escapeHtml(text: string): string {
  return text.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);
}

export type PageKind = 'done' | 'failed';

/** The page the browser tab shows: self-contained, inline style only. */
export function callbackPage(language: Language, kind: PageKind, script?: string): string {
  const title = translate(language, kind === 'done' ? 'auth.callback.doneTitle' : 'auth.callback.failedTitle');
  const body = translate(language, kind === 'done' ? 'auth.callback.done' : 'auth.callback.failed');
  return [
    '<!doctype html>',
    `<html lang="${escapeHtml(language)}">`,
    '<head><meta charset="utf-8">',
    `<title>${escapeHtml(title)}</title>`,
    '</head>',
    '<body style="font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;line-height:1.5;color:#222">',
    `<h1 style="font-size:1.25rem">${escapeHtml(title)}</h1>`,
    `<p>${escapeHtml(body)}</p>`,
    script ? `<script>${script}</script>` : '',
    '</body></html>',
    '',
  ].join('\n');
}

const FORWARD_SCRIPT =
  `var h=location.hash.slice(1);` +
  `location.replace('${CALLBACK_PATH}?'+(h?h+'&':'')+'${FRAGMENT_PARAM}=1');`;

function statusOf(session: Session | null, persistence: Persistence): AccountStatus {
  const user = session?.user ?? null;
  const provider = user?.app_metadata?.provider;
  return {
    signedIn: user !== null,
    userId: user?.id ?? null,
    email: user?.email ?? null,
    provider: typeof provider === 'string' ? provider : null,
    persistence,
  };
}

function sameStatus(a: AccountStatus, b: AccountStatus): boolean {
  return a.signedIn === b.signedIn && a.userId === b.userId && a.email === b.email && a.provider === b.provider;
}

/** Listens on the first port of `ports` that binds; `null` when none does. */
async function listenOnFirstFree(
  server: http.Server,
  ports: readonly number[],
  log: Logger,
): Promise<number | null> {
  for (const port of ports) {
    try {
      await new Promise<void>((resolve, reject) => {
        const onError = (error: Error) => {
          server.off('listening', onListening);
          reject(error);
        };
        const onListening = () => {
          server.off('error', onError);
          resolve();
        };
        server.once('error', onError);
        server.once('listening', onListening);
        server.listen(port, CALLBACK_HOST);
      });
      return port;
    } catch (error) {
      log.info('a sign-in port is not free', { port, error: (error as NodeJS.ErrnoException).code ?? String(error) });
    }
  }
  return null;
}

/** One sign-in, from the listener's start to its close. */
class Attempt {
  readonly server: http.Server;
  readonly done: Promise<SignInResult>;
  flowId: string | null = null;
  private resolve!: (result: SignInResult) => void;
  private claimed = false;
  settled = false;
  private timer: NodeJS.Timeout | null = null;
  private grace: NodeJS.Timeout | null = null;

  constructor(
    private readonly auth: CloudAuth,
    private readonly log: Logger,
    private readonly graceMs: number,
  ) {
    this.done = new Promise((resolve) => (this.resolve = resolve));
    this.server = http.createServer((req, res) => {
      this.handle(req, res).catch((error: unknown) => {
        this.log.error('the sign-in callback failed', { error: String(error) });
        if (!res.headersSent) this.page(res, 'failed');
        this.finish(this.auth.failure('auth.error.failed'));
      });
    });
  }

  startTimer(ms: number): void {
    this.timer = setTimeout(() => {
      this.log.warn('sign-in timed out');
      this.finish(this.auth.failure('auth.error.timeout'));
    }, ms);
  }

  private page(res: http.ServerResponse, kind: PageKind, script?: string): void {
    const csp = script
      ? "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'"
      : "default-src 'none'; style-src 'unsafe-inline'";
    res.writeHead(200, {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
      'Referrer-Policy': 'no-referrer',
      'Content-Security-Policy': csp,
      Connection: 'close',
    });
    res.end(callbackPage(this.auth.language(), kind, script));
  }

  private async handle(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', `http://${CALLBACK_HOST}`);
    if (req.method !== 'GET' || url.pathname !== CALLBACK_PATH) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8', Connection: 'close' });
      res.end('Not found\n');
      return;
    }
    if (this.claimed) {
      this.log.warn('a second sign-in callback was refused');
      this.page(res, 'failed');
      return;
    }
    const params = url.searchParams;
    const code = params.get('code');
    const error = params.get('error');
    const errorCode = params.get('error_code');
    const description = params.get('error_description');
    const hasError = error !== null || errorCode !== null || description !== null;
    if (!code && !hasError && !params.has(FRAGMENT_PARAM)) {
      this.page(res, 'failed', FORWARD_SCRIPT);
      this.grace ??= setTimeout(() => {
        if (this.claimed) return;
        this.claimed = true;
        this.log.warn('the sign-in callback carried no code');
        this.finish(this.auth.failure('auth.error.failed'));
      }, this.graceMs);
      return;
    }
    this.claimed = true;
    if (hasError) {
      this.log.warn('the sign-in was refused on the redirect', {
        error,
        error_code: errorCode,
        error_description: description,
      });
      this.page(res, 'failed');
      this.finish(this.auth.failure(redirectErrorKey(error, description)));
      return;
    }
    if (!code) {
      this.log.warn('the sign-in callback carried no code');
      this.page(res, 'failed');
      this.finish(this.auth.failure('auth.error.failed'));
      return;
    }
    const result = await this.auth.exchange(code, this.flowId);
    this.page(res, result.ok ? 'done' : 'failed');
    this.finish(result);
  }

  /** Settles the sign-in once and closes the listener. */
  finish(result: SignInResult): void {
    if (this.settled) return;
    this.settled = true;
    this.claimed = true;
    if (this.timer) clearTimeout(this.timer);
    if (this.grace) clearTimeout(this.grace);
    // `close` stops new connections; the open ones were answered with
    // `Connection: close`, and `closeIdleConnections` drops any left idle.
    this.server.close();
    this.server.closeIdleConnections();
    this.resolve(result);
  }

  closed(): Promise<void> {
    return new Promise((resolve) => {
      if (!this.server.listening) resolve();
      else this.server.once('close', () => resolve());
    });
  }
}

/** The account, signed in or not. One per launch. */
export class CloudAuth {
  readonly client: SupabaseClient;
  readonly language: () => Language;
  private readonly storage: SessionStore;
  private readonly openExternal: (url: string) => Promise<void>;
  private readonly log: Logger;
  private readonly ports: readonly number[];
  private readonly timeoutMs: number;
  private readonly graceMs: number;
  private current: AccountStatus;
  private attempt: Attempt | null = null;
  private readonly listeners = new Set<(status: AccountStatus) => void>();

  constructor(options: CloudAuthOptions) {
    this.storage = options.storage;
    this.openExternal = options.openExternal;
    this.log = options.log ?? silent;
    this.language = options.language ?? currentLanguage;
    this.ports = options.ports ?? CALLBACK_PORTS;
    this.timeoutMs = options.timeoutMs ?? SIGN_IN_TIMEOUT_MS;
    this.graceMs = options.fragmentGraceMs ?? FRAGMENT_GRACE_MS;
    this.current = statusOf(null, this.storage.persistence);
    const fetch = options.fetch;
    this.client = createClient(options.supabase.url, options.supabase.anonKey, {
      auth: {
        flowType: 'pkce',
        storage: this.storage,
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: false,
      },
      global: { fetch: (input, init) => fetch(input instanceof URL ? input.href : input, init) },
    });
    this.client.auth.onAuthStateChange((_event, session) => this.update(session));
  }

  private update(session: Session | null): void {
    const next = statusOf(session, this.storage.persistence);
    if (sameStatus(next, this.current)) return;
    this.current = next;
    for (const listener of [...this.listeners]) listener(next);
  }

  /** The status once the stored session, if any, has been read (and
   *  refreshed when it had expired). */
  async ready(): Promise<AccountStatus> {
    const { data } = await this.client.auth.getSession();
    this.update(data.session);
    return this.current;
  }

  status(): AccountStatus {
    return this.current;
  }

  /** Calls `listener` on every change of the account; returns the unsubscribe. */
  onChange(listener: (status: AccountStatus) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  failure(error: SignInError, params?: Record<string, string>): SignInResult {
    return { ok: false, error, message: translate(this.language(), error satisfies Key, params) };
  }

  /** Exchanges a callback's code for the flow's session. */
  async exchange(code: string, flowId: string | null): Promise<SignInResult> {
    let failure: Record<string, unknown> | null = null;
    try {
      const { data, error } = await this.client.auth.exchangeCodeForSession(code, flowId ? { flowId } : undefined);
      if (!error && data.session) {
        this.update(data.session);
        this.log.info('signed in', { provider: this.current.provider });
        return { ok: true, account: this.current };
      }
      failure = error
        ? { name: error.name, status: error.status ?? null, error_code: error.code ?? null, message: error.message }
        : { message: 'no session in the response' };
    } catch (error) {
      failure = { message: String(error) };
    }
    this.log.warn('the sign-in code could not be exchanged for a session', failure);
    return this.failure('auth.error.failed');
  }

  /** Signs in with `provider` in the system browser. A sign-in already
   *  waiting is cancelled first. Resolves when the callback came, the
   *  timeout passed or the sign-in was cancelled; never rejects. */
  async signIn(provider: Provider): Promise<SignInResult> {
    await this.cancelSignIn();
    const attempt = new Attempt(this, this.log, this.graceMs);
    this.attempt = attempt;
    void attempt.done.then(() => {
      if (this.attempt === attempt) this.attempt = null;
    });
    const port = await listenOnFirstFree(attempt.server, this.ports, this.log);
    // Cancelled while the port was being bound: `finish` closed nothing then.
    if (attempt.settled) {
      attempt.server.close();
      return attempt.done;
    }
    if (port === null) {
      this.log.warn('no sign-in port is free', { ports: this.ports });
      attempt.finish(this.failure('auth.error.noPort', { ports: this.ports.join(', ') }));
      return attempt.done;
    }
    attempt.startTimer(this.timeoutMs);
    try {
      const { data, error } = await this.client.auth.signInWithOAuth({
        provider,
        options: {
          redirectTo: `http://${CALLBACK_HOST}:${port}${CALLBACK_PATH}`,
          skipBrowserRedirect: true,
          scopes: PROVIDER_SCOPES[provider],
        },
      });
      if (error || !data.url) throw error ?? new Error('no authorize URL');
      // Cancelled while the URL was being built: the listener is closed, so
      // the browser is never sent to a page whose redirect nobody answers.
      if (attempt.settled) return attempt.done;
      attempt.flowId = data.flowId ?? null;
      await this.openExternal(data.url);
    } catch (error) {
      this.log.warn('the sign-in page could not be opened', { error: String(error) });
      attempt.finish(this.failure('auth.error.failed'));
    }
    return attempt.done;
  }

  /** Cancels a sign-in that is waiting for its callback; resolves once its
   *  listener is closed. Nothing waiting is nothing to do. */
  async cancelSignIn(): Promise<void> {
    const attempt = this.attempt;
    if (!attempt) return;
    this.attempt = null;
    attempt.finish(this.failure('auth.error.cancelled'));
    await attempt.closed();
  }

  /** Signs out of this install: the refresh token is revoked when the
   *  network allows, and the stored session is removed either way. */
  async signOut(): Promise<void> {
    const { error } = await this.client.auth.signOut({ scope: 'local' });
    if (error) this.log.warn('signing out reached no server; the session was removed here', { error: error.message });
    this.update(null);
  }

  /** Stops the refresh timer and any waiting sign-in. */
  async dispose(): Promise<void> {
    await this.cancelSignIn();
    await this.client.auth.stopAutoRefresh();
  }
}
