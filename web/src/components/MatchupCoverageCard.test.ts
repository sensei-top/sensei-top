import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { CoverageOut } from '../api'
import { AiFeaturesContext } from '../shell/aiFeatures'
import { MatchupCoverageCard } from './MatchupCoverageCard'

const rows = [
  { archetype_key: 'burn', label: 'Burn', times_faced: 3, field_share: 0.12, status: 'missing' },
  { archetype_key: 'tron', label: 'Tron', times_faced: 0, field_share: 0.05, status: 'ok' },
]

function draw(data: Partial<CoverageOut>, aiOn: boolean): string {
  const coverage = {
    fmt: 'Modern',
    rows,
    matches_covered: 1,
    matches_covered_numerator: 1,
    matches_covered_denominator: 2,
    field_covered: 0.5,
    ...data,
  } as CoverageOut
  const client = new QueryClient()
  client.setQueryData(['guide-coverage', 'deck'], coverage)
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(
        MemoryRouter,
        null,
        createElement(
          AiFeaturesContext.Provider,
          { value: aiOn },
          createElement(MatchupCoverageCard, { guideKey: 'deck' }),
        ),
      ),
    ),
  )
}

describe('MatchupCoverageCard', () => {
  it('draws the briefs, tiles and Brief column when AI features are on', () => {
    const html = draw({}, true)
    expect(html).toContain('Matchup coverage')
    expect(html).toContain('Matches covered')
    expect(html).toContain('>Brief<')
    expect(html).toContain('Not written')
  })

  it('is field-only when they are off', () => {
    const html = draw({}, false)
    expect(html).toContain('Archetypes to prepare for')
    expect(html).toContain('Each opens its matchup.')
    expect(html).toContain('>Archetype<')
    expect(html).toContain('>Field<')
    expect(html).toContain('Burn')
    expect(html).toContain('Tron')
    expect(html).toContain('12%')
    expect(html).not.toContain('>Brief<')
    expect(html).not.toContain('Matches covered')
    expect(html).not.toContain('Not written')
    expect(html).not.toContain('Write every missing brief')
    expect(html).not.toContain('brief')
  })

  it('says the format is unknown in the field-only words when they are off', () => {
    const html = draw({ fmt: null, rows: [] }, false)
    expect(html).toContain('there are no tournament results to compare it with')
    expect(html).not.toContain('write a brief')
  })
})
