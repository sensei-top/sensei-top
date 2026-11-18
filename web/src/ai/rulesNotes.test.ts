import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AccountState, CoachResult, Shell } from '../bridge'
import { POLICY_VERSION } from '../lib/policy'
import { askRulesNotes, notesMissing, pressThenAct, type NotesOutcome, type RulesRequest } from './rulesNotes'

const REQUEST: RulesRequest = { feature: 'match', match_id: 'm1', expected: [] }

const account = (profile: Record<string, unknown> = {}): AccountState =>
  ({
    available: true,
    signedIn: true,
    profile: { state: 'read', consentVersion: POLICY_VERSION, rulesNotes: true, ...profile },
  }) as unknown as AccountState

const answer = (question: string, extra: Record<string, unknown> = {}): CoachResult =>
  ({
    question,
    ok: true,
    outcome: 'answered',
    verdict: 'Yes.',
    explanation: 'Because.',
    citations: [],
    confidence: 'high',
    out_of_scope: false,
    rules_version: '2026-11-01',
    ...extra,
  }) as CoachResult

function setup(questions: { question: string; answered: boolean }[], results: CoachResult[]) {
  const ask = vi.fn(async (_q: string[]) => results)
  const shell = { coach: { ask } } as unknown as Shell
  const calls: { method: string; path: string; body: unknown }[] = []
  vi.stubGlobal('window', { location: { origin: 'http://127.0.0.1:8000' } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: URL, init: { method: string; body: string }) => {
      calls.push({ method: init.method, path: url.pathname, body: JSON.parse(init.body) })
      const body = url.pathname === '/api/rules-questions' ? { questions } : { question_hashes: [] }
      return { ok: true, status: 200, json: async () => body }
    }),
  )
  return { ask, shell, calls }
}

afterEach(() => vi.unstubAllGlobals())

describe('the gate', () => {
  it.each([
    ['no shell', null, account(), 'unavailable'],
    ['no coach in the shell', {} as Shell, account(), 'unavailable'],
    ['signed out', { coach: { ask: vi.fn() } } as unknown as Shell, { available: true, signedIn: false } as AccountState, 'signedOut'],
    ['no account in the build', { coach: { ask: vi.fn() } } as unknown as Shell, { available: false }, 'signedOut'],
    ['consent older than the policy', { coach: { ask: vi.fn() } } as unknown as Shell, account({ consentVersion: '2026-11-07' }), 'consent'],
    ['notes off', { coach: { ask: vi.fn() } } as unknown as Shell, account({ rulesNotes: false }), 'notesOff'],
  ])('skips, asking nothing: %s', async (_name, shell, acc, reason) => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const outcome = await askRulesNotes(REQUEST, shell, acc)
    expect(outcome).toEqual({ stored: 0, reason, gated: true })
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(notesMissing(outcome)).toBe(false)
  })

  it('reads an absent rulesNotes field as on', async () => {
    const acc = account()
    delete (acc as { profile: Record<string, unknown> }).profile.rulesNotes
    const { shell } = setup([], [])
    expect((await askRulesNotes(REQUEST, shell, acc)).reason).toBeNull()
  })
})

describe('the press', () => {
  it('asks only the unanswered questions and stores only answered or refused', async () => {
    const { ask, shell, calls } = setup(
      [
        { question: 'Q1', answered: true },
        { question: 'Q2', answered: false },
        { question: 'Q3', answered: false },
        { question: 'Q4', answered: false },
      ],
      [answer('Q2'), answer('Q3', { outcome: 'refused', verdict: null }), answer('Q4', { outcome: 'try_again', rules_version: null })],
    )
    const outcome = await askRulesNotes(REQUEST, shell, account())
    expect(ask).toHaveBeenCalledWith(['Q2', 'Q3', 'Q4'])
    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.path).toBe('/api/rules-notes')
    expect((put.body as { notes: { question: string }[] }).notes.map((n) => n.question)).toEqual(['Q2', 'Q3'])
    expect(outcome.stored).toBe(2)
    expect(notesMissing(outcome)).toBe(true)
  })

  it('stores nothing and does not ask when every question is answered', async () => {
    const { ask, shell, calls } = setup([{ question: 'Q1', answered: true }], [])
    expect(await askRulesNotes(REQUEST, shell, account())).toEqual({ stored: 0, reason: null, gated: false })
    expect(ask).not.toHaveBeenCalled()
    expect(calls.map((c) => c.method)).toEqual(['POST'])
  })

  it('reports a coach refusal as missing, writing nothing', async () => {
    const { shell, calls } = setup([{ question: 'Q1', answered: false }], [{ question: 'Q1', ok: false, reason: 'limit' }])
    const outcome = await askRulesNotes(REQUEST, shell, account())
    expect(outcome).toEqual({ stored: 0, reason: 'limit', gated: false })
    expect(notesMissing(outcome)).toBe(true)
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
  })

  it('never throws: a failing API is a reason, so the generate can still run', async () => {
    const shell = { coach: { ask: vi.fn() } } as unknown as Shell
    vi.stubGlobal('window', { location: { origin: 'http://127.0.0.1:8000' } })
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('down') }))
    vi.spyOn(console, 'debug').mockImplementation(() => {})
    const outcome = await askRulesNotes(REQUEST, shell, account())
    expect(outcome).toEqual({ stored: 0, reason: 'failed', gated: false })
    expect(notesMissing(outcome)).toBe(true)
  })
})

describe('a coach reason is never the gate', () => {
  it('shows the missing line for signedOut or unavailable from the coach', async () => {
    for (const reason of ['signedOut', 'unavailable'] as const) {
      const { shell } = setup([{ question: 'Q1', answered: false }], [{ question: 'Q1', ok: false, reason }])
      const outcome = await askRulesNotes(REQUEST, shell, account())
      expect(outcome).toEqual({ stored: 0, reason, gated: false })
      expect(notesMissing(outcome)).toBe(true)
    }
  })
})

describe('pressThenAct', () => {
  it('runs the action and flags missing when the press rejects', async () => {
    const act = vi.fn()
    const missing = await pressThenAct(async () => { throw new Error('x') }, notesMissing, act)
    expect(act).toHaveBeenCalledWith(null)
    expect(missing).toBe(true)
  })

  it('runs the action and flags missing when the press returns failed', async () => {
    const act = vi.fn()
    const failed: NotesOutcome = { stored: 0, reason: 'failed', gated: false }
    expect(await pressThenAct(async () => failed, notesMissing, act)).toBe(true)
    expect(act).toHaveBeenCalledWith(failed)
  })

  it('runs the action with no line when there is no press or the gate skipped', async () => {
    const act = vi.fn()
    expect(await pressThenAct(undefined, notesMissing, act)).toBe(false)
    const gated: NotesOutcome = { stored: 0, reason: 'signedOut', gated: true }
    expect(await pressThenAct(async () => gated, notesMissing, act)).toBe(false)
    expect(act).toHaveBeenCalledTimes(2)
  })
})
