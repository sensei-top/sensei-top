import { describe, expect, it } from 'vitest'
import type { CoverageOut, CoverageRowOut, Match, MatchupBriefOut } from '../api'
import { type FieldRecord, matchupRows, NBSP } from './matchups'
import {
  briefState,
  lastMetLine,
  pairingAddress,
  pairingHeading,
  pairingMatches,
  pairingTiles,
  withVersion,
} from './pairing'

// Every row, key and name is invented. Timestamps are bare, so UTC, and at
// midday, so that no zone moves the day.

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

describe('pairingAddress', () => {
  it('spells both keys in one segment each, the colon bare', () => {
    expect(pairingAddress('guid:1234', 'archetype:dimir_midrange')).toBe(
      '/decks/guid:1234/matchups/archetype:dimir_midrange',
    )
  })

  it('encodes a space, a comma, the middle dot and a double-faced card’s // in the key', () => {
    // ' ' %20, '·' (U+00B7, C2 B7 in UTF-8) %C2%B7, ',' %2C, '/' %2F.
    expect(pairingAddress('guid:1234', 'colors:RG · Alpha, the Card // Beta Face')).toBe(
      '/decks/guid:1234/matchups/colors:RG%20%C2%B7%20Alpha%2C%20the%20Card%20%2F%2F%20Beta%20Face',
    )
  })
})

describe('withVersion', () => {
  it('carries a chosen version, and leaves the address alone for every version', () => {
    expect(withVersion('/decks/guid:1234/matchups', 'v2')).toBe('/decks/guid:1234/matchups?version=v2')
    expect(withVersion('/decks/guid:1234/matchups', null)).toBe('/decks/guid:1234/matchups')
  })
})

describe('pairingMatches', () => {
  it('keeps the key’s matches over every version, finished or not, newest first', () => {
    const against = pairingMatches('k', [
      [
        match('a', { opponent_key: 'k', started_at: on(1) }),
        match('b', { opponent_key: 'other', started_at: on(5) }),
      ],
      [
        match('c', { opponent_key: 'k', result: null, started_at: on(3) }),
        // No readable start: last.
        match('d', { opponent_key: 'k', started_at: null }),
      ],
    ])
    expect(against.map((m) => m.match_id)).toEqual(['c', 'a', 'd'])
  })
})

describe('pairingHeading', () => {
  it('names an archetype by the newest match’s label, finished or not', () => {
    const heading = pairingHeading('archetype:dimir_midrange', [
      match('a', { opponent_label: 'OlderLabel', started_at: on(1) }),
      // The newest, still in progress.
      match('b', { opponent_label: 'DimirMidrange', result: null, started_at: on(6) }),
    ])
    expect(heading).toEqual({ name: 'Dimir Midrange', showed: null, muted: false, colors: 'UB' })
  })

  it('takes the colours most matches showed, the unfinished counted', () => {
    // Counted over all four: UB twice, UBR once. Over the finished alone
    // it would be one each, and the newest finished (b) showed UBR.
    const heading = pairingHeading('archetype:dimir_midrange', [
      match('a', { opponent_colors: 'UB', started_at: on(1) }),
      match('b', { opponent_colors: 'UBR', started_at: on(4) }),
      match('c', { opponent_colors: 'UB', result: null, started_at: on(2) }),
      match('d', { opponent_colors: null, started_at: on(3) }),
    ])
    expect(heading.colors).toBe('UB')
  })

  it('writes a deck known by colours and a card as unrecognized, the card under it', () => {
    const heading = pairingHeading('colors:RG · Some Card', [
      match('a', {
        opponent_key: 'colors:RG · Some Card',
        opponent_source: 'colors',
        opponent_label: 'RG · Some Card',
        opponent_colors: 'RG',
        started_at: on(2),
      }),
    ])
    expect(heading).toEqual({ name: 'Unrecognized deck', showed: 'showed Some Card', muted: false, colors: 'RG' })
  })

  it('writes a deck with nothing seen as unknown, muted', () => {
    const heading = pairingHeading('unknown', [
      match('a', {
        opponent_key: 'unknown',
        opponent_source: 'unknown',
        opponent_label: 'unknown',
        opponent_colors: null,
        started_at: on(2),
      }),
    ])
    expect(heading).toEqual({ name: 'Unknown deck', showed: null, muted: true, colors: null })
  })

  it('writes a manual pick by its label, as a Matchups row does', () => {
    const heading = pairingHeading('manual:My Pick', [
      match('a', {
        opponent_key: 'manual:My Pick',
        opponent_source: 'manual',
        opponent_label: 'My Pick',
        opponent_colors: 'WU',
        started_at: on(2),
      }),
    ])
    expect(heading).toEqual({ name: 'My Pick', showed: null, muted: false, colors: 'WU' })
  })

  it('with no match, reads the key alone, with no colours', () => {
    expect(pairingHeading('archetype:DimirMidrange', [])).toEqual({
      name: 'Dimir Midrange',
      showed: null,
      muted: false,
      colors: null,
    })
    // As typed: not spaced.
    expect(pairingHeading('manual:MyPick', [])).toEqual({ name: 'MyPick', showed: null, muted: false, colors: null })
    expect(pairingHeading('colors:RG · Some Card', [])).toEqual({
      name: 'Unrecognized deck',
      showed: null,
      muted: false,
      colors: null,
    })
    expect(pairingHeading('unknown', [])).toEqual({ name: 'Unknown deck', showed: null, muted: true, colors: null })
  })

  it('with no match, names an archetype by coverage’s label when given', () => {
    // The key is not the name: the label is taken as it is, not spaced.
    expect(pairingHeading('archetype:Control', [], 'Jeskai Control')).toEqual({
      name: 'Jeskai Control',
      showed: null,
      muted: false,
      colors: null,
    })
    // No label: the key, spaced.
    expect(pairingHeading('archetype:UBMidrange', [], null).name).toBe('UBMidrange')
    expect(pairingHeading('archetype:DimirMidrange', [], undefined).name).toBe('Dimir Midrange')
  })

  it('with a match, keeps the match’s name over coverage’s label', () => {
    const heading = pairingHeading('archetype:dimir_midrange', [match('a', { started_at: on(2) })], 'Other Name')
    expect(heading.name).toBe('Dimir Midrange')
  })
})

