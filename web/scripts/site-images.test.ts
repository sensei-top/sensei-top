import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
// The scripts are plain .mjs, typed by inference (`allowJs` in
// tsconfig.node.json); none of them opens a browser on import.
import { OG_TEXT, SITE_VIEWS, VIEWPORT, convertToWebp, parseClock } from './site-images.mjs'
import { VIEWS, addressOf } from './views.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (relative: string) => readFileSync(join(HERE, relative), 'utf8')

interface SiteView {
  name: string
  path: string
}

/** The addresses `src/routes.tsx` declares, as the shell's children write
 *  them (relative, no leading slash). The children of the `decks/:id` block
 *  are known only under `decks/:id/`; every other literal only at the top
 *  level. The index route is the empty address. */
function knownAddresses(): Set<string> {
  const source = read('../src/routes.tsx')
  const literalsOf = (text: string) => [...text.matchAll(/path: '([^']+)'/g)].map((m) => m[1])
  const start = source.indexOf("path: 'decks/:id'")
  const end = source.indexOf('],', start)
  const [parent, ...nested] = literalsOf(source.slice(start, end))
  const top = literalsOf(source.slice(0, start)).concat(literalsOf(source.slice(end)))
  // The deck's own path is the Overview, the parent's index route.
  const known = new Set<string>(['', parent])
  for (const literal of top) known.add(literal.replace(/^\//, ''))
  for (const literal of nested) known.add(`decks/:id/${literal}`)
  return known
}

/** A view's path as the router sees it: every placeholder is a route
 *  parameter (`:id`), the query string is not part of the address. */
function asRoute(viewPath: string): string {
  return viewPath
    .replace(/\?.*$/, '')
    .replace(/:(match|deck|largest|version|event)\b/g, ':id')
    .replace(/^\//, '')
}

describe('SITE_VIEWS', () => {
  const views: SiteView[] = SITE_VIEWS

  it('names the nine views the plan lists, once each', () => {
    expect(views.map((view) => view.name)).toEqual([
      'home',
      'matches',
      'match-report',
      'replay',
      'matchups',
      'guide',
      'field',
      'coach',
      'live',
    ])
  })

  it('opens only addresses routes.tsx knows', () => {
    const known = knownAddresses()
    for (const view of views) {
      expect(known.has(asRoute(view.path)), `${view.name}: ${view.path}`).toBe(true)
    }
  })

  it('does not know a nested address at the top level, nor a top-level one under a deck', () => {
    const known = knownAddresses()
    expect(known.has('decks/:id')).toBe(true)
    expect(known.has('decks/:id/matchups')).toBe(true)
    expect(known.has('guide')).toBe(false)
    expect(known.has('matchups')).toBe(false)
    expect(known.has('decks/:id/coach')).toBe(false)
  })

  it('fills :match and :largest from the ids and skips a view with none', () => {
    const ids = { match: 'm-1', deck: null, largest: 'arena:abc', version: null, event: null }
    const byName = (name: string) => views.find((view) => view.name === name)
    // A deck's key keeps its colon bare, as the dashboard's own address does.
    expect(addressOf(byName('matchups'), ids)).toBe('/decks/arena:abc/matchups')
    expect(addressOf(byName('replay'), ids)).toBe('/matches/m-1/replay')
    expect(addressOf(byName('home'), ids)).toBe('/')
    const none = { match: null, deck: null, largest: null, version: null, event: null }
    expect(addressOf(byName('guide'), none)).toBeNull()
    expect(addressOf(byName('match-report'), none)).toBeNull()
  })

  it('captures a desktop display', () => {
    expect(VIEWPORT).toEqual({ width: 1440, height: 900 })
  })
})

describe('the screenshots views kept by the move', () => {
  it('still hold the nineteen views, each with an id and an address', () => {
    expect(VIEWS).toHaveLength(19)
    for (const view of VIEWS) {
      expect(view.id).toBeTruthy()
      expect(view.path.startsWith('/')).toBe(true)
    }
  })
})

describe('the Open Graph card', () => {
  const template = read('og-card.html')
  const slotsIn = (html: string) => [...html.matchAll(/data-slot="([^"]+)"/g)].map((m) => m[1]).sort()

  it('has a text for English and for Portuguese', () => {
    expect(Object.keys(OG_TEXT).sort()).toEqual(['en-US', 'pt-BR'])
  })

  it('has, in both languages, a non-empty text for every slot the template fills', () => {
    const slots = slotsIn(template)
    expect(slots.length).toBeGreaterThan(0)
    for (const [locale, text] of Object.entries(OG_TEXT as Record<string, Record<string, string>>)) {
      expect(Object.keys(text).sort(), locale).toEqual(slots)
      for (const [key, value] of Object.entries(text)) {
        expect(value.trim().length, `${locale}.${key}`).toBeGreaterThan(0)
      }
    }
  })

  it('loads its fonts from site/fonts, which exist', () => {
    const files = [...template.matchAll(/url\(\.\.\/\.\.\/site\/fonts\/([^)]+)\)/g)].map((m) => m[1])
    expect(files.length).toBeGreaterThan(0)
    for (const file of files) {
      expect(() => readFileSync(join(HERE, '../../site/fonts', file)), file).not.toThrow()
    }
  })
})

describe('convertToWebp', () => {
  it('reports a missing magick instead of throwing', () => {
    const result = convertToWebp('/nonexistent/in.png', '/nonexistent/out.webp', 'magick-that-is-not-installed')
    expect(result.ok).toBe(false)
    expect(result.reason).toContain('not installed')
  })
})

describe('parseClock', () => {
  it('gives nothing when the flag is absent', () => {
    expect(parseClock(undefined)).toBeNull()
  })

  it('gives the moment a valid ISO 8601 date-time names', () => {
    const date = parseClock('2026-08-26T21:36:00Z')
    expect(date).toBeInstanceOf(Date)
    expect(date?.toISOString()).toBe('2026-08-26T21:36:00.000Z')
  })

  it('reads a value with no offset as local time', () => {
    const date = parseClock('2026-08-26T21:36:00')
    expect(date?.getFullYear()).toBe(2026)
    expect(date?.getMonth()).toBe(7)
    expect(date?.getDate()).toBe(26)
    expect(date?.getHours()).toBe(21)
    expect(date?.getMinutes()).toBe(36)
  })

  it('refuses a value that is not a date', () => {
    expect(() => parseClock('last tuesday')).toThrow('--clock')
    expect(() => parseClock('')).toThrow('--clock')
  })
})
