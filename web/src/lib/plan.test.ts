import { describe, expect, it } from 'vitest'
import {
  ALLOWANCE_USED,
  KEY_REFUSED,
  NOT_REMOVED,
  PAGE_NOT_OPENED,
  activeSentence,
  allowanceSentence,
  answerOf,
  allowanceUsed,
  daysLeft,
  deviceLimitSentence,
  endedSentence,
  offerButton,
  paymentFailedSentence,
  percentLeft,
  planDay,
  pressFailure,
  pricesSentence,
  startsAgainSentence,
  trialOfferSentence,
  trialSentence,
  trialThenSentence,
} from './plan'

/** Tuesday, September 29, 2026, 10:00 in the viewer's zone. */
const now = new Date(2026, 8, 29, 10).getTime()

/** A timestamp for the local day `day` of October 2026, at `hour`. */
const october = (day: number, hour = 12) => new Date(2026, 9, day, hour).toISOString()

describe('planDay', () => {
  it('writes a bare date from its own parts', () => {
    expect(planDay('2026-10-03', now)).toBe('Oct 3')
  })

  it('writes a timestamp in the viewer zone', () => {
    expect(planDay(october(3), now)).toBe('Oct 3')
  })

  it('adds the year in a year other than now', () => {
    expect(planDay('2027-01-15', now)).toBe('Jan 15, 2027')
  })

  it('says nothing of a day it cannot read', () => {
    expect(planDay('soon', now)).toBeNull()
  })
})

describe('daysLeft and trialSentence', () => {
  it('counts calendar days, not hours', () => {
    expect(daysLeft('2026-10-03', now)).toBe(4)
    // Early on the fourth day is still four days by the calendar.
    expect(daysLeft(october(3, 1), now)).toBe(4)
  })

  it('says the days left and the day it ends', () => {
    expect(trialSentence('2026-10-03', now)).toBe('4 days of the trial are left. It ends on Oct 3.')
  })

  it('says tomorrow on the day before', () => {
    expect(trialSentence('2026-09-30', now)).toBe('The trial ends tomorrow, on Sep 30.')
  })

  it('says today on the day itself', () => {
    expect(trialSentence('2026-09-29', now)).toBe('The trial ends today.')
    // Late the same day is still today.
    expect(trialSentence(new Date(2026, 8, 29, 23).toISOString(), now)).toBe('The trial ends today.')
  })

  it('reads a day that has passed as today', () => {
    expect(trialSentence('2026-09-27', now)).toBe('The trial ends today.')
  })

  it('says nothing of a day it cannot read', () => {
    expect(daysLeft('soon', now)).toBeNull()
    expect(trialSentence('soon', now)).toBeNull()
  })
})

describe('trialThenSentence', () => {
  it('says when the card is charged and how much, as the shell wrote it', () => {
    expect(trialThenSentence('2026-10-03', { on: '2026-10-03', amount: '<monthly>' }, now)).toBe(
      'On Oct 3 your card is charged <monthly> and the plan starts.',
    )
  })

  it('says a cancelled trial works to its end and charges nothing', () => {
    expect(trialThenSentence('2026-10-03', null, now)).toBe(
      'The trial was cancelled. It works until Oct 3 and nothing is charged.',
    )
  })
})

describe('activeSentence', () => {
  it('says how the plan is paid and when it renews', () => {
    expect(activeSentence('month', { on: '2026-10-18', amount: '<monthly>' }, '2026-10-18', now)).toBe(
      'Paid by the month. It renews on Oct 18 for <monthly>.',
    )
    expect(activeSentence('year', { on: '2027-04-17', amount: '<yearly>' }, '2027-04-17', now)).toBe(
      'Paid by the year. It renews on Apr 17, 2027 for <yearly>.',
    )
  })

  it('says until when a cancelled plan works', () => {
    expect(activeSentence('month', null, '2026-10-18', now)).toBe('The plan was cancelled. It works until Oct 18.')
  })
})

describe('the other dated sentences', () => {
  it('says until when a plan whose payment failed works', () => {
    expect(paymentFailedSentence('2026-10-05', now)).toBe('The plan works until Oct 5. Update the card to keep it.')
  })

  it('says when a plan ended and what still works', () => {
    expect(endedSentence('2026-09-17', now)).toBe(
      'Your plan ended on Sep 17. Every report still gives you its prompt to copy, and a key of your own still writes them.',
    )
  })

  it('says when the allowance starts again', () => {
    expect(startsAgainSentence('2026-10-18', now)).toBe('It starts again on Oct 18.')
  })
})

