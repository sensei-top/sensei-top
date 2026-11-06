import { createClient } from '@supabase/supabase-js';
import { describe, expect, it } from 'vitest';
import { AccountApi, ReportsLink } from '../settings';
import type { ShellJson } from '../store';
import {
  CloudAccount,
  EXPORT_FILE_NAME,
  parseProfileChange,
  restoredUser,
  supabaseAccountDb,
  type AccountDb,
  type ConsentPatch,
  type ProfileRow,
} from './account';
import type { AccountStatus } from './auth';
import { BATCH_SIZE, CloudSync, type LocalPayload, type PulledRow, type SyncDb, type SyncRunOptions, type SyncStatus } from './sync';

// Made-up identifiers only: no real account, project or address.
const USER = '00000000-0000-4000-8000-0000000000a1';
const OTHER = '00000000-0000-4000-8000-0000000000b2';
const SUPABASE_URL = 'https://project.example.invalid';
const NOW = '2026-03-04T05:06:07.000Z';
const persistence = { kept: true } as const;

function signedIn(userId: string): AccountStatus {
  return { signedIn: true, userId, email: 'player@example.invalid', provider: 'google', persistence } as AccountStatus;
}
const signedOut = { signedIn: false, userId: null, email: null, provider: null, persistence } as AccountStatus;

function profile(userId: string, over: Partial<ProfileRow> = {}): ProfileRow {
  return {
    user_id: userId,
    age_confirmed_at: '2026-01-01T00:00:00.000Z',
    consent_sync: true,
    consent_errors: true,
    consent_coach_history: false,
    consent_version: '2026-11-01',
    consented_at: '2026-01-01T00:00:00.000Z',
    ...over,
  };
}

const SYNC_STATUS: SyncStatus = { running: false, lastSyncAt: null, backedUp: 7, lastError: null };

/** `public.matches` for one user, shared by every install that uses it:
 *  a write takes the next tick of its clock, as `updated_at` takes `now()`. */
function fakeCloud() {
  let clock = Date.parse('2026-03-04T00:00:00Z');
  const tick = () => new Date((clock += 1000)).toISOString();
  const rows: PulledRow[] = [];
  /** Each upsert as it is sent, and each delete. */
  const log: string[] = [];
  let hold: Promise<void> | null = null;
  const db: SyncDb = {
    async upsertMatches(batch) {
      log.push(`upsert ${batch.map((r) => r.match_id).join(',')}`);
      if (hold) await hold;
      for (const r of batch) {
        const row: PulledRow = { ...r, updated_at: tick(), deleted_at: null };
        const at = rows.findIndex((x) => x.match_id === r.match_id);
        if (at === -1) rows.push(row);
        else rows[at] = row;
      }
    },
    upsertDevice: async () => undefined,
    async pullMatches(_userId, after, limit) {
      const key = (row: { updatedAt: string; matchId: string }) => [Date.parse(row.updatedAt), row.matchId] as const;
      const later = (a: readonly [number, string], b: readonly [number, string]) => a[0] > b[0] || (a[0] === b[0] && a[1] > b[1]);
      return rows
        .filter((row) => !after || later(key({ updatedAt: row.updated_at, matchId: row.match_id }), key(after)))
        .sort((a, b) => Date.parse(a.updated_at) - Date.parse(b.updated_at) || (a.match_id < b.match_id ? -1 : 1))
        .slice(0, limit);
    },
  };
  return {
    rows,
    log,
    db,
    /** Holds every upsert until the returned release is called. */
    holdUpserts: () => {
      let release!: () => void;
      hold = new Promise<void>((resolve) => (release = resolve));
      return () => {
        hold = null;
        release();
      };
    },
    async deleteHistory() {
      log.push('delete');
      let n = 0;
      for (const row of rows) {
        if (row.deleted_at !== null) continue;
        row.deleted_at = row.updated_at = tick();
        n++;
      }
      return n;
    },
    live: () => rows.filter((row) => row.deleted_at === null).map((row) => row.match_id).sort(),
  };
}
type FakeCloud = ReturnType<typeof fakeCloud>;

function matches(...ids: string[]): LocalPayload[] {
  return ids.map((id) => ({ match_id: id, source: 'arena', played_at: null, digest: `d-${id}`, payload: { schema_version: 1 } }));
}

