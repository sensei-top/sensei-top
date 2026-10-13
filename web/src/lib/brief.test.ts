import { describe, expect, it } from 'vitest'
import type { CoverageOut, CoverageRowOut } from '../api'
import { translator } from '../i18n'
import {
  ageText,
  coverageName,
  coveragePromptNotes as promptNotes,
  coverageStatusWord as statusWord,
  coverageTiles as tilesOf,
  isCoverageGap,
} from './brief'
import { NBSP } from './matchups'

const t = translator('en')
const coverageTiles = (coverage: CoverageOut) => tilesOf(coverage, t)
const coverageStatusWord = (status: string) => statusWord(status, t)
const coveragePromptNotes = (prompt: { no_consensus: string[]; deferred: string[] }, rows: CoverageRowOut[]) =>
  promptNotes(prompt, rows, t)

// Every row, key and name is invented.

/** A coverage row with only what these functions read. */
function row(archetypeKey: string, status: string, rest: Partial<CoverageRowOut> = {}): CoverageRowOut {
  return { archetype_key: archetypeKey, label: null, field_share: null, status, ...rest } as CoverageRowOut
}

/** A deck's coverage with only what `coverageTiles` reads. */
function coverage(rows: CoverageRowOut[], rest: Partial<CoverageOut> = {}): CoverageOut {
  return {
    rows,
    matches_covered: null,
    matches_covered_numerator: 0,
    matches_covered_denominator: 0,
    field_covered: 0,
    ...rest,
  } as CoverageOut
}

describe('isCoverageGap', () => {
  it('is a row missing or stale, never one ok or with too few lists', () => {
    expect(['missing', 'stale', 'ok', 'no_consensus'].map((s) => isCoverageGap(row('A', s)))).toEqual([
      true,
      true,
      false,
      false,
    ])
  })
})

describe('coverageTiles', () => {
  it('with gaps and rows of too few lists, counts both', () => {
    // Two gaps (missing, stale) of five rows; two more no_consensus.
    // 12 of 21 is 57.1%, whole 57; the field's 0.34 is 34%.
    const tiles = coverageTiles(
      coverage(
        [
          row('A', 'missing', { field_share: 0.2 }),
          row('B', 'stale', { field_share: 0.1 }),
          row('C', 'ok', { field_share: 0.34 }),
          row('D', 'no_consensus'),
          row('E', 'no_consensus', { field_share: 0.05 }),
        ],
        {
          matches_covered: 12 / 21,
          matches_covered_numerator: 12,
          matches_covered_denominator: 21,
          field_covered: 0.34,
        },
      ),
    )
    expect(tiles).toEqual([
      {
        label: 'Matches covered',
        value: '57%',
        detail: `12 of 21${NBSP}matches against a named archetype`,
      },
      { label: 'Field covered', value: '34%', detail: 'of tournament decks have an up-to-date brief' },
      { label: 'To write', value: '2', detail: `of 5${NBSP}archetypes; 2${NBSP}more have too few lists` },
    ])
  })

  it('with no gap, no rows of too few lists, and no match against a named archetype', () => {
    // matches_covered null: none met. Every field_share null: no results.
    const tiles = coverageTiles(coverage([row('A', 'ok'), row('B', 'ok')], { field_covered: 0 }))
    expect(tiles).toEqual([
      { label: 'Matches covered', value: '—', detail: 'no match against a named archetype yet' },
      { label: 'Field covered', value: '—', detail: 'no tournament results yet' },
      { label: 'To write', value: '0', detail: `of 2${NBSP}archetypes` },
    ])
  })

  it('writes each word singular after a count of one', () => {
    // One match against a named archetype, covered: 1 of 1 is 100%, and
    // "match" follows the second count. One row, stale: one to write, of
    // one archetype, and none of too few lists.
    const [matches, , toWrite] = coverageTiles(
      coverage([row('A', 'stale')], {
        matches_covered: 1,
        matches_covered_numerator: 1,
        matches_covered_denominator: 1,
      }),
    )
    expect(matches).toEqual({
      label: 'Matches covered',
      value: '100%',
      detail: `1 of 1${NBSP}match against a named archetype`,
    })
    expect(toWrite).toEqual({ label: 'To write', value: '1', detail: `of 1${NBSP}archetype` })
  })

  it('writes "1 more has" for one row of too few lists', () => {
    // Three rows: one missing, one ok, one no_consensus.
    const [, , toWrite] = coverageTiles(coverage([row('A', 'missing'), row('B', 'ok'), row('C', 'no_consensus')]))
    expect(toWrite).toEqual({
      label: 'To write',
      value: '1',
      detail: `of 3${NBSP}archetypes; 1${NBSP}more has too few lists`,
    })
  })

  it('keeps "matches" plural when only the numerator is one', () => {
    // 1 of 21 is 4.76%, whole 5.
    const [matches] = coverageTiles(
      coverage([row('A', 'missing')], {
        matches_covered: 1 / 21,
        matches_covered_numerator: 1,
        matches_covered_denominator: 21,
      }),
    )
    expect(matches).toEqual({
      label: 'Matches covered',
      value: '5%',
      detail: `1 of 21${NBSP}matches against a named archetype`,
    })
  })

  it('writes the field’s share once any row knows its share, zero included', () => {
    // One row knows a share of the field; none is covered: 0%.
    const [, field] = coverageTiles(
      coverage([row('A', 'missing', { field_share: 0.1 }), row('B', 'missing')], { field_covered: 0 }),
    )
    expect(field).toEqual({ label: 'Field covered', value: '0%', detail: 'of tournament decks have an up-to-date brief' })
  })
})

