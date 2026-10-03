import { describe, expect, it } from 'vitest'
import { NBSP } from './matchups'
import { patternSentence, patternWords } from './patterns'

describe('patternSentence', () => {
  it('writes counts over 999 with a thousands comma, and holds the count to "matches"', () => {
    const clause = 'where you led the damage race'
    expect(patternSentence(clause, { wins: 1234, n: 2345 }, { wins: 1000, n: 1500 })).toBe(
      `You won 1,234 of the 2,345${NBSP}matches where you led the damage race, and 1,000 of the other 1,500.`,
    )
  })

  it('writes one match the same way, as the Guide has always written it', () => {
    // The sentence has one form: no singular for a single match.
    expect(patternSentence('where this happened', { wins: 1, n: 1 }, { wins: 0, n: 1 })).toBe(
      `You won 1 of the 1${NBSP}matches where this happened, and 0 of the other 1.`,
    )
  })
})

describe('patternWords', () => {
  it("is the table's title and clause for a code it knows, whatever the API's title", () => {
    expect(patternWords({ code: 'race_ahead', sample_title: 'Led the damage race' })).toEqual({
      title: 'Ahead on damage, and still losing',
      clause: 'where you led the damage race',
    })
  })

  it("is the API's title and the generic clause for a code it does not know", () => {
    expect(patternWords({ code: 'some_new_code', sample_title: 'A new pattern' })).toEqual({
      title: 'A new pattern',
      clause: 'where this happened',
    })
  })
})