/** A real `CloudSync` for one install, on `cloud`, with `payloads` as its local matches. */
function installSync(cloud: FakeCloud, payloads: LocalPayload[]) {
  let text: string | null = null;
  const box: { sync?: CloudSync } = {};
  const make = (account: () => CloudAccount, status: () => AccountStatus) =>
    (box.sync = new CloudSync({
      db: cloud.db,
      local: { payloads: async () => payloads, putPulled: async () => undefined },
      file: { read: () => text, write: (next) => void (text = next), remove: () => void (text = null) },
      currentUser: () => (status().signedIn ? status().userId : null),
      enabled: () => account().syncEnabled(),
      installId: () => 'install-for-tests',
      appVersion: '9.9.9',
      os: 'Linux 6.0',
      now: () => new Date(NOW),
      onStatus: () => undefined,
    }));
  return { make, idle: () => box.sync!.idle() };
}

async function until(done: () => boolean): Promise<void> {
  for (let i = 0; i < 100 && !done(); i++) await new Promise((resolve) => setTimeout(resolve, 0));
}

interface Extra {
  /** A real `CloudSync` in place of the recording fake. */
  sync?: (account: () => CloudAccount, status: () => AccountStatus) => CloudSync;
  /** Where "Delete my cloud history" deletes; otherwise it answers 3. */
  cloud?: FakeCloud;
  restored?: Promise<unknown>;
}

function harness(start: AccountStatus = signedIn(USER), rows: Record<string, ProfileRow> = { [USER]: profile(USER) }, extra: Extra = {}) {
  const calls: string[] = [];
  let status = start;
  const listeners: Array<(status: AccountStatus) => void> = [];
  const applies: Array<{ consent?: boolean; user?: string | null }> = [];
  const runs: SyncRunOptions[] = [];
  const inserts: ProfileRow[] = [];
  const updates: Array<{ userId: string; patch: ConsentPatch }> = [];
  const saved: Array<{ name: string; text: string }> = [];
  const fail = { read: false, write: false, export: false, deleteHistory: false, deleteAccount: false };
  let save = true;
  let pendingRead: Promise<void> | null = null;

  const db: AccountDb = {
    async readProfile(userId) {
      calls.push(`readProfile ${userId}`);
      if (pendingRead) await pendingRead;
      if (fail.read) throw new Error('timeout');
      return rows[userId] ?? null;
    },
    async insertProfile(row) {
      if (fail.write) throw new Error('403');
      inserts.push(row);
      rows[row.user_id] = row;
    },
    async updateProfile(userId, patch) {
      if (fail.write) throw new Error('403');
      calls.push('updateProfile');
      updates.push({ userId, patch });
      rows[userId] = { ...rows[userId]!, ...patch };
    },
    async exportData() {
      if (fail.export) throw new Error('500');
      return { profile: rows[USER] ?? null, matches: [] };
    },
    async deleteCloudHistory() {
      calls.push('deleteHistory');
      if (fail.deleteHistory) throw new Error('500');
      return extra.cloud ? extra.cloud.deleteHistory() : 3;
    },
    async deleteAccount() {
      calls.push('deleteAccount');
      if (fail.deleteAccount) throw new Error('500');
    },
  };

  const account: CloudAccount = new CloudAccount({
    auth: {
      status: () => status,
      onChange: (listener) => {
        listeners.push(listener);
        return () => void listeners.splice(listeners.indexOf(listener), 1);
      },
      signOut: async () => {
        calls.push('signOut');
        status = signedOut;
      },
    },
    db,
    sync: extra.sync?.((): CloudAccount => account, () => status) ?? {
      run: async (options) => void runs.push(options),
      status: () => SYNC_STATUS,
      clear: async () => void calls.push('clear'),
      idle: async () => undefined,
    },
    reports: {
      apply: async (change) => {
        calls.push('apply');
        applies.push(change);
      },
    },
    saveJson: async (name, text) => {
      if (!save) return false;
      saved.push({ name, text });
      return true;
    },
    now: () => new Date(NOW),
    changed: () => void calls.push('changed'),
    restored: extra.restored,
  });

  return {
    account,
    calls,
    applies,
    runs,
    inserts,
    updates,
    saved,
    fail,
    rows,
    cancelSave: () => (save = false),
    holdReads: () => {
      let release!: () => void;
      pendingRead = new Promise<void>((resolve) => (release = resolve));
      return () => {
        pendingRead = null;
        release();
      };
    },
    /** What `CloudAuth` does on a sign-in or a sign-out. */
    emit: async (next: AccountStatus) => {
      status = next;
      for (const listener of [...listeners]) listener(next);
      await new Promise((resolve) => setTimeout(resolve, 0));
    },
    listeners: () => listeners.length,
  };
}