describe('coverageStatusWord', () => {
  it('writes each status as its word, and one not known here as sent', () => {
    expect(coverageStatusWord('ok')).toBe('Written')
    expect(coverageStatusWord('stale')).toBe('Out of date')
    expect(coverageStatusWord('missing')).toBe('Not written')
    expect(coverageStatusWord('no_consensus')).toBe('Too few lists')
    expect(coverageStatusWord('something_new')).toBe('something_new')
  })
})

describe('coverageName', () => {
  it('is the row’s label, or its key spaced with none', () => {
    expect(coverageName(row('Control', 'ok', { label: 'Jeskai Control' }))).toBe('Jeskai Control')
    expect(coverageName(row('BorosBurn', 'ok'))).toBe('Boros Burn')
  })
})

describe('coveragePromptNotes', () => {
  const rows = [row('Control', 'missing', { label: 'Jeskai Control' }), row('UBMidrange', 'stale')]

  it('names each key by its row’s label, or the key spaced, joined by commas', () => {
    // Control has a label; BorosBurn has no row, spaced; UBMidrange has a
    // row with no label, and no lower-case letter before a capital, so it
    // stays as it is; Lifegain has no row and nothing to space.
    expect(
      coveragePromptNotes({ no_consensus: ['Control', 'BorosBurn'], deferred: ['UBMidrange', 'Lifegain'] }, rows),
    ).toEqual([
      'Too few lists to write: Jeskai Control, Boros Burn.',
      'Left for the next prompt: UBMidrange, Lifegain. Save this answer, then build it again.',
    ])
  })

  it('writes no note for an empty list', () => {
    expect(coveragePromptNotes({ no_consensus: [], deferred: ['Control'] }, rows)).toEqual([
      'Left for the next prompt: Jeskai Control. Save this answer, then build it again.',
    ])
    expect(coveragePromptNotes({ no_consensus: [], deferred: [] }, rows)).toEqual([])
  })
})

describe('ageText', () => {
  const ago = (hours: number) => ageText(new Date(Date.now() - hours * 3_600_000).toISOString(), t)

  it('writes under an hour as just now, then hours, then days', () => {
    expect(ago(0.2)).toBe('just now')
    expect(ago(5)).toBe('5h ago')
    expect(ago(72)).toBe('3d ago')
  })
})
