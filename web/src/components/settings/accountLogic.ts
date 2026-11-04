import type { AccountReply, ProfileChange, ProfileState, Saved, SyncStatus } from '../../bridge'
import { POLICY_VERSION } from '../../lib/policy'

type Read = Extract<ProfileState, { state: 'read' }>

/** Why a delete did not happen, as the line the dialog shows. Cloud history
 *  has two: `historyOn`, backup still on and nothing changed, and
 *  `historyOff`, backup now off because the shell turns it off first. */
export type DeleteFailure = 'historyOn' | 'historyOff' | 'account'

export type DeleteOutcome = { ok: true; deleted?: number } | { ok: false; failure: DeleteFailure }

/** Which of Delete cloud history's two failures this is. The shell publishes
 *  the switch's change before it answers, so `profileNow` is read after the
 *  reply and never before it. */
export function historyFailure(profile: ProfileState | undefined): DeleteFailure {
  return profile?.state === 'read' && !profile.consentSync ? 'historyOff' : 'historyOn'
}

/** The one place a delete reaches the bridge, and only when called. A call
 *  that throws is a failure like a refused one. */
export async function confirmDelete(
  kind: 'history' | 'account',
  call: () => Promise<AccountReply>,
  profileNow: () => ProfileState | undefined,
): Promise<DeleteOutcome> {
  let reply: AccountReply | null
  try {
    reply = await call()
  } catch {
    reply = null
  }
  if (reply?.ok) return { ok: true, deleted: reply.deleted }
  return { ok: false, failure: kind === 'account' ? 'account' : historyFailure(profileNow()) }
}

/** What a delete dialog's two buttons do. Nothing is called until `confirm`;
 *  `cancel` only closes. */
export function deleteControls({
  kind,
  call,
  profileNow,
  close,
  settled,
}: {
  kind: 'history' | 'account'
  call: () => Promise<AccountReply>
  profileNow: () => ProfileState | undefined
  close: () => void
  settled: (outcome: DeleteOutcome) => void
}): { cancel: () => void; confirm: () => Promise<void> } {
  return {
    cancel: close,
    confirm: async () => settled(await confirmDelete(kind, call, profileNow)),
  }
}

/** The version a Settings write records: this install's, never older than
 *  the one the answers were given under (versions are `YYYY-MM-DD`). */
function versionFor(profile: Read): string {
  return profile.consentVersion > POLICY_VERSION ? profile.consentVersion : POLICY_VERSION
}

function keep(profile: Read): ProfileChange {
  return {
    consentSync: profile.consentSync,
    consentErrors: profile.consentErrors,
    consentCoachHistory: profile.consentCoachHistory,
    policyVersion: versionFor(profile),
  }
}

/** The write for the backup or coach-history switch: every other answer as
 *  it is. */
export function switchChange(profile: Read, field: 'consentSync' | 'consentCoachHistory', on: boolean): ProfileChange {
  return { ...keep(profile), [field]: on }
}

/** The write for the error-reports switch. Turning it on is the transfer
 *  consent, so it needs `agreed` (the dialog's confirm button) and is `null`
 *  without it; turning it off needs nothing. */
export function errorsChange(profile: Read, on: boolean, agreed: boolean): ProfileChange | null {
  if (on && !agreed) return null
  return { ...keep(profile), consentErrors: on }
}

/** What the transfer dialog's two buttons do: `confirm` writes the consent
 *  and hands the answer to `settled`, `cancel` writes nothing and the
 *  switch stays off. */
export function errorsControls({
  profile,
  save,
  close,
  settled,
}: {
  profile: Read
  save: (change: ProfileChange) => Promise<Saved>
  close: () => void
  settled: (saved: Saved) => void
}): { cancel: () => void; confirm: () => Promise<void> } {
  return {
    cancel: close,
    confirm: async () => {
      const change = errorsChange(profile, true, true)
      if (change) settled(await save(change))
    },
  }
}

/** One profile write at a time. Every write is a whole profile built from
 *  what the page held when it was pressed, so a second one started before
 *  the first is answered would carry stale answers, the error-reports
 *  consent among them. `run` refuses (`null`) while one is in flight. */
export function profileGate(): { run: <T>(work: () => Promise<T>) => Promise<T | null> } {
  let inFlight = false
  return {
    run: async (work) => {
      if (inFlight) return null
      inFlight = true
      try {
        return await work()
      } finally {
        inFlight = false
      }
    },
  }
}

/** A sign-in press starts over: `begin` returns a check that stays true only
 *  until the next `begin`, so a superseded reply is ignored. */
export function attemptGuard(): { begin: () => () => boolean } {
  let latest = 0
  return {
    begin: () => {
      const mine = ++latest
      return () => mine === latest
    },
  }
}

/** What the export's reply says: `saved`, `failed`, or `null` for a save
 *  dialog that was closed. */
export function exportLine(reply: AccountReply | null): 'saved' | 'failed' | null {
  if (!reply?.ok) return 'failed'
  return reply.cancelled ? null : 'saved'
}

/** The sync status line: a translation key and the count it needs. Backup
 *  off wins, then a run in progress, then why the last one stopped; a count
 *  of zero reads as nothing backed up yet. `null` while the shell has not
 *  sent a status. */
export function syncLine(
  backupOn: boolean,
  sync: SyncStatus | undefined,
): { key: string; count?: number; when?: boolean } | null {
  if (!backupOn) return { key: 'account.settings.sync.off' }
  if (!sync) return null
  if (sync.running) return { key: 'account.settings.sync.running' }
  if (sync.lastError) return { key: `account.settings.sync.error.${sync.lastError}` }
  if (sync.backedUp === 0) return { key: 'account.settings.sync.none' }
  const key = sync.lastSyncAt === null ? 'account.settings.sync.doneUndated' : 'account.settings.sync.done'
  return { key, count: sync.backedUp, when: sync.lastSyncAt !== null }
}

export function providerName(provider: string | null): string | null {
  if (provider === 'google') return 'Google'
  if (provider === 'discord') return 'Discord'
  return provider
}

