import { describe, expect, it } from 'vitest'
import type {
  ArchetypeChangeOut,
  ArchetypeShareOut,
  CardVerdictOut,
  Match,
  MatchupPlanOut,
  PlanProblemOut,
} from '../api'
import {
  categoryLabel,
  copiesLine,
  differSentence,
  fieldCaption,
  gapPoints,
  guideSections,
  inLineSummary,
  listGroups,
  movementWords,
  num,
  orphanProblems,
  ownedProblems,
  patternMatches,
  problemSentence,
  rowScrollTarget,
  scrollEdge,
  spyCurrent,
  TIMING_BUCKETS,
  TIMING_LABELS,
  timingRecord,
  turnsOf,
  verdictLabel,
  winsOf,
  zoneLabel,
} from './guide'

/** A no-break space, as the functions write it between a count and its word. */
const NBSP = '\u00a0'

describe('num', () => {
  it('writes a number as text', () => {
    expect(num(0)).toBe('0')
    expect(num(5.5)).toBe('5.5')
  })

  it('is a dash for null or undefined', () => {
    expect(num(null)).toBe('—')
    expect(num(undefined)).toBe('—')
  })
})

describe('winsOf', () => {
  it('rounds the rate times the count', () => {
    // 0.349 * 43 = 15.007.
    expect(winsOf(0.349, 43)).toBe(15)
  })

  it('is zero at a zero rate', () => {
    expect(winsOf(0, 10)).toBe(0)
  })
})

describe('turnsOf', () => {
  it('holds each turn once, from both sides', () => {
    expect(turnsOf({ '2': {}, '3': {} }, { '3': {}, '4': {} })).toEqual(['2', '3', '4'])
  })

  it('reads the turns of one side when the other is absent', () => {
    expect(turnsOf(undefined, { '5': {}, '6': {} })).toEqual(['5', '6'])
  })

  it('is an empty list when both sides are absent', () => {
    expect(turnsOf(undefined, undefined)).toEqual([])
  })

  it('orders numerically, not lexically', () => {
    // Two sides, because one object's integer keys already come out in
    // numeric order: only the join can put '10' before '2'.
    expect(turnsOf({ '10': {} }, { '2': {}, '9': {} })).toEqual(['2', '9', '10'])
  })
})

describe('categoryLabel', () => {
  it('capitalizes a plain category', () => {
    expect(categoryLabel('clock')).toBe('Clock')
  })

  it('turns every underscore into a space', () => {
    expect(categoryLabel('card_advantage')).toBe('Card advantage')
  })
})

describe('gapPoints', () => {
  it('rounds a fraction to whole percentage points', () => {
    expect(gapPoints(0.236)).toBe(24)
  })

  it('is zero at a zero gap', () => {
    expect(gapPoints(0)).toBe(0)
  })
})

describe('zoneLabel', () => {
  it('reads each known zone', () => {
    expect(zoneLabel('hand/Creature')).toBe('Creatures in your hand')
    expect(zoneLabel('graveyard/Instant')).toBe('Instants in your graveyard')
    expect(zoneLabel('exile/Creature')).toBe('Creatures in exile')
    expect(zoneLabel('battlefield/Land')).toBe('Lands on the battlefield')
  })

  it('pluralizes a type other than the four-zone examples', () => {
    expect(zoneLabel('graveyard/Sorcery')).toBe('Sorceries in your graveyard')
  })

  it('returns an unknown zone as sent', () => {
    expect(zoneLabel('command/Creature')).toBe('command/Creature')
  })

  it('returns an unknown type as sent', () => {
    expect(zoneLabel('hand/Emblem')).toBe('hand/Emblem')
  })

  it('returns text with no slash as sent', () => {
    expect(zoneLabel('hand')).toBe('hand')
  })
})

describe('TIMING_LABELS', () => {
  it('holds a label for every one of TIMING_BUCKETS', () => {
    for (const bucket of TIMING_BUCKETS) {
      expect(TIMING_LABELS[bucket]).toBeTypeOf('string')
    }
  })
})

