import { describe, expect, it } from 'vitest'
import type { ContribAnswer, Contribute } from '../bridge'
import {
  answerFor,
  ageBox,
  contribAskedOnWelcome,
  contribPageDue,
  dialogNeeded,
  settingsFailureKey,
  stateKey,
  submitAnswer,
  turnOffAnswer,
  turnOnAnswer,
  contribWaits,
  failureKey,
  hintFor,
  isPressed,
  pressAnswer,
  savedAnswer,
} from './contribute'

const stored = (change: Partial<Contribute> = {}): Contribute => ({
  yes: true,
  policyVersion: '2026-10-01',
  answeredAt: '2026-10-02T00:00:00Z',
  ageConfirmed: true,
  ...change,
})

// The approved copy, section A: the sentences are the key's own words.
const t = ((key: string) =>
  ({
    'contribute.failure.notSaved': "Your answer wasn't saved, and no game is sent. Try again.",
    'contribute.failure.stillSending': "Your answer wasn't saved, so your games are still being sent. Try again.",
    'settings.saveFailed': 'Could not save.',
  })[key] ?? key) as never

describe('when the question is asked', () => {
  it('only to a build that can upload, with nothing stored', () => {
    expect(contribAskedOnWelcome(true, null)).toBe(true)
    expect(contribAskedOnWelcome(false, null)).toBe(false)
    expect(contribAskedOnWelcome(true, stored({ yes: false }))).toBe(false)
  })

  it('makes Go to Home wait until the shell or a press answers', () => {
    expect(contribWaits(true, null, null)).toBe(true)
    expect(contribWaits(true, null, false)).toBe(false)
    expect(contribWaits(true, stored(), null)).toBe(false)
    expect(contribWaits(false, null, null)).toBe(false)
  })

  it('reads the saved answer from the shell first, else the press', () => {
    expect(savedAnswer(null, null)).toBeNull()
    expect(savedAnswer(null, true)).toBe(true)
    expect(savedAnswer(stored({ yes: false }), true)).toBe(false)
  })
})

describe('what a press sends', () => {
  it('refuses a yes without the age box and sends one with it', () => {
    expect(answerFor(true, false, null, 'v')).toBeNull()
    expect(answerFor(true, true, null, 'v')).toEqual({ yes: true, policyVersion: 'v', ageConfirmed: true })
  })

  it('sends a no at once, never claiming an age, and keeps what is stored', () => {
    expect(answerFor(false, true, null, 'v')).toEqual({ yes: false, policyVersion: 'v', ageConfirmed: false })
    expect(answerFor(false, false, stored(), 'v')).toEqual({
      yes: false,
      policyVersion: '2026-10-01',
      ageConfirmed: true,
    })
  })
})

describe('the hint and the failure line', () => {
  it('shows only the first hint that applies', () => {
    expect(hintFor(true, false, true)).toBe('age')
    expect(hintFor(false, false, true)).toBe('waitsWelcome')
    expect(hintFor(false, false, false)).toBeNull()
  })

  it('clears the age hint once the box is ticked', () => {
    expect(hintFor(true, true, false)).toBeNull()
    expect(hintFor(true, true, true)).toBe('waitsWelcome')
  })

  it('keeps the box ticked and locked once a yes is saved, and free after a saved no', () => {
    expect(ageBox(false, true, false)).toEqual({ checked: true, disabled: true })
    expect(ageBox(false, false, false)).toEqual({ checked: false, disabled: false })
    expect(ageBox(true, null, false)).toEqual({ checked: true, disabled: false })
    expect(ageBox(true, null, true).disabled).toBe(true)
  })

  it('shows pressed only the saved answer', () => {
    expect(isPressed(null, true)).toBe(false)
    expect(isPressed(null, false)).toBe(false)
    expect(isPressed(true, true)).toBe(true)
    expect(isPressed(true, false)).toBe(false)
  })

  it('says the games are still sent only for a no after a saved yes', () => {
    expect(failureKey(false, true)).toBe('stillSending')
    expect(failureKey(false, null)).toBe('notSaved')
    expect(failureKey(true, null)).toBe('notSaved')
  })
})

