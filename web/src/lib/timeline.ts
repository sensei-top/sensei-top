import type { PositionPoint, ReportEvidence, ReportFinding } from '../api'
import type { FindingWeight } from '../components/ui'
import type { TFunction } from '../i18n'

/** The report's weights, heaviest first. */
export const FINDING_WEIGHTS: readonly FindingWeight[] = ['decisive', 'flag', 'notice', 'note']

/** A finding's or a beat's severity as a weight. The report sends only the
 *  four; anything else is a note, so no code ever reaches the page. */
export function weightOf(severity: string): FindingWeight {
  return (FINDING_WEIGHTS as readonly string[]).includes(severity) ? (severity as FindingWeight) : 'note'
}

/** One slot of the match's line. A game's boundary is a slot of its own
 *  with no position, so the line breaks there instead of joining the last
 *  turn of one game to the first of the next. */
export type TimelineSlot = {
  x: number
  game: number
  /** `null` on a boundary slot. */
  turn: number | null
  /** Which of the player's own turns it was, when it was one. */
  selfTurn: number | null
  index: number | null
}

/** One game's stretch of the line: its boundary slot, then its turns. */
export type TimelineSegment = {
  game: number
  boundary: number
  first: number
  last: number
}

export type Timeline = {
  slots: TimelineSlot[]
  segments: TimelineSegment[]
  /** The x of every turn, for the axis's ticks. */
  ticks: number[]
  /** The y axis runs from `-reach` to `reach`, one scale for the match. */
  reach: number
}

/** The smallest half-range of the line's axis: a match that never moved far
 *  from zero still reads as close, rather than filling the box. */
const MIN_REACH = 0.25

/** The largest distance from zero in the match, rounded up to a quarter,
 *  and never past 1, the index's own bound. */
export function reachOf(points: readonly PositionPoint[]): number {
  const largest = Math.max(0, ...points.map((point) => Math.abs(point.index)))
  return Math.min(1, Math.max(MIN_REACH, Math.ceil(largest / MIN_REACH) * MIN_REACH))
}

/** The position track as one continuous index: games in order, each game's
 *  turns in order, every game opened by its boundary slot. A game with no
 *  point has no segment. */
export function buildTimeline(track: readonly PositionPoint[]): Timeline {
  const byGame = new Map<number, PositionPoint[]>()
  for (const point of track) {
    const points = byGame.get(point.game_number) ?? []
    points.push(point)
    byGame.set(point.game_number, points)
  }
  const slots: TimelineSlot[] = []
  const segments: TimelineSegment[] = []
  const ticks: number[] = []
  for (const game of [...byGame.keys()].sort((a, b) => a - b)) {
    const points = (byGame.get(game) ?? []).slice().sort((a, b) => a.turn_number - b.turn_number)
    const boundary = slots.length
    slots.push({ x: boundary, game, turn: null, selfTurn: null, index: null })
    for (const point of points) {
      ticks.push(slots.length)
      slots.push({
        x: slots.length,
        game,
        turn: point.turn_number,
        selfTurn: point.self_turn_index ?? null,
        index: point.index,
      })
    }
    segments.push({ game, boundary, first: boundary + 1, last: slots.length - 1 })
  }
  return { slots, segments, ticks, reach: reachOf(track) }
}

/** Where a marker sits on the chart: on a turn's point, or on its game's
 *  boundary label. `nearest` says the finding's own turn has no point, so
 *  the marker sits on `shownTurn`, the nearest earlier one;
 *  `shownSelfTurn` is that point's count of the player's own turns. */
export type Placement =
  | { kind: 'turn'; x: number; y: number; shownTurn: number; shownSelfTurn: number | null; nearest: boolean }
  | { kind: 'game'; x: number; y: number }

/** What routing reads of a finding. `beat` says one of its game's beats
 *  was built from it. */
export type MarkerSource = {
  id: number
  game: number | null
  turn: number | null
  weight: FindingWeight
  beat: boolean
}

/** A finding on the timeline. `placement` is `null` when its game has no
 *  line: it is in the strip, and not on the chart. */
export type Marker = MarkerSource & { placement: Placement | null }

export type Routed = {
  /** No game (D9): the "Whole match" list above the timeline. */
  wholeMatch: MarkerSource[]
  /** In strip order: by game, a game's own markers before its turns',
   *  then by turn, heaviest first, then as the report listed them. */
  markers: Marker[]
  /** A note that is not a beat: behind "Every other finding". */
  rest: MarkerSource[]
}

/** Where on the timeline a finding of `game` at `turn` sits. */
export function placeOn(timeline: Timeline, game: number, turn: number | null): Placement | null {
  const segment = timeline.segments.find((s) => s.game === game)
  if (!segment) return null
  const onBoundary: Placement = { kind: 'game', x: segment.boundary, y: timeline.reach }
  if (turn == null) return onBoundary
  let earlier: TimelineSlot | undefined
  for (let x = segment.first; x <= segment.last; x++) {
    const slot = timeline.slots[x]
    if (slot.turn == null || slot.index == null) continue
    if (slot.turn === turn) {
      return { kind: 'turn', x, y: slot.index, shownTurn: turn, shownSelfTurn: slot.selfTurn, nearest: false }
    }
    if (slot.turn < turn) earlier = slot
  }
  if (earlier && earlier.turn != null && earlier.index != null) {
    return {
      kind: 'turn',
      x: earlier.x,
      y: earlier.index,
      shownTurn: earlier.turn,
      shownSelfTurn: earlier.selfTurn,
      nearest: true,
    }
  }
  return onBoundary
}

