import { type ComponentProps, createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Prose } from '../../components/ui/Card'
import { setLanguage } from '../../i18n'
import en from '../../locales/en/prompts.json'
import ptBR from '../../locales/pt-BR/prompts.json'
import { RulesNotesProvider, type RulesNote } from './context'

const note = (marker: string, confidence: string | null): RulesNote => ({
  marker,
  question: 'q',
  verdict: 'It resolves first.',
  explanation: 'Because of the stack.',
  citations: ['603.3'],
  confidence,
  rules_version: 'v1',
})

const render = (text: string, notes: RulesNote[]) =>
  renderToStaticMarkup(
    createElement(
      RulesNotesProvider,
      { notes } as unknown as ComponentProps<typeof RulesNotesProvider>,
      createElement(Prose, { text }),
    ),
  )

// The markup escapes an apostrophe, so compare against the escaped line.
const escaped = (line: string) => line.replace(/'/g, '&#x27;')

describe('Prose rules-note markers', () => {
  it.each([
    ['en', en],
    ['pt-BR', ptBR],
  ] as const)('draws a chip with the disclosure verbatim in %s', (language, words) => {
    setLanguage(language)
    const html = render('Trigger order [N2] matters.', [note('N2', 'high')])
    expect(html).toContain('>N2<')
    expect(html).toContain(escaped(words.rulesNotes.disclosure))
    expect(html).toContain(escaped(words.rulesNotes.cited))
    expect(html).toContain('It resolves first.')
    setLanguage('en')
  })

  it('names the note and its confidence in the button label', () => {
    setLanguage('en')
    const html = render('[N2]', [note('N2', 'high')])
    expect(html).toContain('aria-label="Open rules note 2, high"')
  })

  it('draws nothing for a marker the provider does not know', () => {
    setLanguage('en')
    const html = render('Trigger order [N3] matters.', [note('N2', null)])
    expect(html).not.toContain('N3')
    expect(html).not.toContain(en.rulesNotes.disclosure)
  })

  it('draws nothing without a provider', () => {
    expect(renderToStaticMarkup(createElement(Prose, { text: 'a [N1] b' }))).not.toContain('N1')
  })
})
