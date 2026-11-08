import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as net from 'node:net';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { Logger } from '../log';
import {
  CALLBACK_PORTS,
  SIGN_IN_TIMEOUT_MS,
  CloudAuth,
  FRAGMENT_PARAM,
  PROVIDER_SCOPES,
  redirectErrorKey,
  type CloudAuthOptions,
  type NetFetch,
  type SignInResult,
} from './auth';
import { parseBuildConfig } from './config';
import { SESSION_FILE, SessionStore, sessionPersistence, type SafeStorageLike } from './sessionStore';

const SUPABASE = { url: 'https://project.example.invalid', anonKey: 'anon-key-for-tests' };

// The hook's refusal and the English texts, as the wording for the sign-in gives them.
const HOOK_TEXT = 'An account needs a verified email address.';
const EN_FAILED = "Sign-in didn't finish. Try again.";
const EN_CANCELLED = 'Sign-in was cancelled.';

interface Line {
  level: string;
  message: string;
  fields: unknown;
}

function recorder(): { log: Logger; lines: Line[] } {
  const lines: Line[] = [];
  const at = (level: string) => (message: string, fields?: unknown) => void lines.push({ level, message, fields });
  return { log: { debug: at('DEBUG'), info: at('INFO'), warn: at('WARNING'), error: at('ERROR') }, lines };
}

/** "Encrypts" by prefix, so a test can tell the file is not the plain text. */
function fakeSafeStorage(backend = 'gnome_libsecret', available = true): SafeStorageLike {
  return {
    isEncryptionAvailable: () => available,
    encryptString: (text) => Buffer.from(`enc:${Buffer.from(text).toString('base64')}`),
    decryptString: (data) => {
      const text = data.toString();
      if (!text.startsWith('enc:')) throw new Error('not ours');
      return Buffer.from(text.slice(4), 'base64').toString();
    },
    getSelectedStorageBackend: () => backend,
  };
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

/** A port nothing listens on, as the OS hands one out. */
async function freePort(): Promise<number> {
  const server = net.createServer();
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as net.AddressInfo).port;
  await new Promise<void>((resolve) => server.close(() => resolve()));
  return port;
}

async function occupied(): Promise<{ port: number; close: () => Promise<void> }> {
  const server = net.createServer();
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as net.AddressInfo).port;
  return { port, close: () => new Promise((resolve) => server.close(() => resolve())) };
}

function sessionBody(over: Record<string, unknown> = {}) {
  return {
    access_token: 'access-token-value',
    refresh_token: 'refresh-token-value',
    token_type: 'bearer',
    expires_in: 3600,
    user: {
      id: '00000000-0000-4000-8000-000000000001',
      aud: 'authenticated',
      email: 'player@example.invalid',
      app_metadata: { provider: 'google', providers: ['google'] },
      user_metadata: {},
      created_at: '2026-11-04T00:00:00Z',
    },
    ...over,
  };
}

interface Seen {
  url: string;
  method: string;
  body: string | null;
}

/** Supabase's side, mocked: the token exchange answers `token`, logout 204. */
function supabaseFetch(token: () => Promise<Response> | Response): { fetch: NetFetch; seen: Seen[] } {
  const seen: Seen[] = [];
  const fetch: NetFetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input.url;
    const body = init?.body == null ? null : String(init.body);
    seen.push({ url, method: init?.method ?? 'GET', body });
    if (url.startsWith(`${SUPABASE.url}/auth/v1/token?grant_type=pkce`)) return token();
    if (url.startsWith(`${SUPABASE.url}/auth/v1/logout`)) return new Response(null, { status: 204 });
    return new Response(JSON.stringify({ msg: 'unexpected in a test' }), { status: 500 });
  };
  return { fetch, seen };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

let dir: string;
const made: CloudAuth[] = [];

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shell-auth-'));
});

afterEach(async () => {
  for (const auth of made.splice(0)) await auth.dispose();
  fs.rmSync(dir, { recursive: true, force: true });
});

function harness(over: Partial<CloudAuthOptions> & { token?: () => Promise<Response> | Response } = {}) {
  const { log, lines } = recorder();
  const { fetch, seen } = supabaseFetch(over.token ?? (() => json(sessionBody())));
  const opened = deferred<string>();
  const storage =
    over.storage ?? new SessionStore({ dir, safeStorage: fakeSafeStorage(), platform: 'linux', log });
  const auth = new CloudAuth({
    supabase: SUPABASE,
    fetch,
    storage,
    openExternal: async (url) => opened.resolve(url),
    log,
    language: () => 'en',
    ...over,
  });
  made.push(auth);
  return { auth, lines, seen, opened: opened.promise, storage };
}

