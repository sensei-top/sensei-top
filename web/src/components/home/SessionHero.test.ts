import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import '../../i18n'
import type { Session, ThirtyDays } from '../../lib/home'
import { SessionHero } from './SessionHero'

const session: Session = {
  matches: [],
  start: Date.UTC(2026, 8, 27, 12),
  tally: { played: 3, wins: 2, losses: 1, draws: 0 },
  decks: [],
}

describe('SessionHero', () => {
  it('writes the 30 days with three emphasised figures inside the sentence', () => {
    const thirty: ThirtyDays = { played: 40, won: 25, outsideSession: true }
    const html = renderToStaticMarkup(
      createElement(SessionHero, { session, thirty, art: null, now: Date.UTC(2026, 8, 28) }),
    )
    const spans = [...html.matchAll(/<span class="font-semibold text-ink">([^<]*)<\/span>/g)].map((m) => m[1])
    expect(spans).toEqual(['25', '40', '63%'])
    const text = html.replace(/<[^>]*>/g, '')
    expect(text).toContain('Over the last 30 days you have won 25 of 40 matches, or 63%.')
  })
})
