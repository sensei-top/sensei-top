import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import { documentTitle, layoutName, placeAt, type RouteHandle } from './places'

// The English catalogue itself: the words below are the layout's own, as
// docs/frontend.md ("The layout") gives them.
const t = translator('en')

const welcome: RouteHandle = { title: 'welcome', needsShell: true }

describe('documentTitle', () => {
  it('names a non-place by its title, and a place by its label', () => {
    expect(documentTitle(null, t, 'Welcome')).toBe('Welcome · Sensei Top')
    expect(documentTitle(null, t)).toBe('Sensei Top')
    expect(documentTitle(placeAt('/matches'), t)).toBe('Matches · Sensei Top')
    expect(documentTitle(placeAt('/'), t)).toBe('Sensei Top')
  })
})

describe('layoutName', () => {
  it('names a place by its label', () => {
    expect(layoutName(placeAt('/settings'), undefined, false, t)).toEqual({ name: 'Settings', title: null })
  })

  it('names a titled non-place, given a shell', () => {
    expect(layoutName(null, welcome, true, t)).toEqual({ name: 'Welcome', title: 'Welcome' })
  })

  it('finds a page that needs a shell not found in a browser', () => {
    expect(layoutName(null, welcome, false, t)).toEqual({ name: 'No such page', title: null })
  })

  it('names a titled page that needs no shell in a browser', () => {
    expect(layoutName(null, { title: 'mtgoPicks' }, false, t).name).toBe('Pick MTGO decks')
  })

  it('is not found for the not-found route and for an unnamed non-place', () => {
    expect(layoutName(null, { notFound: true }, true, t).name).toBe('No such page')
    expect(layoutName(null, undefined, true, t).name).toBe('No such page')
  })
})