/** The `redirect_to` of the authorize URL the browser was sent to. */
async function redirectOf(opened: Promise<string>): Promise<URL> {
  const authorize = new URL(await opened);
  return new URL(authorize.searchParams.get('redirect_to') ?? '');
}

async function hit(redirect: URL, query: string): Promise<{ status: number; text: string }> {
  const response = await fetch(`${redirect.origin}${redirect.pathname}${query}`);
  return { status: response.status, text: await response.text() };
}

describe('the sign-in listener', () => {
  it('listens on the three fixed loopback ports, in order', () => {
    expect(CALLBACK_PORTS).toEqual([53682, 53683, 53684]);
  });

  it('waits 5 minutes by default', () => {
    expect(SIGN_IN_TIMEOUT_MS).toBe(5 * 60 * 1000);
  });

  it('falls back to the next port when the first is taken', async () => {
    const taken = await occupied();
    const next = await freePort();
    try {
      const { auth, opened } = harness({ ports: [taken.port, next] });
      const result = auth.signIn('google');
      const redirect = await redirectOf(opened);
      expect(redirect.href).toBe(`http://127.0.0.1:${next}/auth/callback`);
      await hit(redirect, '?code=a-code');
      expect((await result).ok).toBe(true);
    } finally {
      await taken.close();
    }
  });

  it('names every port when all of them are taken', async () => {
    const a = await occupied();
    const b = await occupied();
    try {
      const { auth } = harness({ ports: [a.port, b.port] });
      const result = await auth.signIn('google');
      expect(result).toEqual({
        ok: false,
        error: 'auth.error.noPort',
        message: `Sign-in needs one of the ports ${a.port}, ${b.port} on this computer, and all of them are in use. Close the program using them and try again.`,
      });
    } finally {
      await a.close();
      await b.close();
    }
  });

  it('times out, and closes the listener', async () => {
    const port = await freePort();
    const { auth, opened } = harness({ ports: [port], timeoutMs: 50 });
    const result = await auth.signIn('google');
    const redirect = await redirectOf(opened);
    expect(result).toMatchObject({ ok: false, error: 'auth.error.timeout' });
    await expect(fetch(redirect.href)).rejects.toThrow();
  });
});

describe('the authorize URL', () => {
  it('is PKCE with S256, asks only the provider scopes, and redirects to the listener', async () => {
    const port = await freePort();
    const { auth, opened, seen } = harness({ ports: [port] });
    const result = auth.signIn('discord');
    const authorize = new URL(await opened);
    expect(authorize.origin + authorize.pathname).toBe(`${SUPABASE.url}/auth/v1/authorize`);
    expect(authorize.searchParams.get('provider')).toBe('discord');
    expect(authorize.searchParams.get('scopes')).toBe(PROVIDER_SCOPES.discord);
    expect(authorize.searchParams.get('code_challenge_method')).toBe('s256');
    expect(authorize.searchParams.get('redirect_to')).toBe(`http://127.0.0.1:${port}/auth/callback`);
    await hit(new URL(authorize.searchParams.get('redirect_to') ?? ''), '?code=the-auth-code');
    expect((await result).ok).toBe(true);
    // RFC 7636: the challenge is base64url(SHA-256(verifier)), and the
    // exchange sends this flow's verifier with the callback's code.
    expect(seen.map((s) => s.url)).toEqual([`${SUPABASE.url}/auth/v1/token?grant_type=pkce`]);
    const exchange = seen[0];
    const body = JSON.parse(exchange?.body ?? '{}') as { auth_code: string; code_verifier: string };
    expect(body.auth_code).toBe('the-auth-code');
    const challenge = crypto.createHash('sha256').update(body.code_verifier).digest('base64url');
    expect(authorize.searchParams.get('code_challenge')).toBe(challenge);
  });
});

