import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import '../i18n'
import { AiFeaturesContext } from '../shell/aiFeatures'
import type { AppSettings, Shell, ShellApp } from '../bridge'
import type { SettingsGroupId } from '../lib/settings'
import { sampleWriting, useSampleShell } from '../lib/sampleShell'
import { SettingsView } from '../views/SettingsView'
import { SettingsPage } from './SettingsPage'

function draw(aiOn: boolean, group?: SettingsGroupId): string {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(
        MemoryRouter,
        null,
        createElement(AiFeaturesContext.Provider, { value: aiOn }, createElement(SettingsPage, { group })),
      ),
    ),
  ).replace(/&#x27;/g, "'")
}

describe('Settings, the AI features switch', () => {
  it('has its section and switch, checked when on and not when off', () => {
    const on = draw(true, 'writing')
    const off = draw(false, 'writing')
    expect(on).toContain('>AI features<')
    expect(on).toContain('The coach, written reports and guides, matchup briefs, and the prompts that write them.')
    const checked = (html: string) => /AI features<\/p>.*?aria-checked="(true|false)"/s.exec(html)?.[1]
    expect(checked(on)).toBe('true')
    expect(checked(off)).toBe('false')
  })

  it('words Advice during a game without the matchup brief when off', () => {
    const on = draw(true, 'general')
    const off = draw(false, 'general')
    expect(on).toContain('what the opponent may be holding and the matchup brief')
    expect(off).not.toContain('matchup brief, in casual')
    expect(off).toContain(
      'The keep guide and what the opponent may be holding, in casual games and on the ranked ladder.',
    )
  })
})

describe('each group draws its sections in order', () => {
  const order = (html: string, ids: string[]) => ids.map((id) => html.indexOf(`id="${id}"`))
  const ascending = (at: number[]) => at.every((n, i) => n >= 0 && (i === 0 || n > at[i - 1]))

  it('General: language, appearance, live', () => {
    const html = draw(true, 'general')
    expect(ascending(order(html, ['language-heading', 'appearance', 'live-settings']))).toBe(true)
    expect(html).not.toContain('id="ai-settings"')
    expect(html).not.toContain('id="credits"')
  })

  it('Writing: the AI features switch, nothing of the others', () => {
    const html = draw(true, 'writing')
    expect(html.indexOf('id="ai-settings"')).toBeGreaterThanOrEqual(0)
    expect(html.indexOf('id="ai-settings"')).toBeLessThan(html.indexOf('id="writing"'))
    expect(html).not.toContain('id="language-heading"')
    expect(html).not.toContain('id="live-settings"')
  })

  it('About: the credits', () => {
    const html = draw(true, 'about')
    expect(html).toContain('id="credits"')
    expect(html).not.toContain('id="ai-settings"')
  })

  it('Sources, Backup and Account draw nothing of the browser sections', () => {
    for (const group of ['sources', 'backup', 'account'] as const) {
      const html = draw(true, group)
      expect(html).not.toContain('id="language-heading"')
      expect(html).not.toContain('id="credits"')
    }
  })
})

describe('the shell groups draw their sections in order', () => {
  function Sample({ group }: { group: SettingsGroupId }) {
    const sample = useSampleShell('everything')
    const settings: AppSettings = {
      startWithSystem: false,
      keepRunningOnClose: false,
      checkForUpdates: true,
      diagnostic: false,
      update: { state: 'idle' },
      onboarded: true,
      aiFeatures: true,
      canContribute: true,
      contribAsked: false,
      contribute: null,
      account: { available: true, signedIn: false, userId: null, email: null, provider: null, persistence: { kept: true } },
      askAutostart: false,
      canAutostart: true,
      windowsStore: false,
      rulesText: null,
      firstData: { state: 'idle' },
      version: '1.0.0',
      platform: 'linux',
    }
    // Drawn to static markup, so no function on it is ever called.
    const shell = { ...sample!, app: { settings, account: {} } as unknown as ShellApp } as Shell
    return createElement(
      SettingsView,
      { shell, writing: sampleWriting('everything'), group },
      createElement('div', { id: 'credits-marker' }),
    )
  }
  const drawShell = (group: SettingsGroupId) =>
    renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        createElement(MemoryRouter, null, createElement(Sample, { group })),
      ),
    )

  it('General has the App\'s general half and not its about half', () => {
    const html = drawShell('general')
    expect(html).toContain('id="app"')
    expect(html).not.toContain('id="app-about"')
  })

  it('About has the App\'s about half before the credits and not the general half', () => {
    const html = drawShell('about')
    expect(html.indexOf('id="app-about"')).toBeGreaterThanOrEqual(0)
    expect(html.indexOf('id="app-about"')).toBeLessThan(html.indexOf('id="credits-marker"'))
    expect(html).not.toContain('id="app"')
  })

  it('Account has Account before Contribute', () => {
    const html = drawShell('account')
    expect(html.indexOf('id="account"')).toBeGreaterThanOrEqual(0)
    expect(html.indexOf('id="account"')).toBeLessThan(html.indexOf('id="contribute"'))
  })
})