describe('percentLeft', () => {
  it('gives the part left as a whole percentage', () => {
    expect(percentLeft(0.38)).toBe('62% left')
    expect(percentLeft(0.2)).toBe('80% left')
    expect(percentLeft(0)).toBe('100% left')
    expect(percentLeft(1)).toBe('0% left')
  })

  it('holds a part outside 0 to 1 at its end', () => {
    expect(percentLeft(1.4)).toBe('0% left')
    expect(percentLeft(-0.2)).toBe('100% left')
  })
})

describe('allowanceSentence', () => {
  it('joins the kinds as alternatives, in the order coach, guide, leaks, match', () => {
    const left = [
      { kind: 'match' as const, about: 40 },
      { kind: 'coach' as const, about: 3 },
      { kind: 'guide' as const, about: 4 },
    ]
    expect(allowanceSentence(left)).toBe(
      'Enough for about 3 coach reports, or about 4 deck guides, or about 40 match reports.',
    )
  })

  it('says one of a kind in the singular', () => {
    const left = [
      { kind: 'coach' as const, about: 1 },
      { kind: 'guide' as const, about: 1 },
      { kind: 'leaks' as const, about: 1 },
      { kind: 'match' as const, about: 8 },
    ]
    expect(allowanceSentence(left)).toBe(
      'Enough for about 1 coach report, or about 1 deck guide, or about 1 leak report, or about 8 match reports.',
    )
  })

  it('leaves out a kind with none left', () => {
    const left = [
      { kind: 'coach' as const, about: 0 },
      { kind: 'leaks' as const, about: 2 },
      { kind: 'match' as const, about: 12 },
    ]
    expect(allowanceSentence(left)).toBe('Enough for about 2 leak reports, or about 12 match reports.')
  })

  it('names one kind alone with no alternative', () => {
    expect(allowanceSentence([{ kind: 'match', about: 3 }])).toBe('Enough for about 3 match reports.')
  })

  it('says the allowance is used when no kind has any left', () => {
    const left = [
      { kind: 'coach' as const, about: 0 },
      { kind: 'match' as const, about: 0 },
    ]
    expect(allowanceUsed(left)).toBe(true)
    expect(allowanceSentence(left)).toBe(ALLOWANCE_USED)
    expect(allowanceSentence([])).toBe(
      'The allowance is used. Every report still gives you its prompt to copy.',
    )
  })

  it('does not read an allowance with something left as used', () => {
    expect(allowanceUsed([{ kind: 'guide', about: 1 }])).toBe(false)
  })
})

describe('the offer', () => {
  it('writes the two prices as the shell wrote them', () => {
    expect(pricesSentence('<monthly>', '<yearly>')).toBe('<monthly> a month, or <yearly> a year.')
  })

  it('offers the trial, or a subscription when there is none', () => {
    expect(offerButton(7)).toBe('Start the 7-day trial')
    expect(offerButton(null)).toBe('Subscribe')
  })

  it('says what the trial is', () => {
    expect(trialOfferSentence(7)).toBe(
      'The trial asks for a card. It turns into the plan you pick after 7 days, and costs nothing if you cancel before then.',
    )
  })
})

describe('pressFailure and answerOf', () => {
  it('says nothing of a press that worked', () => {
    expect(pressFailure({ ok: true }, PAGE_NOT_OPENED)).toBeNull()
  })

  it("keeps the shell's own sentence", () => {
    expect(pressFailure({ ok: false, error: 'The browser is not set.' }, PAGE_NOT_OPENED)).toBe(
      'The browser is not set.',
    )
  })

  it('gives the plain sentence of each press when the shell gave none', () => {
    expect(pressFailure({ ok: false, error: ' ' }, KEY_REFUSED)).toBe(
      'The key was not accepted. Check it against your receipt.',
    )
    expect(pressFailure({ ok: false, error: '' }, PAGE_NOT_OPENED)).toBe('The page could not be opened. Try again.')
    expect(pressFailure({ ok: false, error: '' }, NOT_REMOVED)).toBe('The computer was not removed. Try again.')
  })

  it('reads a refused answer as a failure with no sentence', async () => {
    const refused = answerOf(Promise.reject(new Error('gone')))
    expect(await refused).toEqual({ ok: false, error: '' })
    expect(pressFailure(await answerOf(Promise.reject(new Error('gone'))), KEY_REFUSED)).toBe(
      'The key was not accepted. Check it against your receipt.',
    )
  })

  it('passes an answer through', async () => {
    expect(await answerOf(Promise.resolve({ ok: true }))).toEqual({ ok: true })
  })
})

describe('deviceLimitSentence', () => {
  it('says how many computers the plan works on', () => {
    expect(deviceLimitSentence(2)).toBe('The plan works on 2 computers at a time.')
    expect(deviceLimitSentence(1)).toBe('The plan works on one computer at a time.')
  })
})
