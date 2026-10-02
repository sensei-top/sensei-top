/**
 * Everything the Field page counts and says, as pure functions of the
 * API's rows and a clock (`now`, milliseconds since the epoch), and the one
 * hook that reads its three parameters from the address. The view in
 * `views/FieldView.tsx` only draws what these return.
 *
 * The parameters follow `lib/filters.ts`'s rules: absent or unknown means
 * the default, and a setter replaces the history entry and keeps the
 * scroll. A default is computed from what the API sends and never written
 * into the address, so a bare `/field` stays bare.
 */
import { useSearchParams } from 'react-router'
import type { Match, MetaMatchup, MetaPresence, MetaWinrate, MetaWindow } from '../api'
import { MIN_TRUSTED_FIELD_SAMPLE } from '../theme'
import type { FieldRecord, Tier } from './home'
import {
  HOME_MATCH_LIMIT,
  TIERS,
  fieldWindowStart,
  firstTierWithLists,
  hasLists,
  recordAgainst,
  startOf,
} from './home'
import { ago, formatIsoDateShort } from './time'

const DAY = 24 * 3_600_000

/* ------------------------------------------------------------ the address */

export type FieldParam = 'window' | 'tier' | 'pairs'

/** The three parameters as the address holds them, unread. */
export type FieldParams = Record<FieldParam, string | null>

/** The three parameters, and a setter that writes one (`undefined` takes
 *  it out of the address). */
export function useFieldParams(): {
  params: FieldParams
  setParam: (key: FieldParam, value: string | undefined) => void
} {
  const [search, setSearch] = useSearchParams()
  return {
    params: { window: search.get('window'), tier: search.get('tier'), pairs: search.get('pairs') },
    setParam: (key, value) =>
      setSearch(
        (previous) => {
          const next = new URLSearchParams(previous)
          if (value) next.set(key, value)
          else next.delete(key)
          return next
        },
        { replace: true, preventScrollReset: true },
      ),
  }
}

/** What a setter writes for `value`: nothing when it is the default, so
 *  choosing the default leaves the address as a bare `/field` has it. */
export function paramFor(value: string, fallback: string): string | undefined {
  return value === fallback ? undefined : value
}

/* ------------------------------------------------------------ the window */

/** A window of days back from today, or the format's last reset. */
export type FieldWindow = 'reset' | number

export const DAY_WINDOWS = [7, 15, 30, 90, 180, 365] as const

/** The window with no reset known. */
export const FALLBACK_DAYS = 90

/** The status's reset when it is a bare date the page can read, else
 *  `null`. */
export function resetOf(formatResetStart: string | null | undefined): string | null {
  return formatResetStart && /^\d{4}-\d{2}-\d{2}$/.test(formatResetStart) ? formatResetStart : null
}

/** The window a bare `/field` opens on: the reset when one is known, else
 *  the last 90 days. */
export function defaultWindow(reset: string | null): FieldWindow {
  return reset ? 'reset' : FALLBACK_DAYS
}

/** `?window=`: `reset` or one of the day counts; absent or unknown is the
 *  default, and `reset` with no reset known is the last 90 days. */
export function windowOf(raw: string | null, reset: string | null): FieldWindow {
  if (raw === 'reset') return reset ? 'reset' : FALLBACK_DAYS
  const days = (DAY_WINDOWS as readonly number[]).find((d) => String(d) === raw)
  return days ?? defaultWindow(reset)
}

/** The window as the metagame hooks ask for it. */
export function metaWindowOf(window: FieldWindow, reset: string | null): MetaWindow {
  return window === 'reset' && reset ? { since: reset } : { days: window === 'reset' ? FALLBACK_DAYS : window }
}

/** The window's start, in ms: the reset as Home reads it (00:00 UTC), else
 *  the day count back from `now`. */
export function windowStartOf(window: FieldWindow, reset: string | null, now: number): number {
  return window === 'reset' && reset ? fieldWindowStart(reset, now) : now - (window === 'reset' ? FALLBACK_DAYS : window) * DAY
}

/** The window's words: `when` inside a sentence ("since Aug 11", "in the
 *  last 30 days"), `short` as a card's action ("since Aug 11", "last 30
 *  days"). */
