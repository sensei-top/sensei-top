import { describe, expect, it } from 'vitest'
import type { Match, MetaWinrate } from '../api'
import { translator } from '../i18n'
import {
  archetypeKeyOf,
  fieldLine as fieldLineOf,
  type FieldRecord,
  fieldRecordsByKey,
  matchupName as nameOf,
  matchupRows,
  NBSP,
  matchupTiles as tilesOf,
  type MatchupRow,
} from './matchups'

// Every row and name is invented. Timestamps are bare, the log's own local
// clock; only their order matters here. The no-break space is the source's own `NBSP`.

/** The word joiner a record keeps each side of its dash. */
const WJ = '\u2060'

const t = translator('en')
const matchupName = (row: Parameters<typeof nameOf>[0]) => nameOf(row, t)
const matchupTiles = (rows: MatchupRow[]) => tilesOf(rows, t)
const fieldLine = (games: { won: number; lost: number }, field: FieldRecord | null | undefined) =>
  fieldLineOf(games, field, t)

/** A row of `/api/matches` with only what these functions read. */
function match(matchId: string, rest: Partial<Match> = {}): Match {
  return {
    match_id: matchId,
    deck_id: 'v1',
    result: 'win',
    started_at: null,
    opponent_key: 'archetype:dimir_midrange',
    opponent_label: 'DimirMidrange',
    opponent_colors: 'UB',
    opponent_source: 'classifier',
    games_won: null,
    games_lost: null,
    ...rest,
  } as Match
}

/** The day `day` of September 2026 at noon. */
const on = (day: number) => `2026-09-${String(day).padStart(2, '0')}T12:00:00`

/** A row of `matchupRows` with only what the tiles read. */
function row(key: string, matches: number, won: number, rest: Partial<MatchupRow> = {}): MatchupRow {
  return {
    key,
    kind: 'named',
    label: key,
    colors: null,
    matches,
    won,
    // No draws unless a test says so.
    lost: matches - won,
    gamesWon: 0,
    gamesLost: 0,
    ...rest,
  }
}

