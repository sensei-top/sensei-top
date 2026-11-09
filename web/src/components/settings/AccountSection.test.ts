import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import type { AccountActions, AccountReply, ProfileState, SyncStatus } from '../../bridge'
import '../../i18n'
import { POLICY_VERSION } from '../../lib/policy'
import { deleteControls, attemptGuard, errorsChange, errorsControls, exportLine, historyFailure, profileGate, switchChange, syncLine } from './accountLogic'
import { AccountSection } from './AccountSection'

const read = (over: Partial<Extract<ProfileState, { state: 'read' }>> = {}): Extract<ProfileState, { state: 'read' }> => ({
  state: 'read',
  ageConfirmedAt: '2026-10-01T00:00:00Z',
  consentSync: true,
  consentErrors: false,
  consentCoachHistory: false,
  consentVersion: POLICY_VERSION,
  consentedAt: '2026-10-01T00:00:00Z',
  ...over,
})

const ok: AccountReply = { ok: true, deleted: 3 }

describe('the delete dialogs', () => {
  for (const kind of ['history', 'account'] as const) {
    it(`${kind}: nothing is called until the confirm button`, async () => {
      const call = vi.fn(async () => ok)
      const close = vi.fn()
      const settled = vi.fn()
      const controls = deleteControls({ kind, call, profileNow: () => read(), close, settled })
      expect(call).not.toHaveBeenCalled()
      await controls.confirm()
      expect(call).toHaveBeenCalledTimes(1)
      expect(settled).toHaveBeenCalledWith({ ok: true, deleted: 3 })
    })

    it(`${kind}: Cancel calls nothing but close`, () => {
      const call = vi.fn(async () => ok)
      const close = vi.fn()
      const settled = vi.fn()
      deleteControls({ kind, call, profileNow: () => read(), close, settled }).cancel()
      expect(close).toHaveBeenCalledTimes(1)
      expect(call).not.toHaveBeenCalled()
      expect(settled).not.toHaveBeenCalled()
    })
  }

  it('a refused or thrown delete is a failure, and the history one reads the profile after the reply', async () => {
    let profile: ProfileState = read({ consentSync: true })
    const refused = async (): Promise<AccountReply> => {
      profile = read({ consentSync: false })
      return { ok: false, error: 'failed' }
    }
    const history = await deleteControls({ kind: 'history', call: refused, profileNow: () => profile, close() {}, settled() {} }).confirm()
    expect(history).toBeUndefined()
    const seen: unknown[] = []
    await deleteControls({ kind: 'history', call: refused, profileNow: () => profile, close() {}, settled: (o) => seen.push(o) }).confirm()
    expect(seen).toEqual([{ ok: false, failure: 'historyOff' }])
    await deleteControls({
      kind: 'account',
      call: async () => {
        throw new Error('gone')
      },
      profileNow: () => profile,
      close() {},
      settled: (o) => seen.push(o),
    }).confirm()
    expect(seen[1]).toEqual({ ok: false, failure: 'account' })
  })

  it('tells the two history failures apart by the backup switch', () => {
    expect(historyFailure(read({ consentSync: true }))).toBe('historyOn')
    expect(historyFailure(read({ consentSync: false }))).toBe('historyOff')
    expect(historyFailure({ state: 'unknown' })).toBe('historyOn')
    expect(historyFailure(undefined)).toBe('historyOn')
  })
})

