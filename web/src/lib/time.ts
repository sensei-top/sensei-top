import { useEffect, useState } from 'react'
import { currentT } from '../i18n'
import { formatDate, formatNumber } from './format'

/** Re-renders once a second so "updated Ns ago" stays honest between polls. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

/** Milliseconds since the epoch for a timestamp from the API, or `null`
 *  when it is absent or cannot be parsed. The database writes UTC without
 *  an offset in some paths, so a bare timestamp is read as UTC rather than
 *  silently as local time. The one place that reading lives: every function
 *  below, and `lib/home.ts`, go through it. */
export function parseTimestamp(iso: string | null | undefined): number | null {
  if (!iso) return null
  const normalised = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`
  const then = Date.parse(normalised)
  return Number.isNaN(then) ? null : then
}

/** How long ago `iso` was, in the largest whole unit: "59s ago", "1m ago",
 *  "3h ago", "6d ago". `null` when it cannot be parsed. Written in the
 *  language at the moment of the call (`time.ago.*`), so a caller outside a
 *  component still follows a change of language at its next render. */
export function ago(iso: string | null | undefined, now: number): string | null {
  const then = parseTimestamp(iso)
  if (then == null) return null

  const t = currentT()
  const seconds = Math.max(0, Math.round((now - then) / 1000))
  if (seconds < 60) return t('time.ago.seconds', { count: seconds })
  if (seconds < 3600) return t('time.ago.minutes', { count: Math.floor(seconds / 60) })
  if (seconds < 86_400) return t('time.ago.hours', { count: Math.floor(seconds / 3600) })
  return t('time.ago.days', { count: Math.floor(seconds / 86_400) })
}

/** Minutes since `iso`, or `null` when it can't be parsed — the raw number
 *  behind `ago()`'s formatted string, for callers that need to compare
 *  against a threshold (e.g. flagging a match `v_current_match` still calls
 *  current only because nothing newer has started yet — see
 *  `docs/current-match.md`). Same bare-timestamp-is-UTC normalisation. */
export function minutesSince(iso: string | null | undefined, now: number): number | null {
  const then = parseTimestamp(iso)
  if (then == null) return null
  return Math.max(0, (now - then) / 60_000)
}

/** An absolute date/time for a match, in the active language and the
 *  viewer's own zone. Same bare-timestamp-is-UTC normalisation as `ago`, so
 *  a match listed as "3h ago" and one listed by clock time never disagree
 *  about when it was. */
export function when(iso: string | null | undefined): string {
  const then = parseTimestamp(iso)
  if (then == null) return '—'
  return formatDate(then, { dateStyle: 'medium', timeStyle: 'short' })
}

/* The day and number formatters (D3): a date and a number read the same
 * way whatever the browser's own locale, in the active language
 * (`lib/format.ts`, so en-US for English) and the viewer's own zone. */

const LONG_DAY: Intl.DateTimeFormatOptions = { weekday: 'long', month: 'long', day: 'numeric' }
const LONG_DAY_YEAR: Intl.DateTimeFormatOptions = { ...LONG_DAY, year: 'numeric' }
const SHORT_DAY: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }
const SHORT_DAY_YEAR: Intl.DateTimeFormatOptions = { ...SHORT_DAY, year: 'numeric' }
const DAY_TIME: Intl.DateTimeFormatOptions = {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
}

const sameYear = (ms: number, now: number) => new Date(ms).getFullYear() === new Date(now).getFullYear()

/** "Sunday, September 27", and "Sunday, September 27, 2025" in a year
 *  other than `now`'s. */
export function formatLongDay(ms: number, now: number): string {
  return formatDate(ms, sameYear(ms, now) ? LONG_DAY : LONG_DAY_YEAR)
}

/** "Sep 27", and "Sep 27, 2025" in a year other than `now`'s. */
export function formatShortDay(ms: number, now: number): string {
  return formatDate(ms, sameYear(ms, now) ? SHORT_DAY : SHORT_DAY_YEAR)
}

/** A calendar date the API sends bare (`YYYY-MM-DD`, a format's reset) as
 *  "Sep 27": read from its own parts, never through a zone, so it cannot
 *  land on the day before. `null` for anything else. */
export function formatIsoDateShort(date: string, now: number): string | null {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date)
  if (!parts) return null
  const local = new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3])).getTime()
  return formatShortDay(local, now)
}

/** "Sep 27, 22:46". */
export function formatDayTime(ms: number): string {
  return formatDate(ms, DAY_TIME)
}

/** "1,032". */
export function formatCount(value: number): string {
  return formatNumber(value)
}

/** A share or a rate, 0..1, as a whole percentage without its sign: "46".
 *  `lib/format.ts`'s `formatPercent` is the one with its sign. */
export function formatPercent(fraction: number): string {
  return formatNumber(Math.round(fraction * 100))
}
