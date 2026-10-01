import { describe, expect, it } from 'vitest'
import { livePanels } from './livePanels'

const ADVICE_PANELS = ['opening-hand', 'keep-guide', 'keep-guide-dense', 'opponent-hand']

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
      rail: ['opponent-hand', 'keep-guide-dense', 'opponent-read-dense'],
    })
  })
})
