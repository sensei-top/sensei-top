import { describe, expect, it } from 'vitest'
import type { AccountState, AppSettings, ProfileState } from '../bridge'
import {
  afterConsent,
  consentState,
  canContinue,
  contribAnswer,
  hintFor,
  initialDraft,
  introLines,
  opening,
  kindOf,
  needsConsent,
  policyDate,
  privacyUrl,
  profileChange,
  showContribute,
  stepHint,
  stepsOf,
  storedNo,
  termsUrl,
  withErrors,
  type Answer,
  type Draft,
} from './accountWelcome'

const VERSION = '2026-11-03'

const read = (over: Partial<Extract<ProfileState, { state: 'read' }>> = {}): ProfileState => ({
  state: 'read',
  ageConfirmedAt: '2026-10-01T00:00:00Z',
  consentSync: true,
  consentErrors: false,
  consentCoachHistory: true,
  consentVersion: VERSION,
  consentedAt: '2026-10-01T00:00:00Z',
  ...over,
})

const answered = (over: Partial<Draft> = {}): Draft => ({
  age: true,
  terms: true,
  privacy: true,
  sync: true,
  errors: false,
  coach: false,
  transfer: false,
  contribute: null,
  ...over,
})

describe('the consent screen on a first sign-in', () => {
  const draft = initialDraft({ state: 'none' })

  it('starts with nothing ticked or chosen', () => {
    expect(draft).toEqual({ age: false, terms: false, privacy: false, sync: null, errors: null, coach: null, transfer: false, contribute: null })
    expect(kindOf({ state: 'none' })).toBe('first')
  })

  it('waits on the age and on each answer', () => {
    expect(canContinue('first', draft, false)).toBe(false)
    expect(canContinue('first', answered(), false)).toBe(true)
    expect(canContinue('first', answered({ age: false }), false)).toBe(false)
    for (const field of ['sync', 'errors', 'coach'] as const) {
      const missing: Answer = null
      expect(canContinue('first', answered({ [field]: missing }), false)).toBe(false)
    }
  })

  it('waits on the contribute answer only while that block is shown', () => {
    expect(canContinue('first', answered(), true)).toBe(false)
    expect(canContinue('first', answered({ contribute: false }), true)).toBe(true)
    expect(hintFor('first', answered(), true)).toBe('answers')
  })

  it('says what is missing first, then the transfer hint', () => {
    expect(hintFor('first', draft, false)).toBe('answers')
    expect(hintFor('first', answered({ errors: true }), false)).toBe('transfer')
    expect(hintFor('first', answered({ age: false, errors: true }), false)).toBe('answers')
    expect(hintFor('first', answered({ errors: true, transfer: true }), false)).toBeNull()
  })

  it('does not let Send stand without the transfer box', () => {
    expect(canContinue('first', answered({ errors: true }), false)).toBe(false)
    expect(canContinue('first', answered({ errors: true, transfer: true }), false)).toBe(true)
  })
})

describe('the transfer consent record', () => {
  it('never writes consentErrors true unless the box is ticked', () => {
    for (const kind of ['first', 'returning'] as const) {
      for (const errors of [null, true, false] as const) {
        for (const transfer of [true, false]) {
          const change = profileChange(kind, answered({ errors, transfer }), VERSION)
          expect(change.consentErrors).toBe(errors === true && transfer)
        }
      }
    }
    expect(profileChange('first', answered({ errors: true, transfer: false }), VERSION).consentErrors).toBe(false)
  })

  it('unticks the box when Send is left, so a later Send starts unticked', () => {
    const sent = withErrors(answered({ errors: null }), true)
    const ticked = { ...sent, transfer: true }
    const off = withErrors(ticked, false)
    expect(off.transfer).toBe(false)
    expect(withErrors(off, true).transfer).toBe(false)
    expect(withErrors(ticked, true).transfer).toBe(true)
  })

  it('carries the answers, the policy version and, on a first profile only, the age', () => {
    const draft = answered({ sync: true, errors: true, transfer: true, coach: false })
    expect(profileChange('first', draft, VERSION)).toEqual({
      consentSync: true,
      consentErrors: true,
      consentCoachHistory: false,
      policyVersion: VERSION,
      termsAgreed: true,
      ageConfirmed: true,
    })
    expect('ageConfirmed' in profileChange('returning', draft, VERSION)).toBe(false)
  })
})

describe('the consent screen for a returning user', () => {
  it('pre-selects the earlier answers, and ticks the box when error reports were on', () => {
    const on = initialDraft(read({ consentSync: false, consentErrors: true, consentCoachHistory: true }))
    expect(on).toMatchObject({ sync: false, errors: true, coach: true, transfer: true, age: false })
    const off = initialDraft(read({ consentErrors: false }))
    expect(off).toMatchObject({ errors: false, transfer: false })
    expect(kindOf(read())).toBe('returning')
  })

  it('starts with Continue off until the agreement, then on, and shows only the transfer hint when the box is cleared', () => {
    const start = initialDraft(read({ consentErrors: true }))
    expect(canContinue('returning', start, false)).toBe(false)
    const agreed = { ...start, terms: true, privacy: true }
    expect(canContinue('returning', agreed, false)).toBe(true)
    expect(hintFor('returning', { ...agreed, transfer: false }, false)).toBe('transfer')
    expect(canContinue('returning', { ...initialDraft(read()), terms: true, privacy: true }, false)).toBe(true)
  })
})

