// The storage adapter supabase-js keeps the session in: a small key-value
// map in memory, written encrypted by Electron's `safeStorage` to
// `<userData>/session.bin` whenever it changes, and read back at launch.
//
// Traps and contracts:
// - On Linux with no keyring, `safeStorage` falls back to the `basic_text`
//   backend, which "encrypts" with a fixed password, and still reports
//   encryption as available. The session is then never written or read:
//   the person signs in at each launch. `unknown` (asked before the app is
//   ready) is refused the same way.
// - supabase-js keeps the PKCE code verifier in this same storage, under
//   keys ending `-code-verifier`. Those stay in memory only: a sign-in never
//   outlives its launch, and a verifier never reaches the disk.
// - The file is the whole map, replaced through a temporary file and a
//   rename, mode 0600. One that cannot be decrypted or parsed is ignored
//   with a warning and replaced by the next write.
//
// Electron-free: `safeStorage` is an argument, so vitest runs it under Node.

import * as fs from 'node:fs';
import * as path from 'node:path';
import { silent, type Logger } from '../log';

export const SESSION_FILE = 'session.bin';

/** The part of Electron's `safeStorage` this module uses. */
export interface SafeStorageLike {
  isEncryptionAvailable(): boolean;
  encryptString(plainText: string): Buffer;
  decryptString(encrypted: Buffer): string;
  /** Linux only in Electron; absent elsewhere. */
  getSelectedStorageBackend?(): string;
}

/** Whether the session outlives the launch, and if not, why. */
export type Persistence =
  | { kept: true }
  | { kept: false; reason: 'noKeyring' | 'noEncryption' };

const REFUSED_BACKENDS = new Set(['basic_text', 'unknown']);

export function sessionPersistence(safeStorage: SafeStorageLike, platform: NodeJS.Platform): Persistence {
  if (platform === 'linux') {
    const backend = safeStorage.getSelectedStorageBackend?.() ?? 'unknown';
    if (REFUSED_BACKENDS.has(backend)) return { kept: false, reason: 'noKeyring' };
  }
  if (!safeStorage.isEncryptionAvailable()) return { kept: false, reason: 'noEncryption' };
  return { kept: true };
}

function memoryOnly(key: string): boolean {
  return key.endsWith('-code-verifier');
}

/** Writes `data` to `file` through a temporary file beside it, owner-only. */
function writeSecretAtomically(file: string, data: Buffer): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.tmp`;
  const fd = fs.openSync(temp, 'w', 0o600);
  try {
    fs.writeSync(fd, data);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  try {
    fs.renameSync(temp, file);
  } catch (error) {
    fs.rmSync(temp, { force: true });
    throw error;
  }
}

export interface SessionStoreOptions {
  /** Electron's `userData` directory. */
  dir: string;
  safeStorage: SafeStorageLike;
  platform: NodeJS.Platform;
  log?: Logger;
}

/** supabase-js's `SupportedStorage`, synchronous. */
export class SessionStore {
  readonly file: string;
  readonly persistence: Persistence;
  private readonly items = new Map<string, string>();
  private readonly safeStorage: SafeStorageLike;
  private readonly log: Logger;

  constructor(options: SessionStoreOptions) {
    this.file = path.join(options.dir, SESSION_FILE);
    this.safeStorage = options.safeStorage;
    this.log = options.log ?? silent;
    this.persistence = sessionPersistence(options.safeStorage, options.platform);
    if (this.persistence.kept) this.load();
    else this.log.info('the session is kept for this launch only', { reason: this.persistence.reason });
  }

  private load(): void {
    let data: Buffer;
    try {
      data = fs.readFileSync(this.file);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
        this.log.warn('session.bin could not be read', { error: String(error) });
      }
      return;
    }
    try {
      const parsed: unknown = JSON.parse(this.safeStorage.decryptString(data));
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new SyntaxError('not an object');
      for (const [key, value] of Object.entries(parsed)) {
        if (typeof value === 'string' && !memoryOnly(key)) this.items.set(key, value);
      }
    } catch (error) {
      this.log.warn('session.bin could not be decrypted or parsed; ignored', { error: String(error) });
    }
  }

  private save(): void {
    if (!this.persistence.kept) return;
    const kept: Record<string, string> = {};
    for (const [key, value] of this.items) if (!memoryOnly(key)) kept[key] = value;
    try {
      if (Object.keys(kept).length === 0) fs.rmSync(this.file, { force: true });
      else writeSecretAtomically(this.file, this.safeStorage.encryptString(JSON.stringify(kept)));
    } catch (error) {
      this.log.warn('session.bin could not be written', { error: String(error) });
    }
  }

  getItem(key: string): string | null {
    return this.items.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.items.set(key, value);
    if (!memoryOnly(key)) this.save();
  }

  removeItem(key: string): void {
    if (!this.items.delete(key)) return;
    if (!memoryOnly(key)) this.save();
  }
}