describe('the callback', () => {
  async function signInWith(query: string, over: Parameters<typeof harness>[0] = {}) {
    const port = await freePort();
    const h = harness({ ports: [port], ...over });
    const result = h.auth.signIn('google');
    const redirect = await redirectOf(h.opened);
    const page = await hit(redirect, query);
    return { ...h, result: await result, page, redirect };
  }

  it('signs in on a code, and answers the done page', async () => {
    const { result, page, auth } = await signInWith('?code=a-code');
    expect(result).toMatchObject({ ok: true, account: { signedIn: true, provider: 'google' } });
    expect(page.status).toBe(200);
    expect(page.text).toContain('<html lang="en">');
    expect(page.text).toContain("You're signed in. You can close this tab and go back to Sensei Top.");
    expect(auth.status().signedIn).toBe(true);
  });

  it('answers in the shell language', async () => {
    const { page } = await signInWith('?code=a-code', { language: () => 'pt-BR' });
    expect(page.text).toContain('<html lang="pt-BR">');
    expect(page.text).toContain('Você entrou no Sensei Top');
  });

  it('refuses a callback with no code', async () => {
    const { result, page } = await signInWith(`?${FRAGMENT_PARAM}=1`);
    expect(result).toEqual({ ok: false, error: 'auth.error.failed', message: EN_FAILED });
    expect(page.text).toContain("Sign-in didn't finish. Close this tab and try again from Sensei Top.");
  });

  it('refuses a code the exchange rejects, logging the error but not the code', async () => {
    const { result, lines, page } = await signInWith('?code=a-code-from-another-flow', {
      token: () => json({ code: 404, error_code: 'flow_state_not_found', msg: 'invalid flow state' }, 404),
    });
    expect(result).toEqual({ ok: false, error: 'auth.error.failed', message: EN_FAILED });
    expect(page.text).toContain("Sign-in didn't finish");
    const logged = JSON.stringify(lines);
    expect(logged).toContain('flow_state_not_found');
    expect(logged).not.toContain('a-code-from-another-flow');
  });

  it('refuses a second callback while the first is being exchanged', async () => {
    const release = deferred<void>();
    const port = await freePort();
    const { auth, opened } = harness({
      ports: [port],
      token: async () => {
        await release.promise;
        return json(sessionBody());
      },
    });
    const result = auth.signIn('google');
    const redirect = await redirectOf(opened);
    const first = hit(redirect, '?code=first');
    // The first request has reached the exchange before the second is sent.
    await new Promise((resolve) => setTimeout(resolve, 50));
    const second = await hit(redirect, '?code=second');
    expect(second.text).toContain("Sign-in didn't finish");
    release.resolve();
    expect((await first).text).toContain("You're signed in");
    expect((await result).ok).toBe(true);
  });

  it('answers another path with 404 and keeps waiting', async () => {
    const port = await freePort();
    const { auth, opened } = harness({ ports: [port] });
    const result = auth.signIn('google');
    const redirect = await redirectOf(opened);
    const favicon = await fetch(`${redirect.origin}/favicon.ico`);
    expect(favicon.status).toBe(404);
    await hit(redirect, '?code=a-code');
    expect((await result).ok).toBe(true);
  });

  it('maps the provider cancelling', async () => {
    const { result } = await signInWith('?error=access_denied&error_description=The+user+denied+access');
    expect(result).toEqual({ ok: false, error: 'auth.error.cancelled', message: EN_CANCELLED });
  });

  it("maps the sign-up hook's refusal by its text", async () => {
    const { result, page } = await signInWith(
      `?error=server_error&error_code=unexpected_failure&error_description=${encodeURIComponent(HOOK_TEXT)}`,
    );
    expect(result).toMatchObject({ ok: false, error: 'auth.error.unverifiedEmail' });
    expect(page.text).not.toContain(HOOK_TEXT);
  });

  it('sends a fragment back as a query, and reads the error from it', async () => {
    const port = await freePort();
    const { auth, opened } = harness({ ports: [port] });
    const result = auth.signIn('google');
    const redirect = await redirectOf(opened);
    const forward = await hit(redirect, '');
    expect(forward.text).toContain('location.hash');
    expect(forward.text).toContain(FRAGMENT_PARAM);
    await hit(redirect, `?error=access_denied&${FRAGMENT_PARAM}=1`);
    expect(await result).toMatchObject({ ok: false, error: 'auth.error.cancelled' });
  });

  it('fails a callback with nothing in it when no fragment comes back', async () => {
    const { result } = await signInWith('', { fragmentGraceMs: 30 });
    expect(result).toMatchObject({ ok: false, error: 'auth.error.failed' });
  });
});

