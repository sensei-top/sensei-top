import { describe, expect, it } from 'vitest'
import type { CoverageOut, CoverageRowOut, Match, MatchupBriefOut } from '../api'
import { translator } from '../i18n'
import { type FieldRecord, matchupRows, type MatchupRow, NBSP } from './matchups'
import {
  briefState,
  lastMetLine as lastMetOf,
  pairingAddress,
  pairingHeading as headingOf,
  pairingMatches,
  pairingTiles as tilesOf,
  withVersion,
} from './pairing'

const t = translator('en')
const pairingHeading = (key: string, matches: Match[], label?: string | null) => headingOf(key, matches, label, t)
const lastMetLine = (matches: Match[], now: number) => lastMetOf(matches, now, t)
const pairingTiles = (row: MatchupRow, field: Map<string, FieldRecord>) => tilesOf(row, field, t)

// Every row, key and name is invented. Timestamps are bare, the log's own
// local clock, and at midday, so that no zone moves the day.

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

  it('carries a known format as ?format=, and none for a missing one', () => {
    expect(pairingAddress('guid:1234', 'archetype:dimir_midrange', 'Modern')).toBe(
      '/decks/guid:1234/matchups/archetype:dimir_midrange?format=Modern',
    )
    expect(pairingAddress('guid:1234', 'archetype:dimir_midrange', null)).toBe(
      '/decks/guid:1234/matchups/archetype:dimir_midrange',
    )
  })
})