const CHANGE = { consentSync: true, consentErrors: false, consentCoachHistory: true, policyVersion: '2026-11-01' };

describe('following the account', () => {
  it('handles the restored account at start: user and consent in one step, a backup with a pull', async () => {
    const h = harness();
    await h.account.start();
    expect(h.applies).toEqual([{ user: USER, consent: true }]);
    expect(h.runs).toEqual([{ userId: USER, pull: 'always' }]);
    expect(h.account.syncEnabled()).toBe(true);
    expect(h.account.details()).toEqual({
      profile: {
        state: 'read',
        ageConfirmedAt: '2026-01-01T00:00:00.000Z',
        consentSync: true,
        consentErrors: true,
        consentCoachHistory: false,
        consentVersion: '2026-11-01',
        consentedAt: '2026-01-01T00:00:00.000Z',
      },
      sync: SYNC_STATUS,
    });
  });

  it('treats a later sign-in as one, and a refreshed session as nothing', async () => {
    const h = harness(signedOut);
    await h.account.start();
    expect(h.applies).toEqual([{ user: null }]);
    expect(h.runs).toEqual([]);

    await h.emit(signedIn(USER));
    expect(h.applies.at(-1)).toEqual({ user: USER, consent: true });
    expect(h.runs).toEqual([{ userId: USER, pull: 'ifNever' }]);

    await h.emit(signedIn(USER));
    expect(h.applies).toHaveLength(2);
    expect(h.runs).toHaveLength(1);

    await h.emit(signedOut);
    expect(h.applies.at(-1)).toEqual({ user: null });
    expect(h.account.syncEnabled()).toBe(false);
    expect(h.account.details().profile).toEqual({ state: 'unknown' });

    h.account.dispose();
    expect(h.listeners()).toBe(0);
  });

  it('keeps error reports off and backs nothing up for an account with no answers yet', async () => {
    const h = harness(signedIn(OTHER));
    await h.account.start();
    expect(h.applies).toEqual([{ user: OTHER, consent: false }]);
    expect(h.runs).toEqual([]);
    expect(h.account.details().profile).toEqual({ state: 'none' });
  });

  it('runs no backup when the profile says no', async () => {
    const h = harness(signedIn(USER), { [USER]: profile(USER, { consent_sync: false, consent_errors: false }) });
    await h.account.start();
    expect(h.applies).toEqual([{ user: USER, consent: false }]);
    expect(h.runs).toEqual([]);
    await h.account.matchEnded();
    expect(h.runs).toEqual([]);
  });

  it('leaves a profile it could not read unknown, and reads it again when a match ends', async () => {
    const h = harness();
    h.fail.read = true;
    await h.account.start();
    expect(h.applies).toEqual([{ user: USER }]);
    expect(h.account.details().profile).toEqual({ state: 'unknown' });
    expect(h.runs).toEqual([]);

    h.fail.read = false;
    await h.account.matchEnded();
    expect(h.applies.at(-1)).toEqual({ consent: true });
    // The start's pull never ran, so this run pulls.
    expect(h.runs).toEqual([{ userId: USER, pull: 'always' }]);
    await h.account.matchEnded();
    expect(h.runs.at(-1)).toEqual({ userId: USER, pull: 'never' });
    expect(h.applies).toHaveLength(2);
    expect(h.calls.filter((c) => c.startsWith('readProfile'))).toHaveLength(3);
  });

  it("reads a profile it could not read again on the page's Try again, and says whether it could", async () => {
    const h = harness();
    h.fail.read = true;
    await h.account.start();
    expect(await h.account.readProfileAgain()).toEqual({ ok: false, error: 'failed' });
    expect(h.account.details().profile).toEqual({ state: 'unknown' });
    expect(h.runs).toEqual([]);

    h.fail.read = false;
    expect(await h.account.readProfileAgain()).toEqual({ ok: true });
    expect(h.account.details().profile.state).toBe('read');
    expect(h.applies.at(-1)).toEqual({ consent: true });
    expect(h.runs).toEqual([{ userId: USER, pull: 'always' }]);
  });

  it('answers signedOut to a Try again with no one signed in', async () => {
    const h = harness(signedOut);
    await h.account.start();
    expect(await h.account.readProfileAgain()).toEqual({ ok: false, error: 'signedOut' });
    expect(h.calls.filter((c) => c.startsWith('readProfile'))).toHaveLength(0);
  });

  it('reads the profile at every match end, and pushes nothing once it says no', async () => {
    const h = harness();
    await h.account.start();
    h.rows[USER] = profile(USER, { consent_sync: false });
    await h.account.matchEnded();
    expect(h.runs).toEqual([{ userId: USER, pull: 'always' }]);
    expect(h.account.syncEnabled()).toBe(false);

    h.rows[USER] = profile(USER);
    h.fail.read = true;
    await h.account.matchEnded();
    expect(h.runs).toHaveLength(1);
  });

  it('treats the restored session as the app start, whether it is read before or after start()', async () => {
    let settle!: () => void;
    const restored = new Promise<void>((resolve) => (settle = resolve));
    const late = harness(signedOut, undefined, { restored });
    await late.account.start();
    await late.emit(signedIn(USER));
    settle();
    await restored;
    expect(late.runs).toEqual([{ userId: USER, pull: 'always' }]);
    // After the restore, a change of account is a sign-in.
    await late.emit(signedOut);
    await late.emit(signedIn(OTHER));
    await late.emit(signedIn(USER));
    expect(late.runs.at(-1)).toEqual({ userId: USER, pull: 'ifNever' });

    const early = harness(signedIn(USER), undefined, { restored: Promise.resolve() });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await early.account.start();
    expect(early.runs).toEqual([{ userId: USER, pull: 'always' }]);

    const failed = harness(signedOut, undefined, { restored: Promise.reject(new Error('unreadable')) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await failed.account.start();
    await failed.emit(signedIn(USER));
    expect(failed.runs).toEqual([{ userId: USER, pull: 'ifNever' }]);
  });

  it('drops a profile read for an account already signed out of', async () => {
    const h = harness(signedOut);
    await h.account.start();
    const release = h.holdReads();
    void h.emit(signedIn(USER));
    await h.emit(signedOut);
    release();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(h.applies).toEqual([{ user: null }, { user: null }]);
    expect(h.runs).toEqual([]);
    expect(h.account.details().profile).toEqual({ state: 'unknown' });
  });
});

describe('the profile write', () => {
  it('refuses a malformed change', async () => {
    const h = harness();
    await h.account.start();
    expect(await h.account.setProfile({ ...CHANGE, policyVersion: '../x' })).toEqual({ ok: false, error: 'invalid' });
    expect(await h.account.setProfile({ ...CHANGE, consentSync: 'yes' })).toEqual({ ok: false, error: 'invalid' });
    expect(await h.account.setProfile({ ...CHANGE, ageConfirmed: 1 })).toEqual({ ok: false, error: 'invalid' });
    expect(await h.account.setProfile(null)).toEqual({ ok: false, error: 'invalid' });
    expect(parseProfileChange({ ...CHANGE, extra: 1 })).toEqual(CHANGE);
  });

  it('needs a sign-in', async () => {
    const h = harness(signedOut);
    await h.account.start();
    expect(await h.account.setProfile(CHANGE)).toEqual({ ok: false, error: 'signedOut' });
  });

  it('writes the first profile only with the age confirmed, both dates this machine\'s now', async () => {
    const h = harness(signedIn(OTHER));
    await h.account.start();
    expect(await h.account.setProfile(CHANGE)).toEqual({ ok: false, error: 'ageNotConfirmed' });
    expect(await h.account.setProfile({ ...CHANGE, ageConfirmed: false })).toEqual({ ok: false, error: 'ageNotConfirmed' });
    expect(h.inserts).toEqual([]);

    expect(await h.account.setProfile({ ...CHANGE, ageConfirmed: true })).toEqual({ ok: true });
    expect(h.inserts).toEqual([
      {
        user_id: OTHER,
        age_confirmed_at: NOW,
        consent_sync: true,
        consent_errors: false,
        consent_coach_history: true,
        consent_version: '2026-11-01',
        consented_at: NOW,
      },
    ]);
    expect(h.applies.at(-1)).toEqual({ consent: false });
    expect(h.runs).toEqual([{ userId: OTHER, pull: 'always' }]);
    expect(h.account.syncEnabled()).toBe(true);
  });

  it('updates a later change, keeping the age confirmation it was first given', async () => {
    const h = harness();
    await h.account.start();
    expect(await h.account.setProfile({ ...CHANGE, consentErrors: true, ageConfirmed: true })).toEqual({ ok: true });
    expect(h.inserts).toEqual([]);
    expect(h.updates).toEqual([
      {
        userId: USER,
        patch: { consent_sync: true, consent_errors: true, consent_coach_history: true, consent_version: '2026-11-01', consented_at: NOW },
      },
    ]);
    expect(h.account.details().profile).toMatchObject({ state: 'read', ageConfirmedAt: '2026-01-01T00:00:00.000Z', consentedAt: NOW });
    // The backup was already on: the start's run is the only one.
    expect(h.runs).toEqual([{ userId: USER, pull: 'always' }]);

    expect(await h.account.setProfile({ ...CHANGE, consentSync: false })).toEqual({ ok: true });
    expect(h.account.syncEnabled()).toBe(false);
  });

  it('changes nothing when the cloud refuses the write', async () => {
    const h = harness();
    await h.account.start();
    const before = h.account.details().profile;
    h.fail.write = true;
    expect(await h.account.setProfile({ ...CHANGE, consentSync: false })).toEqual({ ok: false, error: 'failed' });
    expect(h.account.details().profile).toEqual(before);
    expect(h.applies).toHaveLength(1);
  });

  it('will not write over a profile it could not read', async () => {
    const h = harness();
    h.fail.read = true;
    await h.account.start();
    expect(await h.account.setProfile({ ...CHANGE, ageConfirmed: true })).toEqual({ ok: false, error: 'failed' });
    expect(h.inserts).toEqual([]);
    expect(h.updates).toEqual([]);
  });
});

describe('the rights actions', () => {
  it('saves the export as indented JSON under its file name, or reports a cancel', async () => {
    const h = harness();
    await h.account.start();
    expect(await h.account.exportData()).toEqual({ ok: true });
    expect(h.saved).toHaveLength(1);
    expect(h.saved[0]!.name).toBe(EXPORT_FILE_NAME);
    expect(JSON.parse(h.saved[0]!.text)).toEqual({ profile: h.rows[USER], matches: [] });
    expect(h.saved[0]!.text).toContain('\n  "profile"');

    h.cancelSave();
    expect(await h.account.exportData()).toEqual({ ok: true, cancelled: true });
    h.fail.export = true;
    expect(await h.account.exportData()).toEqual({ ok: false, error: 'failed' });
  });


  it('turns the backup off before it deletes the history', async () => {
    const h = harness();
    await h.account.start();
    h.calls.length = 0;
    expect(await h.account.deleteCloudHistory()).toEqual({ ok: true, deleted: 3 });
    expect(h.calls.indexOf('updateProfile')).toBeGreaterThanOrEqual(0);
    expect(h.calls.indexOf('updateProfile')).toBeLessThan(h.calls.indexOf('deleteHistory'));
    expect(h.calls.indexOf('deleteHistory')).toBeLessThan(h.calls.indexOf('clear'));
    expect(h.updates).toEqual([
      {
        userId: USER,
        patch: { consent_sync: false, consent_errors: true, consent_coach_history: false, consent_version: '2026-11-01', consented_at: NOW },
      },
    ]);
    // The same error-reports answer: `ReportsLink` restarts nothing for it.
    expect(h.applies.at(-1)).toEqual({ consent: true });
    expect(h.account.syncEnabled()).toBe(false);
    expect(h.calls.at(-1)).toBe('changed');
  });

  it('deletes nothing and answers failed when the backup cannot be turned off', async () => {
    const h = harness();
    await h.account.start();
    h.calls.length = 0;
    h.fail.write = true;
    expect(await h.account.deleteCloudHistory()).toEqual({ ok: false, error: 'failed' });
    expect(h.calls).not.toContain('deleteHistory');
    expect(h.calls).not.toContain('clear');
    expect(h.account.syncEnabled()).toBe(true);
  });

  it('deletes nothing and answers failed when the profile cannot be read', async () => {
    const h = harness();
    h.fail.read = true;
    await h.account.start();
    h.calls.length = 0;
    expect(await h.account.deleteCloudHistory()).toEqual({ ok: false, error: 'failed' });
    expect(h.calls).not.toContain('deleteHistory');
    expect(h.updates).toEqual([]);
  });

  it('leaves the backup off, and tells the page, when the delete fails after it', async () => {
    const h = harness();
    await h.account.start();
    h.calls.length = 0;
    h.fail.deleteHistory = true;
    expect(await h.account.deleteCloudHistory()).toEqual({ ok: false, error: 'failed' });
    expect(h.updates.map((u) => u.patch.consent_sync)).toEqual([false]);
    expect(h.rows[USER]!.consent_sync).toBe(false);
    expect(h.account.syncEnabled()).toBe(false);
    expect(h.calls).not.toContain('clear');
    expect(h.calls.at(-1)).toBe('changed');
  });

  it('clears the sync state for an account whose backup was already off', async () => {
    const h = harness(signedIn(USER), { [USER]: profile(USER, { consent_sync: false }) });
    await h.account.start();
    expect(await h.account.deleteCloudHistory()).toEqual({ ok: true, deleted: 3 });
    expect(h.updates).toEqual([]);
    expect(h.calls).toContain('clear');
  });

  it('after the delete, backs nothing up until it is turned on again, then every match', async () => {
    const cloud = fakeCloud();
    const pc = installSync(cloud, matches('m1', 'm2', 'm3'));
    const h = harness(signedIn(USER), undefined, { cloud, sync: pc.make });
    await h.account.start();
    expect(cloud.live()).toEqual(['m1', 'm2', 'm3']);
    expect(h.account.details().sync.backedUp).toBe(3);

    expect(await h.account.deleteCloudHistory()).toEqual({ ok: true, deleted: 3 });
    expect(h.account.details().sync.backedUp).toBe(0);
    expect(cloud.live()).toEqual([]);
    await h.account.matchEnded();
    expect(cloud.log).toEqual(['upsert m1,m2,m3', 'delete']);

    expect(await h.account.setProfile({ ...CHANGE, consentSync: true })).toEqual({ ok: true });
    await pc.idle();
    expect(cloud.log.at(-1)).toBe('upsert m1,m2,m3');
    expect(cloud.live()).toEqual(['m1', 'm2', 'm3']);
    expect(h.account.details().sync.backedUp).toBe(3);
  });

  it('lets a running backup finish before the delete, and uploads no batch after it', async () => {
    const cloud = fakeCloud();
    const ids = Array.from({ length: BATCH_SIZE + 5 }, (_, n) => `m${String(n).padStart(4, '0')}`);
    const pc = installSync(cloud, matches(...ids));
    const h = harness(signedIn(USER), undefined, { cloud, sync: pc.make });
    const release = cloud.holdUpserts();
    const started = h.account.start();
    await until(() => cloud.log.length > 0);
    expect(cloud.log).toEqual([`upsert ${ids.slice(0, BATCH_SIZE).join(',')}`]);

    const deleting = h.account.deleteCloudHistory();
    expect(h.account.syncEnabled()).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(cloud.log).toHaveLength(1);
    release();
    expect(await deleting).toEqual({ ok: true, deleted: BATCH_SIZE });
    await started;
    expect(cloud.log).toEqual([`upsert ${ids.slice(0, BATCH_SIZE).join(',')}`, 'delete']);
    expect(cloud.live()).toEqual([]);
  });

  it('refuses a profile write sent while the delete runs, and still ends with the backup off', async () => {
    const cloud = fakeCloud();
    const pc = installSync(cloud, matches('m1'));
    const h = harness(signedIn(USER), undefined, { cloud, sync: pc.make });
    const release = cloud.holdUpserts();
    const started = h.account.start();
    await until(() => cloud.log.length > 0);
    const deleting = h.account.deleteCloudHistory();
    expect(await h.account.setProfile({ ...CHANGE, consentSync: true })).toEqual({ ok: false, error: 'failed' });
    release();
    expect(await deleting).toEqual({ ok: true, deleted: 1 });
    await started;
    expect(h.updates.map((u) => u.patch.consent_sync)).toEqual([false]);
    expect(h.rows[USER]!.consent_sync).toBe(false);
    expect(h.account.syncEnabled()).toBe(false);
  });

  it('lifts the hold when the backup cannot be turned off', async () => {
    const h = harness();
    await h.account.start();
    h.fail.write = true;
    const deleting = h.account.deleteCloudHistory();
    expect(h.account.syncEnabled()).toBe(false);
    expect(await deleting).toEqual({ ok: false, error: 'failed' });
    expect(h.account.syncEnabled()).toBe(true);
  });

  it('on another install, stops at the next match end and uploads every match once turned on again', async () => {
    const cloud = fakeCloud();
    const rows = { [USER]: profile(USER) };
    const local = matches('b1', 'b2');
    const pcA = installSync(cloud, matches('a1', 'a2'));
    const pcB = installSync(cloud, local);
    const a = harness(signedIn(USER), rows, { cloud, sync: pcA.make });
    const b = harness(signedIn(USER), rows, { cloud, sync: pcB.make });
    await a.account.start();
    await b.account.start();
    expect(cloud.live()).toEqual(['a1', 'a2', 'b1', 'b2']);

    expect(await a.account.deleteCloudHistory()).toEqual({ ok: true, deleted: 4 });
    expect(rows[USER]!.consent_sync).toBe(false);
    const sent = cloud.log.length;

    local.push(...matches('b3'));
    await b.account.matchEnded();
    await pcB.idle();
    expect(cloud.log).toHaveLength(sent);
    expect(b.account.syncEnabled()).toBe(false);

    expect(await b.account.setProfile({ ...CHANGE, consentSync: true })).toEqual({ ok: true });
    await pcB.idle();
    expect(cloud.log.slice(sent)).toEqual(['upsert b1,b2,b3']);
    expect(cloud.live()).toEqual(['b1', 'b2', 'b3']);
    expect(b.account.details().sync.backedUp).toBe(3);
  });

  it('deletes the account first, then forgets the sync state, the reports user and the session', async () => {
    const h = harness();
    await h.account.start();
    h.calls.length = 0;
    expect(await h.account.deleteAccount()).toEqual({ ok: true });
    expect(h.calls).toEqual(['deleteAccount', 'clear', 'apply', 'signOut']);
    expect(h.applies.at(-1)).toEqual({ consent: false, user: null });
  });

  it('changes nothing when the cloud refuses the delete', async () => {
    const h = harness();
    await h.account.start();
    h.calls.length = 0;
    h.fail.deleteAccount = true;
    expect(await h.account.deleteAccount()).toEqual({ ok: false, error: 'failed' });
    expect(h.calls).toEqual(['deleteAccount']);
  });

  it('needs a sign-in for each', async () => {
    const h = harness(signedOut);
    await h.account.start();
    for (const reply of [await h.account.exportData(), await h.account.deleteCloudHistory(), await h.account.deleteAccount()]) {
      expect(reply).toEqual({ ok: false, error: 'signedOut' });
    }
  });
});

describe('the session restored at launch', () => {
  it('gives its user, or null when it is slower than the wait or unreadable', async () => {
    expect(await restoredUser(Promise.resolve(signedIn(USER)), 1000)).toBe(USER);
    expect(await restoredUser(Promise.resolve(signedOut), 1000)).toBeNull();
    expect(await restoredUser(new Promise<AccountStatus>(() => undefined), 5)).toBeNull();
    expect(await restoredUser(Promise.reject(new Error('unreadable')), 1000)).toBeNull();
  });
});

describe('the cloud adapter', () => {
  function client(answer: (url: URL) => Response) {
    const requests: Array<{ url: URL; method: string; body: string | null }> = [];
    const supabase = createClient(SUPABASE_URL, 'anon-key-for-tests', {
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
      global: {
        fetch: async (input: string | URL | Request, init?: RequestInit) => {
          const url = new URL(input instanceof Request ? input.url : String(input));
          requests.push({ url, method: init?.method ?? 'GET', body: (init?.body as string | undefined) ?? null });
          return answer(url);
        },
      },
    });
    return { db: supabaseAccountDb(supabase), requests };
  }
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

  it('reads the signed-in user\'s profile, none as null', async () => {
    let rows: ProfileRow[] = [profile(USER)];
    const { db, requests } = client(() => json(rows));
    expect(await db.readProfile(USER)).toEqual(profile(USER));
    rows = [];
    expect(await db.readProfile(USER)).toBeNull();
    expect(requests[0]!.url.pathname).toBe('/rest/v1/profiles');
    expect(requests[0]!.url.searchParams.get('user_id')).toBe(`eq.${USER}`);
    expect(requests[0]!.url.searchParams.get('select')).toBe(
      'user_id,age_confirmed_at,consent_sync,consent_errors,consent_coach_history,consent_version,consented_at',
    );
  });

  it('inserts and updates the profile row', async () => {
    const { db, requests } = client(() => new Response(null, { status: 201 }));
    await db.insertProfile(profile(USER));
    const patch: ConsentPatch = { consent_sync: false, consent_errors: false, consent_coach_history: false, consent_version: '1', consented_at: NOW };
    await db.updateProfile(USER, patch);
    expect(requests.map((r) => [r.method, r.url.pathname])).toEqual([
      ['POST', '/rest/v1/profiles'],
      ['PATCH', '/rest/v1/profiles'],
    ]);
    expect(requests[1]!.url.searchParams.get('user_id')).toBe(`eq.${USER}`);
    expect(JSON.parse(requests[1]!.body ?? '')).toEqual(patch);
  });

  it('calls the three rights functions', async () => {
    const { db, requests } = client((url) => (url.pathname.endsWith('delete_my_cloud_history') ? json(3) : json({ profile: null })));
    expect(await db.exportData()).toEqual({ profile: null });
    expect(await db.deleteCloudHistory()).toBe(3);
    await db.deleteAccount();
    expect(requests.map((r) => [r.method, r.url.pathname])).toEqual([
      ['POST', '/rest/v1/rpc/export_my_data'],
      ['POST', '/rest/v1/rpc/delete_my_cloud_history'],
      ['POST', '/rest/v1/rpc/delete_my_account'],
    ]);
  });

  it('throws on an error answer', async () => {
    const { db } = client(() => json({ message: 'denied', code: '42501' }, 403));
    await expect(db.deleteAccount()).rejects.toThrow(/42501/);
  });
});

describe('the page bridge', () => {
  const store = () => {
    let prefs: ShellJson = {};
    return {
      get: () => prefs,
      update: (patch: Partial<ShellJson>) => {
        prefs = { ...prefs, ...patch };
        return true;
      },
    };
  };
  const details = { profile: { state: 'none' as const }, sync: SYNC_STATUS };

  it('adds the profile and the backup status for a signed-in account only', () => {
    let status = signedIn(USER);
    const auth = { status: () => status };
    const api = new AccountApi(() => auth as never, store(), () => 'id', () => 'unavailable', () => 'failed', undefined, () => details);
    expect(api.state()).toEqual({ available: true, ...signedIn(USER), ...details });
    status = signedOut;
    expect(api.state()).toEqual({ available: true, ...signedOut });
  });

  it('restarts the server once for a new user and consent together', async () => {
    let restarts = 0;
    const reporter = { setUser: () => undefined, setConsent: async () => undefined };
    const link = new ReportsLink(store(), reporter, 'https://public@sentry.example.invalid/1', async () => void restarts++);
    await link.apply({ user: USER, consent: true });
    expect(restarts).toBe(1);
    expect(link.env().SENSEI_TOP_SENTRY_USER).toBe(USER);
    await link.apply({ user: OTHER, consent: true });
    expect(restarts).toBe(2);
    await link.apply({ consent: false, user: null });
    expect(restarts).toBe(3);
    expect(link.consent).toBe(false);
    await link.apply({ user: null });
    expect(restarts).toBe(3);
  });
});