describe('timingRecord', () => {
  it('is wins-losses, wins first, en dash', () => {
    expect(timingRecord({ w: 40, l: 36 })).toBe('40–36')
  })

  it('is a dash alone for no record', () => {
    expect(timingRecord(undefined)).toBe('—')
  })
})

describe('patternMatches', () => {
  // Only `match_id` and `started_at` matter to this function: the rest of
  // `Match` is asked for by the type but never read here.
  const row = (matchId: string, startedAt: string | null): Match => ({ match_id: matchId, started_at: startedAt }) as Match

  it('orders rows newest first, out of the order given', () => {
    const matches = [row('a', '2026-08-01T00:00:00'), row('b', '2026-08-10T00:00:00'), row('c', '2026-08-05T00:00:00')]
    expect(patternMatches(['c', 'a', 'b'], matches).rows.map((m) => m.match_id)).toEqual(['b', 'c', 'a'])
  })

  it('puts a match with no start after every match that has one', () => {
    const matches = [row('a', null), row('b', '2026-08-10T00:00:00')]
    expect(patternMatches(['a', 'b'], matches).rows.map((m) => m.match_id)).toEqual(['b', 'a'])
  })

  it('counts an id the list does not hold as missing, not as a row', () => {
    const matches = [row('a', '2026-08-01T00:00:00')]
    const result = patternMatches(['a', 'x'], matches)
    expect(result.rows.map((m) => m.match_id)).toEqual(['a'])
    expect(result.missing).toEqual(['x'])
  })

  it('is one row for an id given twice', () => {
    const matches = [row('a', '2026-08-01T00:00:00')]
    const result = patternMatches(['a', 'a'], matches)
    expect(result.rows.map((m) => m.match_id)).toEqual(['a'])
    expect(result.missing).toEqual([])
  })

  it('is empty rows and empty missing for no id', () => {
    const matches = [row('a', '2026-08-01T00:00:00')]
    expect(patternMatches([], matches)).toEqual({ rows: [], missing: [] })
  })
})

// A card of the list diff carries only what the list's functions read.
const verdictCard = (
  card: string,
  verdict: string,
  yours = 4,
  copies: number | null = 4,
  share: number | null = 1,
): CardVerdictOut =>
  ({ card, verdict, yours, consensus_copies: copies, consensus_share: share }) as CardVerdictOut

describe('verdictLabel', () => {
  it('names each of the four verdicts that differ', () => {
    expect(verdictLabel('add')).toBe('Add')
    expect(verdictLabel('trim')).toBe('Trim')
    expect(verdictLabel('cut')).toBe('Cut')
    expect(verdictLabel('flex')).toBe('Not in the field')
  })

  it('is null for correct, which draws no chip', () => {
    expect(verdictLabel('correct')).toBeNull()
  })

  it('reads an unknown word through categoryLabel', () => {
    expect(verdictLabel('side_only')).toBe('Side only')
  })
})

describe('listGroups', () => {
  it('splits the cards, each group in the order given', () => {
    // Neither a sort by name nor one by verdict gives this order.
    const cards = [
      verdictCard('d', 'correct'),
      verdictCard('c', 'flex'),
      verdictCard('b', 'correct'),
      verdictCard('a', 'add'),
    ]
    const { differing, inLine } = listGroups(cards)
    expect(differing.map((c) => c.card)).toEqual(['c', 'a'])
    expect(inLine.map((c) => c.card)).toEqual(['d', 'b'])
  })

  it('is no card differing when every card is correct', () => {
    const { differing, inLine } = listGroups([verdictCard('a', 'correct'), verdictCard('b', 'correct')])
    expect(differing).toEqual([])
    expect(inLine.map((c) => c.card)).toEqual(['a', 'b'])
  })

  it('is two empty groups for no card', () => {
    expect(listGroups([])).toEqual({ differing: [], inLine: [] })
  })
})

