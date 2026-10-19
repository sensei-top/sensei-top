import { describe, expect, it } from 'vitest'
import type { LibraryCardOut } from '../api'
import { groupByManaValue, landsLine, nextDrawChance } from './library'

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
  it('orders by mana value, an unknown one last, most copies left first, lands left out', () => {
    const groups = groupByManaValue([
      card({ grp_id: 1, name: 'Zed', mana_value: 3, left: 2 }),
      card({ grp_id: 2, name: 'Mystery', mana_value: null, left: 1 }),
      card({ grp_id: 3, name: 'Bolt', mana_value: 1, left: 4 }),
      card({ grp_id: 4, name: 'Alpha', mana_value: 3, left: 1 }),
      card({ grp_id: 5, name: 'Forest', is_land: true, mana_value: 0, left: 9 }),
      card({ grp_id: 6, name: 'Beta', mana_value: 3, left: 1 }),
    ])
    expect(groups.map((g) => g.manaValue)).toEqual([1, 3, 99])
    expect(groups[1].cards.map((c) => c.name)).toEqual(['Zed', 'Alpha', 'Beta'])
    expect(groups[2].cards.map((c) => c.name)).toEqual(['Mystery'])
  })

  it('keeps a row whose copies are all seen, last in its group', () => {
    const groups = groupByManaValue([
      card({ grp_id: 1, name: 'Aardvark', mana_value: 2, left: 0, quantity: 4 }),
      card({ grp_id: 2, name: 'Zebra', mana_value: 2, left: 1, quantity: 2 }),
    ])
    expect(groups[0].cards.map((c) => c.name)).toEqual(['Zebra', 'Aardvark'])
  })
})

describe('landsLine', () => {
  // 10 cards in the library, 4 of them lands (3 + 1 left). Next draw: 4/10.
  // Within 2: P(none) = 6/10 * 5/9 = 1/3, so 2/3. Within 3: P(none) =
  // 6/10 * 5/9 * 4/8 = 1/6, so 5/6. The total is every land row's quantity.
  it('sums lands left and the deck total, and works each horizon', () => {
    const line = landsLine(
      [
        card({ grp_id: 1, is_land: true, left: 3, quantity: 12 }),
        card({ grp_id: 2, is_land: true, left: 1, quantity: 4 }),
        card({ grp_id: 3, left: 6, quantity: 8 }),
      ],
      10,
    )
    expect(line.left).toBe(4)
    expect(line.total).toBe(16)
    expect(line.chances[0]).toBeCloseTo(4 / 10, 10)
    expect(line.chances[1]).toBeCloseTo(2 / 3, 10)
    expect(line.chances[2]).toBeCloseTo(5 / 6, 10)
  })

  // A land stack that ran out stays in the rows at 0 left, so the deck's
  // 16 lands still add up.
  it('keeps the deck total when a land row has run out', () => {
    const line = landsLine(
      [
        card({ grp_id: 1, is_land: true, left: 2, quantity: 12 }),
        card({ grp_id: 2, is_land: true, left: 0, quantity: 4 }),
      ],
      20,
    )
    expect(line.left).toBe(2)
    expect(line.total).toBe(16)
  })

  // A library of 2 with 1 land: only 2 cards can be drawn. P(none) = 1/2 * 0/1
  // = 0, so within 2 and within 3 are both certain.
  it('caps the draws at a library under three cards', () => {
    expect(landsLine([card({ is_land: true, left: 1 })], 2).chances).toEqual([0.5, 1, 1])
  })
})

describe('nextDrawChance', () => {
  it('is copies left over cards left', () => {
    expect(nextDrawChance(40, 4)).toBeCloseTo(0.1, 10)
  })

  it('is zero once every copy is seen', () => {
    expect(nextDrawChance(40, 0)).toBe(0)
  })
})
