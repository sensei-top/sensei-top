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
  const hero = (thirty: ThirtyDays) =>
    renderToStaticMarkup(createElement(SessionHero, { session, thirty, art: null, now: Date.UTC(2026, 8, 28) }))
  const emphasised = (html: string) =>
    [...html.matchAll(/<span class="font-semibold text-ink">([^<]*)<\/span>/g)].map((m) => m[1])

  it('writes the 30 days with the record and the rate emphasised, from ten decided matches', () => {
    const html = hero({ played: 41, won: 25, losses: 15, outsideSession: true })
    expect(emphasised(html)).toEqual(['25\u2060–\u206015', '63%'])
    expect(html.replace(/<[^>]*>/g, '')).toContain('You are 25\u2060–\u206015, or 63%.')
  })

  it('writes the record alone under ten decided matches', () => {
    const html = hero({ played: 9, won: 6, losses: 3, outsideSession: true })
    expect(emphasised(html)).toEqual(['6\u2060–\u20603'])
    expect(html.replace(/<[^>]*>/g, '')).toContain('You are 6\u2060–\u20603.')
  })
})