describe('matchupRows', () => {
  it('counts one key over every version, finished matches only, a draw a match and not a win', () => {
    const rows = matchupRows([
      match('a', { deck_id: 'v1', result: 'win', started_at: on(1), games_won: 2, games_lost: 1 }),
      match('b', { deck_id: 'v2', result: 'loss', started_at: on(2), games_won: 0, games_lost: 2 }),
      match('c', { deck_id: 'v2', result: 'draw', started_at: on(3), games_won: 1, games_lost: 1 }),
      // Not finished: left out, its games too.
      match('d', { deck_id: 'v1', result: null, started_at: on(4), games_won: 1, games_lost: 0 }),
      match('e', { deck_id: 'v1', result: 'incomplete', started_at: on(5) }),
    ])
    // Three finished (a, b, c); one win (a), one loss (b), one draw (c); games 2+0+1 won, 1+2+1 lost.
    expect(rows).toEqual([
      {
        key: 'archetype:dimir_midrange',
        kind: 'named',
        label: 'DimirMidrange',
        colors: 'UB',
        matches: 3,
        won: 1,
        lost: 1,
        gamesWon: 3,
        gamesLost: 4,
      },
    ])
  })

  it('leaves out a key whose every match is unfinished', () => {
    expect(matchupRows([match('a', { result: null })])).toEqual([])
  })

  it('takes the colours most matches showed, not the union', () => {
    const rows = matchupRows([
      match('a', { started_at: on(1), opponent_colors: 'UB' }),
      match('b', { started_at: on(2), opponent_colors: 'UB' }),
      // The newest shows a third colour; two of three showed UB.
      match('c', { started_at: on(3), opponent_colors: 'UBR' }),
      match('d', { started_at: on(4), opponent_colors: null }),
    ])
    expect(rows[0].colors).toBe('UB')
  })

  it('among equal counts takes the newest match’s colours', () => {
    const rows = matchupRows([
      match('a', { started_at: on(1), opponent_colors: 'UB' }),
      match('b', { started_at: on(2), opponent_colors: 'UBR' }),
      match('c', { started_at: on(3), opponent_colors: 'UB' }),
      match('d', { started_at: on(4), opponent_colors: 'UBR' }),
    ])
    // Two each; the newest (d, Sep 4) showed UBR.
    expect(rows[0].colors).toBe('UBR')
  })

  it('has no colours when no match showed any', () => {
    const rows = matchupRows([match('a', { opponent_colors: null }), match('b', { opponent_colors: '' })])
    expect(rows[0].colors).toBeNull()
  })

  it('tells the three kinds by the newest match, as a match row does', () => {
    const rows = matchupRows([
      // Named by the classifier once, then by the viewer: the newest decides.
      match('a', { opponent_key: 'k1', opponent_source: 'classifier', opponent_label: 'Old', started_at: on(1) }),
      match('b', { opponent_key: 'k1', opponent_source: 'manual', opponent_label: 'Mine', started_at: on(9) }),
      match('c', {
        opponent_key: 'k2',
        opponent_source: 'colors',
        opponent_label: 'RG · Some Card',
        opponent_colors: 'RG',
        started_at: on(8),
      }),
      match('d', { opponent_key: 'k3', opponent_source: 'unknown', opponent_label: 'unknown', started_at: on(7) }),
      // Named, but with no label: nothing to call it by.
      match('e', { opponent_key: 'k4', opponent_source: 'classifier', opponent_label: null, started_at: on(6) }),
    ])
    expect(rows.map((r) => [r.key, r.kind, r.label])).toEqual([
      ['k1', 'named', 'Mine'],
      ['k2', 'unrecognized', 'RG · Some Card'],
      ['k3', 'unknown', 'unknown'],
      ['k4', 'unknown', null],
    ])
  })

  it('orders by matches, then the one met last, then the label', () => {
    const rows = matchupRows([
      // k-few: one match, the newest of all, still after both of two.
      match('a', { opponent_key: 'k-few', opponent_label: 'A', started_at: on(20) }),
      // k-old and k-new: two matches each; k-new was met last (Sep 10).
      match('b', { opponent_key: 'k-old', opponent_label: 'A', started_at: on(1) }),
      match('c', { opponent_key: 'k-old', opponent_label: 'A', started_at: on(5) }),
      match('d', { opponent_key: 'k-new', opponent_label: 'Z', started_at: on(2) }),
      match('e', { opponent_key: 'k-new', opponent_label: 'Z', started_at: on(10) }),
      // One match each, met the same moment: by label, B before C.
      match('f', { opponent_key: 'k-c', opponent_label: 'C', started_at: on(3) }),
      match('g', { opponent_key: 'k-b', opponent_label: 'B', started_at: on(3) }),
      // One match with no readable start: after every one that has one.
      match('h', { opponent_key: 'k-undated', opponent_label: 'A', started_at: null }),
    ])
    expect(rows.map((r) => r.key)).toEqual(['k-new', 'k-old', 'k-few', 'k-b', 'k-c', 'k-undated'])
  })
})

describe('matchupName', () => {
  it('spaces a named archetype’s label', () => {
    expect(matchupName(row('k', 1, 1, { label: 'DimirMidrange', colors: 'UB' }))).toEqual({
      name: 'Dimir Midrange',
      showed: null,
      inSentence: 'Dimir Midrange',
    })
  })

  it('writes a deck known by colours and a card as unrecognized, the card under it', () => {
    expect(matchupName(row('k', 1, 1, { kind: 'unrecognized', label: 'RG · Some Card', colors: 'RG' }))).toEqual({
      name: 'Unrecognized deck',
      showed: 'showed Some Card',
      inSentence: 'an unrecognized deck',
    })
  })

  it('writes a deck with nothing seen as unknown', () => {
    expect(matchupName(row('k', 1, 1, { kind: 'unknown', label: null }))).toEqual({
      name: 'Unknown deck',
      showed: null,
      inSentence: 'an unknown deck',
    })
  })
})

