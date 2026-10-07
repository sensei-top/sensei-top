import { describe, expect, it } from 'vitest'
import { probAtLeastOneIn } from './odds'

describe('probAtLeastOneIn', () => {
  it('is the share of the library for one draw', () => {
    expect(probAtLeastOneIn(10, 1, 1)).toBeCloseTo(0.1, 12)
    expect(probAtLeastOneIn(60, 4, 1)).toBeCloseTo(4 / 60, 12)
  })

  it('is one minus the chance of none, without replacement', () => {
    // Two draws from 10 cards with 2 copies: none is 8/10 × 7/9.
    expect(probAtLeastOneIn(10, 2, 2)).toBeCloseTo(1 - (8 / 10) * (7 / 9), 12)
    // Four copies in 60, seven cards: none is
    // (53 × 52 × 51 × 50) / (60 × 59 × 58 × 57) = 7,027,800 / 11,703,240.
    expect(probAtLeastOneIn(60, 4, 7)).toBeCloseTo(1 - 7_027_800 / 11_703_240, 12)
  })

  it('is certain once the draws outnumber the other cards', () => {
    expect(probAtLeastOneIn(10, 10, 1)).toBe(1)
    expect(probAtLeastOneIn(5, 1, 5)).toBe(1)
    expect(probAtLeastOneIn(5, 1, 9)).toBe(1)
  })

  it('is zero with no library, no copy or no draw', () => {
    expect(probAtLeastOneIn(0, 4, 7)).toBe(0)
    expect(probAtLeastOneIn(60, 0, 7)).toBe(0)
    expect(probAtLeastOneIn(60, 4, 0)).toBe(0)
    expect(probAtLeastOneIn(60, 4, -2)).toBe(0)
  })
})