export function windowWords(window: FieldWindow, reset: string | null, now: number): { when: string; short: string } {
  if (window === 'reset' && reset) {
    const since = `since ${formatIsoDateShort(reset, now) ?? reset}`
    return { when: since, short: since }
  }
  const days = window === 'reset' ? FALLBACK_DAYS : window
  return { when: `in the last ${days} days`, short: `last ${days} days` }
}

/** The window select's options, the reset first when one is known. */
export function windowOptions(reset: string | null, now: number): { value: string; label: string }[] {
  const days = DAY_WINDOWS.map((d) => ({ value: String(d), label: `Last ${d} days` }))
  return reset
    ? [{ value: 'reset', label: `Since the last reset (${formatIsoDateShort(reset, now) ?? reset})` }, ...days]
    : days
}

/* ------------------------------------------------------------ the tiers */

// The tiers and their rank order live in `lib/home.ts`, which reads Home's
// field from the same walk; this module already imports from it.
export type { Tier }
export { TIERS }

/** A tier's lists in a sentence. */
export const TIER_KIND: Record<Tier, string> = {
  A: 'paper tournaments of 64+ players',
  B: 'MTGO challenges',
  C: 'MTGO leagues',
  D: 'paper tournaments under 64 players',
}

/** A tier in the `Segmented`. */
export const TIER_OPTION: Record<Tier, string> = {
  A: 'Paper 64+',
  B: 'MTGO challenges',
  C: 'MTGO leagues',
  D: 'Paper under 64',
}

/** The first tier in rank order with lists in the window: A, then B, then
 *  C, then D, as Home reads its field (`firstTierWithLists`). With no list
 *  in any tier, A, the first. */
export function defaultTier(presence: MetaPresence[]): Tier {
  return firstTierWithLists(presence) ?? 'A'
}

/** `?tier=`: `A`, `B`, `C` or `D`; absent or unknown is the default. */
export function tierOf(raw: string | null, presence: MetaPresence[]): Tier {
  return TIERS.find((tier) => tier === raw) ?? defaultTier(presence)
}

/** The tiers the matchups are counted over, one step at a time: paper
 *  tournaments of 64+ players alone, then with MTGO challenges, then with
 *  smaller paper events too. A league (C) is never counted: it publishes
 *  no losses. */
export type Pairs = 'A' | 'AB' | 'ABD'

export const PAIRS: readonly Pairs[] = ['A', 'AB', 'ABD']

export const PAIRS_TIERS: Record<Pairs, string[]> = { A: ['A'], AB: ['A', 'B'], ABD: ['A', 'B', 'D'] }

/** A step of the pairs in the `Segmented`: each after the first adds a
 *  tier to the one before. */
export const PAIRS_OPTION: Record<Pairs, string> = {
  A: 'Paper 64+',
  AB: '+ MTGO challenges',
  ABD: '+ smaller paper',
}

/** The first step with lists: A when tier A has lists in the window, else
 *  AB when tier B has, else ABD. */
export function defaultPairs(presence: MetaPresence[]): Pairs {
  if (hasLists(presence, 'A')) return 'A'
  if (hasLists(presence, 'B')) return 'AB'
  return 'ABD'
}

/** `?pairs=`: `A`, `AB` or `ABD`; absent or unknown is the default. */
export function pairsOf(raw: string | null, presence: MetaPresence[]): Pairs {
  return PAIRS.find((pairs) => pairs === raw) ?? defaultPairs(presence)
}

/** The step empty matchups offer, never a dead end: from A, AB when tier
 *  B has lists in the window, else ABD when tier D has (counting B would
 *  add nothing); from AB, ABD when tier D has lists; else none. */
export function nextPairs(pairs: Pairs, presence: MetaPresence[]): Pairs | null {
  if (pairs === 'ABD') return null
  if (pairs === 'A' && hasLists(presence, 'B')) return 'AB'
  return hasLists(presence, 'D') ? 'ABD' : null
}

/** The empty matchups' sentence, naming the tiers counted up to the last
 *  step, which counts every tier with rounds. */
export function noPairsMessage(pairs: Pairs | null, when: string): string {
  if (pairs === 'A') return `No rounds between two named decks in paper tournaments of 64+ players ${when}.`
  if (pairs === 'AB')
    return `No rounds between two named decks in paper tournaments of 64+ players or MTGO challenges ${when}.`
  return `No rounds between two named decks ${when}.`
}

