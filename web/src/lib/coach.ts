/**
 * What the coach's page reads, as pure functions of the API's rows: the
 * report its address names, the report's title and byline, a row of the
 * history, the cost sentence under the model picker, and, from a report's
 * `sources`, the order the Sources card lists them in, a web page's host
 * and where a citation in the prose points; and, for the profile under
 * the report ("Your numbers"), the words of a rate, a day, the roles and
 * mulligans in order, the labels under an archetype, a pattern's
 * direction and the lost games by stage.
 */
import type {
  CoachEvidenceModel,
  CoachModelOption,
  CoachReportSummary,
  CoachSource,
  RateModel,
  TurningBucketOut,
} from '../api'
import { NBSP, type TileText } from './matchups'
import { gapPoints } from './guide'
import { UNNAMED_DECK } from './home'
import { formatCount, formatIsoDateShort, formatPercent, formatShortDay, parseTimestamp } from './time'

/** The report an address names: `'latest'` for `/coach`, the number for
 *  `/coach/:id`. */
export type ReportParam = 'latest' | 'unknown' | number

/** `/coach/:id`'s parameter read: absent is `'latest'`, a positive integer
 *  written in digits with no leading zero is its number, anything else is
 *  `'unknown'`. "03" is unknown, so a report has one address. */
export function reportParam(param: string | undefined): ReportParam {
  if (param === undefined) return 'latest'
  if (!/^[1-9]\d*$/.test(param)) return 'unknown'
  const n = Number(param)
  return Number.isSafeInteger(n) ? n : 'unknown'
}

/** The label of the model whose id is `id` ("Opus 5.5"); the id as
 *  stored when no listed model has it. */
export function modelLabel(id: string, models: CoachModelOption[]): string {
  return models.find((m) => m.id === id)?.label ?? id
}

/** "Report of Sep 22", the year added in a year other than `now`'s
 *  (`formatShortDay`); "Report" when the day cannot be read. */
export function reportTitle(generatedAt: string | null | undefined, now: number): string {
  const ms = parseTimestamp(generatedAt)
  return ms == null ? 'Report' : `Report of ${formatShortDay(ms, now)}`
}

type ReportFacts = {
  /** The model's label, `modelLabel`'s answer. */
  label: string
  costUsd: number | null | undefined
  searches: number | null | undefined
}

/** A cost to three places, as `writtenNote` writes it: "$1.038". */
const dollars = (cost: number) => `$${cost.toFixed(3)}`

/** Who wrote the report, then what it cost and how often it searched the
 *  web: "Written by Opus 5.5. It cost $1.038 and searched the web 8
 *  times." A search count of null or 0 is no searches, and says nothing;
 *  one search is "once". */
export function reportByline({ label, costUsd, searches }: ReportFacts): string {
  const first = `Written by ${label}.`
  const n = searches ?? 0
  const times = n === 1 ? 'once' : `${n} times`
  if (costUsd != null) {
    return n > 0
      ? `${first} It cost ${dollars(costUsd)} and searched the web ${times}.`
      : `${first} It cost ${dollars(costUsd)}.`
  }
  return n > 0 ? `${first} It searched the web ${times}.` : first
}

/** A history row's caption: "Opus 5.5 · $1.038 · 8 web searches", "1 web
 *  search" for one. A part with no value (a null cost or search count) is
 *  left out with its separator; a count of 0 is a value and reads "0 web
 *  searches". */
export function historyDetail({ label, costUsd, searches }: ReportFacts): string {
  return [
    label,
    costUsd != null ? dollars(costUsd) : null,
    searches != null ? (searches === 1 ? '1 web search' : `${searches} web searches`) : null,
  ]
    .filter((part) => part != null)
    .join(' · ')
}

/** The sentence under the model picker, for the model a report would be
 *  written with: what the newest report written with it cost, when one
 *  has a cost (`reports` newest first, as `/api/coach` sends them);
 *  otherwise its price per million tokens, as the API sends it, when it
 *  is priced; otherwise `null`. */
export function modelCostNote(
  modelId: string | null | undefined,
  models: CoachModelOption[],
  reports: CoachReportSummary[],
): string | null {
  if (!modelId) return null
  const label = modelLabel(modelId, models)
  const last = reports.find((r) => r.model === modelId && r.cost_usd != null)
  if (last?.cost_usd != null) return `Your last report with ${label} cost ${dollars(last.cost_usd)}.`
  const model = models.find((m) => m.id === modelId)
  if (model?.input_per_mtok != null && model.output_per_mtok != null) {
    return `${label} costs $${model.input_per_mtok} per million tokens it reads and $${model.output_per_mtok} per million it writes, plus its web searches.`
  }
  return null
}

/** A reading entry's number, 4 for `R4`; `null` for a label of any other
 *  shape. */
function readingNumber(label: string): number | null {
  const match = /^R(\d+)$/.exec(label)
  return match ? Number(match[1]) : null
}