describe('copiesLine', () => {
  it('reads a card the viewer plays once, which every list plays', () => {
    expect(copiesLine(verdictCard('a', 'add', 1, 4.6, 1))).toBe('You play 1 · the field 4.6, in 100.0% of its lists')
  })

  it('reads a card the viewer does not play', () => {
    // 0.575 of the lists is 57.5%.
    expect(copiesLine(verdictCard('a', 'add', 0, 2.8, 0.575))).toBe(
      'You play none · the field 2.8, in 57.5% of its lists',
    )
  })

  it('says no list plays a flex card', () => {
    expect(copiesLine(verdictCard('a', 'flex', 1, null, null))).toBe('You play 1 · no list of the field plays it')
  })

  it('writes a share of 0.025 with its decimal', () => {
    expect(copiesLine(verdictCard('a', 'trim', 2, 1, 0.025))).toBe('You play 2 · the field 1.0, in 2.5% of its lists')
  })
})

describe('differSentence', () => {
  it('counts several cards that differ, in the plural', () => {
    expect(differSentence(4, 19)).toBe(`4 of the 19${NBSP}cards differ from the field.`)
  })

  it('counts one card that differs, in the singular', () => {
    expect(differSentence(1, 19)).toBe(`1 of the 19${NBSP}cards differs from the field.`)
  })

  it('says none differs', () => {
    expect(differSentence(0, 19)).toBe(`None of the 19${NBSP}cards differs from the field.`)
  })

  it('reads a board of one card in its own words', () => {
    expect(differSentence(0, 1)).toBe('The one card is in line with the field.')
    expect(differSentence(1, 1)).toBe('The one card differs from the field.')
  })

  it('says a board of no card has none', () => {
    expect(differSentence(0, 0)).toBe('No card.')
  })
})

describe('inLineSummary', () => {
  it('counts several cards in line', () => {
    expect(inLineSummary(15)).toBe(`The 15${NBSP}cards in line with the field`)
  })

  it('reads one card in line in its own words', () => {
    expect(inLineSummary(1)).toBe('The one card in line with the field')
  })
})

describe('movementWords', () => {
  it('reads a rise in points, one decimal', () => {
    // 0.1399 is 13.99 points, 14.0 at one decimal.
    expect(movementWords(0.1399)).toBe(`up 14.0${NBSP}points`)
  })

  it('reads a fall in points, the sign in words', () => {
    expect(movementWords(-0.032)).toBe(`down 3.2${NBSP}points`)
  })

  it('is level when the movement rounds to 0.0 points, either way', () => {
    // 0.0004 is 0.04 points.
    expect(movementWords(0.0004)).toBe('level')
    expect(movementWords(-0.0004)).toBe('level')
  })

  it('is null with no movement', () => {
    expect(movementWords(null)).toBeNull()
    expect(movementWords(undefined)).toBeNull()
  })
})

describe('fieldCaption', () => {
  const share = (decks: number, movement: number | null): ArchetypeShareOut =>
    ({ archetype: 'A', decks, movement }) as ArchetypeShareOut
  const change = (verdict: string): ArchetypeChangeOut => ({ archetype: 'A', verdict }) as ArchetypeChangeOut

  it('names a change at the reset', () => {
    expect(fieldCaption(share(285, 0.14), change('changed'))).toBe(
      `285${NBSP}lists · up 14.0${NBSP}points · changed at the reset`,
    )
  })

  it('leaves an intact archetype unsaid', () => {
    expect(fieldCaption(share(285, 0.14), change('intact'))).toBe(`285${NBSP}lists · up 14.0${NBSP}points`)
  })

  it('names an archetype gone since the reset', () => {
    expect(fieldCaption(share(285, -0.032), change('gone'))).toBe(
      `285${NBSP}lists · down 3.2${NBSP}points · gone since the reset`,
    )
  })

  it('leaves the reset out with no entry in changes', () => {
    expect(fieldCaption(share(285, 0.14), undefined)).toBe(`285${NBSP}lists · up 14.0${NBSP}points`)
  })

  it('leaves the movement out when there is none', () => {
    expect(fieldCaption(share(285, null), change('changed'))).toBe(`285${NBSP}lists · changed at the reset`)
  })

  it('reads one list in the singular, and too few to trust', () => {
    // One list is under MIN_TRUSTED_FIELD_SAMPLE (5) too.
    expect(fieldCaption(share(1, null), undefined)).toBe(`1${NBSP}list, too few to trust`)
  })

  it('says four lists are too few to trust', () => {
    expect(fieldCaption(share(4, null), undefined)).toBe(`4${NBSP}lists, too few to trust`)
  })
})

