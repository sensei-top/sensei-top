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
import { useSearchParams } from 'react-router'
import type {
  CoachEvidenceModel,
  CoachModelOption,
  CoachReportSummary,
  CoachSource,
  FormatEntry,
  FormatsOut,
  RateModel,
  TurningBucketOut,
} from '../api'
import type { TFunction } from '../i18n'
import { type TileText } from './matchups'
import { formatDollars, formatList, formatPercent, formatPrice, formatRecord, WORD_JOINER } from './format'
import { formatOf, paramFor } from './field'
import { gapPoints } from './guide'
import { RATE_MIN_MATCHES } from './sample'
import { formatCount, formatIsoDateShort, formatShortDay, parseTimestamp } from './time'

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

/** The format a stored report is for: a report with none is a Standard
 *  report (the store's rule). */
export function reportFormat(report: Pick<CoachReportSummary, 'format'>): string {
  return report.format ?? 'Standard'
}

/** "Modern report of Sep 22", the year added in a year other than `now`'s
 *  (`formatShortDay`); "Modern report" when the day cannot be read. */
export function reportTitle(
  format: string,
  generatedAt: string | null | undefined,
  now: number,
  t: TFunction,
): string {
  const ms = parseTimestamp(generatedAt)
  return ms == null
    ? t('coach.report.title', { format })
    : t('coach.report.titleOf', { format, day: formatShortDay(ms, now) })
}

/** The formats the control offers: those with matches of the viewer's or a
 *  stored report, in `/api/formats`' order, and always `selected` (the
 *  address's). */
export function coachFormatChoices(
  formats: FormatsOut,
  selected: string,
  reports: Pick<CoachReportSummary, 'format'>[],
): FormatEntry[] {
  const written = new Set(reports.map(reportFormat))
  return formats.formats.filter(
    (entry) => entry.format === selected || entry.matches.total > 0 || written.has(entry.format),
  )
}

/** The Coach page's format: `?format=` read as Field reads it (`formatOf`:
 *  absent or unknown is the default `/api/formats` reports, never written
 *  into the address), and a setter that takes the default out of the
 *  address, replacing the history entry and keeping the scroll. `format`
 *  is `undefined` until `/api/formats` has answered. */
export function useCoachFormat(formats: FormatsOut | undefined): {
  format: string | undefined
  setFormat: (format: string) => void
} {
  const [search, setSearch] = useSearchParams()
  return {
    format: formats ? formatOf(search.get('format'), formats) : undefined,
    setFormat: (next) =>
      setSearch(
        (previous) => {
          const params = new URLSearchParams(previous)
          const value = formats ? paramFor(next, formats.default) : next
          if (value) params.set('format', value)
          else params.delete('format')
          return params
        },
        { replace: true, preventScrollReset: true },
      ),
  }
}

/** Whether "Every report" is drawn: some stored report is not the one on
 *  the page (`onPage`, `null` when none is). */
export function showHistory(reports: Pick<CoachReportSummary, 'id'>[], onPage: number | null): boolean {
  return reports.some((r) => r.id !== onPage)
}

/** The address of a format's page: `/coach`, with `?format=` when it is not
 *  the default (which a bare address never names). */
export function coachAddress(format: string, defaultFormat: string): string {
  return format === defaultFormat ? '/coach' : `/coach?format=${encodeURIComponent(format)}`
}

/** The newest report of `format` (`reports` newest first), if any. */
export function latestOfFormat<T extends Pick<CoachReportSummary, 'format'>>(
  reports: T[],
  format: string,
): T | undefined {
  return reports.find((r) => reportFormat(r) === format)
}

/** Where a history row points: the newest report of the page's own format
 *  to the page's own address, every other report to `/coach/{id}`. */
export function reportLink(
  report: Pick<CoachReportSummary, 'id' | 'format'>,
  reports: Pick<CoachReportSummary, 'id' | 'format'>[],
  pageFormat: string,
  defaultFormat: string,
): string {
  return latestOfFormat(reports, pageFormat)?.id === report.id
    ? coachAddress(pageFormat, defaultFormat)
    : `/coach/${report.id}`
}

type ReportFacts = {
  /** The model's label, `modelLabel`'s answer. */
  label: string
  costUsd: number | null | undefined
  searches: number | null | undefined
  /** The report's model is the sentinel for a pasted answer
   *  (`isPasted`): `label` is then never shown. */
  pasted?: boolean
}

/** Who wrote the report, then what it cost and how often it searched the
 *  web: "Written by Opus 5.5. It cost $1.038 and searched the web 8
 *  times." A search count of null or 0 is no searches, and says nothing;
 *  one search is "once". A pasted report says "Pasted in." and nothing
 *  more: it has no model, cost or searches to name. */