function stripOrder(a: MarkerSource, b: MarkerSource): number {
  const game = (a.game ?? 0) - (b.game ?? 0)
  if (game !== 0) return game
  if (a.turn == null || b.turn == null) {
    if (a.turn !== b.turn) return a.turn == null ? -1 : 1
  } else if (a.turn !== b.turn) {
    return a.turn - b.turn
  }
  const weight = FINDING_WEIGHTS.indexOf(a.weight) - FINDING_WEIGHTS.indexOf(b.weight)
  return weight !== 0 ? weight : a.id - b.id
}

/** The findings routed per D9: a note that no beat was built from goes
 *  behind "Every other finding", one with no game to the whole match's
 *  list, and every other one is a marker. */
export function routeFindings(sources: readonly MarkerSource[], timeline: Timeline): Routed {
  const wholeMatch: MarkerSource[] = []
  const rest: MarkerSource[] = []
  const placed: MarkerSource[] = []
  for (const source of sources) {
    if (source.weight === 'note' && !source.beat) rest.push(source)
    else if (source.game == null) wholeMatch.push(source)
    else placed.push(source)
  }
  const markers = placed
    .sort(stripOrder)
    .map((source) => ({ ...source, placement: placeOn(timeline, source.game as number, source.turn) }))
  return { wholeMatch, markers, rest }
}

/** Heaviest first, then by game and turn; the whole match before its
 *  games, and a game's own findings before its turns'. */
export function byWeightThenPlace(a: ReportFinding, b: ReportFinding): number {
  const weight = FINDING_WEIGHTS.indexOf(weightOf(a.severity)) - FINDING_WEIGHTS.indexOf(weightOf(b.severity))
  if (weight !== 0) return weight
  const game = (a.game_number ?? 0) - (b.game_number ?? 0)
  if (game !== 0) return game
  return (a.turn_number ?? 0) - (b.turn_number ?? 0)
}

/** Where a finding happened, in words, without the partial mark. */
export function barePlace(f: ReportFinding, t: TFunction): string {
  if (f.game_number == null) return t('matches.report.wholeMatch')
  if (f.self_turn_index != null) return t('matches.report.placeYourTurn', { game: f.game_number, turn: f.self_turn_index })
  if (f.turn_number != null) return t('matches.report.placeTurn', { game: f.game_number, turn: f.turn_number })
  return t('matches.game.title', { n: f.game_number })
}

/** Where a finding happened, and "partly hidden" when it is. */
export function placeText(f: ReportFinding, t: TFunction): string {
  const place = barePlace(f, t)
  return f.confidence === 'partial' ? t('matches.report.placePartial', { place }) : place
}

/** A marker's full sentence, for the screen reader: its game, its turn
 *  when it has one, its weight in words and its title. */
export function markerLabel(f: ReportFinding, weightWord: string, t: TFunction): string {
  const game = f.game_number ?? 0
  const severity = weightWord
  if (f.self_turn_index != null) {
    return t('matches.timeline.markerYourTurn', { game, turn: f.self_turn_index, severity, title: f.title })
  }
  if (f.turn_number != null) return t('matches.timeline.marker', { game, turn: f.turn_number, severity, title: f.title })
  return t('matches.timeline.markerGame', { game, severity, title: f.title })
}

/** An evidence row whose raw value already appears, spelled out, in the
 *  finding's own title is not repeated beneath it; the full finding is
 *  still in the API response. A row whose value never surfaces in prose (a
 *  pace, a share) still renders, since that is the only place it appears. */
export function evidenceIsRedundant(title: string, value: ReportEvidence['value']): boolean {
  if (value == null || typeof value === 'boolean') return false
  return title.includes(String(value))
}

/** The `?finding=` value as a finding's index, or `null`. */
export function parseFinding(value: string | null): number | null {
  if (value == null || !/^\d+$/.test(value)) return null
  return Number(value)
}

/** The fields a game beat shares with the finding it was built from
 *  (review/summary.py's `_game_beat`). */
type BeatKey = { code: string; game_number?: number | null; turn_number?: number | null }

/** Each game beat's finding, by the finding's index: the first finding of
 *  the same code, game and turn not yet taken. A beat with no such finding
 *  is left out. */
export function beatsByFinding<B extends BeatKey>(
  findings: readonly BeatKey[],
  beats: readonly B[],
): Map<number, B> {
  const taken = new Map<number, B>()
  for (const beat of beats) {
    const index = findings.findIndex(
      (f, i) =>
        !taken.has(i) &&
        f.code === beat.code &&
        (f.game_number ?? null) === (beat.game_number ?? null) &&
        (f.turn_number ?? null) === (beat.turn_number ?? null),
    )
    if (index >= 0) taken.set(index, beat)
  }
  return taken
}