describe('withVersion', () => {
  it('carries a chosen version, and leaves the address alone for every version', () => {
    expect(withVersion('/decks/guid:1234/matchups', 'v2')).toBe('/decks/guid:1234/matchups?version=v2')
    expect(withVersion('/decks/guid:1234/matchups', null)).toBe('/decks/guid:1234/matchups')
  })

  it('adds the version after a format the address already carries', () => {
    expect(withVersion('/decks/guid:1234/matchups/k?format=Modern', 'v2')).toBe(
      '/decks/guid:1234/matchups/k?format=Modern&version=v2',
    )
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

  const formats = [
    [
      match('a', { opponent_key: 'k', format: 'Modern', started_at: on(3) }),
      match('b', { opponent_key: 'k', format: 'Pioneer', started_at: on(2) }),
      match('c', { opponent_key: 'k', format: null, started_at: on(1) }),
      match('d', { opponent_key: 'other', format: 'Modern', started_at: on(4) }),
    ],
  ]

  it('keeps one format’s matches when the address names it', () => {
    expect(pairingMatches('k', formats, 'Modern').map((m) => m.match_id)).toEqual(['a'])
  })

  it('keeps every format’s matches without one', () => {
    expect(pairingMatches('k', formats).map((m) => m.match_id)).toEqual(['a', 'b', 'c'])
    expect(pairingMatches('k', formats, null).map((m) => m.match_id)).toEqual(['a', 'b', 'c'])
  })

  it('keeps none for a format no match was played in', () => {
    expect(pairingMatches('k', formats, 'Legacy')).toEqual([])
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
  // Sep 20 at noon on the log's own clock, as the bare timestamps are.
  const now = new Date(2026, 8, 20, 12, 0, 0).getTime()

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

  /** A record as `formatRecord` writes it: a word joiner each side of the dash. */
  const record = (wins: number, losses: number) => `${wins}\u2060–\u2060${losses}`
  const tooFew = `too few for a rate, under 5${NBSP}matches`
  const rough = (wins: number, losses: number) => `${record(wins, losses)} · rough, under 10${NBSP}matches`

  it('at one finished match writes the record, muted, the unfinished left out', () => {
    const [tile, games] = pairingTiles(matchupRows([win('a'), match('b', { result: null, games_won: 1 })])[0], none)
    expect(tile).toEqual({ label: 'Record', value: record(1, 0), detail: tooFew, muted: true })
    expect(games).toEqual({ label: 'Games', value: '2\u2060–\u20601', detail: 'yours first' })
  })

  it('at nine finished, a draw among them, writes a rough rate over wins and losses', () => {
    // Five wins, three losses, one draw: 5–3, eight rated matches, 5 of 8
    // is 0.625, 63, muted. Games:
    // 5×2 + 3×1 + 1 = 14 won, 5×1 + 3×2 + 1 = 12 lost.
    const nine = [win('a'), win('b'), win('c'), win('d'), win('e'), loss('f'), loss('g'), loss('h'), draw('i')]
    const [tile, games] = pairingTiles(matchupRows(nine)[0], none)
    expect(tile).toEqual({ label: 'Record', value: '63%', detail: rough(5, 3), muted: true })
    expect(games).toEqual({ label: 'Games', value: '14\u2060–\u206012', detail: 'yours first' })
  })

  it('at ten wins plus losses, a draw aside, writes the rate over them, as Matchups does', () => {
    // Seven wins, three losses and a draw: 7 of 10 is 70%; the draw is
    // neither. With the draw among the ten (7–2 and a draw) it would be
    // nine rated, 7 of 9 is 0.778, a rough 78%.
    const ten = [win('a'), win('b'), win('c'), win('d'), win('e'), win('f'), win('g'), loss('h'), loss('i'), loss('j'), draw('k')]
    const [tile] = pairingTiles(matchupRows(ten)[0], none)
    expect(tile).toEqual({ label: 'Record', value: '70%', detail: record(7, 3) })
    const nine = [...ten.slice(0, 9), draw('l')]
    expect(pairingTiles(matchupRows(nine)[0], none)[0]).toEqual({
      label: 'Record',
      value: '78%',
      detail: rough(7, 2),
      muted: true,
    })
  })

  /** A finished best-of-three match as `/api/matches` sends one: its games,
   *  game 1's result and games 2 and 3 won and lost. */
  const bo3 = (
    id: string,
    result: 'win' | 'loss',
    game1: 'win' | 'loss',
    postboard: [number, number],
  ): Match => {
    const g1 = game1 === 'win' ? [1, 0] : [0, 1]
    return match(id, {
      result,
      best_of: 3,
      games_won: g1[0] + postboard[0],
      games_lost: g1[1] + postboard[1],
      game1_result: game1,
      postboard_won: postboard[0],
      postboard_lost: postboard[1],
    })
  }
  const tooFewGames = `too few for a rate, under 5${NBSP}games`

  it('draws three tiles with no best-of-three match, best of one or unknown', () => {
    const rows = matchupRows([
      match('a', { result: 'win', best_of: 1, games_won: 1, games_lost: 0 }),
      match('b', { result: 'loss', best_of: null, games_won: 1, games_lost: 2 }),
    ])
    expect(pairingTiles(rows[0], none).map((tile) => tile.label)).toEqual(['Record', 'Games', 'In tournaments'])
  })

  it('draws five with a best-of-three match, game 1 and games 2–3 between Games and In tournaments', () => {
    const rows = matchupRows([
      bo3('a', 'win', 'loss', [2, 0]),
      bo3('b', 'loss', 'win', [0, 2]),
      // A best of one: in Record and Games, in neither split.
      match('c', { result: 'win', best_of: 1, games_won: 1, games_lost: 0 }),
    ])
    const tiles = pairingTiles(rows[0], none)
    expect(tiles.map((tile) => tile.label)).toEqual(['Record', 'Games', 'Game 1', 'Games 2–3', 'In tournaments'])
    // Game 1: won in b, lost in a. Games 2–3: 2–0 in a, 0–2 in b.
    expect(tiles[2]).toEqual({ label: 'Game 1', value: record(1, 1), detail: tooFewGames, muted: true })
    expect(tiles[3]).toEqual({ label: 'Games 2–3', value: record(2, 2), detail: tooFewGames, muted: true })
  })

  it('writes a split’s rate over its record from ten games won or lost', () => {
    const rows = matchupRows([
      // Four won game 1, then split games 2 and 3: 4–0, then 4–4.
      bo3('a', 'win', 'win', [1, 1]),
      bo3('b', 'win', 'win', [1, 1]),
      bo3('c', 'win', 'win', [1, 1]),
      bo3('d', 'win', 'win', [1, 1]),
      // Two lost game 1, then won 2 and 3: 0–2, then 4–0.
      bo3('e', 'win', 'loss', [2, 0]),
      bo3('f', 'win', 'loss', [2, 0]),
      // Two won game 1, then lost 2 and 3: 2–0, then 0–4.
      bo3('g', 'loss', 'win', [0, 2]),
      bo3('h', 'loss', 'win', [0, 2]),
      // Two lost game 1, then split: 0–2, then 2–2.
      bo3('i', 'loss', 'loss', [1, 1]),
      bo3('j', 'loss', 'loss', [1, 1]),
    ])
    // Game 1: 4 + 2 won, 2 + 2 lost, 6 of 10 is 60%. Games 2–3: 4 + 4 + 0 + 2
    // won, 4 + 0 + 4 + 2 lost, 10 of 20 is 50%.
    const tiles = pairingTiles(rows[0], none)
    expect(tiles[2]).toEqual({ label: 'Game 1', value: '60%', detail: record(6, 4) })
    expect(tiles[3]).toEqual({ label: 'Games 2–3', value: '50%', detail: record(10, 10) })
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
