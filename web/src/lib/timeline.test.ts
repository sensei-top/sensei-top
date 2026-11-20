import { describe, expect, it } from 'vitest'
import type { PositionPoint } from '../api'
import type { ReportFinding } from '../api'
import type { TFunction } from '../i18n'
import {
  barePlace,
  beatsByFinding,
  buildTimeline,
  markerLabel,
  parseFinding,
  placeOn,
  reachOf,
  routeFindings,
  type MarkerSource,
} from './timeline'

function point(game: number, turn: number, index: number): PositionPoint {
  return { game_number: game, turn_number: turn, self_turn_index: null, index }
}

// Game 1 has three turns, game 2 five; listed out of order on purpose.
const TRACK: PositionPoint[] = [
  point(2, 3, -0.1),
  point(1, 1, 0),
  point(2, 1, 0.1),
  point(1, 2, 0.2),
  point(2, 2, 0.3),
  point(1, 3, -0.4),
  point(2, 5, 0.6),
  point(2, 4, 0.2),
]

describe('buildTimeline', () => {
  const timeline = buildTimeline(TRACK)

  it('runs one index across games of unequal length, each opened by its boundary', () => {
    expect(timeline.slots.map((s) => [s.x, s.game, s.turn])).toEqual([
      [0, 1, null],
      [1, 1, 1],
      [2, 1, 2],
      [3, 1, 3],
      [4, 2, null],
      [5, 2, 1],
      [6, 2, 2],
      [7, 2, 3],
      [8, 2, 4],
      [9, 2, 5],
    ])
    expect(timeline.slots[3].index).toBe(-0.4)
    expect(timeline.slots[4].index).toBeNull()
  })

  it('puts each boundary just before its game, and ticks only on turns', () => {
    expect(timeline.segments).toEqual([
      { game: 1, boundary: 0, first: 1, last: 3 },
      { game: 2, boundary: 4, first: 5, last: 9 },
    ])
    expect(timeline.ticks).toEqual([1, 2, 3, 5, 6, 7, 8, 9])
  })

  it('takes one reach over every game, a quarter at least and never past 1', () => {
    // The largest distance is game 2's 0.6, rounded up to 0.75.
    expect(timeline.reach).toBe(0.75)
    expect(reachOf([point(1, 1, 0.05)])).toBe(0.25)
    expect(reachOf([point(1, 1, -1)])).toBe(1)
  })

  it('has nothing for an empty track', () => {
    expect(buildTimeline([])).toEqual({ slots: [], segments: [], ticks: [], reach: 0.25 })
  })
})

describe('placeOn', () => {
  const timeline = buildTimeline([point(1, 2, 0.1), point(1, 4, -0.3), point(1, 6, 0.5)])

  it('puts a recorded turn on its own point', () => {
    expect(placeOn(timeline, 1, 4)).toEqual({ kind: 'turn', x: 2, y: -0.3, shownTurn: 4, shownSelfTurn: null, nearest: false })
  })

  it('puts an unrecorded turn on the nearest earlier point, and says so', () => {
    expect(placeOn(timeline, 1, 5)).toEqual({ kind: 'turn', x: 2, y: -0.3, shownTurn: 4, shownSelfTurn: null, nearest: true })
    expect(placeOn(timeline, 1, 9)).toEqual({ kind: 'turn', x: 3, y: 0.5, shownTurn: 6, shownSelfTurn: null, nearest: true })
  })

  it("puts a turn before the game's first point, or no turn, on the game's boundary", () => {
    expect(placeOn(timeline, 1, 1)).toEqual({ kind: 'game', x: 0, y: 0.5 })
    expect(placeOn(timeline, 1, null)).toEqual({ kind: 'game', x: 0, y: 0.5 })
  })

  it("carries the shown point's count of the player's own turns", () => {
    const own = buildTimeline([
      { game_number: 1, turn_number: 1, self_turn_index: 1, index: 0 },
      { game_number: 1, turn_number: 2, self_turn_index: null, index: 0.1 },
      { game_number: 1, turn_number: 3, self_turn_index: 2, index: 0.2 },
    ])
    expect(placeOn(own, 1, 5)).toEqual({ kind: 'turn', x: 3, y: 0.2, shownTurn: 3, shownSelfTurn: 2, nearest: true })
    expect(placeOn(own, 1, 2)).toEqual({ kind: 'turn', x: 2, y: 0.1, shownTurn: 2, shownSelfTurn: null, nearest: false })
  })

  it('places nothing for a game with no line', () => {
    expect(placeOn(timeline, 2, 3)).toBeNull()
  })
})

