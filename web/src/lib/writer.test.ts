import { describe, expect, it } from 'vitest'
import type { Allowance, Offer, Plan } from '../bridge'
import { OFFER_HREF, OFFER_LINK, OFFER_SENTENCE, leftSentence, usedSentence, writerFrom } from './writer'

/** Tuesday, September 29, 2026, 10:00 in the viewer's zone. */
const now = new Date(2026, 8, 29, 10).getTime()

const offer: Offer = { byMonth: '<monthly>', byYear: '<yearly>', trialDays: 7 }

const allowance: Allowance = {
  used: 0.4,
  startsAgain: '2026-10-18',
  left: [
    { kind: 'coach', about: 3 },
    { kind: 'match', about: 40 },
    { kind: 'leaks', about: 0 },
  ],
}

const usedUp: Allowance = {
  used: 1,
  startsAgain: '2026-10-18',
  left: [
    { kind: 'coach', about: 0 },
    { kind: 'match', about: 0 },
  ],
}

const key = { configured: true }
const noKey = { configured: false }

describe('writerFrom', () => {
  it('lets a plan in trial write, with no day it starts again', () => {
    const plan: Plan = { state: 'trial', ends: '2026-10-03', then: null, allowance }
    expect(writerFrom(noKey, plan, 'coach')).toEqual({ by: 'plan', about: 3, used: false, startsAgain: null })
  })

  it('lets a running plan write, with the day its allowance starts again', () => {
    const plan: Plan = { state: 'active', every: 'month', renews: null, until: '2026-10-18', allowance }
    expect(writerFrom(noKey, plan, 'match')).toEqual({
      by: 'plan',
      about: 40,
      used: false,
      startsAgain: '2026-10-18',
    })
  })

  it('lets a plan whose payment failed write', () => {
    const plan: Plan = { state: 'payment-failed', until: '2026-10-05', allowance }
    expect(writerFrom(noKey, plan, 'coach')).toEqual({
      by: 'plan',
      about: 3,
      used: false,
      startsAgain: '2026-10-18',
    })
  })

  it('puts a plan that writes before a key', () => {
    const plan: Plan = { state: 'payment-failed', until: '2026-10-05', allowance }
    expect(writerFrom(key, plan, 'coach').by).toBe('plan')
  })

  it('gives no count for a kind the allowance does not name', () => {
    const plan: Plan = { state: 'trial', ends: '2026-10-03', then: null, allowance }
    expect(writerFrom(noKey, plan, 'guide')).toEqual({ by: 'plan', about: null, used: false, startsAgain: null })
  })

  it('reads the allowance as used when no kind has any left', () => {
    const plan: Plan = { state: 'active', every: 'year', renews: null, until: '2027-04-17', allowance: usedUp }
    expect(writerFrom(key, plan, 'coach')).toEqual({ by: 'plan', about: 0, used: true, startsAgain: '2026-10-18' })
  })

  it('reads the allowance as used for a kind it does not name, once no kind has any left', () => {
    const plan: Plan = { state: 'active', every: 'month', renews: null, until: '2026-10-18', allowance: usedUp }
    expect(writerFrom(noKey, plan, 'guide')).toEqual({
      by: 'plan',
      about: null,
      used: true,
      startsAgain: '2026-10-18',
    })
  })

  it('reads the allowance as used for a kind with none left', () => {
    const plan: Plan = { state: 'trial', ends: '2026-10-03', then: null, allowance }
    expect(writerFrom(noKey, plan, 'leaks')).toEqual({ by: 'plan', about: 0, used: true, startsAgain: null })
  })

  it('lets a key write with no plan, or a plan that does not write', () => {
    expect(writerFrom(key, null, 'coach')).toEqual({ by: 'key' })
    expect(writerFrom(key, { state: 'not-offered' }, 'coach')).toEqual({ by: 'key' })
    expect(writerFrom(key, { state: 'none', offer }, 'guide')).toEqual({ by: 'key' })
    expect(writerFrom(key, { state: 'ended', on: '2026-09-17', offer }, 'match')).toEqual({ by: 'key' })
  })

  it('has nobody write, offering nothing, with no key and no shell', () => {
    expect(writerFrom(noKey, null, 'coach')).toEqual({ by: 'nobody', offered: false })
  })

  it('has nobody write before the key status answers', () => {
    expect(writerFrom(undefined, null, 'coach')).toEqual({ by: 'nobody', offered: false })
    expect(writerFrom(null, null, 'match')).toEqual({ by: 'nobody', offered: false })
  })

  it('offers the plan to a viewer with none, or whose plan ended', () => {
    expect(writerFrom(noKey, { state: 'none', offer }, 'coach')).toEqual({ by: 'nobody', offered: true })
    expect(writerFrom(noKey, { state: 'ended', on: '2026-09-17', offer }, 'leaks')).toEqual({
      by: 'nobody',
      offered: true,
    })
  })

  it('offers nothing where no plan is sold', () => {
    expect(writerFrom(noKey, { state: 'not-offered' }, 'guide')).toEqual({ by: 'nobody', offered: false })
  })
})

describe('the sentences', () => {
  it('offers the plan with one link', () => {
    expect(`${OFFER_SENTENCE} ${OFFER_LINK}`).toBe('Pro writes this for you. See the plan')
    expect(OFFER_HREF).toBe('/settings#plan')
  })

  it('says how many are left this month', () => {
    expect(leftSentence(12, false)).toBe('Enough is left for about 12 more of these this month.')
    expect(leftSentence(1, false)).toBe('Enough is left for about 1 more of these this month.')
  })

  it('says how many are left in the trial', () => {
    expect(leftSentence(4, true)).toBe('Enough is left for about 4 more of these in the trial.')
    expect(leftSentence(1, true)).toBe('Enough is left for about 1 more of these in the trial.')
  })

  it('says nothing with no count', () => {
    expect(leftSentence(null, false)).toBeNull()
  })

  it('says the allowance is used and when it starts again', () => {
    expect(usedSentence('2026-10-18', now)).toBe(
      "This month's allowance is used. It starts again on Oct 18. The prompt is here to copy until then.",
    )
  })

  it("says the trial's allowance is used", () => {
    expect(usedSentence(null, now)).toBe("The trial's allowance is used. The prompt is here to copy.")
  })

  it("falls back to the plan's sentence with a day it cannot read", () => {
    expect(usedSentence('soon', now)).toBe(
      'The allowance is used. Every report still gives you its prompt to copy.',
    )
  })
})
