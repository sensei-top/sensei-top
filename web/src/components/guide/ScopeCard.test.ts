import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import '../../i18n'
import type { FirstData } from '../../bridge'
import { GapLines } from './ScopeCard'

const TEXT = 'Rules text is missing for 2 of your 60 cards.'
const LEGALITY = 'No card legality data is present.'
const OTHER = 'This deck has no recorded matches.'
const draw = (state: FirstData | null, gaps = [TEXT], codes: (string | null)[] = ['rules_text_missing']) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(GapLines, { gaps, codes, state })))
const count = (html: string, part: string) => html.split(part).length - 1

describe('the card-data gaps in the scope card', () => {
  it('wait for card data, with a percent when the download has a total', () => {
    expect(
      draw({ state: 'running', line: null, progress: { stage: 'download', done: 43, total: 100 } }),
    ).toContain('This guide waits for card data · 43%')
    expect(draw({ state: 'running', line: null })).toContain('This guide waits for card data<')
  })

  it('point to Settings → Sources when no download is running', () => {
    const html = draw({ state: 'idle' }, [LEGALITY], ['legality_missing'])
    expect(html).toContain('Download card data in Settings → Sources')
    expect(html).toContain('href="/settings/sources"')
    expect(html).not.toContain(LEGALITY)
  })

  it("keep the server's sentence in a browser, and for any other gap", () => {
    expect(draw(null)).toContain(TEXT)
    expect(draw({ state: 'running', line: null }, [TEXT], [null])).toContain(TEXT)
  })

  it('show one line when both codes are present, other gaps untouched', () => {
    const gaps = [TEXT, LEGALITY, OTHER]
    const codes = ['rules_text_missing', 'legality_missing', null]
    const running = draw(
      { state: 'running', line: null, progress: { stage: 'download', done: 43, total: 100 } },
      gaps,
      codes,
    )
    expect(count(running, 'waits for card data')).toBe(1)
    expect(running).toContain(OTHER)
    const idle = draw({ state: 'idle' }, gaps, codes)
    expect(count(idle, 'Download card data')).toBe(1)
    expect(idle).toContain(OTHER)
    expect(count(draw(null, gaps, codes), 'Rules text is missing')).toBe(1)
  })
})
