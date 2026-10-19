import { describe, expect, it } from 'vitest'
import { livePanels, railAlternatives } from './livePanels'

const ADVICE_PANELS = ['opening-hand', 'keep-guide', 'opponent-hand']

describe('livePanels', () => {
  it('draws no advice in any phase of a ranked game', () => {
    for (const decisionPending of [true, false]) {
      for (const mulliganPhase of [true, false]) {
        const { primary, rail } = livePanels({ decisionPending, mulliganPhase, advice: false })
        for (const panel of [primary, ...rail]) expect(ADVICE_PANELS).not.toContain(panel)
      }
    }
  })

  it('keeps the library and the opponent in a ranked game', () => {
    expect(livePanels({ decisionPending: true, mulliganPhase: true, advice: false })).toEqual({
      primary: 'library',
      rail: ['opponent-read'],
    })
    expect(livePanels({ decisionPending: false, mulliganPhase: false, advice: false })).toEqual({
      primary: 'library',
      rail: ['opponent-hand-facts', 'opponent-read-dense'],
    })
  })

  it('leads with the opening hand and its keep guide when advice is allowed', () => {
    expect(livePanels({ decisionPending: true, mulliganPhase: true, advice: true })).toEqual({
      primary: 'opening-hand',
      rail: ['keep-guide'],
    })
    expect(livePanels({ decisionPending: false, mulliganPhase: true, advice: true })).toEqual({
      primary: 'keep-guide',
      rail: ['opponent-read'],
    })
    expect(livePanels({ decisionPending: false, mulliganPhase: false, advice: true })).toEqual({
      primary: 'library',
      rail: ['opponent-hand', 'opponent-read-dense'],
    })
  })
})

describe('railAlternatives', () => {
  const alternatives = [{ archetype_key: 'a' }, { archetype_key: 'b' }, { archetype_key: 'c' }]

  it('keeps every alternative beside an exact plan', () => {
    const got = railAlternatives({ alternatives, plan_basis: 'exact', plan: { archetype_key: 'z' } })
    expect(got).toEqual(alternatives)
  })

  it('drops the alternative the closest plan is', () => {
    const got = railAlternatives({ alternatives, plan_basis: 'closest', plan: { archetype_key: 'b' } })
    expect(got.map((a) => a.archetype_key)).toEqual(['a', 'c'])
  })

  it('drops the first when the closest plan has no archetype key', () => {
    const got = railAlternatives({ alternatives, plan_basis: 'closest', plan: { archetype_key: null } })
    expect(got.map((a) => a.archetype_key)).toEqual(['b', 'c'])
  })

  it('gives nothing for missing or null alternatives', () => {
    expect(railAlternatives({})).toEqual([])
    expect(railAlternatives({ alternatives: null, plan_basis: 'closest' })).toEqual([])
  })
})
