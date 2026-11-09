import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import '../i18n'
import type { FirstData } from '../bridge'
import { CardDataChipView } from './CardDataChip'

const draw = (state: FirstData | null) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(CardDataChipView, { state })))

describe('the card-data chip', () => {
  it('shows the percent of a download with a total', () => {
    const html = draw({ state: 'running', line: null, progress: { stage: 'download', done: 43, total: 100 } })
    expect(html).toContain('Card data · 43%')
    expect(html).toContain('href="/settings/sources"')
  })

  it('says downloading without a total, and saving while it saves', () => {
    expect(draw({ state: 'running', line: null, progress: { stage: 'download', done: 5, total: null } })).toContain(
      'Card data · downloading',
    )
    expect(draw({ state: 'running', line: null })).toContain('Card data · downloading')
    expect(draw({ state: 'running', line: null, progress: { stage: 'save' } })).toContain('Card data · saving')
  })

  it("says it didn't finish when it failed, linking the same place", () => {
    const html = draw({ state: 'failed', error: 'x' })
    expect(html).toContain("Card data · didn&#x27;t finish")
    expect(html).toContain('href="/settings/sources"')
  })

  it('draws nothing when idle, done or in a browser', () => {
    expect(draw({ state: 'idle' })).toBe('')
    expect(draw({ state: 'done', line: 'x' })).toBe('')
    expect(draw(null)).toBe('')
  })
})
