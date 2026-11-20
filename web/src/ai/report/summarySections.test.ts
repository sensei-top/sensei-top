import { describe, expect, it } from 'vitest'
import { summaryBody, summaryTeaser } from './summarySections'

const FULL = {
  games: 'Game 1 turned on a mulligan.',
  key_leak: 'You kept two-landers. It cost game 2.',
  counter_argument: 'The opponent drew well.',
  confidence: 'Medium.',
}

describe('summaryBody', () => {
  it('lists the four parts in reading order', () => {
    const body = summaryBody({ confidence: 'c', games: 'g', counter_argument: 'x', key_leak: 'k' }, 'prose')
    expect(body).toEqual({
      kind: 'sections',
      parts: [
        { key: 'games', text: 'g' },
        { key: 'key_leak', text: 'k' },
        { key: 'counter_argument', text: 'x' },
        { key: 'confidence', text: 'c' },
      ],
    })
  })

  it('skips a blank part', () => {
    const body = summaryBody({ ...FULL, counter_argument: '   ' }, 'prose')
    expect(body.kind === 'sections' && body.parts.map((p) => p.key)).toEqual(['games', 'key_leak', 'confidence'])
  })

  it('falls back on the prose for an older narrative', () => {
    expect(summaryBody(null, 'One paragraph.')).toEqual({ kind: 'prose', text: 'One paragraph.' })
    expect(summaryBody(undefined, 'One paragraph.')).toEqual({ kind: 'prose', text: 'One paragraph.' })
    expect(summaryBody({ games: ' ', key_leak: '', counter_argument: '', confidence: '' }, 'P.')).toEqual({
      kind: 'prose',
      text: 'P.',
    })
  })
})

describe('summaryTeaser', () => {
  it("is the key leak's first sentence", () => {
    expect(summaryTeaser(FULL)).toBe('You kept two-landers.')
  })

  it('is null without a key leak', () => {
    expect(summaryTeaser(null)).toBeNull()
    expect(summaryTeaser({ ...FULL, key_leak: ' ' })).toBeNull()
  })
})
