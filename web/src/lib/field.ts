/**
 * Everything the Field page counts and says, as pure functions of the
 * API's rows and a clock (`now`, milliseconds since the epoch), and the one
 * hook that reads its four parameters from the address. The view in
 * `views/FieldView.tsx` only draws what these return.
 *
 * The parameters follow `lib/filters.ts`'s rules: absent or unknown means
 * the default, and a setter replaces the history entry and keeps the
 * scroll. A default is computed from what the API sends and never written
 * into the address, so a bare `/field` stays bare.
 */
import { useSearchParams } from 'react-router'
import type {
  FormatEntry,
  FormatsOut,
  Match,
  MetaMatchup,
  MetaPresence,
  MetaWinrate,
  MetaWindow,
  MetagameStatus,
} from '../api'
import type { TFunction } from '../i18n'
import type { FieldRecord, Tier } from './home'
import {
  HOME_MATCH_LIMIT,
  TIERS,
  fieldWindowStart,
  firstTierWithLists,
  hasLists,
  matchesInFormat,
  recordAgainst,
  startOf,
} from './home'
import { WINRATE_MIN_MATCHES, rateAndRecordLine, rateOrRecord } from './sample'
import { type HoldSource, holdLine } from './sources'
import { formatCount, formatIsoDateShort } from './time'

export { matchesInFormat }

const DAY = 24 * 3_600_000

/* ------------------------------------------------------------ the address */

export type FieldParam = 'format' | 'window' | 'tier' | 'pairs'

/** The four parameters as the address holds them, unread. */
export type FieldParams = Record<FieldParam, string | null>

/** The four parameters, and a setter that writes one (`undefined` takes
 *  it out of the address). */
