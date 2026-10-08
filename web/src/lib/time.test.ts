import { describe, expect, it } from 'vitest'
import {
  ago,
  formatCount,
  formatDayTime,
  formatIsoDateShort,
  formatLongDay,
  formatPercent,
  formatShortDay,
  minutesSince,
  parseTimestamp,
} from './time'

// The zone is America/New_York (vitest.config.ts): four hours behind UTC in
// September, five in January.

describe('parseTimestamp', () => {
  it('reads a bare timestamp as UTC, not as the viewer’s own time', () => {
    expect(parseTimestamp('2026-09-27T22:46:00')).toBe(Date.UTC(2026, 8, 27, 22, 46, 0))
  })

  it('keeps an offset that is written', () => {
    expect(parseTimestamp('2026-09-27T22:46:00Z')).toBe(Date.UTC(2026, 8, 27, 22, 46, 0))
    expect(parseTimestamp('2026-09-27T22:46:00+02:00')).toBe(Date.UTC(2026, 8, 27, 20, 46, 0))
  })

  it('is null for nothing and for what is not a timestamp', () => {
    expect(parseTimestamp(null)).toBeNull()
    expect(parseTimestamp(undefined)).toBeNull()
    expect(parseTimestamp('')).toBeNull()
    expect(parseTimestamp('yesterday')).toBeNull()
  })
})

describe('ago', () => {
  const then = '2026-09-27T12:00:00'
  const at = (seconds: number) => Date.UTC(2026, 8, 27, 12, 0, 0) + seconds * 1000

  it('changes unit at the minute, the hour and the day', () => {
    expect(ago(then, at(59))).toBe('59s ago')
    expect(ago(then, at(60))).toBe('1m ago')
    expect(ago(then, at(3599))).toBe('59m ago')
    expect(ago(then, at(3600))).toBe('1h ago')
    expect(ago(then, at(86_399))).toBe('23h ago')
    expect(ago(then, at(86_400))).toBe('1d ago')
  })

  it('never counts below zero for a timestamp ahead of the clock', () => {
    expect(ago(then, at(-30))).toBe('0s ago')
  })

  it('is null without a timestamp', () => {
    expect(ago(null, at(0))).toBeNull()
  })
})

describe('minutesSince', () => {
  it('is the minutes between the timestamp and the clock', () => {
    expect(minutesSince('2026-09-27T12:00:00', Date.UTC(2026, 8, 27, 13, 30, 0))).toBe(90)
  })

  it('is null without a timestamp', () => {
    expect(minutesSince(undefined, 0)).toBeNull()
  })
})

describe('the formatters', () => {
  const now = Date.UTC(2026, 8, 28, 15, 0, 0)
  // 02:46 UTC on the 28th is 22:46 on the 27th, a Sunday, in New York.
  const sundayNight = Date.UTC(2026, 8, 28, 2, 46, 0)

  it('write a day in the viewer’s zone', () => {
    expect(formatLongDay(sundayNight, now)).toBe('Sunday, September 27')
    expect(formatShortDay(sundayNight, now)).toBe('Sep 27')
    expect(formatDayTime(sundayNight)).toBe('Sep 27, 22:46')
  })

  it('name the year when it is not the clock’s', () => {
    const lastYear = Date.UTC(2025, 8, 27, 16, 0, 0)
    expect(formatLongDay(lastYear, now)).toBe('Saturday, September 27, 2025')
    expect(formatShortDay(lastYear, now)).toBe('Sep 27, 2025')
  })

  it('write a bare date as its own day, west of UTC too', () => {
    expect(formatIsoDateShort('2026-09-27', now)).toBe('Sep 27')
    expect(formatIsoDateShort('2025-01-01', now)).toBe('Jan 1, 2025')
  })

  it('refuse a date that is not bare', () => {
    expect(formatIsoDateShort('2026-09-27T00:00:00', now)).toBeNull()
    expect(formatIsoDateShort('soon', now)).toBeNull()
  })

  it('write a count and a percentage', () => {
    expect(formatCount(1032)).toBe('1,032')
    expect(formatCount(7)).toBe('7')
    expect(formatPercent(0.5)).toBe('50')
    expect(formatPercent(0.004)).toBe('0')
    expect(formatPercent(1)).toBe('100')
  })
})
