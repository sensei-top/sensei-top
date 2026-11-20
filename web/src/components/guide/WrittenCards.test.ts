import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { GuideNarrativeOut, GuideNarrativeResponse } from '../../api'
import { AiFeaturesContext } from '../../shell/aiFeatures'
import { FoldedProse, HowItWorksCard } from './WrittenCards'

const guide = { engine: 'How the deck wins.' } as unknown as GuideNarrativeOut

function draw(author: string, aiOn: boolean, stale = false): string {
  const response = {
    author,
    authored_at: '2025-09-18T12:00:00Z',
    stale,
  } as unknown as GuideNarrativeResponse
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(
        MemoryRouter,
        null,
        createElement(
          AiFeaturesContext.Provider,
          { value: aiOn },
          createElement(HowItWorksCard, { guide, response }),
        ),
      ),
    ),
  )
}

describe('HowItWorksCard', () => {
  it('names the model when AI features are on', () => {
    const html = draw('claude-opus-5', true)
    expect(html).toContain('Written by claude-opus-5 on Sep 18, 2025.')
    expect(html).toContain('How the deck wins.')
  })

  it('draws the stored prose with no model when they are off', () => {
    const html = draw('claude-opus-5', false)
    expect(html).toContain('Written on Sep 18, 2025.')
    expect(html).not.toContain('claude-opus-5')
    expect(html).toContain('How the deck wins.')
  })

  it('keeps the stale warning but not the link to write again when they are off', () => {
    const off = draw('claude-opus-5', false, true)
    expect(off).toContain('Written before the list changed')
    expect(off).not.toContain('Write it again')
    expect(draw('claude-opus-5', true, true)).toContain('Write it again')
  })

  it('keeps the pasted-in line when they are off', () => {
    expect(draw('pasted', false)).toContain('Pasted in on Sep 18, 2025.')
  })
})

describe('FoldedProse', () => {
  const drawFolded = (lead: string | null | undefined, prose: string) =>
    renderToStaticMarkup(createElement(FoldedProse, { lead, prose }))

  it('shows the stored lead as the teaser, the prose behind the fold', () => {
    const html = drawFolded('Race them.', 'A long account. It goes on.')
    expect(html).toContain('<p class="text-body text-ink2">Race them.</p>')
    expect(html).toContain('Read in full')
    expect(html).toMatch(/<details(?![^>]*\bopen\b)[^>]*>[\s\S]*A long account\. It goes on\.[\s\S]*<\/details>/)
  })

  it('falls back to the prose\'s first sentence without a lead', () => {
    const html = drawFolded(null, 'Race them early. Then hold the line.')
    expect(html).toContain('<p class="text-body text-ink2">Race them early.</p>')
  })

  it('draws nothing for empty prose', () => {
    expect(drawFolded('A lead.', '  ')).toBe('')
  })
})
