import { describe, expect, it, vi } from 'vitest'
import { readShellGlobal, shellStore, type BridgeSettings, type RawShell } from './bridge'

const never = () => Promise.resolve({ ok: true } as const)

function settings(version: string, model = 'm'): BridgeSettings {
  return {
    sources: {
      arenaLog: { path: null, found: false, detailedLogs: 'unknown' },
      dateOrder: 'auto',
      mtgoHandle: null,
      mtgoDir: null,
      mtgoFound: null,
      dataDir: '/d',
    },
    writing: { claudeKey: false, topdeckKey: false, model, models: [] },
    backup: { dir: '/b', keep: 7, last: null, inFolder: 0 },
    sharing: null,
    app: {
      startWithSystem: false,
      keepRunningOnClose: false,
      checkForUpdates: true,
      diagnostic: false,
      update: { state: 'idle' },
      onboarded: true,
      askAutostart: false,
      rulesText: null,
      firstData: { state: 'idle' },
      version,
      platform: 'linux',
    },
  }
}

function fake(initial: BridgeSettings | null) {
  const listeners = new Set<(s: BridgeSettings) => void>()
  const raw = {
    initial,
    save: never,
    setKey: never,
    pickFolder: () => Promise.resolve(null),
    pickFile: () => Promise.resolve(null),
    backUpNow: never,
    restoreFrom: never,
    setSharing: never,
    payloadOf: () => Promise.resolve(null),
    sharedState: () => Promise.resolve({ state: 'not-shared' as const, at: null }),
    unshare: never,
    deleteContributions: () => Promise.resolve({ ok: true as const, count: 0 }),
    newInstallation: never,
    app: {
      set: never,
      checkForUpdates: never,
      restartToUpdate: never,
      showLogs: never,
      exportDiagnostics: never,
      showDataFolder: never,
      recheck: never,
      firstData: never,
      finishOnboarding: never,
    },
    onChange: (listener: (s: BridgeSettings) => void) => {
      listeners.add(listener)
      return () => void listeners.delete(listener)
    },
  } satisfies RawShell
  return { raw, emit: (s: BridgeSettings) => listeners.forEach((l) => l(s)), listeners }
}

describe('the shell store', () => {
  it('is null with no global', () => {
    const store = shellStore(undefined)
    expect(store.snapshot()).toBeNull()
    store.subscribe(() => {})()
  })

  it('holds the shell global\'s settings and follows its change events', () => {
    const { raw, emit } = fake(settings('1.0.0'))
    const store = shellStore(raw)
    const first = store.snapshot()
    expect(first?.settings.sources.dataDir).toBe('/d')
    expect(first?.app?.settings.version).toBe('1.0.0')
    expect(store.snapshot()).toBe(first)
    let heard = 0
    const stop = store.subscribe(() => heard++)
    emit(settings('1.0.1', 'other'))
    expect(heard).toBe(1)
    expect(store.snapshot()?.settings.writing.model).toBe('other')
    expect(store.snapshot()?.app?.settings.version).toBe('1.0.1')
    expect(store.snapshot()?.app?.showDataFolder).toBe(raw.app.showDataFolder)
    stop()
    emit(settings('1.0.2'))
    expect(heard).toBe(1)
  })

  it('is null while initial is null, until a change event brings settings', () => {
    const { raw, emit } = fake(null)
    const store = shellStore(raw)
    expect(store.snapshot()).toBeNull()
    store.subscribe(() => {})
    emit(settings('2.0.0'))
    expect(store.snapshot()?.app?.settings.version).toBe('2.0.0')
  })
})

describe('the store between pages', () => {
  it('keeps an event that arrives with no subscriber for the next snapshot', () => {
    const { raw, emit } = fake(settings('1.0.0'))
    const store = shellStore(raw)
    store.subscribe(() => {})()
    emit(settings('1.0.3'))
    expect(store.snapshot()?.app?.settings.version).toBe('1.0.3')
  })
})

describe('the global', () => {
  it('is read from senseiTopShell, and is undefined without it', () => {
    const { raw } = fake(null)
    const holder = globalThis as { senseiTopShell?: unknown }
    holder.senseiTopShell = raw
    try {
      expect(readShellGlobal()).toBe(raw)
    } finally {
      delete holder.senseiTopShell
    }
    expect(readShellGlobal()).toBeUndefined()
  })
})

describe('the dashboard\'s store', () => {
  it('hears an event published before the first store read, from module load', async () => {
    const { raw, emit } = fake(settings('1.0.0'))
    const holder = globalThis as { senseiTopShell?: unknown }
    holder.senseiTopShell = raw
    try {
      vi.resetModules()
      const fresh = await import('./bridge')
      emit(settings('1.0.4'))
      expect(fresh.startShellStore().snapshot()?.app?.settings.version).toBe('1.0.4')
    } finally {
      delete holder.senseiTopShell
    }
  })
})