export function useFieldParams(): {
  params: FieldParams
  setParam: (key: FieldParam, value: string | undefined) => void
} {
  const [search, setSearch] = useSearchParams()
  return {
    params: {
      format: search.get('format'),
      window: search.get('window'),
      tier: search.get('tier'),
      pairs: search.get('pairs'),
    },
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

/* ------------------------------------------------------------ the format */

/** `?format=`: a format `/api/formats` lists; absent or unknown is the
 *  default it reports (D13), never written into the address. */
export function formatOf(raw: string | null, formats: FormatsOut): string {
  return formats.formats.find((entry) => entry.format === raw)?.format ?? formats.default
}

/** The formats the control offers: those with matches or tournament events,
 *  in the API's order, and always `selected` (the address's), even when it
 *  holds neither. */
export function formatChoices(formats: FormatsOut, selected: string): FormatEntry[] {
  return formats.formats.filter(
    (entry) => entry.format === selected || entry.matches.total > 0 || entry.corpus_events > 0,
  )
}

/** Whether any format holds matches or tournament events. */
export function anyFormatData(formats: FormatsOut): boolean {
  return formats.formats.some((entry) => entry.matches.total > 0 || entry.corpus_events > 0)
}

/** The caption under the control: the viewer's own matches in the format
 *  and where each was read from, parts at 0 left out. */
export function formatCaption(entry: FormatEntry, t: TFunction): string {
  const { format, matches } = entry
  if (matches.total === 0) return t('field.format.none', { format })
  const parts = [
    matches.log > 0 ? t('field.format.fromLog', { n: formatCount(matches.log) }) : null,
    matches.pick > 0 ? t('field.format.confirmed', { n: formatCount(matches.pick) }) : null,
    matches.inferred > 0 ? t('field.format.inferred', { n: formatCount(matches.inferred) }) : null,
  ].filter((part): part is string => part != null)
  const head = t('field.format.head', { count: matches.total, n: formatCount(matches.total), format })
  return parts.length > 0 ? t('field.format.withParts', { head, parts: parts.join(', ') }) : t('field.format.headOnly', { head })
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

/** The window's start, in ms: the reset as Home reads it (the viewer's local
 *  midnight), else the day count back from `now`. */
export function windowStartOf(window: FieldWindow, reset: string | null, now: number): number {
  return window === 'reset' && reset ? fieldWindowStart(reset, now) : now - (window === 'reset' ? FALLBACK_DAYS : window) * DAY
}

/** The window's words: `when` inside a sentence ("since Aug 11", "in the
 *  last 30 days"), `short` as a card's action ("since Aug 11", "last 30
 *  days"). */
export function windowWords(
  window: FieldWindow,
  reset: string | null,
  now: number,
  t: TFunction,
): { when: string; short: string } {
  if (window === 'reset' && reset) {
    const since = t('field.window.since', { date: formatIsoDateShort(reset, now) ?? reset })
    return { when: since, short: since }
  }
  const days = window === 'reset' ? FALLBACK_DAYS : window
  return { when: t('field.window.whenLast', { days }), short: t('field.window.shortLast', { days }) }
}

/** The window select's options, the reset first when one is known. */
export function windowOptions(reset: string | null, now: number, t: TFunction): { value: string; label: string }[] {
  const days = DAY_WINDOWS.map((d) => ({ value: String(d), label: t('field.window.optionLast', { days: d }) }))
  return reset
    ? [{ value: 'reset', label: t('field.window.optionReset', { date: formatIsoDateShort(reset, now) ?? reset }) }, ...days]
    : days
}

/* ------------------------------------------------------------ the tiers */

// The tiers and their rank order live in `lib/home.ts`, which reads Home's
// field from the same walk; this module already imports from it.
export type { Tier }
export { TIERS }

/** A tier's lists in a sentence. */
export function tierKind(tier: Tier, t: TFunction): string {
  const kinds: Record<Tier, string> = {
    A: t('field.tier.kind.A'),
    B: t('field.tier.kind.B'),
    C: t('field.tier.kind.C'),
    D: t('field.tier.kind.D'),
  }
  return kinds[tier]
}

/** A tier in the `Segmented`. */
export function tierOption(tier: Tier, t: TFunction): string {
  const options: Record<Tier, string> = {
    A: t('field.tier.option.A'),
    B: t('field.tier.option.B'),
    C: t('field.tier.option.C'),
    D: t('field.tier.option.D'),
  }
  return options[tier]
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
export function pairsOption(pairs: Pairs, t: TFunction): string {
  const options: Record<Pairs, string> = {
    A: t('field.pairs.option.A'),
    AB: t('field.pairs.option.AB'),
    ABD: t('field.pairs.option.ABD'),
  }
  return options[pairs]
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
export function noPairsMessage(pairs: Pairs | null, when: string, t: TFunction): string {
  if (pairs === 'A') return t('field.pairs.none.A', { when })
  if (pairs === 'AB') return t('field.pairs.none.AB', { when })
  return t('field.pairs.none.ABD', { when })
}

/** "MTGO challenges since Aug 11", "Paper tournaments of 64+ players, last
 *  30 days": the share card's action, the comma only before "last". */
export function shareAction(tier: Tier, window: FieldWindow, reset: string | null, now: number, t: TFunction): string {
  const kind = tierKind(tier, t)
  const { short } = windowWords(window, reset, now, t)
  const head = kind.charAt(0).toUpperCase() + kind.slice(1)
  // The comma goes only before a count of days, not before a date.
  return window === 'reset' && reset
    ? t('field.share.actionSince', { kind: head, short })
    : t('field.share.actionLast', { kind: head, short })
}

/* ------------------------------------------------------------ the rows */

/** How many rows a card shows before its button shows the rest. */
export const SHARE_SHOWN = 12
export const EVENTS_SHOWN = 12
export const WINRATE_SHOWN = 12
export const MATCHUPS_SHOWN = 20

/** The rows a card shows: the first `limit` until the rest are asked for. */
export function shownRows<T>(rows: T[], limit: number, all: boolean): T[] {
  return all ? rows : rows.slice(0, limit)
}

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

/** What the Field page says of the viewer's own matches: the record
 *  against each share row and against the first two together, from the
 *  selected format's matches only (a match with no format counts toward
 *  none), and whether the list is short. `short` reads the whole list,
 *  because the fetch cap applies to it, not to a format. */
export function ownCounts(
  matches: Match[],
  share: MetaPresence[],
  format: string,
  windowStart: number,
  liveMatches: number | undefined,
): { records: FieldRecord[]; topTwo: FieldRecord; short: boolean } {
  const own = matchesInFormat(matches, format)
  return {
    records: share.map((row) => recordAgainstRows(own, [row], windowStart)),
    topTwo: recordAgainstRows(own, share.slice(0, 2), windowStart),
    short: listShort(matches, liveMatches, windowStart),
  }
}

/* ------------------------------------------------------------ the sources */

/** Older than this, the results or the rules are worth downloading again. */
export const STALE_HOURS = 7 * 24

/** An age in hours, in the largest whole unit and without an "ago": "6d",
 *  "5h", "30m", "12s" (`time.age.*`). */
export function ageWords(hours: number, t: TFunction): string {
  const seconds = Math.max(0, Math.round((Math.max(0, hours) * 3_600_000) / 1000))
  if (seconds < 60) return t('time.age.seconds', { count: seconds })
  if (seconds < 3600) return t('time.age.minutes', { count: Math.floor(seconds / 60) })
  if (seconds < 86_400) return t('time.age.hours', { count: Math.floor(seconds / 3600) })
  return t('time.age.days', { count: Math.floor(seconds / 86_400) })
}

/** Never fetched, or fetched more than seven days ago. */
export function isStale(hours: number | null | undefined): boolean {
  return hours == null || hours > STALE_HOURS
}

const EVENT_SOURCES: Record<string, string> = { MTGO: 'mtgo.com', MTGmelee: 'melee.gg', Topdeck: 'TopDeck.gg' }

/** An event's caption line: its source, its lists and, when known, who won,
 *  joined by " · ". A source nobody named is left out rather than guessed. */
export function eventCaption(
  event: { source: string; lists: number; winner?: string | null },
  count: (n: number) => string,
  t: TFunction,
): string {
  const source = EVENT_SOURCES[event.source]
  const lists = event.lists === 0 ? t('field.events.standingsOnly') : t('field.events.lists', { count: event.lists, n: count(event.lists) })
  return [source, lists, event.winner != null ? t('field.events.wonBy', { winner: event.winner }) : null]
    .filter((part) => part != null)
    .join(' · ')
}

/** The address of an event's page: each segment of its key encoded, the
 *  slashes kept. */
export const eventHref = (key: string): string => `/field/events/${key.split('/').map(encodeURIComponent).join('/')}`

const isHoldSource = (source: string): source is HoldSource => source === 'mtgo' || source === 'topdeck'

/** The hold lines of the sources whose hold has the given status, in the
 *  sources' order. A source `holdLine` has no words for, or with no hold,
 *  gives none. */
export function holdLines(status: MetagameStatus, which: 'paused' | 'waiting', now: number, t: TFunction): string[] {
  const lines: string[] = []
  for (const src of status.corpus_sources ?? []) {
    if (!isHoldSource(src.source) || src.hold?.status !== which) continue
    const line = holdLine(src.source, src.hold, new Date(now), t)
    if (line != null) lines.push(line)
  }
  return lines
}

/** The "against the top two" tile: the value, whether it is muted, and its
 *  line. Nothing played: a dash and the not-met line. Only draws: a dash and
 *  "no finished match yet". Otherwise `rateOrRecord`, its line followed by
 *  where the record comes from. */
export function topTwoTile(
  record: FieldRecord,
  when: string,
  t: TFunction,
): { value: string; muted: boolean; detail: string } {
  if (record.played === 0) return { value: '—', muted: false, detail: t('field.tiles.notMet', { when }) }
  const result = rateOrRecord({ wins: record.won, losses: record.losses }, t)
  if (result.figure == null) return { value: '—', muted: false, detail: result.line }
  return { value: result.figure, muted: result.thin, detail: `${result.line} · ${t('field.tiles.wonDetail')}` }
}

/** A field row's caption: the one-line form of the record ("58% · 35–25"
 *  or "6–3"), `notPlayed` when no match was played, "no finished match
 *  yet" when every one was a draw. */
export function rowCaption(record: FieldRecord, notPlayed: string, t: TFunction): string {
  if (record.played === 0) return notPlayed
  return rateAndRecordLine({ wins: record.won, losses: record.losses }) ?? t('common.sample.noMatch')
}
