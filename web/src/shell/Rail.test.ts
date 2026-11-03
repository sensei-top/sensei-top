import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import '../i18n'
import { AiFeaturesContext } from './aiFeatures'
import { BottomBar } from './BottomBar'
import { Rail } from './Rail'

function draw(node: typeof Rail, aiOn: boolean): string {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(
        AiFeaturesContext.Provider,
        { value: aiOn },
        createElement(MemoryRouter, null, createElement(node, { current: null })),
      ),
    ),
  )
}

describe('the Coach in the navigation', () => {
  it('is in the rail, and in the bottom bar\'s More, when AI features are on', () => {
    expect(draw(Rail, true)).toContain('href="/coach"')
    expect(draw(BottomBar, true)).toContain('href="/coach"')
  })

  it('is in neither when they are off, and the other places stay', () => {
    for (const node of [Rail, BottomBar]) {
      const html = draw(node, false)
      expect(html).not.toContain('href="/coach"')
      expect(html).toContain('href="/settings"')
    }
  })
})
