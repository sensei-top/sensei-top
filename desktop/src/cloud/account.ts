// The account's actions from the shell's main process, and what follows a
// sign-in or a sign-out: the profile (the consent screen's three answers),
// export, "Delete my cloud history", "Delete my account", and the backup
// runs (`sync.ts`) each of these and the app's own events start.
//
// - **Sign-in.** The signed-in user goes to the error reports (`ReportsLink`)
//   and the profile is read; its `consent_errors` goes to them too, in the
//   same step, so the server restarts at most once. No profile means no
//   answers yet: error reports are off until the consent screen writes one.
// - **Backup runs**, only while the profile's `consent_sync` is on: at the
//   app's start (with a pull), at a sign-in (a pull only on an install that
//   never pulled for the account), when a match ends, and when a profile
//   write turns it on (with a pull). The session restored at launch is the
//   app's start whenever it arrives, before `start()` or after it. A match's
//   end reads the profile again first, so a backup another install turned
//   off sends nothing more.
// - **Delete my cloud history** also turns the backup off: the backup is
//   held off and any running backup let finish before the cloud deletes,
//   so nothing uploads after the delete; then `consent_sync` is written
//   false (the other answers as they were) and the sync state is cleared,
//   so turning the backup on again uploads every match. On another install
//   the pull that turning it on runs sees the deleted rows and drops their
//   digests, to the same effect (`sync.ts`). A failed delete changes nothing.
// - **Delete my account.** The cloud deletes the account first; only then is
//   the sync state removed and the session signed out. A failed delete
//   changes nothing here.
// - Replies carry an `AccountError` code, never text: the page words them.
//
// Traps and contracts:
// - `consented_at` and `age_confirmed_at` are this machine's time; the
//   profile has no server default for them. The age confirmation is written
//   once, by the first profile write, and never again.
// - A profile that could not be read is `unknown`, not `none`: the page
//   must not ask the consent questions again over a failed request. The next
//   backup trigger reads it again.
//
// Electron-free: the cloud, the reports and the save dialog are arguments.

import type { SupabaseClient } from '@supabase/supabase-js';
import { silent, type Logger } from '../log';
import type { AccountStatus } from './auth';
import type { CloudSync, PullWhen, SyncStatus } from './sync';

/** The user of the session restored at launch, when it is read within
 *  `waitMs`; `null` otherwise, a failed read included. */