describe('matchupTiles', () => {
  it('counts the archetypes met and how many are named', () => {
    const mixed = [
      row('a', 1, 1),
      row('b', 1, 0),
      row('c', 1, 0, { kind: 'unrecognized' }),
      row('d', 1, 0, { kind: 'unknown' }),
    ]
    expect(matchupTiles(mixed)[0]).toEqual({ label: 'Archetypes met', value: '4', detail: `2${NBSP}named, 2${NBSP}not` })
    expect(matchupTiles([row('a', 1, 1), row('b', 1, 0)])[0].detail).toBe('all named')
    expect(matchupTiles([row('c', 1, 0, { kind: 'unknown' })])[0]).toEqual({
      label: 'Archetypes met',
      value: '1',
      detail: 'none named',
    })
  })

  it('names neither best nor worst when no archetype was met ten times', () => {
    const [, best, worst] = matchupTiles([row('a', 9, 9), row('b', 6, 0), row('c', 1, 1)])
    expect(best).toEqual({ label: 'Best matchup', value: '—', detail: `no archetype met 10${NBSP}times yet` })
    expect(worst).toEqual({ label: 'Worst matchup', value: '—', detail: `no archetype met 10${NBSP}times yet` })
  })

  it('with one archetype met ten times, it is the best and the worst says so', () => {
    const [, best, worst] = matchupTiles([row('Solo', 10, 4), row('b', 9, 0)])
    expect(best).toEqual({ label: 'Best matchup', value: '40%', detail: `4${WJ}–${WJ}6 against Solo` })
    expect(worst).toEqual({ label: 'Worst matchup', value: '—', detail: `one archetype met 10${NBSP}times so far` })
  })

  it('leaves out an archetype met nine times and ranks one met ten', () => {
    // 8 of 10 is 80%; 3 of 9 is left out however low.
    const [, best, worst] = matchupTiles([row('High', 10, 8), row('Low', 9, 3), row('Few', 4, 1)])
    expect(best).toEqual({ label: 'Best matchup', value: '80%', detail: `8${WJ}–${WJ}2 against High` })
    expect(worst).toEqual({ label: 'Worst matchup', value: '—', detail: `one archetype met 10${NBSP}times so far` })
  })

  it('ranks by wins over wins plus losses, a draw in neither', () => {
    // Eleven matches with one draw: 6 won, 4 lost is 60%, over ten finished.
    const [, best] = matchupTiles([row('Drawn', 11, 6, { lost: 4 })])
    expect(best).toEqual({ label: 'Best matchup', value: '60%', detail: `6${WJ}–${WJ}4 against Drawn` })
    // Ten matches with a draw leave nine to rate: left out.
    const [, none] = matchupTiles([row('Short', 10, 5, { lost: 4 })])
    expect(none.value).toBe('—')
  })

  it('among equal rates takes the row of more matches, for the best and the worst', () => {
    // Best: 6 of 10 and 12 of 20 are both 60%, the twenty taken. Worst: 2 of 10
    // and 4 of 20 both 20%, the twenty taken.
    const [, best, worst] = matchupTiles([
      row('BestTen', 10, 6),
      row('BestTwenty', 20, 12),
      row('WorstTen', 10, 2),
      row('WorstTwenty', 20, 4),
    ])
    expect(best.detail).toBe(`12${WJ}–${WJ}8 against Best Twenty`)
    expect(worst.detail).toBe(`4${WJ}–${WJ}16 against Worst Twenty`)
  })

  it('with two rows equal in rate and matches, the best takes the first and the worst the other', () => {
    const [, best, worst] = matchupTiles([row('First', 12, 6), row('Second', 12, 6)])
    expect(best.detail).toBe(`6${WJ}–${WJ}6 against First`)
    expect(worst.detail).toBe(`6${WJ}–${WJ}6 against Second`)
  })

  it('writes an archetype that is not named in the tile’s line', () => {
    const [, best, worst] = matchupTiles([
      row('a', 10, 10, { kind: 'unrecognized', label: 'RG · Some Card', colors: 'RG' }),
      row('b', 10, 0, { kind: 'unknown', label: null }),
    ])
    expect(best.detail).toBe(`10${WJ}–${WJ}0 against an unrecognized deck`)
    expect(worst.detail).toBe(`0${WJ}–${WJ}10 against an unknown deck`)
  })
})

