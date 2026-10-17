import i18next from 'i18next'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it } from 'vitest'
import '../../i18n'
import { DetailedLogsGuide } from './DetailedLogsGuide'

// The expected words are the plan's (D11: Arena's own labels, en, and the
// pt-BR help page's), and the sentences the approved copy gives the caption
// and the image's label; each language's are drawn from its own catalogue.
const WORDS = {
  en: {
    labels: ['Options', 'Account', 'Detailed Logs (Plugin Support)'],
    restart: 'Then close Arena and start it again.',
    aria: 'In Arena, open Options, then Account, and tick Detailed Logs (Plugin Support). Then close Arena and start it again.',
  },
  'pt-BR': {
    labels: ['Opções', 'Conta', 'Registros detalhados (suporte de plugin)'],
    restart: 'Depois, feche o Arena e abra-o de novo.',
    aria: 'No Arena, abra Opções, depois Conta, e marque Registros detalhados (suporte de plugin). Depois, feche o Arena e abra-o de novo.',
  },
} as const

function render(compact: boolean) {
  const html = renderToStaticMarkup(createElement(DetailedLogsGuide, { compact }))
  return { html, text: html.replace(/<[^>]*>/g, '') }
}

afterEach(async () => {
  await i18next.changeLanguage('en')
})

describe('DetailedLogsGuide', () => {
  for (const language of ['en', 'pt-BR'] as const) {
    for (const compact of [false, true]) {
      it(`draws ${language}'s labels and says the steps once${compact ? ', compact' : ''}`, async () => {
        await i18next.changeLanguage(language)
        const { html, text } = render(compact)
        const words = WORDS[language]

        // One image, whose label is the whole sentence; it is the outermost
        // element, and everything drawn inside it is hidden from a screen
        // reader so the sentence is heard once.
        expect(html.match(/role="img"/g)).toHaveLength(1)
        expect(html).toMatch(new RegExp(`^<div role="img" aria-label="${escape(words.aria)}"><div aria-hidden="true"`))

        // The three labels, one per panel, and the caption under them.
        for (const label of words.labels) expect(text).toContain(label)
        expect(text).toContain(words.restart)
        // The numbered discs, 1 to 3, in order.
        expect([...html.matchAll(/text-on-accent[^"]*">(\d)</g)].map((m) => m[1])).toEqual(['1', '2', '3'])
      })
    }
  }
})

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