export async function restoredUser(restored: Promise<AccountStatus>, waitMs: number, log: Logger = silent): Promise<string | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), waitMs);
    timer.unref?.();
  });
  try {
    const status = await Promise.race([restored, timeout]);
    return status?.signedIn ? status.userId : null;
  } catch (error) {
    log.warn('account: the stored session could not be read', { error: String(error) });
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export const EXPORT_FILE_NAME = 'sensei-top-account.json';
/** The shape `contribute_games` checks a policy version against (coach repo). */
export const POLICY_VERSION_PATTERN = /^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$/;

/** `public.profiles` as this module reads and writes it. */
export interface ProfileRow {
  user_id: string;
  age_confirmed_at: string;
  consent_sync: boolean;
  consent_errors: boolean;
  consent_coach_history: boolean;
  consent_version: string;
  consented_at: string;
}

export type ConsentPatch = Pick<ProfileRow, 'consent_sync' | 'consent_errors' | 'consent_coach_history' | 'consent_version' | 'consented_at'>;

/** The cloud's half: the profile and the rights functions. */
export interface AccountDb {
  readProfile(userId: string): Promise<ProfileRow | null>;
  insertProfile(row: ProfileRow): Promise<void>;
  updateProfile(userId: string, patch: ConsentPatch): Promise<void>;
  exportData(): Promise<unknown>;
  /** How many matches it marked deleted. */
  deleteCloudHistory(): Promise<number>;
  deleteAccount(): Promise<void>;
}

const PROFILE_COLUMNS = 'user_id,age_confirmed_at,consent_sync,consent_errors,consent_coach_history,consent_version,consented_at';

function failure(what: string, error: { message?: string; code?: string }): Error {
  return new Error(`${what}: ${error.code ?? ''} ${error.message ?? ''}`.trim());
}

/** `AccountDb` on the shell's one supabase-js client (`CloudAuth.client`). */
export function supabaseAccountDb(client: SupabaseClient): AccountDb {
  return {
    async readProfile(userId) {
      const { data, error } = await client.from('profiles').select(PROFILE_COLUMNS).eq('user_id', userId).maybeSingle();
      if (error) throw failure('profile select', error);
      return (data ?? null) as ProfileRow | null;
    },
    async insertProfile(row) {
      const { error } = await client.from('profiles').insert(row);
      if (error) throw failure('profile insert', error);
    },
    async updateProfile(userId, patch) {
      const { error } = await client.from('profiles').update(patch).eq('user_id', userId);
      if (error) throw failure('profile update', error);
    },
    async exportData() {
      const { data, error } = await client.rpc('export_my_data');
      if (error) throw failure('export_my_data', error);
      return data;
    },
    async deleteCloudHistory() {
      const { data, error } = await client.rpc('delete_my_cloud_history');
      if (error) throw failure('delete_my_cloud_history', error);
      return typeof data === 'number' ? data : Number(data ?? 0);
    },
    async deleteAccount() {
      const { error } = await client.rpc('delete_my_account');
      if (error) throw failure('delete_my_account', error);
    },
  };
}

/** The profile as the page sees it. */
export type ProfileState =
  | { state: 'unknown' }
  | { state: 'none' }
  | {
      state: 'read';
      ageConfirmedAt: string;
      consentSync: boolean;
      consentErrors: boolean;
      consentCoachHistory: boolean;
      consentVersion: string;
      consentedAt: string;
    };

/** What `AccountState` adds for a signed-in account. */
export interface AccountDetails {
  profile: ProfileState;
  sync: SyncStatus;
}

/** `unavailable`: no account in this build. `signedOut`: the action needs a
 *  sign-in. `invalid`: the page sent something malformed. `ageNotConfirmed`:
 *  a first profile needs the age confirmation. `failed`: the cloud or the
 *  disk refused it. */
export type AccountError = 'unavailable' | 'signedOut' | 'invalid' | 'ageNotConfirmed' | 'failed';

export type AccountReply = { ok: true; cancelled?: boolean; deleted?: number } | { ok: false; error: AccountError };

/** What the consent screen sends. */
export interface ProfileChange {
  consentSync: boolean;
  consentErrors: boolean;
  consentCoachHistory: boolean;
  /** The privacy policy's version the answers were given under. */
  policyVersion: string;
  /** Required by the first write, ignored after it. */
  ageConfirmed?: boolean;
}

export function parseProfileChange(value: unknown): ProfileChange | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  if (typeof raw.consentSync !== 'boolean' || typeof raw.consentErrors !== 'boolean' || typeof raw.consentCoachHistory !== 'boolean') return null;
  if (typeof raw.policyVersion !== 'string' || !POLICY_VERSION_PATTERN.test(raw.policyVersion)) return null;
  if (raw.ageConfirmed !== undefined && typeof raw.ageConfirmed !== 'boolean') return null;
  return {
    consentSync: raw.consentSync,
    consentErrors: raw.consentErrors,
    consentCoachHistory: raw.consentCoachHistory,
    policyVersion: raw.policyVersion,
    ...(raw.ageConfirmed === undefined ? {} : { ageConfirmed: raw.ageConfirmed }),
  };
}

function toState(row: ProfileRow | null): ProfileState {
  if (!row) return { state: 'none' };
  return {
    state: 'read',
    ageConfirmedAt: row.age_confirmed_at,
    consentSync: row.consent_sync === true,
    consentErrors: row.consent_errors === true,
    consentCoachHistory: row.consent_coach_history === true,
    consentVersion: row.consent_version,
    consentedAt: row.consented_at,
  };
}

export interface CloudAccountDeps {
  auth: { status(): AccountStatus; onChange(listener: (status: AccountStatus) => void): () => void; signOut(): Promise<void> };
  db: AccountDb;
  sync: Pick<CloudSync, 'run' | 'status' | 'clear' | 'idle'>;
  /** `ReportsLink.apply`: one restart of the server at most per call. */
  reports: { apply(change: { consent?: boolean; user?: string | null }): Promise<void> };
  /** Asks where to save `text` and writes it; `false` when the person cancelled. */
  saveJson(defaultName: string, text: string): Promise<boolean>;
  now(): Date;
  /** Called whenever `details()` may have changed. */
  changed(): void;
  /** Settles once the stored session was read (`CloudAuth.ready()`): a change
   *  of account before then is the restore, an app start. */
  restored?: Promise<unknown>;
  log?: Logger;
}

export class CloudAccount {
  private readonly log: Logger;
  private profile: ProfileState = { state: 'unknown' };
  /** The user the last sign-in or sign-out handled was for. */
  private handled: string | null = null;
  /** One per sign-in or sign-out: a profile read for an earlier one is dropped. */
  private generation = 0;
  private started = false;
  private unsubscribe: (() => void) | null = null;
  private restoring: boolean;
  /** Set while "Delete my cloud history" runs: the backup counts as off. */
  private deleting = false;

