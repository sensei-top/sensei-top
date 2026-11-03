import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import '../../i18n'
import { AiFeaturesContext } from '../../shell/aiFeatures'
import { ThreeThings, type Thing } from './ThreeThings'

describe('ThreeThings', () => {
  it('draws two pending things with their label and loading line, at places 1 and 2', () => {
    const things: Thing[] = [
      { kind: 'pending', slot: 'pattern' },
      { kind: 'pending', slot: 'field' },
    ]
    const html = renderToStaticMarkup(createElement(ThreeThings, { things, now: Date.UTC(2026, 8, 28) }))
    const items = html.split('<li ').slice(1)
    expect(items).toHaveLength(2)
    const text = items.map((item) => item.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim())
    expect(text[0]).toMatch(/^.*1 Pattern Looking for a pattern in your matches…/)
    expect(text[1]).toMatch(/^.*2 Field Reading the field…/)
  })

  const pattern: Thing = {
    kind: 'pattern',
    art: null,
    pattern: {
      wonWith: 1,
      wonWithout: 3,
      leak: {
        code: 'long_game',
        category: 'tempo',
        sample_title: 'Long games',
        n_with: 4,
        win_rate_with: 0.25,
        ci_with: [0, 1],
        n_without: 4,
        win_rate_without: 0.75,
        ci_without: [0, 1],
        gap: 0.5,
        match_ids_with: [],
      },
    },
  }
  const drawn = (value: boolean) =>
    renderToStaticMarkup(
      createElement(AiFeaturesContext.Provider, { value }, createElement(MemoryRouter, null, createElement(ThreeThings, { things: [pattern], now: 0 })),
      ),
    )

  it('keeps the pattern card with AI features off, without its button to the coach', () => {
    const off = drawn(false)
    expect(off).toContain('Long games are where you lose')
    expect(off).toContain('You are 1\u2060–\u20603 in the matches')
    expect(off).toContain('and 3\u2060–\u20601 in the rest.')
    expect(off).not.toContain('See every pattern')
    expect(off).not.toContain('/coach')
  })

  it('gives the pattern card its button to the coach with AI features on', () => {
    const on = drawn(true)
    expect(on).toContain('See every pattern')
    expect(on).toContain('href="/coach"')
  })
})
