import { describe, expect, it, vi } from 'vitest'
import type { AccountState, ProfileState, ReportOutcome } from '../bridge'
import { POLICY_VERSION } from './policy'
import {
  aboutOf,
  blockerOf,
  COUNTER_FROM,
  outcomeKey,
  REPORT_LIMIT,
  sendControls,
  sendReport,
  signedInOf,
  standingConsentOf,
  detailOf,
  matchIdOf,
  pageOf,
  reportText,
  wasSent,
  type ReportDraft,
} from './reportProblem'

const draft = (change: Partial<ReportDraft> = {}): ReportDraft => ({ text: 'It broke', attachLog: false, agreed: true, ...change })

const BUG = { kind: 'bug', page: null, matchId: null } as const

describe('what keeps Send report disabled', () => {
  it('names the first that applies, in the order of the hints', () => {
    expect(blockerOf({ text: '  \n', agreed: false })).toBe('noText')
    expect(blockerOf({ text: 'x'.repeat(REPORT_LIMIT + 1), agreed: false })).toBe('tooLong')
    expect(blockerOf({ text: 'It broke', agreed: false })).toBe('notAgreed')
    expect(blockerOf({ text: 'It broke', agreed: true })).toBeNull()
  })

  it('allows exactly the limit', () => {
    expect(blockerOf({ text: 'x'.repeat(REPORT_LIMIT), agreed: true })).toBeNull()
    expect(COUNTER_FROM).toBeLessThan(REPORT_LIMIT)
  })
})

describe('the technical detail of a dialog opened from an error', () => {
  it('is the message as one line', () => {
    expect(detailOf('Boom\n  at x')).toBe('Boom at x')
  })
  it('is empty with no message', () => {
    expect(detailOf(null)).toBe('')
    expect(detailOf('  ')).toBe('')
  })
  it('cuts a very long message', () => {
    expect(detailOf('a'.repeat(5000)).length).toBe(500)
  })
  it('is sent under the text after a blank line, never in its place', () => {
    expect(reportText('  It broke \n', 'Technical detail: Boom')).toBe('It broke\n\nTechnical detail: Boom')
    expect(reportText('It broke', '')).toBe('It broke')
    expect(reportText('It broke', undefined)).toBe('It broke')
  })
  it('is left out when the two would pass the limit together', () => {
    const long = 'x'.repeat(REPORT_LIMIT - 5)
    expect(reportText(long, 'Technical detail: Boom')).toBe(long)
  })
})

describe('sending a report', () => {
  it('sends the detail under the text', async () => {
    const call = vi.fn(async (): Promise<ReportOutcome> => 'sent')
    await sendReport(call, draft({ detail: 'Technical detail: Boom' }))
    expect(call).toHaveBeenCalledExactlyOnceWith({ text: 'It broke\n\nTechnical detail: Boom', attachLog: false, ...BUG })
  })

  it('sends the trimmed text and the log choice through the bridge call', async () => {
    const call = vi.fn(async (): Promise<ReportOutcome> => 'sent')
    expect(await sendReport(call, draft({ text: '  It broke \n', attachLog: true }))).toBe('sent')
    expect(call).toHaveBeenCalledExactlyOnceWith({ text: 'It broke', attachLog: true, ...BUG })
  })

  it('calls nothing for a draft the dialog would have blocked', async () => {
    const call = vi.fn(async (): Promise<ReportOutcome> => 'sent')
    expect(await sendReport(call, draft({ agreed: false }))).toBe('invalid')
    expect(await sendReport(call, draft({ text: '' }))).toBe('invalid')
    expect(call).not.toHaveBeenCalled()
  })

  it('reads a call that throws, or a word it does not know, as failed', async () => {
    expect(await sendReport(async () => { throw new Error('gone') }, draft())).toBe('failed')
    expect(await sendReport((async () => 'weird') as never, draft())).toBe('failed')
  })

  it('passes each outcome the shell names', async () => {
    for (const outcome of ['sent', 'sent-without-log', 'unavailable', 'invalid', 'failed'] as const) {
      expect(await sendReport(async () => outcome, draft())).toBe(outcome)
    }
  })

  it('is unavailable with no shell call', async () => {
    expect(await sendReport(undefined, draft())).toBe('unavailable')
  })
})