/** "MTGO challenges since Aug 11", "Paper tournaments of 64+ players, last
 *  30 days": the share card's action, the comma only before "last". */
export function shareAction(tier: Tier, window: FieldWindow, reset: string | null, now: number): string {
  const kind = TIER_KIND[tier]
  const { short } = windowWords(window, reset, now)
  const head = kind.charAt(0).toUpperCase() + kind.slice(1)
  return short.startsWith('last') ? `${head}, ${short}` : `${head} ${short}`
}

/* ------------------------------------------------------------ the rows */

/** How many rows a card shows before its button shows the rest. */
export const SHARE_SHOWN = 12
export const WINRATE_SHOWN = 12
export const MATCHUPS_SHOWN = 20

/** The rows a card shows: the first `limit` until the rest are asked for. */
export function shownRows<T>(rows: T[], limit: number, all: boolean): T[] {
  return all ? rows : rows.slice(0, limit)
}

/** A win rate needs this many finished matches to be listed. */
export const WINRATE_MIN_MATCHES = 2

/** Below this many matches, a matchup's rate is muted. */
export const MATCHUP_THIN = MIN_TRUSTED_FIELD_SAMPLE

const byName = (a: string, b: string) => a.localeCompare(b, 'en')

/** The tier's rows with lists, the most played first, then by name. */
export function shareRows(presence: MetaPresence[], tier: Tier): MetaPresence[] {
  return presence
    .filter((row) => row.tier === tier && row.decks > 0)
    .sort((a, b) => b.decks - a.decks || byName(a.label, b.label))
}

/** Every list of the tier in the window. */
export function listCount(rows: MetaPresence[]): number {
  return rows.reduce((sum, row) => sum + row.decks, 0)
}

export const matchesOf = (row: MetaWinrate) => row.matches_won + row.matches_lost + row.matches_drawn

/** Rows with two finished matches or more, the most matches first, then
 *  the highest rate, then by name: sorted by rate alone, the top rows are
 *  decks of one list on a handful of matches. */
export function winrateRows(rows: MetaWinrate[]): MetaWinrate[] {
  return rows
    .filter((row) => matchesOf(row) >= WINRATE_MIN_MATCHES && row.winrate != null)
    .sort(
      (a, b) =>
        matchesOf(b) - matchesOf(a) || (b.winrate ?? 0) - (a.winrate ?? 0) || byName(a.label, b.label),
    )
}

/** The most matches first, then by the archetype's name, then the
 *  opponent's. */
export function matchupRows(rows: MetaMatchup[]): MetaMatchup[] {
  return rows
    .slice()
    .sort((a, b) => b.n - a.n || byName(a.label, b.label) || byName(a.opponent_label, b.opponent_label))
}

/* ------------------------------------------------------------ the viewer */

/** The viewer's record against one row, or the first rows together, in
 *  the window, over every deck of theirs (Home's `recordAgainst`, with no
 *  deck named): a match counts for a row when its opponent carries the
 *  row's key and the row's label. */
export function recordAgainstRows(matches: Match[], rows: MetaPresence[], windowStart: number): FieldRecord {
  return recordAgainst(matches, rows, windowStart)
}

/** Home's rule: the list is full when it holds the limit and the heartbeat
 *  counts more matches than it holds (or has not answered), and short when
 *  its oldest match started after the window's. */
export function listShort(matches: Match[], liveMatches: number | undefined, windowStart: number): boolean {
  const full = matches.length >= HOME_MATCH_LIMIT && (liveMatches == null || liveMatches > matches.length)
  if (!full) return false
  const starts = matches.map(startOf).filter((start): start is number => start != null)
  return starts.length > 0 && Math.min(...starts) > windowStart
}

/* ------------------------------------------------------------ the sources */

/** Older than this, the results or the rules are worth downloading again. */
export const STALE_HOURS = 7 * 24

/** `ago()`'s form without its "ago": "6d", "5h". */
export function ageWords(hours: number): string {
  return (ago(new Date(0).toISOString(), Math.max(0, hours) * 3_600_000) ?? '').replace(/ ago$/, '')
}

/** Never fetched, or fetched more than seven days ago. */
export function isStale(hours: number | null | undefined): boolean {
  return hours == null || hours > STALE_HOURS
}
