import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { PairingBrief } from './PairingBrief'

describe('PairingBrief pending', () => {
  it('keeps its card and carries no status region', () => {
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        createElement(PairingBrief, { deckKey: 'deck', opponentKey: 'archetype:azorius-control' }),
      ),
    )
    expect(html).not.toContain('role="status"')
    expect(html).toContain('animate-pulse')
  })
})