describe('the error-reports transfer dialog', () => {
  it('cannot write consent_errors: true without the agreement', () => {
    expect(errorsChange(read(), true, false)).toBeNull()
    expect(errorsChange(read(), true, true)?.consentErrors).toBe(true)
    expect(errorsChange(read({ consentErrors: true }), false, false)?.consentErrors).toBe(false)
  })

  it('writes only on confirm, and Cancel writes nothing', async () => {
    const save = vi.fn(async () => ({ ok: true as const }))
    const close = vi.fn()
    const settled = vi.fn()
    const controls = errorsControls({ profile: read(), save, close, settled })
    expect(save).not.toHaveBeenCalled()
    controls.cancel()
    expect(save).not.toHaveBeenCalled()
    await controls.confirm()
    expect(settled).toHaveBeenCalledWith({ ok: true })
    expect(save).toHaveBeenCalledTimes(1)
    expect(save.mock.calls[0]).toEqual([
      { consentSync: true, consentErrors: true, consentCoachHistory: false, policyVersion: POLICY_VERSION },
    ])
  })

  it('the other switches leave the transfer consent as it is and never write an older version', () => {
    const change = switchChange(read({ consentErrors: true, consentVersion: '2099-01-01' }), 'consentSync', false)
    expect(change).toEqual({
      consentSync: false,
      consentErrors: true,
      consentCoachHistory: false,
      policyVersion: '2099-01-01',
    })
  })
})

describe('one write at a time', () => {
  it('refuses a second profile write while one is in flight', async () => {
    const gate = profileGate()
    let release: () => void = () => {}
    const first = gate.run(() => new Promise<string>((done) => (release = () => done('first'))))
    const refused = await gate.run(async () => 'second')
    expect(refused).toBeNull()
    release()
    expect(await first).toBe('first')
    expect(await gate.run(async () => 'third')).toBe('third')
  })

  it('frees the gate after a write that throws', async () => {
    const gate = profileGate()
    await expect(gate.run(async () => Promise.reject(new Error('x')))).rejects.toThrow()
    expect(await gate.run(async () => 1)).toBe(1)
  })
})

describe('a sign-in pressed again', () => {
  it('ignores the superseded attempt', () => {
    const guard = attemptGuard()
    const first = guard.begin()
    expect(first()).toBe(true)
    const second = guard.begin()
    expect(first()).toBe(false)
    expect(second()).toBe(true)
  })
})

describe('what the section says', () => {
  const sync = (over: Partial<SyncStatus> = {}): SyncStatus => ({ running: false, lastSyncAt: null, backedUp: 0, lastError: null, ...over })

  it('picks the sync line', () => {
    expect(syncLine(false, sync({ running: true }))?.key).toBe('account.settings.sync.off')
    expect(syncLine(true, sync({ running: true }))?.key).toBe('account.settings.sync.running')
    expect(syncLine(true, sync({ lastError: 'cloud' }))?.key).toBe('account.settings.sync.error.cloud')
    expect(syncLine(true, sync())?.key).toBe('account.settings.sync.none')
    expect(syncLine(true, sync({ backedUp: 4, lastSyncAt: '2026-11-01T00:00:00Z' }))).toMatchObject({ count: 4, when: true })
    expect(syncLine(true, undefined)).toBeNull()
  })

  it('reads the export reply', () => {
    expect(exportLine({ ok: true })).toBe('saved')
    expect(exportLine({ ok: true, cancelled: true })).toBeNull()
    expect(exportLine({ ok: false, error: 'failed' })).toBe('failed')
    expect(exportLine(null)).toBe('failed')
  })

  const actions = {} as AccountActions
  const draw = (state: Parameters<typeof AccountSection>[0]['state']) =>
    renderToStaticMarkup(createElement(MemoryRouter, null, createElement(AccountSection, { state, actions })))

  it('draws no account, signed out, and signed in', () => {
    expect(draw({ available: false })).toContain('This version of Sensei Top has no account.')
    const out = draw({ available: true, signedIn: false, userId: null, email: null, provider: null, persistence: { kept: true } })
    expect(out).toContain('Sign in with Google')
    expect(out).toContain('Sign in with Discord')
    const inn = draw({
      available: true,
      signedIn: true,
      userId: 'u',
      email: 'a@example.com',
      provider: 'google',
      persistence: { kept: false, reason: 'noKeyring' },
      profile: read(),
      sync: sync(),
    })
    expect(inn).toContain('Signed in as a@example.com, with Google.')
    expect(inn).not.toContain('Back up my match history')
    expect(inn).toContain('This system has no keyring')
    expect(inn).toContain('Delete cloud history')
  })
})
