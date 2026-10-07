/**
 * Cloud sync's sentences, as pure functions of what the shell hands over:
 * the passphrase's check, the storage's sentence and the meter's part, the
 * last sync, and what a pause says. A size is `sizeOf`'s and a day the
 * plan's; nothing here writes either its own way. Every function that
 * reads a time takes `now`, so a test needs no clock.
 */
import type { SyncPause, SyncSetUp } from '../bridge'
import { planDay } from './plan'
import { sizeOf } from './size'
import { ago } from './time'

/** The fewest characters a passphrase has. */
export const PASSPHRASE_MIN = 12

/** Under the passphrase's field when it is shorter than the least. */
export const TOO_SHORT = 'It needs 12 characters or more.'

/** Under the second field when the two passphrases differ. */
export const NOT_THE_SAME = 'The two are not the same.'

/** Said in each step of the setup, in the same words. */
export const SYNC_WARNING = 'If you lose the passphrase and the recovery code, the copy cannot be read again by anyone.'

/** Under "Continue" when the setup failed and the shell gave no sentence. */
export const SETUP_FAILED = 'Cloud sync was not set up. Try again.'

/** Under the locked card's field when the copy did not open and the shell
 *  gave no sentence. */
export const UNLOCK_FAILED = 'That did not open the copy. Check it and try again.'

/** Under "Sync now" when it failed and the shell gave no sentence. */
export const SYNC_FAILED = 'It did not sync. Try again.'

/** Under "Delete my cloud data" when the deletion failed and the shell
 *  gave no sentence. */
export const NOT_DELETED = 'The cloud copy was not deleted. Try again.'

/** Said in the card after the cloud copy was deleted. */
export const CLOUD_DELETED = 'The cloud copy was deleted.'

/** A passphrase's length in characters, a character outside the basic
 *  plane counted once. */
function characters(text: string): number {
  return Array.from(text).length
}

/** The two passphrase fields read together: the sentence under the first
 *  when it is too short, said once the second has been typed into so it
 *  does not show while the first is still being typed; the sentence under
 *  the second when it has been typed into and differs; and whether
 *  "Continue" can be pressed, which is when both are alike and long
 *  enough. Nothing is trimmed: a space is a character of the passphrase. */
export function passphraseCheck(
  first: string,
  again: string,
): { short: string | null; differ: string | null; ready: boolean } {
  const long = characters(first) >= PASSPHRASE_MIN
  return {
    short: !long && first !== '' && again !== '' ? TOO_SHORT : null,
    differ: again !== '' && again !== first ? NOT_THE_SAME : null,
    ready: long && first === again,
  }
}

/** The storage beside the meter: "412 MB of 2 GB". */
export function storageSentence(bytes: number, quota: number): string {
  return `${sizeOf(bytes)} of ${sizeOf(quota)}`
}

/** The part of the quota used, 0 to 1, held at 1 past the quota. `null`
 *  when the quota is not a size above nothing or the bytes are not a
 *  number, so the page draws no meter it cannot fill truly. */
export function storagePart(bytes: number, quota: number): number | null {
  if (!Number.isFinite(quota) || quota <= 0 || !Number.isFinite(bytes)) return null
  return Math.min(1, Math.max(0, bytes / quota))
}

/** When this computer last synced, "Last synced 12m ago.", or "Not synced
 *  yet." before the first. `null` when the time cannot be read. */
export function lastSyncedSentence(last: string | null, now: number): string | null {
  if (last === null) return 'Not synced yet.'
  const when = ago(last, now)
  return when === null ? null : `Last synced ${when}.`
}

/** The callout over a paused card: its tone, its title and its sentence.
 *  A full quota and a lapsed plan are `warn`, a lost connection `neutral`.
 *  A lapsed plan says until when the copy is kept when that day can be
 *  read, and leaves the day out otherwise. */
export function pauseCallout(
  why: SyncPause,
  keptUntil: string | null,
  now: number,
): { tone: 'neutral' | 'warn'; title: string; sentence: string } {
  switch (why) {
    case 'quota':
      return {
        tone: 'warn',
        title: 'Sync is paused: the storage is full',
        sentence: 'Nothing new is sent until there is room. Your matches on this computer are untouched.',
      }
    case 'offline':
      return {
        tone: 'neutral',
        title: 'Sync is waiting for a connection',
        sentence: 'It starts again by itself. Your matches on this computer are untouched.',
      }
    case 'plan': {
      const day = keptUntil === null ? null : planDay(keptUntil, now)
      return {
        tone: 'warn',
        title: 'Sync is paused: the plan ended',
        sentence:
          day === null
            ? 'Your matches on this computer are untouched.'
            : `Your matches on this computer are untouched. The cloud copy is kept until ${day} and deleted after.`,
      }
    }
  }
}

/** The setup's answer, with a refused promise read as a failure with no
 *  sentence of the shell's own. */
export function setUpAnswer(setting: Promise<SyncSetUp>): Promise<SyncSetUp> {
  return setting.catch((): SyncSetUp => ({ ok: false, error: '' }))
}

/** The sentence under "Continue" when the setup failed: the shell's own,
 *  or the plain one. `null` for a setup that worked. */
export function setUpFailure(answer: SyncSetUp): string | null {
  return answer.ok ? null : answer.error.trim() || SETUP_FAILED
}