describe('guideSections', () => {
  const labels = (parts: { written: boolean; plans: boolean; checklist: boolean }) =>
    guideSections(parts).map((s) => s.label)

  it('holds nine sections with every written part, in the page order', () => {
    expect(labels({ written: true, plans: true, checklist: true })).toEqual([
      'Scope',
      'How it works',
      'Your play',
      'The list',
      'The field',
      'Sideboard plans',
      'Matchup coverage',
      'Between rounds',
      'Write and export',
    ])
  })

  it('holds six with no written guide', () => {
    expect(labels({ written: false, plans: false, checklist: false })).toEqual([
      'Scope',
      'Your play',
      'The list',
      'The field',
      'Matchup coverage',
      'Write and export',
    ])
  })

  it('holds seven with a written guide that has no plan and no checklist', () => {
    expect(labels({ written: true, plans: false, checklist: false })).toEqual([
      'Scope',
      'How it works',
      'Your play',
      'The list',
      'The field',
      'Matchup coverage',
      'Write and export',
    ])
  })

  it('gives each section its own id', () => {
    const ids = guideSections({ written: true, plans: true, checklist: true }).map((s) => s.id)
    expect(new Set(ids).size).toBe(9)
    expect(ids).toEqual([
      'guide-scope',
      'guide-how-it-works',
      'guide-your-play',
      'guide-the-list',
      'guide-the-field',
      'guide-sideboard-plans',
      'guide-matchup-coverage',
      'guide-between-rounds',
      'guide-write',
    ])
  })
})

describe('scrollEdge', () => {
  // A page 3,000 px tall in a window 800 px tall: its end is at scrollY 2,200.
  it('is the top when the window is not scrolled', () => {
    expect(scrollEdge(0, 800, 3000)).toBe('top')
  })

  it('is the end at the last scroll position, and within 2 px of it', () => {
    expect(scrollEdge(2200, 800, 3000)).toBe('end')
    expect(scrollEdge(2198, 800, 3000)).toBe('end')
  })

  it('is neither 3 px short of the end, nor 1 px down from the top', () => {
    expect(scrollEdge(2197, 800, 3000)).toBeNull()
    expect(scrollEdge(1, 800, 3000)).toBeNull()
  })

  it('is the top for a page that fits the window', () => {
    expect(scrollEdge(0, 800, 600)).toBe('top')
  })
})

describe('spyCurrent', () => {
  const ids = ['guide-scope', 'guide-the-list', 'guide-write']

  it("is the observer's answer between the ends", () => {
    expect(spyCurrent(ids, 'guide-the-list', null)).toBe('guide-the-list')
  })

  it('is the first id at the top, whatever the observer said last', () => {
    expect(spyCurrent(ids, 'guide-the-list', 'top')).toBe('guide-scope')
  })

  it('is the last id at the end, whatever the observer said last', () => {
    expect(spyCurrent(ids, 'guide-the-list', 'end')).toBe('guide-write')
  })

  it("is the observer's answer with no ids", () => {
    expect(spyCurrent([], '', 'end')).toBe('')
  })
})