/** `sources` in the order the Sources card lists them: the reading
 *  entries by their number (R1, R2, …, R18), then every other entry (the
 *  web pages) in the order given. A reading entry whose label is not `R`
 *  and digits comes after the numbered ones, in the order given. */
export function readingOrder(sources: CoachSource[]): CoachSource[] {
  const reading = sources
    .filter((s) => s.kind === 'reading')
    .map((s, index) => ({ s, index, n: readingNumber(s.label) }))
    .sort((a, b) => {
      if (a.n != null && b.n != null) return a.n - b.n || a.index - b.index
      if (a.n != null) return -1
      if (b.n != null) return 1
      return a.index - b.index
    })
    .map(({ s }) => s)
  return [...reading, ...sources.filter((s) => s.kind !== 'reading')]
}

/** `url`'s host without a leading `www.`; `null` when it does not parse
 *  as a url or has no host. */
export function hostOf(url: string): string | null {
  let host: string
  try {
    host = new URL(url).hostname
  } catch {
    return null
  }
  return host ? host.replace(/^www\./, '') : null
}

/** Where the citation `[label]` points: the url of the reading entry of
 *  `sources` whose label is `label`, compared exactly, and its accessible
 *  name, `label: title`, the url for the title when the entry has none
 *  (or an empty one). `null` when no reading entry carries the label. */
export function citationOf(label: string, sources: CoachSource[]): { url: string; name: string } | null {
  const entry = sources.find((s) => s.kind === 'reading' && s.label === label)
  if (!entry) return null
  return { url: entry.url, name: `${label}: ${entry.title || entry.url}` }
}

/* The profile ("Your numbers"). */

/** A rate's three parts as the profile writes them: the record "174 of
 *  385", the percent "45%" and the range "40–50%", each end a whole
 *  percent rounded as the percent is. The record is `null` with no match;
 *  the percent and the range are `null` with no match and under ten
 *  (`anecdotal`, the same ten as `RATE_MIN_MATCHES`): a rate needs ten. */
export type RateWords = { record: string | null; percent: string | null; range: string | null }

/** The word joiner (U+2060): no line may break on either side of it. Built
 *  in code, never typed, like `NBSP`. */
export const WORD_JOINER = String.fromCharCode(0x2060)

export function rateWords(rate: RateModel): RateWords {
  if (rate.n === 0) return { record: null, percent: null, range: null }
  const record = `${formatCount(rate.wins)} of ${formatCount(rate.n)}`
  if (rate.anecdotal || rate.rate == null) return { record, percent: null, range: null }
  return {
    record,
    percent: `${formatPercent(rate.rate)}%`,
    // A word joiner each side of the dash: the range never breaks at it.
    range: `${formatPercent(rate.ci_low)}${WORD_JOINER}–${WORD_JOINER}${formatPercent(rate.ci_high)}%`,
  }
}

/** One overall tile: the percent as the value, the record and range as
 *  its detail; under ten, a dash over the record alone; with no match, a
 *  dash over "None played". */
export function rateTile(label: string, rate: RateModel): TileText {
  const words = rateWords(rate)
  if (words.record == null) return { label, value: '—', detail: 'None played' }
  if (words.percent == null) return { label, value: '—', detail: `${words.record} won` }
  return { label, value: words.percent, detail: `${words.record} won · ${words.range}` }
}

/** The six overall tiles, in the profile's order. */
export function overallTiles(
  evidence: Pick<CoachEvidenceModel, 'overall' | 'overall_games' | 'g1' | 'post_board' | 'on_play' | 'on_draw'>,
): TileText[] {
  return [
    rateTile('Matches', evidence.overall),
    rateTile('Games', evidence.overall_games),
    rateTile('Game 1', evidence.g1),
    rateTile('After sideboarding', evidence.post_board),
    rateTile('On the play', evidence.on_play),
    rateTile('On the draw', evidence.on_draw),
  ]
}

/** A day the coach's evidence carries as "Aug 11": a bare calendar date
 *  (`window_start`, a tournament's day) read from its own parts, a
 *  timestamp (`as_of`) in the viewer's zone; `null` when it is absent or
 *  reads as neither. */
export function coachDay(value: string | null | undefined, now: number): string | null {
  if (!value) return null
  const bare = formatIsoDateShort(value, now)
  if (bare != null) return bare
  const ms = parseTimestamp(value)
  return ms == null ? null : formatShortDay(ms, now)
}

/** The profile's first caption sentence: "385 finished constructed
 *  matches, to Aug 11.", the day left out when `asOf` has none. */
export function profileCaption(population: number, asOf: string | null | undefined, now: number): string {
  const matches =
    population === 1 ? '1 finished constructed match' : `${formatCount(population)} finished constructed matches`
  const day = coachDay(asOf, now)
  return day ? `${matches}, to ${day}.` : `${matches}.`
}

/** A deck's name as the user typed it; "Unnamed deck" when it is blank. */
export function deckName(label: string): string {
  return label.trim() ? label : UNNAMED_DECK
}

/** A rate under the word a row of the profile shows for its key. */
export type LabelledRate = { key: string; label: string; rate: RateModel }

