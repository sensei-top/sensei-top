import { describe, expect, it } from 'vitest'
import {
  NOT_THE_SAME,
  SETUP_FAILED,
  TOO_SHORT,
  lastSyncedSentence,
  passphraseCheck,
  pauseCallout,
  setUpAnswer,
  setUpFailure,
  storagePart,
  storageSentence,
} from './sync'

/** Tuesday, September 29, 2026, 10:00 in the viewer's zone. */
const now = new Date(2026, 8, 29, 10).getTime()

describe('passphraseCheck', () => {
  it('is ready when both are alike and 12 characters long', () => {
    expect(passphraseCheck('twelve chars', 'twelve chars')).toEqual({ short: null, differ: null, ready: true })
  })

  it('is not ready at 11 characters, and says so once the second is typed', () => {
    expect(passphraseCheck('eleven char', '')).toEqual({ short: null, differ: null, ready: false })
    expect(passphraseCheck('eleven char', 'eleven char')).toEqual({ short: TOO_SHORT, differ: null, ready: false })
  })

  it('says the two differ under the second field', () => {
    expect(passphraseCheck('a long passphrase', 'a long passphrasE')).toEqual({
      short: null,
      differ: NOT_THE_SAME,
      ready: false,
    })
  })

  it('says nothing of the second field before it is typed into', () => {
    expect(passphraseCheck('a long passphrase', '').differ).toBeNull()
  })

  it('counts a character outside the basic plane once', () => {
    // Eleven letters and one emoji: twelve characters, thirteen UTF-16 units.
    const phrase = 'abcdefghijk\u{1F512}'
    expect(passphraseCheck(phrase, phrase).ready).toBe(true)
  })

  it('keeps spaces as characters', () => {
    expect(passphraseCheck(' short one ', ' short one ').ready).toBe(false)
    expect(passphraseCheck('  short one ', '  short one ').ready).toBe(true)
  })
})

describe('storageSentence and storagePart', () => {
  it('writes the sizes as the wording does', () => {
    expect(storageSentence(412_000_000, 2_000_000_000)).toBe('412 MB of 2 GB')
    expect(storageSentence(1_200_000_000, 2_000_000_000)).toBe('1.2 GB of 2 GB')
    expect(storageSentence(2_000_000_000, 2_000_000_000)).toBe('2 GB of 2 GB')
  })

  it('is the part of the quota used, held at a full quota', () => {
    expect(storagePart(500_000_000, 2_000_000_000)).toBe(0.25)
    expect(storagePart(3_000_000_000, 2_000_000_000)).toBe(1)
  })

  it('draws no part of a quota that is not a size', () => {
    expect(storagePart(1, 0)).toBeNull()
    expect(storagePart(Number.NaN, 2_000_000_000)).toBeNull()
  })
})

describe('lastSyncedSentence', () => {
  it('says when, in ago words', () => {
    const twelveMinutesBefore = new Date(now - 12 * 60_000).toISOString()
    expect(lastSyncedSentence(twelveMinutesBefore, now)).toBe('Last synced 12m ago.')
  })

  it('says it has not synced before the first', () => {
    expect(lastSyncedSentence(null, now)).toBe('Not synced yet.')
  })

  it('says nothing of a time it cannot read', () => {
    expect(lastSyncedSentence('soon', now)).toBeNull()
  })
})

describe('pauseCallout', () => {
  it('warns of a full quota', () => {
    expect(pauseCallout('quota', null, now)).toEqual({
      tone: 'warn',
      title: 'Sync is paused: the storage is full',
      sentence: 'Nothing new is sent until there is room. Your matches on this computer are untouched.',
    })
  })

  it('is neutral while offline', () => {
    expect(pauseCallout('offline', null, now).tone).toBe('neutral')
  })

  it('says until when a lapsed plan keeps the copy', () => {
    expect(pauseCallout('plan', '2026-11-28', now)).toEqual({
      tone: 'warn',
      title: 'Sync is paused: the plan ended',
      sentence:
        'Your matches on this computer are untouched. The cloud copy is kept until Nov 28 and deleted after.',
    })
  })

  it('leaves the day out when none is known or it cannot be read', () => {
    const plain = 'Your matches on this computer are untouched.'
    expect(pauseCallout('plan', null, now).sentence).toBe(plain)
    expect(pauseCallout('plan', 'later', now).sentence).toBe(plain)
  })
})

describe('setUpAnswer and setUpFailure', () => {
  it('reads a refused promise as a failure with the plain sentence', async () => {
    const answer = await setUpAnswer(Promise.reject(new Error('gone')))
    expect(setUpFailure(answer)).toBe(SETUP_FAILED)
  })

  it("says the shell's sentence when it gave one", () => {
    expect(setUpFailure({ ok: false, error: 'The server did not answer.' })).toBe('The server did not answer.')
  })

  it('says nothing of a setup that worked', () => {
    expect(setUpFailure({ ok: true, recovery: 'CODE' })).toBeNull()
  })
})