describe('pressing an answer', () => {
  const ok = () => Promise.resolve({ ok: true } as const)

  it('calls nothing for a yes without the box', async () => {
    const sent: ContribAnswer[] = []
    const save = (a: ContribAnswer) => (sent.push(a), ok())
    expect(await pressAnswer(true, false, null, null, 'v', save, t)).toEqual({ kind: 'needAge' })
    expect(sent).toEqual([])
  })

  it('saves a yes with the box, and a no without it', async () => {
    const sent: ContribAnswer[] = []
    const save = (a: ContribAnswer) => (sent.push(a), ok())
    expect(await pressAnswer(true, true, null, null, 'v', save, t)).toEqual({ kind: 'saved', yes: true })
    expect(await pressAnswer(false, false, null, null, 'v', save, t)).toEqual({ kind: 'saved', yes: false })
    expect(sent.map((a) => a.yes)).toEqual([true, false])
  })

  it('reports a refused, rejected or thrown save, and a missing bridge, as a failure', async () => {
    const lines = "Your answer wasn't saved, and no game is sent. Try again."
    const refused = () => Promise.resolve({ ok: false, error: 'no' } as const)
    const rejected = () => Promise.reject(new Error('x'))
    const thrown = (): never => {
      throw new Error('x')
    }
    for (const save of [refused, rejected, thrown, undefined]) {
      expect(await pressAnswer(true, true, null, null, 'v', save, t)).toEqual({
        kind: 'failed',
        line: lines,
        key: 'notSaved',
      })
    }
  })

  it('words a failed no after a saved yes as still sending', async () => {
    const refused = () => Promise.resolve({ ok: false, error: '' } as const)
    const result = await pressAnswer(false, true, stored(), true, 'v', refused, t)
    expect(result).toMatchObject({ kind: 'failed', key: 'stillSending' })
  })
})

describe('the one-time page', () => {
  const account = (change: object) => ({ available: true, signedIn: true, ...change }) as never
  const app = {
    canContribute: true,
    contribAsked: false,
    contribute: null,
    onboarded: true,
    account: account({ signedIn: false }),
  }
  it('is due once: an onboarded install that can upload, with nothing asked or stored', () => {
    expect(contribPageDue(app, false)).toBe(true)
  })
  it('waits for a signed-in account whose profile is absent or unknown', () => {
    expect(contribPageDue({ ...app, account: account({}) }, false)).toBe(false)
    expect(contribPageDue({ ...app, account: account({ profile: { state: 'unknown' } }) }, false)).toBe(false)
  })
  it('is due for a signed-in account whose profile is read', () => {
    expect(contribPageDue({ ...app, account: account({ profile: { state: 'read' } }) }, false)).toBe(true)
  })
  it('is not due during onboarding, during consent, after it was asked or answered, or when the build cannot upload', () => {
    expect(contribPageDue({ ...app, onboarded: false }, false)).toBe(false)
    expect(contribPageDue(app, true)).toBe(false)
    expect(contribPageDue({ ...app, contribAsked: true }, false)).toBe(false)
    expect(contribPageDue({ ...app, contribute: stored({ yes: false }) }, false)).toBe(false)
    expect(contribPageDue({ ...app, canContribute: false }, false)).toBe(false)
    expect(contribPageDue(undefined, false)).toBe(false)
  })
})

describe('the Settings switch', () => {
  it('needs the dialog for nothing stored, no age confirmation or an older policy', () => {
    expect(dialogNeeded(null, '2026-11-03')).toBe(true)
    expect(dialogNeeded(stored({ ageConfirmed: false, policyVersion: '2026-11-03' }), '2026-11-03')).toBe(true)
    expect(dialogNeeded(stored({ policyVersion: '2026-10-01' }), '2026-11-03')).toBe(true)
  })
  it('skips the dialog for an age-confirmed answer under the current or a newer policy', () => {
    expect(dialogNeeded(stored({ yes: false, policyVersion: '2026-11-03' }), '2026-11-03')).toBe(false)
    expect(dialogNeeded(stored({ policyVersion: '2026-12-01' }), '2026-11-03')).toBe(false)
  })
  it('turns on with the age confirmed and the current version', () => {
    expect(turnOnAnswer('v')).toEqual({ yes: true, policyVersion: 'v', ageConfirmed: true })
  })
  it('turns off keeping the stored age confirmation and version, the current one when nothing is stored', () => {
    expect(turnOffAnswer(stored({ ageConfirmed: false }), 'v')).toEqual({
      yes: false,
      policyVersion: '2026-10-01',
      ageConfirmed: false,
    })
    expect(turnOffAnswer(null, 'v')).toEqual({ yes: false, policyVersion: 'v', ageConfirmed: false })
  })
  it('picks the state line: this visit first, else the stored answer', () => {
    expect(stateKey(stored(), 'on')).toBe('turnedOn')
    expect(stateKey(stored(), 'off')).toBe('turnedOff')
    expect(stateKey(null, null)).toBe('unanswered')
    expect(stateKey(stored(), null)).toBe('on')
    expect(stateKey(stored({ yes: false }), null)).toBe('off')
  })
  it('names the failure line by the turn that failed', () => {
    expect(settingsFailureKey(true)).toBe('turnOn')
    expect(settingsFailureKey(false)).toBe('turnOff')
  })
  it('reads a refused or rejected save as not saved, never a throw', async () => {
    const answer = turnOnAnswer('v')
    expect(await submitAnswer(answer, async () => ({ ok: true }), t)).toBe(true)
    expect(await submitAnswer(answer, async () => ({ ok: false, error: 'no' }), t)).toBe(false)
    expect(await submitAnswer(answer, () => Promise.reject(new Error('x')), t)).toBe(false)
    expect(await submitAnswer(answer, undefined, t)).toBe(false)
  })
})
