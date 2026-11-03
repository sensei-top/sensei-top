import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { RcqGuideOut } from '../../api'
import { AiFeaturesContext } from '../../shell/aiFeatures'
import { RcqResult } from './RcqResult'

function draw(model: string, aiOn: boolean): string {
  const response = {
    status: 'ok',
    model,
    generated_at: '2025-09-18T12:00:00Z',
    guide: {
      game_plan: 'Win the long game.',
      expected_field: 'Mostly midrange.',
      matchups: [],
      problems: [],
      flex_notes: [],
      checklist: [],
    },
  } as unknown as RcqGuideOut
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
          createElement(RcqResult, { deckKey: 'deck', response }),
        ),
      ),
    ),
  )
}

describe('RcqResult', () => {
  it('names the model when AI features are on', () => {
    expect(draw('claude-opus-5', true)).toContain('Written by claude-opus-5 on Sep 18, 2025.')
  })

  it('draws the stored guide with no model when they are off', () => {
    const html = draw('claude-opus-5', false)
    expect(html).toContain('Win the long game.')
    expect(html).toContain('Written on Sep 18, 2025.')
    expect(html).not.toContain('claude-opus-5')
  })

  it('keeps the pasted-in line when they are off', () => {
    expect(draw('pasted', false)).toContain('Pasted in on Sep 18, 2025.')
  })
})