describe('the payload per kind', () => {
  it('carries the page and the match of a bug', async () => {
    const call = vi.fn(async (): Promise<ReportOutcome> => 'sent')
    await sendReport(call, draft({ attachLog: true, detail: 'Technical detail: Boom', kind: 'bug', page: '/matches/m1', matchId: 'm1' }))
    expect(call).toHaveBeenCalledExactlyOnceWith({
      text: 'It broke\n\nTechnical detail: Boom',
      attachLog: true,
      kind: 'bug',
      page: '/matches/m1',
      matchId: 'm1',
    })
  })
  it('never sends the log or the detail of an idea, whatever the draft holds', async () => {
    const call = vi.fn(async (): Promise<ReportOutcome> => 'sent')
    await sendReport(call, draft({ attachLog: true, detail: 'Technical detail: Boom', kind: 'idea', page: '/decks', matchId: null }))
    expect(call).toHaveBeenCalledExactlyOnceWith({ text: 'It broke', attachLog: false, kind: 'idea', page: '/decks', matchId: null })
  })
  it('takes the page only as a path the shell accepts', () => {
    expect(pageOf('/matches/m1')).toBe('/matches/m1')
    expect(pageOf('/decks?x=1')).toBeNull()
    expect(pageOf('/decks#a')).toBeNull()
    expect(pageOf('decks')).toBeNull()
    expect(pageOf(undefined)).toBeNull()
  })
  it('takes the match only on a match page', () => {
    expect(matchIdOf({ id: 'm1' }, '/matches/m1')).toBe('m1')
    expect(matchIdOf({ id: 'm1' }, '/matches/m1/replay')).toBe('m1')
    expect(matchIdOf({ id: 'd1' }, '/decks/d1')).toBeNull()
    expect(matchIdOf(undefined, '/matches')).toBeNull()
  })
})

describe('the outcomes', () => {
  it('replace the form only when the report went', () => {
    expect(wasSent('sent')).toBe(true)
    expect(wasSent('sent-without-log')).toBe(true)
    for (const outcome of ['unavailable', 'invalid', 'failed'] as const) expect(wasSent(outcome)).toBe(false)
  })
  it('each have a catalogue line', () => {
    expect(outcomeKey('sent-without-log')).toBe('report.dialog.result.sentWithoutLog')
    expect(outcomeKey('failed')).toBe('report.dialog.result.failed')
    expect(outcomeKey('sent', 'idea')).toBe('report.dialog.result.sentIdea')
    expect(outcomeKey('failed', 'idea')).toBe('report.dialog.result.failed')
  })
})

describe('whether the report carries an account ID', () => {
  it('only when the account is available and signed in', () => {
    expect(signedInOf(undefined)).toBe(false)
    expect(signedInOf({ available: false })).toBe(false)
    expect(signedInOf({ available: true, signedIn: false, userId: null, email: null, provider: null, persistence: { kept: true } })).toBe(false)
    expect(signedInOf({ available: true, signedIn: true, userId: 'u', email: null, provider: null, persistence: { kept: true } })).toBe(true)
  })
})

