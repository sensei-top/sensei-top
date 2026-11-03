import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import '../i18n'
import { AiFeaturesContext } from '../shell/aiFeatures'
import { SettingsPage } from './SettingsPage'

function draw(aiOn: boolean): string {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(
        MemoryRouter,
        null,
        createElement(AiFeaturesContext.Provider, { value: aiOn }, createElement(SettingsPage)),
      ),
    ),
  ).replace(/&#x27;/g, "'")
}

describe('Settings, the AI features switch', () => {
  it('has its section and switch, checked when on and not when off', () => {
    const on = draw(true)
    const off = draw(false)
    expect(on).toContain('>AI features<')
    expect(on).toContain('The coach, written reports and guides, matchup briefs, and the prompts that write them.')
    const checked = (html: string) => /AI features<\/p>.*?aria-checked="(true|false)"/s.exec(html)?.[1]
    expect(checked(on)).toBe('true')
    expect(checked(off)).toBe('false')
  })

  it('words Advice during a game without the matchup brief when off', () => {
    const on = draw(true)
    const off = draw(false)
    expect(on).toContain('what the opponent may be holding and the matchup brief')
    expect(off).not.toContain('matchup brief, in casual')
    expect(off).toContain(
      'The keep guide and what the opponent may be holding, in casual games and on the ranked ladder.',
    )
  })
})
