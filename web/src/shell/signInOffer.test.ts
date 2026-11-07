import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import '../i18n'
import type { Shell } from '../bridge'
import { AfterRestore, CloudCopyCard } from '../components/settings/BackupSection'
import { signInOffered } from './signInOffer'

function shellWith(over: { available?: boolean; signedIn?: boolean; onboarded?: boolean; dismissed?: boolean }): Shell {
  const available = over.available ?? true
  return {
    app: {
      settings: {
        onboarded: over.onboarded ?? true,
        signInDismissed: over.dismissed ?? false,
        account: available ? { available: true, signedIn: over.signedIn ?? false } : { available: false },
      },
    },
  } as unknown as Shell
}

describe('the sign-in offer', () => {
  it('stands while an account is possible, nobody is in, the welcome was seen and it was not dismissed', () => {
    expect(signInOffered(shellWith({}))).toBe(true)
  })

  it('goes when any one condition is false', () => {
    expect(signInOffered(null)).toBe(false)
    expect(signInOffered({} as Shell)).toBe(false)
    expect(signInOffered(shellWith({ available: false }))).toBe(false)
    expect(signInOffered(shellWith({ signedIn: true }))).toBe(false)
    expect(signInOffered(shellWith({ onboarded: false }))).toBe(false)
    expect(signInOffered(shellWith({ dismissed: true }))).toBe(false)
  })
})

describe('the Cloud copy card', () => {
  const draw = (account: unknown) =>
    renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        createElement(
          MemoryRouter,
          null,
          createElement(CloudCopyCard, { account: account as never, actions: {} as never }),
        ),
      ),
    )

  it('is one line with a link to Account when signed out', () => {
    const html = draw({ available: true, signedIn: false })
    expect(html).toContain('Cloud copy')
    expect(html).toContain('href="/settings/account"')
  })

  it('is not drawn when signed in with no profile read', () => {
    for (const profile of [undefined, { state: 'none' }, { state: 'unknown' }]) {
      const html = draw({ available: true, signedIn: true, profile })
      expect(html).toBe('')
    }
  })

  it('holds the switch and the off status line when signed in with a profile read', () => {
    const html = draw({
      available: true,
      signedIn: true,
      profile: { state: 'read', consentSync: false, consentErrors: false, consentCoachHistory: false },
    })
    expect(html).toContain('Back up my match history')
    expect(html).toContain('role="switch"')
    expect(html).toContain('Backup is off.')
  })

  it('is not drawn in a build with no account', () => {
    expect(draw({ available: false })).toBe('')
  })
})

describe('after a restore', () => {
  const draw = (restored: boolean, relaunch?: () => Promise<{ ok: true }>) =>
    renderToStaticMarkup(createElement(AfterRestore, { restored, relaunch, onFailure: () => {} }))
  const relaunch = () => Promise.resolve({ ok: true as const })

  it('offers Restart now only when restored and the shell can relaunch', () => {
    expect(draw(true, relaunch)).toContain('Restart now')
    expect(draw(true)).not.toContain('Restart now')
    expect(draw(false, relaunch)).not.toContain('Restart now')
    expect(draw(false, relaunch)).toBe('')
  })

  it('says it takes effect at the next start', () => {
    expect(draw(true)).toContain('Restored.')
  })
})