export function reportByline({ label, costUsd, searches, pasted }: ReportFacts, t: TFunction): string {
  if (pasted) return t('coach.report.byline.pasted')
  const n = searches ?? 0
  const times = t('coach.report.times', { count: n, n })
  if (costUsd != null) {
    return n > 0
      ? t('coach.report.byline.costSearched', { label, cost: formatDollars(costUsd), times })
      : t('coach.report.byline.cost', { label, cost: formatDollars(costUsd) })
  }
  return n > 0 ? t('coach.report.byline.searched', { label, times }) : t('coach.report.byline.plain', { label })
}

/** A history row's caption: "Opus 5.5 · $1.038 · 8 web searches", "1 web
 *  search" for one. A part with no value (a null cost or search count) is
 *  left out with its separator; a count of 0 is a value and reads "0 web
 *  searches". */
export function historyDetail({ label, costUsd, searches, pasted }: ReportFacts, t: TFunction): string {
  return [
    pasted ? t('decks.written.pasted') : label,
    costUsd != null ? formatDollars(costUsd) : null,
    searches != null ? t('coach.report.searches', { count: searches, n: searches }) : null,
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
  t: TFunction,
): string | null {
  if (!modelId) return null
  const label = modelLabel(modelId, models)
  const last = reports.find((r) => r.model === modelId && r.cost_usd != null)
  if (last?.cost_usd != null) return t('coach.report.costNote.last', { label, cost: formatDollars(last.cost_usd) })
  const model = models.find((m) => m.id === modelId)
  if (model?.input_per_mtok != null && model.output_per_mtok != null) {
    return t('coach.report.costNote.price', {
      label,
      input: formatPrice(model.input_per_mtok),
      output: formatPrice(model.output_per_mtok),
    })
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

/** A rate's three parts as the profile writes them: the record "174–211"
 *  (wins then losses), the percent "45%" and the range "40%–50%", each end
 *  a whole percent rounded as the percent is. The record is `null` with no
 *  match; the percent and the range are `null` with no match and under ten
 *  (`anecdotal`, the same ten as `RATE_MIN_MATCHES`): a rate needs ten. The
 *  coach's matches and games are wins and losses only (`coach/evidence.py`
 *  keeps `result IN ('win', 'loss')`), so the losses are `n - wins`. */
export type RateWords = { record: string | null; percent: string | null; range: string | null }

export function rateWords(rate: RateModel): RateWords {
  if (rate.n === 0) return { record: null, percent: null, range: null }
  const record = formatRecord(rate.wins, rate.n - rate.wins)
  if (rate.anecdotal || rate.rate == null) return { record, percent: null, range: null }
  return {
    record,
    percent: formatPercent(rate.rate),
    // A word joiner each side of the dash: the range never breaks at it.
    range: `${formatPercent(rate.ci_low)}${WORD_JOINER}–${WORD_JOINER}${formatPercent(rate.ci_high)}`,
  }
}

/** What a coach tile says: `muted` is a record drawn muted, too few for a
 *  rate. */
export type RateTileText = TileText & { muted?: boolean }

/** One overall tile (D7): from ten, the percent as the value, the record
 *  and the range as its detail; under ten, the record as the value, muted,
 *  over the "too few" line (matches or games, by `unit`); with no match, a
 *  dash over "None played". */
export function rateTile(
  label: string,
  rate: RateModel,
  t: TFunction,
  unit: 'matches' | 'games' = 'matches',
): RateTileText {
  const words = rateWords(rate)
  if (words.record == null) return { label, value: '—', detail: t('coach.rate.nonePlayed') }
  if (words.percent == null) {
    const key = unit === 'games' ? 'common.sample.tooFewGames' : 'common.sample.tooFewMatches'
    return { label, value: words.record, detail: t(key, { min: RATE_MIN_MATCHES }), muted: true }
  }
  return { label, value: words.percent, detail: `${words.record} · ${words.range}` }
}

/** The six overall tiles, in the profile's order. */
export function overallTiles(
  evidence: Pick<CoachEvidenceModel, 'overall' | 'overall_games' | 'g1' | 'post_board' | 'on_play' | 'on_draw'>,
  t: TFunction,
): RateTileText[] {
  return [
    rateTile(t('coach.split.matches'), evidence.overall, t),
    rateTile(t('coach.split.games'), evidence.overall_games, t, 'games'),
    rateTile(t('coach.split.game1'), evidence.g1, t, 'games'),
    rateTile(t('coach.split.postBoard'), evidence.post_board, t, 'games'),
    rateTile(t('coach.split.onPlay'), evidence.on_play, t, 'games'),
    rateTile(t('coach.split.onDraw'), evidence.on_draw, t, 'games'),
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
export function profileCaption(
  population: number,
  asOf: string | null | undefined,
  now: number,
  t: TFunction,
): string {
  const matches = t('coach.profile.population', { count: population, n: formatCount(population) })
  const day = coachDay(asOf, now)
  return day ? t('coach.profile.captionTo', { matches, day }) : t('coach.profile.caption', { matches })
}

/** A deck's name as the user typed it; "Unnamed deck" when it is blank. */
export function deckName(label: string, t: TFunction): string {
  return label.trim() ? label : t('common.unnamedDeck')
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


/** `by_role` in words: beatdown, control, mixed, then no role found, and a
 *  role this table does not know after them, as stored. */
export function roleRates(byRole: Record<string, RateModel>, t: TFunction): LabelledRate[] {
  return inOrder(byRole, [
    ['beatdown', t('coach.roles.beatdown')],
    ['control', t('coach.roles.control')],
    ['mixed', t('coach.roles.mixed')],
    ['unknown', t('coach.roles.unknown')],
  ])
}

/** `mulligans` in words: kept seven, then mulliganed, and a key this table
 *  does not know after them, as stored. */
export function mulliganRates(mulligans: Record<string, RateModel>, t: TFunction): LabelledRate[] {
  return inOrder(mulligans, [
    ['kept_seven', t('coach.mulligans.keptSeven')],
    ['mulliganed', t('coach.mulligans.mulliganed')],
  ])
}

/** The labels an archetype was met or listed under, most first: "Red
 *  Aggro 43, Mono Red 4, Red Deck 2, and 4 more". The three most counted
 *  with their counts, then how many more, one list in the language read;
 *  `null` with one label or none, since the name above already says it. */
export function variantsWords(variants: readonly (readonly [string, number])[], t: TFunction): string | null {
  if (variants.length <= 1) return null
  const sorted = [...variants].sort((a, b) => b[1] - a[1])
  const shown = sorted.slice(0, 3).map(([label, n]) => `${label} ${formatCount(n)}`)
  const more = sorted.length - 3
  return formatList(more > 0 ? [...shown, t('coach.field.variantsMore', { n: formatCount(more) })] : shown)
}

/** How many tournament lists an archetype has: "338 lists", "1 list". */
export function listsWords(decks: number, t: TFunction): string {
  return t('coach.field.lists', { count: decks, n: formatCount(decks) })
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
}, t: TFunction): string | null {
  const points = gapPoints(Math.abs(pattern.gap))
  if (points === 0) return t('coach.patterns.noDifference')
  const { present, absent } = pattern
  if (present.rate == null || absent.rate == null) return null
  const n = formatCount(points)
  return present.rate > absent.rate
    ? t('coach.patterns.better', { count: points, n })
    : t('coach.patterns.worse', { count: points, n })
}

/** The summary of a deck's own patterns: "Deck one, 3 patterns". */
export function deckPatternsSummary(label: string, count: number, t: TFunction): string {
  return t('coach.patterns.deckSummary', {
    deck: deckName(label, t),
    patterns: t('coach.patterns.count', { count, n: formatCount(count) }),
  })
}

/** The subtitle of "Where lost games turned": over how many lost games a
 *  turn was found, `lost` being every cell summed; "1 lost game" for one. */
export function turningSubtitle(lost: number, t: TFunction): string {
  const games = t('coach.turning.lostGames', { count: lost, n: formatCount(lost) })
  return t('coach.turning.subtitle', { games })
}

/** The lost games by the stage they turned at: a tile a stage, its lost
 *  games as the value and how many of them were decisive as the detail;
 *  and `lost`, every cell summed. */
export function turningTiles(points: TurningBucketOut[], t: TFunction): { lost: number; tiles: TileText[] } {
  const lost = points.reduce((sum, p) => sum + p.games, 0)
  const stages = [
    ['early', t('coach.turning.early')],
    ['mid', t('coach.turning.mid')],
    ['late', t('coach.turning.late')],
  ] as const
  const tiles = stages.map(([stage, label]) => {
    const cells = points.filter((p) => p.stage === stage)
    const games = cells.reduce((sum, p) => sum + p.games, 0)
    const decisive = cells.filter((p) => p.severity === 'decisive').reduce((sum, p) => sum + p.games, 0)
    return {
      label,
      value: formatCount(games),
      detail:
        decisive === 0 ? t('coach.turning.noneDecisive') : t('coach.turning.decisive', { count: decisive, n: formatCount(decisive) }),
    }
  })
  return { lost, tiles }
}