describe('archetypeKeyOf', () => {
  it('is the archetype’s own key after the prefix', () => {
    expect(archetypeKeyOf('archetype:dimir_midrange')).toBe('dimir_midrange')
  })

  it('is null for a key the classifier did not name', () => {
    expect(archetypeKeyOf('manual:My Pick')).toBeNull()
    expect(archetypeKeyOf('colors:RG · Some Card')).toBeNull()
    expect(archetypeKeyOf('unknown')).toBeNull()
  })
})

/** A row of `/api/metagame/winrate`, one `(archetype_key, label)`. */
function winrate(
  key: string,
  label: string,
  won: number,
  lost: number,
  drawn: number,
  entries: number,
): MetaWinrate {
  return {
    archetype_key: key,
    label,
    colors: null,
    entries,
    matches_won: won,
    matches_lost: lost,
    matches_drawn: drawn,
    winrate: won + lost + drawn > 0 ? won / (won + lost + drawn) : null,
  }
}

describe('fieldRecordsByKey', () => {
  it('pools two labels of one key to the summed record, whatever their order', () => {
    const jeskai = winrate('control', 'Jeskai Control', 6, 3, 1, 10)
    const sultai = winrate('control', 'Sultai Control', 2, 4, 0, 5)
    const forward = fieldRecordsByKey([jeskai, sultai])
    const reversed = fieldRecordsByKey([sultai, jeskai])
    const pooled = { winrate: 8 / 16, entries: 15 }
    expect(forward.get('control')).toEqual(pooled)
    expect(reversed.get('control')).toEqual(pooled)
  })

  it('has a null rate when a key’s rows total no matches', () => {
    const rows = fieldRecordsByKey([winrate('unplayed', 'Unplayed', 0, 0, 0, 3)])
    expect(rows.get('unplayed')).toEqual({ winrate: null, entries: 3 })
  })

  it('keeps two keys apart', () => {
    const rows = fieldRecordsByKey([winrate('aggro', 'Mono Red', 5, 1, 0, 8), winrate('control', 'Azorius', 1, 5, 0, 4)])
    expect(rows.get('aggro')).toEqual({ winrate: 5 / 6, entries: 8 })
    expect(rows.get('control')).toEqual({ winrate: 1 / 6, entries: 4 })
  })
})

describe('fieldLine', () => {
  const games = { won: 17, lost: 4 }

  it('is the games alone when the field has no record, or no rate', () => {
    expect(fieldLine(games, undefined)).toBe(`Games 17${WJ}–${WJ}4`)
    expect(fieldLine(games, null)).toBe(`Games 17${WJ}–${WJ}4`)
    expect(fieldLine(games, { winrate: null, entries: 12 })).toBe(`Games 17${WJ}–${WJ}4`)
  })

  it('adds the field’s rate and entries from five entries', () => {
    expect(fieldLine(games, { winrate: 0.6, entries: 140 })).toBe(
      `Games 17${WJ}–${WJ}4 · wins 60% in tournaments, 140${NBSP}entries`,
    )
    expect(fieldLine(games, { winrate: 0.6, entries: 5 })).toBe(`Games 17${WJ}–${WJ}4 · wins 60% in tournaments, 5${NBSP}entries`)
  })

  it('says under five entries are too few to trust, one entry in the singular', () => {
    expect(fieldLine(games, { winrate: 0.5, entries: 1 })).toBe(
      `Games 17${WJ}–${WJ}4 · wins 50% in tournaments, 1${NBSP}entry, too few to trust`,
    )
    expect(fieldLine(games, { winrate: 0.25, entries: 4 })).toBe(
      `Games 17${WJ}–${WJ}4 · wins 25% in tournaments, 4${NBSP}entries, too few to trust`,
    )
  })
})