describe('"Help build the stats" on the consent screen', () => {
  const stored = (yes: boolean) => ({ yes, policyVersion: VERSION, answeredAt: '2026-10-05T12:00:00Z', ageConfirmed: true })

  it('shows on a first sign-in unless the stored answer is yes, and never for a returning user', () => {
    expect(showContribute('first', null)).toBe(true)
    expect(showContribute('first', stored(false))).toBe(true)
    expect(showContribute('first', stored(true))).toBe(false)
    expect(showContribute('returning', null)).toBe(false)
    expect(showContribute('returning', stored(false))).toBe(false)
  })

  it('names the date only for a stored no', () => {
    expect(storedNo('first', stored(false))?.answeredAt).toBe('2026-10-05T12:00:00Z')
    expect(storedNo('first', null)).toBeNull()
    expect(storedNo('first', stored(true))).toBeNull()
  })

  it('sends the age box with the answer, and nothing when the block was not shown', () => {
    expect(contribAnswer(answered({ contribute: true }), true, VERSION)).toEqual({
      yes: true,
      policyVersion: VERSION,
      ageConfirmed: true,
    })
    expect(contribAnswer(answered({ contribute: false }), true, VERSION)?.yes).toBe(false)
    expect(contribAnswer(answered({ contribute: true }), false, VERSION)).toBeNull()
    expect(contribAnswer(answered({ contribute: null }), true, VERSION)).toBeNull()
  })
})

describe('when the shell layout sends the user to the consent screen', () => {
  const settings = (account: AccountState): AppSettings => ({ account }) as AppSettings
  const signedIn = (profile?: ProfileState): AccountState => ({
    available: true,
    signedIn: true,
    userId: 'u',
    email: null,
    provider: null,
    persistence: { kept: true },
    ...(profile ? { profile } : {}),
  })

  it('does for no profile, and for answers under another version', () => {
    expect(needsConsent(settings(signedIn({ state: 'none' })), VERSION)).toBe(true)
    expect(needsConsent(settings(signedIn(read({ consentVersion: '2026-01-01' }))), VERSION)).toBe(true)
  })

  it('re-asks only for an older version, never a newer one, and a missing version is older', () => {
    expect(needsConsent(settings(signedIn(read({ consentVersion: '2026-11-04' }))), VERSION)).toBe(false)
    expect(needsConsent(settings(signedIn(read({ consentVersion: '2026-11-02' }))), VERSION)).toBe(true)
    expect(needsConsent(settings(signedIn(read({ consentVersion: null as unknown as string }))), VERSION)).toBe(true)
  })

  it('does not for the current version, an unreadable profile, or none yet read', () => {
    expect(needsConsent(settings(signedIn(read())), VERSION)).toBe(false)
    expect(needsConsent(settings(signedIn({ state: 'unknown' })), VERSION)).toBe(false)
    expect(needsConsent(settings(signedIn()), VERSION)).toBe(false)
  })

  it('does not when signed out, without an account in the build, or outside the shell', () => {
    const out: AccountState = { ...signedIn({ state: 'none' }), signedIn: false } as AccountState
    expect(needsConsent(settings(out), VERSION)).toBe(false)
    expect(needsConsent(settings({ available: false }), VERSION)).toBe(false)
    expect(needsConsent(null, VERSION)).toBe(false)
    expect(needsConsent(undefined, VERSION)).toBe(false)
  })
})

describe('the way back from the consent screen', () => {
  it('returns to the setup step a sign-in on the welcome interrupted', () => {
    expect(afterConsent(consentState('/welcome', '?step=start'))).toBe('/welcome?step=start')
    expect(afterConsent(consentState('/welcome', ''))).toBe('/welcome')
  })

  it('goes Home from any other page, and for any other state', () => {
    expect(consentState('/matches', '?page=2')).toBeUndefined()
    expect(afterConsent(consentState('/matches', ''))).toBe('/')
    expect(afterConsent(null)).toBe('/')
    expect(afterConsent({ back: 'https://example.com/' })).toBe('/')
    expect(afterConsent({ back: '/welcomeback' })).toBe('/')
    expect(afterConsent({ back: 7 })).toBe('/')
  })
})