/** `rates` in `words`' order, each under its word; a key `words` does not
 *  know follows them, as stored, in the order it came. */
function inOrder(rates: Record<string, RateModel>, words: readonly (readonly [string, string])[]): LabelledRate[] {
  const byKey = new Map(Object.entries(rates))
  const known = new Set(words.map(([key]) => key))
  const named = words.flatMap(([key, label]) => {
    const rate = byKey.get(key)
    return rate ? [{ key, label, rate }] : []
  })
  const rest = [...byKey].filter(([key]) => !known.has(key)).map(([key, rate]) => ({ key, label: key, rate }))
  return [...named, ...rest]
}

const ROLE_WORDS = [
  ['beatdown', 'Beatdown'],
  ['control', 'Control'],
  ['mixed', 'Mixed'],
  ['unknown', 'No role found'],
] as const

const MULLIGAN_WORDS = [
  ['kept_seven', 'Kept seven'],
  ['mulliganed', 'Mulliganed'],
] as const

/** `by_role` in words: beatdown, control, mixed, then no role found, and a
 *  role this table does not know after them, as stored. */
export function roleRates(byRole: Record<string, RateModel>): LabelledRate[] {
  return inOrder(byRole, ROLE_WORDS)
}

/** `mulligans` in words: kept seven, then mulliganed, and a key this table
 *  does not know after them, as stored. */
export function mulliganRates(mulligans: Record<string, RateModel>): LabelledRate[] {
  return inOrder(mulligans, MULLIGAN_WORDS)
}

/** The labels an archetype was met or listed under, most first: "Red
 *  Aggro 43, Mono Red 4, Red Deck 2 and 4 more". The three most counted
 *  with their counts, then how many more; `null` with one label or none,
 *  since the name above already says it. */
export function variantsWords(variants: readonly (readonly [string, number])[]): string | null {
  if (variants.length <= 1) return null
  const sorted = [...variants].sort((a, b) => b[1] - a[1])
  const shown = sorted
    .slice(0, 3)
    .map(([label, n]) => `${label} ${formatCount(n)}`)
    .join(', ')
  const more = sorted.length - 3
  return more > 0 ? `${shown} and ${formatCount(more)}${NBSP}more` : shown
}

/** How many tournament lists an archetype has: "338 lists", "1 list". */
export function listsWords(decks: number): string {
  return decks === 1 ? `1${NBSP}list` : `${formatCount(decks)}${NBSP}lists`
}

/** A pattern's win rate with it against without it, in whole points and
 *  which way: "30 points better with it", "1 point worse with it". `gap`
 *  is the size alone, so the way is read from the two rates. "No
 *  difference" when the points round to 0, whatever the way; `null` when a
 *  side has no rate to compare. */
export function patternDirection(pattern: {
  present: Pick<RateModel, 'rate'>
  absent: Pick<RateModel, 'rate'>
  gap: number
}): string | null {
  const points = gapPoints(Math.abs(pattern.gap))
  if (points === 0) return 'No difference'
  const { present, absent } = pattern
  if (present.rate == null || absent.rate == null) return null
  const way = present.rate > absent.rate ? 'better' : 'worse'
  return points === 1 ? `1 point ${way} with it` : `${formatCount(points)} points ${way} with it`
}

/** The summary of a deck's own patterns: "Deck one, 3 patterns". */
export function deckPatternsSummary(label: string, count: number): string {
  return `${deckName(label)}, ${count === 1 ? `1${NBSP}pattern` : `${formatCount(count)}${NBSP}patterns`}`
}

const STAGE_WORDS = [
  ['early', 'Early, turns 1 to 3'],
  ['mid', 'Mid, turns 4 to 6'],
  ['late', 'Late, turn 7 on'],
] as const

/** The subtitle of "Where lost games turned": over how many lost games a
 *  turn was found, `lost` being every cell summed; "1 lost game" for one. */
export function turningSubtitle(lost: number): string {
  const games = lost === 1 ? '1 lost game' : `${formatCount(lost)} lost games`
  return `The turn of yours on which a lost game first slipped, over the ${games} where one was found.`
}

/** The lost games by the stage they turned at: a tile a stage, its lost
 *  games as the value and how many of them were decisive as the detail;
 *  and `lost`, every cell summed. */
export function turningTiles(points: TurningBucketOut[]): { lost: number; tiles: TileText[] } {
  const lost = points.reduce((sum, p) => sum + p.games, 0)
  const tiles = STAGE_WORDS.map(([stage, label]) => {
    const cells = points.filter((p) => p.stage === stage)
    const games = cells.reduce((sum, p) => sum + p.games, 0)
    const decisive = cells.filter((p) => p.severity === 'decisive').reduce((sum, p) => sum + p.games, 0)
    return {
      label,
      value: formatCount(games),
      detail: decisive === 0 ? 'None of them decisive' : `${formatCount(decisive)} of them decisive`,
    }
  })
  return { lost, tiles }
}