describe('redirectErrorKey', () => {
  it('matches the hook on its text, whatever the error', () => {
    expect(redirectErrorKey('server_error', HOOK_TEXT)).toBe('auth.error.unverifiedEmail');
    expect(redirectErrorKey('access_denied', `Error: ${HOOK_TEXT}`)).toBe('auth.error.unverifiedEmail');
  });

  it('reads access_denied without the text as cancelled, the rest as failed', () => {
    expect(redirectErrorKey('access_denied', null)).toBe('auth.error.cancelled');
    expect(redirectErrorKey('server_error', 'Forbidden')).toBe('auth.error.failed');
    expect(redirectErrorKey(null, null)).toBe('auth.error.failed');
  });
});

describe('cancelling and superseding a sign-in', () => {
  it('cancels the waiting sign-in when another starts', async () => {
    const port = await freePort();
    const first = deferred<string>();
    const second = deferred<string>();
    const urls = [first, second];
    const { auth } = harness({ ports: [port], openExternal: async (url) => urls.shift()?.resolve(url) });
    const one = auth.signIn('google');
    await first.promise;
    const two = auth.signIn('google');
    expect(await one).toEqual({ ok: false, error: 'auth.error.cancelled', message: EN_CANCELLED });
    const redirect = await redirectOf(second.promise);
    await hit(redirect, '?code=a-code');
    expect((await two).ok).toBe(true);
  });

  it('never opens the browser for a sign-in cancelled while its URL was built', async () => {
    const port = await freePort();
    let auth: CloudAuth | null = null;
    // supabase-js stores the flow's verifier while it builds the authorize URL.
    class CancellingStore extends SessionStore {
      override setItem(key: string, value: string): void {
        super.setItem(key, value);
        if (key.endsWith('-code-verifier')) void auth?.cancelSignIn();
      }
    }
    const storage = new CancellingStore({ dir, safeStorage: fakeSafeStorage(), platform: 'linux' });
    const opened: string[] = [];
    auth = harness({ ports: [port], storage, openExternal: async (url) => void opened.push(url) }).auth;
    expect(await auth.signIn('google')).toEqual({ ok: false, error: 'auth.error.cancelled', message: EN_CANCELLED });
    expect(opened).toEqual([]);
  });

  it('fails when the browser cannot be opened', async () => {
    const port = await freePort();
    const { auth } = harness({
      ports: [port],
      openExternal: async () => {
        throw new Error('no browser');
      },
    });
    expect(await auth.signIn('google')).toMatchObject({ ok: false, error: 'auth.error.failed' });
  });
});

describe('the session across launches and sign-out', () => {
  async function signedIn(storage: SessionStore) {
    const port = await freePort();
    const h = harness({ ports: [port], storage });
    const result = h.auth.signIn('google');
    await hit(await redirectOf(h.opened), '?code=a-code');
    const outcome: SignInResult = await result;
    expect(outcome.ok).toBe(true);
    return h;
  }

  it('reads a kept session back at the next launch', async () => {
    const keyring = fakeSafeStorage();
    await signedIn(new SessionStore({ dir, safeStorage: keyring, platform: 'linux' }));
    const file = fs.readFileSync(path.join(dir, SESSION_FILE));
    expect(file.toString()).not.toContain('refresh-token-value');
    const next = harness({ storage: new SessionStore({ dir, safeStorage: keyring, platform: 'linux' }) });
    expect(await next.auth.ready()).toMatchObject({ signedIn: true, persistence: { kept: true } });
  });

  it('keeps nothing on disk without a keyring, and says why', async () => {
    const storage = new SessionStore({ dir, safeStorage: fakeSafeStorage('basic_text'), platform: 'linux' });
    const { auth } = await signedIn(storage);
    expect(auth.status()).toMatchObject({ signedIn: true, persistence: { kept: false, reason: 'noKeyring' } });
    expect(fs.existsSync(path.join(dir, SESSION_FILE))).toBe(false);
  });

  it('signs out: revokes, removes the file and tells the listeners', async () => {
    const { auth, seen } = await signedIn(new SessionStore({ dir, safeStorage: fakeSafeStorage(), platform: 'linux' }));
    const heard: boolean[] = [];
    auth.onChange((status) => heard.push(status.signedIn));
    await auth.signOut();
    expect(seen.some((s) => s.url.startsWith(`${SUPABASE.url}/auth/v1/logout`) && s.method === 'POST')).toBe(true);
    expect(fs.existsSync(path.join(dir, SESSION_FILE))).toBe(false);
    expect(auth.status().signedIn).toBe(false);
    expect(heard).toEqual([false]);
  });
});

