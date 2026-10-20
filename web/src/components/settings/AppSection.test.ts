import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { AppSettings } from '../../bridge'
import '../../i18n'
import { AppSection } from './AppSection'

// Drawn to static markup with a fake shell's settings: this pins which rows
// appear, not what a press does.

function app(change: Partial<AppSettings> = {}): AppSettings {
  return {
    startWithSystem: false,
    keepRunningOnClose: false,
    checkForUpdates: true,
    diagnostic: false,
    update: { state: 'idle' },
    onboarded: true,
    askAutostart: false,
    canAutostart: true,
    rulesText: null,
    firstData: { state: 'idle' },
    version: '1.0.0',
    platform: 'linux',
    ...change,
  }
}

const draw = (settings: AppSettings) => renderToStaticMarkup(createElement(MemoryRouter, null, createElement(AppSection, { app: settings })))

describe('the login toggle', () => {
  it('shows where the copy can start at login', () => {
    expect(draw(app({ canAutostart: true }))).toContain('Start when you log in')
  })

  it('is absent where it cannot, as in the Linux tarball', () => {
    const html = draw(app({ canAutostart: false }))
    expect(html).not.toContain('Start when you log in')
    expect(html).toContain('Keep running')
  })
})
