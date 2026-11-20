import { describe, expect, it } from 'vitest'
import { parseOpen, serializeOpen, toggleOpen } from './openParam'

describe('open param helpers', () => {
  it('parses a list, dropping blanks and repeats', () => {
    expect(parseOpen(null)).toEqual([])
    expect(parseOpen('')).toEqual([])
    expect(parseOpen('a, b,,a,c')).toEqual(['a', 'b', 'c'])
  })

  it('serializes to null when nothing is open', () => {
    expect(serializeOpen([])).toBeNull()
    expect(serializeOpen(['a', 'b', 'a'])).toBe('a,b')
  })

  it('toggles a slug in and out', () => {
    expect(toggleOpen(['a'], 'b')).toEqual(['a', 'b'])
    expect(toggleOpen(['a', 'b'], 'a')).toEqual(['b'])
  })
})
