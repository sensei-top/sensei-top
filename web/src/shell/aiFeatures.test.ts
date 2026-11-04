import { createElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAi } from '../ai/registry'
import type { BridgeSettings, RawShell } from '../bridge'
import { AiFeaturesContext, useAiFeatures } from './aiFeatures'

let captured: ((on: boolean) => Promise<unknown>) | null = null

function SetterProbe() {
  captured = useAiFeatures()[1]
  return createElement('span')
}

function Probe() {
  const [on, , undecided] = useAiFeatures()
  return createElement('span', null, `${on}/${undecided}`)
}

function AiProbe() {
  return createElement('span', null, useAi() === null ? 'null' : 'registry')
}

function draw(node: () => ReactNode, override?: boolean): string {
  const el = createElement(node as () => ReactNode)
  return renderToStaticMarkup(createElement(AiFeaturesContext.Provider, { value: override }, el))
}

function shellWith(
  aiFeatures: boolean | null,
  set: (change: unknown) => Promise<{ ok: true }> = () => Promise.resolve({ ok: true } as const),
  onChange: RawShell['onChange'] = () => () => {},
): RawShell {
  const never = () => Promise.resolve({ ok: true } as const)
  return {
    initial: {
      sources: {
        arenaLog: { path: null, found: false, detailedLogs: 'unknown' },
        dateOrder: 'auto',
        mtgoHandle: null,
        mtgoDir: null,
        mtgoDeckDir: null,
        mtgoFound: null,
        dataDir: '/d',
      },
      writing: { claudeKey: false, topdeckKey: false, model: 'm', models: [] },
      backup: { dir: '/b', keep: 7, last: null, inFolder: 0 },
      app: {
        startWithSystem: false,
        keepRunningOnClose: false,
        checkForUpdates: true,
        diagnostic: false,
        update: { state: 'idle' },
        onboarded: true,
        aiFeatures,
        account: { available: false },
        askAutostart: false,
        canAutostart: true,
        windowsStore: false,
        rulesText: null,
        firstData: { state: 'idle' },
        version: '1',
        platform: 'linux',
      },
    },
    save: never,
    setKey: never,
    pickFolder: () => Promise.resolve(null),
    pickFile: () => Promise.resolve(null),
    backUpNow: never,
    restoreFrom: never,
    account: {
      status: () => Promise.resolve({ available: false } as const),
      signIn: () => Promise.resolve({ ok: false, error: 'auth.error.failed', message: '' } as const),
      signOut: never,
    },
    app: {
      set,
      checkForUpdates: never,
      restartToUpdate: never,
      showLogs: never,
      exportDiagnostics: never,
      showDataFolder: never,
      recheck: never,
      firstData: never,
      finishOnboarding: never,
    },
    onChange,
  }
}

function stubStorage(value: string | null) {
  vi.stubGlobal('localStorage', { getItem: () => value, setItem: () => {} })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the setter and live updates', () => {
  it('asks the shell to save when one is present', async () => {
    const set = vi.fn(() => Promise.resolve({ ok: true } as const))
    vi.stubGlobal('senseiTopShell', shellWith(true, set))
    draw(SetterProbe)
    await captured?.(false)
    expect(set).toHaveBeenCalledWith({ aiFeatures: false })
  })

  it('writes storage with no shell', async () => {
    const setItem = vi.fn()
    vi.stubGlobal('senseiTopShell', undefined)
    vi.stubGlobal('localStorage', { getItem: () => null, setItem })
    vi.stubGlobal('window', { dispatchEvent: () => true })
    draw(SetterProbe)
    const saved = await captured?.(false)
    expect(setItem).toHaveBeenCalledWith('sensei-top:ai-features', 'off')
    expect(saved).toEqual({ ok: true })
  })

  it('follows the shell\'s change event', () => {
    const held: { listener?: (s: BridgeSettings) => void } = {}
    const raw = shellWith(true, undefined, (l) => {
      held.listener = l
      return () => {}
    })
    vi.stubGlobal('senseiTopShell', raw)
    expect(draw(Probe)).toContain('true/false')
    const next = structuredClone(raw.initial as BridgeSettings)
    next.app.aiFeatures = false
    held.listener?.(next)
    expect(draw(Probe)).toContain('false/false')
  })
})

describe('useAiFeatures order', () => {
  it('context true or false wins over shell and storage', () => {
    vi.stubGlobal('senseiTopShell', shellWith(false))
    stubStorage('off')
    expect(draw(Probe, true)).toContain('true/false')
    vi.stubGlobal('senseiTopShell', shellWith(true))
    stubStorage('on')
    expect(draw(Probe, false)).toContain('false/false')
  })

  it('the shell decides when present: true, false, null', () => {
    stubStorage('off')
    vi.stubGlobal('senseiTopShell', shellWith(true))
    expect(draw(Probe)).toContain('true/false')
    vi.stubGlobal('senseiTopShell', shellWith(false))
    expect(draw(Probe)).toContain('false/false')
    vi.stubGlobal('senseiTopShell', shellWith(null))
    expect(draw(Probe)).toContain('false/true')
  })

  it('storage decides in a browser: absent is on, off is off', () => {
    stubStorage(null)
    expect(draw(Probe)).toContain('true/false')
    stubStorage('off')
    expect(draw(Probe)).toContain('false/false')
  })

  it('useAi is null when off and the registry when on', () => {
    expect(draw(AiProbe, false)).toContain('null')
    expect(draw(AiProbe, true)).toContain('registry')
  })
})