  constructor(private readonly deps: CloudAccountDeps) {
    this.log = deps.log ?? silent;
    this.restoring = deps.restored !== undefined;
    const settled = (): void => {
      this.restoring = false;
    };
    deps.restored?.then(settled, settled);
  }

  /** Once the stored session is read and the server is up: the restored
   *  account is handled as an app start, and every later change of account
   *  as a sign-in or a sign-out. */
  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    this.unsubscribe = this.deps.auth.onChange((status) => void this.follow(status, this.restoring ? 'always' : 'ifNever'));
    await this.follow(this.deps.auth.status(), 'always');
  }

  dispose(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  /** Whether the signed-in account's backup is on, as its profile was last read. */
  syncEnabled(): boolean {
    return !this.deleting && this.profile.state === 'read' && this.profile.consentSync && this.user() === this.handled;
  }

  details(): AccountDetails {
    return { profile: this.profile, sync: this.deps.sync.status() };
  }

  private user(): string | null {
    const status = this.deps.auth.status();
    return status.signedIn ? status.userId : null;
  }

  private async follow(status: AccountStatus, pull: PullWhen): Promise<void> {
    const user = status.signedIn ? status.userId : null;
    if (user === this.handled && pull !== 'always') return;
    this.handled = user;
    const generation = ++this.generation;
    this.profile = { state: 'unknown' };
    this.deps.changed();
    if (user === null) {
      await this.deps.reports.apply({ user: null });
      return;
    }
    const row = await this.readProfile(user);
    if (generation !== this.generation) return;
    if (row === undefined) {
      await this.deps.reports.apply({ user });
      return;
    }
    this.profile = toState(row);
    this.deps.changed();
    await this.deps.reports.apply({ user, consent: row?.consent_errors === true });
    if (generation !== this.generation) return;
    if (row?.consent_sync === true) await this.deps.sync.run({ userId: user, pull });
  }

  /** The row, `null` for none, `undefined` when it could not be read. */
  private async readProfile(user: string): Promise<ProfileRow | null | undefined> {
    try {
      return await this.deps.db.readProfile(user);
    } catch (error) {
      this.log.warn('account: the profile could not be read', { error: String(error) });
      return undefined;
    }
  }

  /** A push, for "a match ended". The profile is read again first, every
   *  time: another install may have turned the backup off. No push when it
   *  cannot be read. */
  async matchEnded(): Promise<void> {
    const user = this.user();
    if (user === null || user !== this.handled || this.deleting) return;
    const generation = this.generation;
    const row = await this.readProfile(user);
    if (row === undefined || generation !== this.generation || this.deleting) return;
    const before = this.profile;
    this.profile = toState(row);
    this.deps.changed();
    const consent = row?.consent_errors === true;
    if (before.state !== 'read' || before.consentErrors !== consent) await this.deps.reports.apply({ consent });
    if (this.profile.state !== 'read' || !this.profile.consentSync) return;
    // Turned on elsewhere: pull, in case the history was deleted meanwhile.
    const wasSyncing = before.state === 'read' && before.consentSync;
    await this.deps.sync.run({ userId: user, pull: wasSyncing ? 'never' : 'always' });
  }

  async setProfile(value: unknown): Promise<AccountReply> {
    const change = parseProfileChange(value);
    if (!change) return { ok: false, error: 'invalid' };
    // The delete writes the profile itself; a write in between would be lost.
    if (this.deleting) return { ok: false, error: 'failed' };
    const user = this.user();
    if (user === null) return { ok: false, error: 'signedOut' };
    const generation = this.generation;
    let current = this.profile;
    if (current.state === 'unknown') {
      const row = await this.readProfile(user);
      if (row === undefined) return { ok: false, error: 'failed' };
      current = toState(row);
    }
    return this.writeProfile(user, change, current, generation);
  }

  /** Writes `change` over `current` (read, or `none`) and follows it: the
   *  error reports get its consent, and a backup turned on runs. */
  private async writeProfile(user: string, change: ProfileChange, current: ProfileState, generation: number): Promise<AccountReply> {
    const at = this.deps.now().toISOString();
    const patch: ConsentPatch = {
      consent_sync: change.consentSync,
      consent_errors: change.consentErrors,
      consent_coach_history: change.consentCoachHistory,
      consent_version: change.policyVersion,
      consented_at: at,
    };
    let row: ProfileRow;
    try {
      if (current.state === 'none') {
        if (change.ageConfirmed !== true) return { ok: false, error: 'ageNotConfirmed' };
        row = { user_id: user, age_confirmed_at: at, ...patch };
        await this.deps.db.insertProfile(row);
      } else {
        await this.deps.db.updateProfile(user, patch);
        row = { user_id: user, age_confirmed_at: current.state === 'read' ? current.ageConfirmedAt : at, ...patch };
      }
    } catch (error) {
      this.log.warn('account: the profile could not be written', { error: String(error) });
      return { ok: false, error: 'failed' };
    }
    if (generation !== this.generation) return { ok: false, error: 'signedOut' };
    const wasSyncing = current.state === 'read' && current.consentSync;
    this.profile = toState(row);
    this.deps.changed();
    await this.deps.reports.apply({ consent: change.consentErrors });
    // A pull: the history may have been deleted from another install.
    if (change.consentSync && !wasSyncing) void this.deps.sync.run({ userId: user, pull: 'always' });
    return { ok: true };
  }

  /** `export_my_data`, saved where the person picks. */
  async exportData(): Promise<AccountReply> {
    if (this.user() === null) return { ok: false, error: 'signedOut' };
    let text: string;
    try {
      text = `${JSON.stringify(await this.deps.db.exportData(), null, 2)}\n`;
    } catch (error) {
      this.log.warn('account: the export could not be read', { error: String(error) });
      return { ok: false, error: 'failed' };
    }
    try {
      const saved = await this.deps.saveJson(EXPORT_FILE_NAME, text);
      return saved ? { ok: true } : { ok: true, cancelled: true };
    } catch (error) {
      this.log.warn('account: the export could not be saved', { error: String(error) });
      return { ok: false, error: 'failed' };
    }
  }

  /** Trap: the backup is held off and any run let finish before the
   *  delete, or a batch uploaded after it stays in the cloud. Trap: the
   *  backup is turned off before the sync state is cleared; the
   *  other way round, a run in between would upload every match again. When
   *  the profile write fails the state is kept, so nothing goes up at once;
   *  but the backup is still on, so the next app start's pull finds the
   *  deleted rows and uploads every match again. The reply is still `ok`
   *  (the history is gone), and the page shows the backup still on. */
  async deleteCloudHistory(): Promise<AccountReply> {
    const user = this.user();
    if (user === null) return { ok: false, error: 'signedOut' };
    if (this.deleting) return { ok: false, error: 'failed' };
    this.deleting = true;
    try {
      return await this.deleteHeldOff(user);
    } finally {
      this.deleting = false;
    }
  }

  private async deleteHeldOff(user: string): Promise<AccountReply> {
    const generation = this.generation;
    await this.deps.sync.idle();
    let deleted: number;
    try {
      deleted = await this.deps.db.deleteCloudHistory();
    } catch (error) {
      this.log.warn('account: the cloud history could not be deleted', { error: String(error) });
      return { ok: false, error: 'failed' };
    }
    this.log.info('account: cloud history deleted', { matches: deleted });
    let current = this.profile;
    if (current.state === 'unknown') {
      const row = await this.readProfile(user);
      current = row === undefined ? current : toState(row);
    }
    if (current.state === 'read' && current.consentSync) {
      const off = await this.writeProfile(
        user,
        {
          consentSync: false,
          consentErrors: current.consentErrors,
          consentCoachHistory: current.consentCoachHistory,
          policyVersion: current.consentVersion,
        },
        current,
        generation,
      );
      if (!off.ok) {
        this.log.warn('account: the backup could not be turned off after the delete');
        this.deps.changed();
        return { ok: true, deleted };
      }
    } else if (current.state === 'unknown') {
      this.log.warn('account: the profile could not be read after the delete; the backup is left as it was');
      return { ok: true, deleted };
    }
    await this.deps.sync.clear();
    this.deps.changed();
    return { ok: true, deleted };
  }

  async deleteAccount(): Promise<AccountReply> {
    if (this.user() === null) return { ok: false, error: 'signedOut' };
    try {
      await this.deps.db.deleteAccount();
    } catch (error) {
      this.log.warn('account: the account could not be deleted', { error: String(error) });
      return { ok: false, error: 'failed' };
    }
    this.log.info('account: deleted');
    await this.deps.sync.clear();
    await this.deps.reports.apply({ consent: false, user: null });
    try {
      await this.deps.auth.signOut();
    } catch (error) {
      this.log.warn('account: signing out after the delete failed', { error: String(error) });
    }
    return { ok: true };
  }
}
