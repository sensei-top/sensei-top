import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import '../../i18n'
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
})