describe('briefState', () => {
  /** A coverage row with only what `briefState` reads. */
  const row = (archetypeKey: string, status: string) => ({ archetype_key: archetypeKey, status }) as CoverageRowOut
  const coverage = (...rows: CoverageRowOut[]) => ({ rows, fmt: 'Standard' }) as CoverageOut
  /** A stored brief with only what `briefState` reads. */
  const brief = (archetypeKey: string) => ({ archetype_key: archetypeKey }) as MatchupBriefOut

  it('is not named for a key that is not archetype:X, whatever is stored', () => {
    // A brief and a row spelled as the rest of the key: still no join.
    const cov = coverage(row('Mine', 'ok'))
    const briefs = [brief('Mine')]
    expect(briefState('manual:Mine', cov, briefs)).toEqual({ kind: 'not_named' })
    expect(briefState('colors:RG · Some Card', cov, briefs)).toEqual({ kind: 'not_named' })
    expect(briefState('unknown', cov, briefs)).toEqual({ kind: 'not_named' })
  })

  it('is format_unknown for a named archetype of a deck whose format is null, before any row is read', () => {
    const unknown = { rows: [], fmt: null } as unknown as CoverageOut
    expect(briefState('archetype:Control', unknown, [])).toEqual({ kind: 'format_unknown', archetype: 'Control' })
    expect(briefState('manual:Mine', unknown, [])).toEqual({ kind: 'not_named' })
  })

  it('is written, not stale, for a stored brief even when the deck’s format is null', () => {
    const unknown = { rows: [], fmt: null } as unknown as CoverageOut
    const stored = brief('Control')
    expect(briefState('archetype:Control', unknown, [stored])).toEqual({
      kind: 'written',
      archetype: 'Control',
      brief: stored,
      stale: false,
    })
  })

  it('is written when a brief is stored for X, fresh with an ok row', () => {
    const stored = brief('Control')
    expect(briefState('archetype:Control', coverage(row('Control', 'ok')), [brief('Other'), stored])).toEqual({
      kind: 'written',
      archetype: 'Control',
      brief: stored,
      stale: false,
    })
  })

  it('is written and stale when coverage’s row says stale', () => {
    const stored = brief('Control')
    expect(briefState('archetype:Control', coverage(row('Control', 'stale')), [stored])).toEqual({
      kind: 'written',
      archetype: 'Control',
      brief: stored,
      stale: true,
    })
  })

  it('is written, not stale, for a brief coverage has no row for', () => {
    const stored = brief('Control')
    expect(briefState('archetype:Control', coverage(row('Other', 'stale')), [stored])).toEqual({
      kind: 'written',
      archetype: 'Control',
      brief: stored,
      stale: false,
    })
  })

  it('cannot be written with no brief and a row no_consensus', () => {
    expect(briefState('archetype:Control', coverage(row('Control', 'no_consensus')), [])).toEqual({
      kind: 'cannot_write',
      archetype: 'Control',
    })
  })

  it('is not written with no brief and a row missing, or no row', () => {
    const notWritten = { kind: 'not_written', archetype: 'Control' }
    expect(briefState('archetype:Control', coverage(row('Control', 'missing')), [])).toEqual(notWritten)
    expect(briefState('archetype:Control', coverage(), [])).toEqual(notWritten)
  })

  it('compares X exactly, case and spelling alike', () => {
    // 'control' and 'Control ' are other keys: no brief, no row for X.
    expect(
      briefState('archetype:Control', coverage(row('control', 'no_consensus')), [brief('Control ')]),
    ).toEqual({ kind: 'not_written', archetype: 'Control' })
  })
})