describe('the Send button', () => {
  function run(outcome: ReportOutcome | 'throws', dismissWhileSending: boolean) {
    const log: string[] = []
    const dismissed = { current: false }
    let busy = false
    let shown: ReportOutcome | null = 'failed'
    const seen: boolean[] = []
    const reopen = vi.fn()
    const { send } = sendControls({
      call: async () => {
        seen.push(busy, shown === null)
        if (dismissWhileSending) dismissed.current = true
        if (outcome === 'throws') throw new Error('gone')
        return outcome
      },
      draft: () => draft(),
      dismissed,
      setBusy: (b) => {
        busy = b
        log.push(`busy:${b}`)
      },
      setOutcome: (o) => {
        shown = o
      },
      reopen,
    })
    return { send, reopen, log, seen, shown: () => shown, busy: () => busy }
  }

  it('is busy during the send, with the previous outcome cleared, and idle after', async () => {
    const r = run('sent', false)
    await r.send()
    expect(r.seen).toEqual([true, true])
    expect(r.busy()).toBe(false)
    expect(r.shown()).toBe('sent')
  })

  it('reopens a dismissed dialog after a failed send', async () => {
    const r = run('failed', true)
    await r.send()
    expect(r.reopen).toHaveBeenCalledTimes(1)
    const t = run('throws', true)
    await t.send()
    expect(t.reopen).toHaveBeenCalledTimes(1)
    expect(t.shown()).toBe('failed')
  })

  it('does not reopen after a failure the dialog was still open for, or after a success', async () => {
    const open = run('failed', false)
    await open.send()
    expect(open.reopen).not.toHaveBeenCalled()
    for (const dismissedToo of [true, false]) {
      const r = run('sent-without-log', dismissedToo)
      await r.send()
      expect(r.reopen).not.toHaveBeenCalled()
    }
  })
})

describe('whether a standing consent replaces the box', () => {
  const read = (change: Partial<Extract<ProfileState, { state: 'read' }>> = {}): ProfileState => ({
    state: 'read',
    ageConfirmedAt: '2026-01-01',
    consentSync: false,
    consentErrors: true,
    consentCoachHistory: false,
    consentVersion: POLICY_VERSION,
    consentedAt: '2026-01-01',
    ...change,
  })
  const account = (profile: ProfileState | undefined, signedIn = true): AccountState => ({
    available: true,
    signedIn,
    userId: signedIn ? 'u' : null,
    email: null,
    provider: null,
    persistence: { kept: true },
    ...(profile ? { profile } : {}),
  }) as AccountState

  it('holds signed in, with error reports on under the current policy', () => {
    expect(standingConsentOf(account(read()))).toBe(true)
  })
  it('holds under a later policy version', () => {
    expect(standingConsentOf(account(read({ consentVersion: '2099-01-01' })))).toBe(true)
  })
  it('does not hold under an older policy version', () => {
    expect(standingConsentOf(account(read({ consentVersion: '2026-11-04' })))).toBe(false)
  })
  it('does not hold with error reports off', () => {
    expect(standingConsentOf(account(read({ consentErrors: false })))).toBe(false)
  })
  it('does not hold when the profile is unknown, unanswered or missing', () => {
    expect(standingConsentOf(account({ state: 'unknown' }))).toBe(false)
    expect(standingConsentOf(account({ state: 'none' }))).toBe(false)
    expect(standingConsentOf(account(undefined))).toBe(false)
  })
  it('does not hold signed out, in a build with no account, or with no shell', () => {
    expect(standingConsentOf(account(read(), false))).toBe(false)
    expect(standingConsentOf({ available: false })).toBe(false)
    expect(standingConsentOf(undefined)).toBe(false)
  })
})

describe('aboutOf', () => {
  const now = Date.parse('2026-11-07T12:00:00')
  it('names the match by date, deck and opponent when it has all three', () => {
    const about = aboutOf({ started_at: '2026-11-02T20:00:00', deck_name: 'Deck A', opponent_label: 'Opp B' }, now)
    expect(about?.key).toBe('report.dialog.about.match')
    expect(about?.values).toMatchObject({ deck: 'Deck A', opponent: 'Opp B' })
    expect(about?.values.date).toBe('Nov 2')
  })
  it('falls back to the date when the deck or the opponent is null', () => {
    expect(aboutOf({ started_at: '2026-11-02T20:00:00', deck_name: null, opponent_label: 'Opp B' }, now)?.key).toBe(
      'report.dialog.about.matchDate',
    )
    expect(aboutOf({ started_at: '2026-11-02T20:00:00', deck_name: 'Deck A', opponent_label: null }, now)?.key).toBe(
      'report.dialog.about.matchDate',
    )
  })
  it('names nothing without a start time', () => {
    expect(aboutOf({ started_at: null, deck_name: 'Deck A', opponent_label: 'Opp B' }, now)).toBeNull()
  })
})