describe('the policy link', () => {
  it('points at the site page in the language, and reads the version as a local date', () => {
    expect(privacyUrl('pt-BR')).toBe('https://senseitop.com/pt-br/privacy/')
    expect(privacyUrl('en')).toBe('https://senseitop.com/privacy/')
    const date = policyDate('2026-11-03')
    expect([date?.getFullYear(), date?.getMonth(), date?.getDate()]).toEqual([2026, 10, 3])
    expect(policyDate('November')).toBeNull()
  })
})

describe('what the screen opens with', () => {
  it('is fixed from the profile: first for none, returning for read, nothing for any other', () => {
    expect(opening({ state: 'none' }, null)?.kind).toBe('first')
    expect(opening({ state: 'none' }, null)?.contributeShown).toBe(true)
    expect(opening(read(), null)).toMatchObject({ kind: 'returning', contributeShown: false })
    expect(opening({ state: 'unknown' }, null)).toBeNull()
    expect(opening(undefined, null)).toBeNull()
  })

  it('shows the first intro, the changes sentence, or no paragraph when none was written', () => {
    expect(introLines('first', false)).toBe('intro')
    expect(introLines('returning', true)).toBe('changed')
    expect(introLines('returning', false)).toBeNull()
  })
})

describe('the steps of the consent screen', () => {
  it('asks the age first and the stats last on a first sign-in, only the account questions on a return', () => {
    expect(stepsOf('first', true)).toEqual(['age', 'keep', 'errors', 'contribute'])
    expect(stepsOf('first', false)).toEqual(['age', 'keep', 'errors'])
    expect(stepsOf('returning', true)).toEqual(['agree', 'keep', 'errors'])
  })

  it('holds each step until it is answered', () => {
    const empty = initialDraft({ state: 'none' })
    expect(stepHint('age', empty)).toBe('age')
    expect(stepHint('age', { ...empty, age: true })).toBe('agree')
    expect(stepHint('age', { ...empty, age: true, terms: true, privacy: true })).toBeNull()
    for (const step of ['errors', 'contribute'] as const) {
      expect(stepHint(step, empty)).toBe('answer')
      expect(stepHint(step, { ...empty, [step]: false })).toBeNull()
    }
  })

  it('holds the keep step until both of its questions are answered', () => {
    const empty = initialDraft({ state: 'none' })
    expect(stepHint('keep', empty)).toBe('answers')
    expect(stepHint('keep', { ...empty, sync: true })).toBe('answers')
    expect(stepHint('keep', { ...empty, coach: false })).toBe('answers')
    expect(stepHint('keep', { ...empty, sync: true, coach: false })).toBeNull()
  })

  it('holds the error-reports step while Send stands without the transfer box', () => {
    const empty = initialDraft({ state: 'none' })
    expect(stepHint('errors', withErrors(empty, true))).toBe('transfer')
    expect(stepHint('errors', { ...withErrors(empty, true), transfer: true })).toBeNull()
  })

  it('lets a returning user through every step as the answers stand', () => {
    const draft = { ...initialDraft(read({ consentErrors: true })), terms: true, privacy: true }
    for (const step of stepsOf('returning', false)) expect(stepHint(step, draft)).toBeNull()
  })
})

describe('the agreement step', () => {
  it('starts both boxes unticked, for a first sign-in and for a return whatever was agreed before', () => {
    for (const profile of [{ state: 'none' } as ProfileState, read({ consentErrors: true })]) {
      const draft = initialDraft(profile)
      expect([draft.terms, draft.privacy]).toEqual([false, false])
    }
  })

  it('is the returning user\'s first step, and the first sign-in\'s age step holds the boxes', () => {
    expect(stepsOf('returning', false)[0]).toBe('agree')
    expect(stepsOf('first', false)[0]).toBe('age')
  })

  it('keeps Continue off until both boxes are ticked, whatever else is answered', () => {
    for (const kind of ['first', 'returning'] as const) {
      expect(canContinue(kind, answered({ terms: false }), false)).toBe(false)
      expect(canContinue(kind, answered({ privacy: false }), false)).toBe(false)
      expect(hintFor(kind, answered({ terms: false }), false)).toBe('agree')
      expect(canContinue(kind, answered(), false)).toBe(true)
    }
    const returning = initialDraft(read())
    expect(stepHint('agree', returning)).toBe('agree')
    expect(stepHint('agree', { ...returning, terms: true })).toBe('agree')
    expect(stepHint('agree', { ...returning, terms: true, privacy: true })).toBeNull()
  })

  it('records the agreement in the profile write only with both boxes ticked', () => {
    expect(profileChange('returning', answered(), VERSION).termsAgreed).toBe(true)
    expect(profileChange('returning', answered({ terms: false }), VERSION).termsAgreed).toBe(false)
  })

  it('points the terms page at the site in the language', () => {
    expect(termsUrl('pt-BR')).toBe('https://senseitop.com/pt-br/terms/')
    expect(termsUrl('en')).toBe('https://senseitop.com/terms/')
    expect(termsUrl(undefined)).toBe('https://senseitop.com/terms/')
  })
})