describe('lastMetLine', () => {
  // Sep 20 at noon, UTC as the bare timestamps are.
  const now = Date.parse('2026-09-20T12:00:00Z')

  it('says how long ago the newest match with a start was', () => {
    // The newest is b (Sep 17), three days before now.
    const line = lastMetLine(
      [
        match('a', { started_at: on(10) }),
        match('b', { result: null, started_at: on(17) }),
        match('c', { started_at: null }),
      ],
      now,
    )
    expect(line).toBe('Last met 3d ago')
  })

  it('is absent without a readable start, or without a match', () => {
    expect(lastMetLine([match('a', { started_at: null })], now)).toBeNull()
    expect(lastMetLine([], now)).toBeNull()
  })
})

describe('pairingTiles', () => {
  const win = (id: string) => match(id, { result: 'win', games_won: 2, games_lost: 1 })
  const loss = (id: string) => match(id, { result: 'loss', games_won: 1, games_lost: 2 })
  const draw = (id: string) => match(id, { result: 'draw', games_won: 1, games_lost: 1 })
  const none = new Map<string, FieldRecord>()

  it('at one finished match writes the count, the unfinished left out', () => {
    const [record, games] = pairingTiles(matchupRows([win('a'), match('b', { result: null, games_won: 1 })])[0], none)
    expect(record).toEqual({ label: 'Record', value: '1 of 1', detail: 'matches won' })
    expect(games).toEqual({ label: 'Games', value: '2–1', detail: 'yours first' })
  })

  it('at nine, a draw among them, writes the count', () => {
    // Five wins, three losses, one draw: nine matches, five won. Games:
    // 5×2 + 3×1 + 1 = 14 won, 5×1 + 3×2 + 1 = 12 lost.
    const nine = [win('a'), win('b'), win('c'), win('d'), win('e'), loss('f'), loss('g'), loss('h'), draw('i')]
    const [record, games] = pairingTiles(matchupRows(nine)[0], none)
    expect(record).toEqual({ label: 'Record', value: '5 of 9', detail: 'matches won' })
    expect(games).toEqual({ label: 'Games', value: '14–12', detail: 'yours first' })
  })

  it('at ten, a draw among them, writes the rate over every finished match', () => {
    // Seven wins, two losses, one draw: 7 of 10 is 70% (7 of 9, draws
    // aside, would be 78%).
    const ten = [win('a'), win('b'), win('c'), win('d'), win('e'), win('f'), win('g'), loss('h'), loss('i'), draw('j')]
    const [record] = pairingTiles(matchupRows(ten)[0], none)
    expect(record).toEqual({ label: 'Record', value: '70%', detail: 'won 7 of 10' })
  })

  it('writes the field’s rate over its entries, and says under five are too few', () => {
    const row = matchupRows([win('a')])[0]
    const field = (record: FieldRecord) => new Map([['dimir_midrange', record]])
    expect(pairingTiles(row, field({ winrate: 0.6, entries: 140 }))[2]).toEqual({
      label: 'In tournaments',
      value: '60%',
      detail: `won in tournaments, 140${NBSP}entries`,
    })
    expect(pairingTiles(row, field({ winrate: 0.6, entries: 5 }))[2].detail).toBe(
      `won in tournaments, 5${NBSP}entries`,
    )
    expect(pairingTiles(row, field({ winrate: 0.5, entries: 1 }))[2]).toEqual({
      label: 'In tournaments',
      value: '50%',
      detail: `won in tournaments, 1${NBSP}entry, too few to trust`,
    })
  })

  it('says a named archetype the field has no rate for has no results', () => {
    const row = matchupRows([win('a')])[0]
    const noResults = { label: 'In tournaments', value: '—', detail: 'no tournament results for it' }
    expect(pairingTiles(row, none)[2]).toEqual(noResults)
    expect(pairingTiles(row, new Map([['dimir_midrange', { winrate: null, entries: 12 }]]))[2]).toEqual(noResults)
  })

  it('joins nothing for a key that is not a named archetype', () => {
    // The field knows an archetype spelled as the manual pick is: still no join.
    const field = new Map<string, FieldRecord>([['dimir_midrange', { winrate: 0.6, entries: 140 }]])
    const manual = matchupRows([
      match('a', { opponent_key: 'manual:dimir_midrange', opponent_source: 'manual', opponent_label: 'Mine' }),
    ])[0]
    expect(pairingTiles(manual, field)[2]).toEqual({
      label: 'In tournaments',
      value: '—',
      detail: 'only a named archetype has results',
    })
  })
})
