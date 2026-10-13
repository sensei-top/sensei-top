import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import { writtenLine, writtenNote } from './written'

const t = translator('en')

// Midday in UTC, a bare timestamp as the API sends it: the morning of the
// same day in New York.
const now = Date.parse('2026-09-29T12:00:00Z')

describe('writtenLine', () => {
  it('names the author and the day', () => {
    expect(writtenLine('claude-opus-5', '2026-09-18T12:00:00', now, t)).toBe('Written by claude-opus-5 on Sep 18.')
  })

  it('adds the year to a day of another year', () => {
    expect(writtenLine('claude-opus-5', '2025-09-18T12:00:00', now, t)).toBe(
      'Written by claude-opus-5 on Sep 18, 2025.',
    )
  })

  it('reads the day alone with no author', () => {
    expect(writtenLine(null, '2026-09-18T12:00:00', now, t)).toBe('Written on Sep 18.')
  })

  it('reads the author alone with no day', () => {
    expect(writtenLine('claude-opus-5', null, now, t)).toBe('Written by claude-opus-5.')
  })

  it('reads the author alone with a day that cannot be read', () => {
    expect(writtenLine('claude-opus-5', 'not a day', now, t)).toBe('Written by claude-opus-5.')
  })

  it('is null with neither', () => {
    expect(writtenLine(null, null, now, t)).toBeNull()
    expect(writtenLine(undefined, 'not a day', now, t)).toBeNull()
  })
})

describe('writtenNote', () => {
  it('joins all three sentences, the caller\'s own stale sentence last', () => {
    expect(
      writtenNote({
        author: 'claude-opus-5',
        authoredAt: '2026-09-18T12:00:00',
        costUsd: 0.539,
        stale: true,
        staleNote: 'The list has changed since.',
        now,
      }, t),
    ).toBe('Written by claude-opus-5 on Sep 18. It cost $0.539. The list has changed since.')
  })

  it('falls back to the default stale sentence with none of its own', () => {
    expect(
      writtenNote({
        author: 'claude-opus-5',
        authoredAt: '2025-09-18T12:00:00',
        costUsd: null,
        stale: true,
        staleNote: undefined,
        now,
      }, t),
    ).toBe('Written by claude-opus-5 on Sep 18, 2025. The evidence has changed since.')
  })

  it('shows a cost of 0, with three decimals', () => {
    expect(
      writtenNote({ author: null, authoredAt: null, costUsd: 0, stale: false, staleNote: undefined, now }, t),
    ).toBe('It cost $0.000.')
  })

  it('says nothing about cost when it is null or undefined', () => {
    expect(
      writtenNote({
        author: null,
        authoredAt: '2026-09-18T12:00:00',
        costUsd: null,
        stale: false,
        staleNote: undefined,
        now,
      }, t),
    ).toBe('Written on Sep 18.')
    expect(
      writtenNote({
        author: null,
        authoredAt: '2026-09-18T12:00:00',
        costUsd: undefined,
        stale: false,
        staleNote: undefined,
        now,
      }, t),
    ).toBe('Written on Sep 18.')
  })

  it('leaves the stale sentence out when stale is false, even when the caller gives one', () => {
    expect(
      writtenNote({
        author: 'claude-opus-5',
        authoredAt: null,
        costUsd: null,
        stale: false,
        staleNote: 'The list has changed since.',
        now,
      }, t),
    ).toBe('Written by claude-opus-5.')
  })

  it('shows the cost alone', () => {
    expect(
      writtenNote({ author: null, authoredAt: null, costUsd: 0.004, stale: false, staleNote: undefined, now }, t),
    ).toBe('It cost $0.004.')
  })

  it('is null when there is nothing to say', () => {
    expect(
      writtenNote({ author: null, authoredAt: null, costUsd: null, stale: false, staleNote: undefined, now }, t),
    ).toBeNull()
  })
})
