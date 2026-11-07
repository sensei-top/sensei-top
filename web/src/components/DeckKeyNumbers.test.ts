import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { DeckKeyNumbers, StripFrames } from './DeckKeyNumbers'

describe('the deck strip pending', () => {
  it('draws the frames with no status region', () => {
    expect(renderToStaticMarkup(createElement(StripFrames))).not.toContain('role="status"')
  })

  it('has no status region while its queries have not answered', () => {
    const client = new QueryClient()
    const html = renderToStaticMarkup(
      createElement(QueryClientProvider, { client }, createElement(DeckKeyNumbers, { versionIds: ['v1'] })),
    )
    expect(html).not.toContain('role="status"')
    expect(html).toContain('<p class="text-caption text-muted">')
  })
})
