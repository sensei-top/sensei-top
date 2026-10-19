import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import { patternSentence, patternWords } from './patterns'

/** The word joiner a record keeps each side of its dash. */
const WJ = '\u2060'

const t = translator('en')

describe('patternSentence', () => {
  it('writes each side as a record, wins then losses', () => {
    const clause = 'where you led the damage race'
    expect(patternSentence(clause, { wins: 1234, n: 2345 }, { wins: 1000, n: 1500 }, t)).toBe(
      `You are 1,234${WJ}–${WJ}1,111 in the matches where you led the damage race, and 1,000${WJ}–${WJ}500 in the rest.`,
    )
  })

  it('writes one match the same way', () => {
    // The sentence has one form: no singular for a single match.
    expect(patternSentence('where this happened', { wins: 1, n: 1 }, { wins: 0, n: 1 }, t)).toBe(
      `You are 1${WJ}–${WJ}0 in the matches where this happened, and 0${WJ}–${WJ}1 in the rest.`,
    )
  })
})

describe('patternWords', () => {
  it("is the table's title and clause for a code it knows, whatever the API's title", () => {
    expect(patternWords({ code: 'race_ahead', sample_title: 'Led the damage race' }, t)).toEqual({
      title: 'Ahead on damage, and still losing',
      clause: 'where you led the damage race',
    })
  })

  it("is the API's title and the generic clause for a code it does not know", () => {
    expect(patternWords({ code: 'some_new_code', sample_title: 'A new pattern' }, t)).toEqual({
      title: 'A new pattern',
      clause: 'where this happened',
    })
  })
})