describe('routeFindings', () => {
  const timeline = buildTimeline(TRACK)
  const source = (id: number, game: number | null, turn: number | null, weight: MarkerSource['weight'], beat = false) => ({
    id,
    game,
    turn,
    weight,
    beat,
  })

  it('sends a finding with no game to the whole match, and a note that is no beat behind the rest', () => {
    const routed = routeFindings(
      [
        source(0, null, null, 'flag'),
        source(1, null, null, 'note'),
        source(2, 1, 2, 'note'),
        source(3, 1, 2, 'note', true),
        source(4, 2, null, 'notice'),
      ],
      timeline,
    )
    expect(routed.wholeMatch.map((s) => s.id)).toEqual([0])
    expect(routed.rest.map((s) => s.id)).toEqual([1, 2])
    expect(routed.markers.map((m) => m.id)).toEqual([3, 4])
  })

  it("sits a game-only finding on its game's boundary label", () => {
    const routed = routeFindings([source(0, 2, null, 'flag')], timeline)
    expect(routed.markers[0].placement).toEqual({ kind: 'game', x: 4, y: 0.75 })
  })

  it("leaves off the chart a finding whose game has no line, and keeps it in the strip", () => {
    const routed = routeFindings([source(0, 3, 2, 'decisive')], timeline)
    expect(routed.markers).toHaveLength(1)
    expect(routed.markers[0].placement).toBeNull()
  })

  it("orders the strip by game, the game's own first, then turn, heaviest first, then as listed", () => {
    const routed = routeFindings(
      [
        source(0, 2, 3, 'notice'),
        source(1, 1, 3, 'flag'),
        source(2, 2, 1, 'flag'),
        source(3, 2, null, 'notice'),
        source(4, 2, 3, 'decisive'),
        source(5, 1, 1, 'notice'),
        source(6, 2, 3, 'notice'),
      ],
      timeline,
    )
    expect(routed.markers.map((m) => m.id)).toEqual([5, 1, 3, 2, 4, 0, 6])
  })
})

describe('beatsByFinding', () => {
  it('pairs each beat with the finding of its code, game and turn, once', () => {
    const findings = [
      { code: 'turning_point', game_number: 1, turn_number: 4 },
      { code: 'damage_race', game_number: 1, turn_number: null },
      { code: 'damage_race', game_number: 2, turn_number: null },
    ]
    const beats = [
      { code: 'damage_race', game_number: 2, turn_number: null, label: 'B' },
      { code: 'turning_point', game_number: 1, turn_number: 4, label: 'A' },
      { code: 'turning_point', game_number: 3, turn_number: 4, label: 'none' },
    ]
    const paired = beatsByFinding(findings, beats)
    expect([...paired.entries()].map(([i, b]) => [i, b.label]).sort()).toEqual([
      [0, 'A'],
      [2, 'B'],
    ])
  })

  it('gives a finding to one beat only, when two beats share its key', () => {
    const findings = [
      { code: 'damage_race', game_number: 1, turn_number: null },
      { code: 'damage_race', game_number: 1, turn_number: null },
    ]
    const beats = [
      { code: 'damage_race', game_number: 1, turn_number: null, label: 'first' },
      { code: 'damage_race', game_number: 1, turn_number: null, label: 'second' },
      { code: 'damage_race', game_number: 1, turn_number: null, label: 'third' },
    ]
    const paired = beatsByFinding(findings, beats)
    expect([...paired.entries()].map(([i, b]) => [i, b.label])).toEqual([
      [0, 'first'],
      [1, 'second'],
    ])
  })
})

describe('parseFinding', () => {
  it('reads an index, and nothing else', () => {
    expect(parseFinding('3')).toBe(3)
    expect(parseFinding(null)).toBeNull()
    expect(parseFinding('x')).toBeNull()
    expect(parseFinding('-1')).toBeNull()
  })
})

describe('place wording', () => {
  // Echoes the key and its parameters, so the test reads which wording was chosen.
  const t = ((key: string, params?: Record<string, unknown>) => `${key}:${JSON.stringify(params)}`) as unknown as TFunction
  const finding = (turn: number | null, self: number | null) =>
    ({ game_number: 1, turn_number: turn, self_turn_index: self, title: 'x' }) as unknown as ReportFinding

  it('leads with the game turn and adds the own turn when known', () => {
    expect(barePlace(finding(12, 6), t)).toBe('matches.report.placeYourTurn:{"game":1,"turn":12,"self":6}')
    expect(markerLabel(finding(12, 6), 'flag', t)).toBe(
      'matches.timeline.markerYourTurn:{"game":1,"turn":12,"self":6,"severity":"flag","title":"x"}',
    )
  })

  it('keeps the game and turn wording with no own turn', () => {
    expect(barePlace(finding(12, null), t)).toBe('matches.report.placeTurn:{"game":1,"turn":12}')
  })
})
