import { describe, expect, it } from 'vitest'
import type { LibraryCardOut } from '../api'
import { groupByManaValue, landsLine, rowChance } from './library'

function card(over: Partial<LibraryCardOut>): LibraryCardOut {
  return {
    grp_id: 1,
    name: 'X',
    quantity: 1,
    left: 1,
    is_land: false,
    mana_value: 1,
    is_interaction: null,
    ...over,
  } as LibraryCardOut
}

describe('groupByManaValue', () => {
  it('orders by mana value, an unknown one last, names sorted, lands left out', () => {
    const groups = groupByManaValue([
      card({ grp_id: 1, name: 'Zed', mana_value: 3, left: 2 }),
      card({ grp_id: 2, name: 'Mystery', mana_value: null, left: 1 }),
      card({ grp_id: 3, name: 'Bolt', mana_value: 1, left: 4 }),
      card({ grp_id: 4, name: 'Alpha', mana_value: 3, left: 1 }),
      card({ grp_id: 5, name: 'Forest', is_land: true, mana_value: 0, left: 9 }),
    ])
    expect(groups.map((g) => g.manaValue)).toEqual([1, 3, 99])
    expect(groups[1].cards.map((c) => c.name)).toEqual(['Alpha', 'Zed'])
    expect(groups[2].cards.map((c) => c.name)).toEqual(['Mystery'])
  })
})

describe('landsLine', () => {
  // 10 cards in the library, 4 of them lands (3 + 1 left). P(no land in 3
  // draws) = 6/10 * 5/9 * 4/8 = 120/720 = 1/6, so at least one is 5/6. The
  // total is the deck's 16 lands, not read off the rows.
  it('sums lands left, takes the total from the deck and works the chance', () => {
    const line = landsLine(
      [
        card({ grp_id: 1, is_land: true, left: 3, quantity: 12 }),
        card({ grp_id: 2, is_land: true, left: 1, quantity: 4 }),
        card({ grp_id: 3, left: 6, quantity: 8 }),
      ],
      10,
      16,
    )
    expect(line.left).toBe(4)
    expect(line.total).toBe(16)
    expect(line.chance).toBeCloseTo(5 / 6, 10)
  })

  // A land stack that ran out is absent from the rows (the server drops a
  // fully seen card); only the 12-stack is left, 2 of 12. The deck still has
  // 16 lands, so the total stays 16.
  it('keeps the deck total when a land row has run out', () => {
    const line = landsLine([card({ grp_id: 1, is_land: true, left: 2, quantity: 12 })], 20, 16)
    expect(line.left).toBe(2)
    expect(line.total).toBe(16)
  })

  it('leaves the total null when the deck count is unknown', () => {
    const line = landsLine([card({ is_land: true, left: 2, quantity: 12 })], 20, null)
    expect(line.total).toBeNull()
    expect(line.left).toBe(2)
  })

  // A library of 2 with 1 land: only 2 cards can be drawn. P(none) = 1/2 * 0/1
  // = 0, so the chance is 1.
  it('caps the draws at a library under three cards', () => {
    expect(landsLine([card({ is_land: true, left: 1 })], 2, 24).chance).toBe(1)
  })
})

describe('rowChance', () => {
  // 40-card library, 4 copies: P(none in 3) = 36/40 * 35/39 * 34/38
  // = 42840/59280 = 0.72267..., so at least one is 0.27733...
  it('works a 4-of in a 40-card library', () => {
    expect(rowChance(40, 4)).toBeCloseTo(1 - 42840 / 59280, 10)
  })

  // 3 cards left, 1 copy: P(none) = 2/3 * 1/2 * 0/1 = 0 -> certain.
  it('is certain when the library is the three draws', () => {
    expect(rowChance(3, 1)).toBe(1)
  })
})