describe('SessionStore', () => {
  it('refuses the basic_text backend, and an undetermined one', () => {
    for (const backend of ['basic_text', 'unknown']) {
      expect(sessionPersistence(fakeSafeStorage(backend), 'linux')).toEqual({ kept: false, reason: 'noKeyring' });
    }
    const store = new SessionStore({ dir, safeStorage: fakeSafeStorage('basic_text'), platform: 'linux' });
    store.setItem('sb-project-auth-token', '{"refresh_token":"x"}');
    expect(store.getItem('sb-project-auth-token')).toBe('{"refresh_token":"x"}');
    expect(fs.readdirSync(dir)).toEqual([]);
  });

  it('never reads a file it would not write', () => {
    fs.writeFileSync(path.join(dir, SESSION_FILE), fakeSafeStorage().encryptString('{"k":"v"}'));
    const store = new SessionStore({ dir, safeStorage: fakeSafeStorage('basic_text'), platform: 'linux' });
    expect(store.getItem('k')).toBeNull();
  });

  it('keeps nothing when encryption is unavailable', () => {
    expect(sessionPersistence(fakeSafeStorage('gnome_libsecret', false), 'win32')).toEqual({
      kept: false,
      reason: 'noEncryption',
    });
  });

  it('asks no backend off Linux', () => {
    const { getSelectedStorageBackend: _, ...windows } = fakeSafeStorage();
    expect(sessionPersistence(windows, 'win32')).toEqual({ kept: true });
  });

  it('writes encrypted, owner-only, and leaves code verifiers in memory', () => {
    const store = new SessionStore({ dir, safeStorage: fakeSafeStorage(), platform: 'linux' });
    store.setItem('sb-project-auth-token', 'session-json');
    store.setItem('sb-project-auth-token-code-verifier', 'verifier');
    store.setItem('sb-project-auth-token-flow-abcdef12-code-verifier', 'verifier');
    const file = path.join(dir, SESSION_FILE);
    const plain = fakeSafeStorage().decryptString(fs.readFileSync(file));
    expect(JSON.parse(plain)).toEqual({ 'sb-project-auth-token': 'session-json' });
    if (process.platform !== 'win32') expect(fs.statSync(file).mode & 0o777).toBe(0o600);
    expect(store.getItem('sb-project-auth-token-code-verifier')).toBe('verifier');
    store.removeItem('sb-project-auth-token');
    expect(fs.existsSync(file)).toBe(false);
  });

  it('ignores a file it cannot decrypt, with a warning', () => {
    fs.writeFileSync(path.join(dir, SESSION_FILE), 'not encrypted by us');
    const { log, lines } = recorder();
    const store = new SessionStore({ dir, safeStorage: fakeSafeStorage(), platform: 'linux', log });
    expect(store.getItem('anything')).toBeNull();
    expect(lines.some((line) => line.level === 'WARNING')).toBe(true);
  });
});

describe('parseBuildConfig', () => {
  it('is absent with nothing set, or with only one of the two Supabase values', () => {
    expect(parseBuildConfig({})).toEqual({ supabase: null, sentryDsnDesktop: null, sentryDsnLocalApi: null });
    expect(parseBuildConfig({ supabaseUrl: 'https://p.example.invalid' }).supabase).toBeNull();
    expect(parseBuildConfig({ supabaseUrl: '  ', supabaseAnonKey: 'k' }).supabase).toBeNull();
  });

  it('refuses a URL that is not http(s)', () => {
    expect(parseBuildConfig({ supabaseUrl: 'not a url', supabaseAnonKey: 'k' }).supabase).toBeNull();
    expect(parseBuildConfig({ supabaseUrl: 'file:///x', supabaseAnonKey: 'k' }).supabase).toBeNull();
  });

  it('keeps what is set, without a trailing slash', () => {
    expect(
      parseBuildConfig({
        supabaseUrl: 'http://127.0.0.1:54321/',
        supabaseAnonKey: 'k',
        sentryDsnDesktop: 'https://d@sentry.example.invalid/1',
      }),
    ).toEqual({
      supabase: { url: 'http://127.0.0.1:54321', anonKey: 'k' },
      sentryDsnDesktop: 'https://d@sentry.example.invalid/1',
      sentryDsnLocalApi: null,
    });
  });
});