describe('rowScrollTarget', () => {
  // A row 360 px wide over 499 px of links: its last scroll position is
  // 499 - 360 = 139.
  const row = { rowWidth: 360, scrollWidth: 499 }

  it('leaves the row alone when the link is whole inside it where it is going', () => {
    // 100..168 lies inside 0..360.
    expect(rowScrollTarget({ ...row, pendingLeft: 0, linkLeft: 100, linkWidth: 68 })).toBeNull()
    // 150..218 lies inside 139..499.
    expect(rowScrollTarget({ ...row, pendingLeft: 139, linkLeft: 150, linkWidth: 68 })).toBeNull()
  })

  it('brings back a link that a scroll in flight would carry out of view', () => {
    // The case measured at 360 px: the row on its way to 139, the link at
    // 65..133, which the row at 139 would not show. Centred it would be
    // 65 - (360 - 68) / 2 = -81, held at 0.
    expect(rowScrollTarget({ ...row, pendingLeft: 139, linkLeft: 65, linkWidth: 68 })).toBe(0)
  })

  it('puts a link in the middle when there is room on both sides', () => {
    // A row 200 px wide over 1,000 px, the link at 500..560, the row at 0:
    // 500 - (200 - 60) / 2 = 430.
    expect(
      rowScrollTarget({ rowWidth: 200, scrollWidth: 1000, pendingLeft: 0, linkLeft: 500, linkWidth: 60 }),
    ).toBe(430)
  })

  it('holds the target at the last scroll position', () => {
    // The last link, 431..499: centred 431 - 146 = 285, held at 139.
    expect(rowScrollTarget({ ...row, pendingLeft: 0, linkLeft: 431, linkWidth: 68 })).toBe(139)
  })

  it('counts a link cut by one pixel as out of view', () => {
    // 293..361 runs 1 px past 0..360; centred 293 - 146 = 147, held at 139.
    expect(rowScrollTarget({ ...row, pendingLeft: 0, linkLeft: 293, linkWidth: 68 })).toBe(139)
  })
})

const problem = (archetype: string, message: string): PlanProblemOut => ({ archetype, message }) as PlanProblemOut
const plan = (archetype: string): MatchupPlanOut => ({ archetype }) as MatchupPlanOut

describe('ownedProblems', () => {
  it("keeps only the plan's own archetype, in the server's order", () => {
    const problems = [
      problem('DimirMidrange', 'first'),
      problem('MonoRedAggro', 'other'),
      problem('DimirMidrange', 'second'),
    ]
    expect(ownedProblems(problems, 'DimirMidrange').map((p) => p.message)).toEqual(['first', 'second'])
    expect(ownedProblems(problems, 'MonoRedAggro').map((p) => p.message)).toEqual(['other'])
    expect(ownedProblems(problems, 'AzoriusControl')).toEqual([])
  })
})

describe('orphanProblems', () => {
  it('keeps the problems no plan owns, grouped by archetype in order of first appearance', () => {
    // DimirMidrange has a plan, so its problem is the plan's own. The
    // others group by archetype: MonoRedAggro first seen first, so both of
    // its problems come before the (sideboard) one given between them.
    const problems = [
      problem('MonoRedAggro', 'red one'),
      problem('(sideboard)', 'never brought in'),
      problem('DimirMidrange', 'owned'),
      problem('MonoRedAggro', 'red two'),
    ]
    const plans = [plan('DimirMidrange'), plan('AzoriusControl')]
    expect(orphanProblems(problems, plans).map((p) => p.message)).toEqual([
      'red one',
      'red two',
      'never brought in',
    ])
  })

  it('is empty when every problem has its plan', () => {
    expect(orphanProblems([problem('DimirMidrange', 'owned')], [plan('DimirMidrange')])).toEqual([])
  })
})

describe('problemSentence', () => {
  it("capitalises a plan's own problem and adds nothing", () => {
    expect(
      problemSentence(problem('DimirMidrange', 'brings in 3x Rest in Peace, but the sideboard only has 2.'), false),
    ).toBe('Brings in 3x Rest in Peace, but the sideboard only has 2.')
  })

  it('leaves the archetype out of an orphan problem whose archetype is in brackets', () => {
    expect(problemSentence(problem('(sideboard)', 'never brought in by any matchup plan: Pyroclasm.'), true)).toBe(
      'Never brought in by any matchup plan: Pyroclasm.',
    )
  })

  it("puts the archetype's name and a colon before any other orphan problem", () => {
    expect(
      problemSentence(problem('DimirMidrange', 'brings in 3x Rest in Peace, but the sideboard only has 2.'), true),
    ).toBe('Dimir Midrange: Brings in 3x Rest in Peace, but the sideboard only has 2.')
  })

  it('leaves a message that starts with a digit as it is', () => {
    expect(problemSentence(problem('DimirMidrange', '3 cards too many.'), false)).toBe('3 cards too many.')
  })

  it('leaves a message that starts with a capital as it is', () => {
    expect(problemSentence(problem('DimirMidrange', 'Too many cards.'), false)).toBe('Too many cards.')
  })
})
