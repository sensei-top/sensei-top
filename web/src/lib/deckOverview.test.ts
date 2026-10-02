import { describe, expect, it } from 'vitest'
import type { Deck, Match, PlayDrawWinrate } from '../api'
import {
  chosenVersion,
  matchesCaption,
  mergeNewestFirst,
  playDrawTiles,
  playDrawTotals,
  rankRows,
  versionDays,
  versionLabel,
  versionRecord,
  versionsInOrder,
} from './deckOverview'

// The zone is America/New_York (vitest.config.ts). Every timestamp below is
// bare, so UTC. Ids are invented. The no-break space and the minus sign are
// written as escapes, as the source writes them.

const NBSP = '\u00a0'
const MINUS = '\u2212'
const NOW = Date.parse('2026-09-29T16:00:00Z')

/** A row of `/api/decks` with only what these functions read. */
function version(deckId: string, rest: Partial<Deck> = {}): Deck {
  return { deck_id: deckId, matches_played: 0, first_played: null, first_seen: null, last_played: null, ...rest } as Deck
}

/** A row of `/api/matches` with only what these functions read. */
function match(matchId: string, rest: Partial<Match> = {}): Match {
  return {
    match_id: matchId,
    result: null,
    started_at: null,
    rank_class: null,
    rank_level: null,
    ...rest,
  } as Match
}

/** `count` finished matches of one result. */
function results(prefix: string, result: string, count: number, rest: Partial<Match> = {}): Match[] {
  return Array.from({ length: count }, (_, index) => match(`${prefix}${index}`, { result, ...rest }))
}

function side(deckId: string, onPlay: boolean, games: number, won: number): PlayDrawWinrate {
  return { deck_id: deckId, on_play: onPlay, games_completed: games, games_won: won } as PlayDrawWinrate
}

describe('versionsInOrder', () => {
  it('lists the deck’s versions by last played, newest first, one never played last', () => {
    const decks = [
      version('a', { last_played: '2026-09-10T12:00:00' }),
      version('b', { last_played: '2026-09-20T12:00:00' }),
      version('c'),
      // Another deck's version, newer than every one of this deck's.
      version('d', { last_played: '2026-09-25T12:00:00' }),
      version('e', { last_played: '2026-09-01T12:00:00' }),
    ]
    expect(versionsInOrder(['a', 'b', 'c', 'e'], decks).map((row) => row.deck_id)).toEqual(['b', 'a', 'e', 'c'])
  })

  it('leaves out a version /api/decks does not list', () => {
    expect(versionsInOrder(['a', 'x'], [version('a')]).map((row) => row.deck_id)).toEqual(['a'])
  })
})

describe('chosenVersion', () => {
  const deckIds = ['a', 'b']

  it('is every version when the address names none', () => {
    expect(chosenVersion(null, deckIds)).toBeNull()
    expect(chosenVersion('', deckIds)).toBeNull()
  })

  it('is the version the address names when it is one of the deck’s', () => {
    expect(chosenVersion('b', deckIds)).toBe('b')
  })

  it('is every version when the address names another deck’s version', () => {
    expect(chosenVersion('z', deckIds)).toBeNull()
  })

  it('is every version on a deck of one version, whatever the address says', () => {
    expect(chosenVersion('a', ['a'])).toBeNull()
  })
})

describe('versionLabel', () => {
  it('names one day once', () => {
    // 09:00 and 22:00 in New York on Sep 14; the second is Sep 15 in UTC.
    const row = version('a', { first_seen: '2026-09-14T13:00:00', last_played: '2026-09-15T02:00:00', matches_played: 1 })
    expect(versionLabel(row, NOW)).toBe(`Sep 14 · 1${NBSP}match`)
  })

  it('names the month once for two days in it', () => {
    const row = version('a', { first_seen: '2026-09-03T15:00:00', last_played: '2026-09-14T20:00:00', matches_played: 37 })
    expect(versionLabel(row, NOW)).toBe(`Sep 3 to 14 · 37${NBSP}matches`)
  })

  it('names both months for days in two', () => {
    const row = version('a', { first_seen: '2026-08-28T15:00:00', last_played: '2026-09-03T15:00:00', matches_played: 12 })
    expect(versionLabel(row, NOW)).toBe(`Aug 28 to Sep 3 · 12${NBSP}matches`)
  })

  it('says undated with no date', () => {
    expect(versionLabel(version('a', { matches_played: 2 }), NOW)).toBe(`Undated · 2${NBSP}matches`)
  })

  it('names the first day alone when the version was never played', () => {
    expect(versionLabel(version('a', { first_seen: '2026-09-03T15:00:00' }), NOW)).toBe(`Sep 3 · 0${NBSP}matches`)
  })
})

describe('versionDays', () => {
  it('writes a year other than now’s once, at the end', () => {
    const row = version('a', { first_seen: '2025-09-03T15:00:00', last_played: '2025-09-14T20:00:00' })
    expect(versionDays(row, NOW)).toBe('Sep 3 to 14, 2025')
  })

  it('starts at the first played match, not the day the deck was saved', () => {
    const row = version('a', {
      first_seen: '2026-09-01T15:00:00',
      first_played: '2026-09-10T15:00:00',
      last_played: '2026-09-14T20:00:00',
    })
    expect(versionDays(row, NOW)).toBe('Sep 10 to 14')
  })

  it('falls back to first_seen when first_played is null', () => {
    const row = version('a', { first_seen: '2026-09-01T15:00:00', last_played: '2026-09-14T20:00:00' })
    expect(versionDays(row, NOW)).toBe('Sep 1 to 14')
  })

  it('is null with no date', () => {
    expect(versionDays(version('a'), NOW)).toBeNull()
  })
})

describe('versionRecord', () => {
  it('gives a rate from ten finished matches', () => {
    // 21 of 37 is 0.5676, 57 in whole percent.
    const matches = [...results('w', 'win', 21), ...results('l', 'loss', 16)]
    expect(versionRecord(matches)).toBe('57% · won 21 of 37')
  })

  it('gives the count from one to nine, a draw finished and a match in progress not', () => {
    const matches = [...results('w', 'win', 3), ...results('l', 'loss', 3), ...results('d', 'draw', 1), match('open')]
    expect(versionRecord(matches)).toBe('won 3 of 7')
  })

  it('says so with no finished match', () => {
    expect(versionRecord([])).toBe('no finished match yet')
    expect(versionRecord([match('open')])).toBe('no finished match yet')
  })
})

describe('playDrawTotals', () => {
  it('adds every version’s rows by side', () => {
    const rows = [side('a', true, 50, 30), side('a', false, 40, 20), side('b', true, 31, 17), side('b', false, 37, 20)]
    expect(playDrawTotals(rows)).toEqual({ play: { games: 81, won: 47 }, draw: { games: 77, won: 40 } })
  })
})

describe('playDrawTiles', () => {
  it('gives both rates and the play ahead when both sides have ten games', () => {
    // 47 of 81 is 0.580, 58; 40 of 77 is 0.519, 52; 58 - 52 = 6.
    const tiles = playDrawTiles({ play: { games: 81, won: 47 }, draw: { games: 77, won: 40 } })
    expect(tiles).toEqual([
      { label: 'On the play', value: '58%', detail: `won 47 of 81${NBSP}games` },
      { label: 'On the draw', value: '52%', detail: `won 40 of 77${NBSP}games` },
      { label: 'Play against draw', value: `+6${NBSP}points`, detail: 'better on the play' },
    ])
  })

  it('gives the draw ahead with a minus sign', () => {
    // 5 of 10 is 50, 6 of 10 is 60.
    const [, , difference] = playDrawTiles({ play: { games: 10, won: 5 }, draw: { games: 10, won: 6 } })
    expect(difference).toEqual({ label: 'Play against draw', value: `${MINUS}10${NBSP}points`, detail: 'better on the draw' })
  })

  it('subtracts the whole percentages, so two that round alike are no difference', () => {
    // 11 of 20 is 55; 6 of 11 is 54.5, 55 in whole percent.
    const [, , difference] = playDrawTiles({ play: { games: 20, won: 11 }, draw: { games: 11, won: 6 } })
    expect(difference).toEqual({ label: 'Play against draw', value: `0${NBSP}points`, detail: 'no difference' })
  })

  it('says one point in the singular', () => {
    // 6 of 10 is 60; 10 of 17 is 58.8, 59.
    const [, , difference] = playDrawTiles({ play: { games: 10, won: 6 }, draw: { games: 17, won: 10 } })
    expect(difference.value).toBe(`+1${NBSP}point`)
  })

  it('gives a count for a side under ten games, and compares nothing', () => {
    // 7 of 12 is 58.3, 58.
    const tiles = playDrawTiles({ play: { games: 9, won: 6 }, draw: { games: 12, won: 7 } })
    expect(tiles).toEqual([
      { label: 'On the play', value: '6 of 9', detail: 'games won' },
      { label: 'On the draw', value: '58%', detail: `won 7 of 12${NBSP}games` },
      { label: 'Play against draw', value: '—', detail: 'too few games to compare' },
    ])
  })

  it('says so for a side with no game', () => {
    const tiles = playDrawTiles({ play: { games: 4, won: 3 }, draw: { games: 0, won: 0 } })
    expect(tiles).toEqual([
      { label: 'On the play', value: '3 of 4', detail: 'games won' },
      { label: 'On the draw', value: '—', detail: 'no game on the draw yet' },
      { label: 'Play against draw', value: '—', detail: 'too few games to compare' },
    ])
  })

  it('says so for both sides with no game at all', () => {
    const tiles = playDrawTiles(playDrawTotals([]))
    expect(tiles).toEqual([
      { label: 'On the play', value: '—', detail: 'no game on the play yet' },
      { label: 'On the draw', value: '—', detail: 'no game on the draw yet' },
      { label: 'Play against draw', value: '—', detail: 'too few games to compare' },
    ])
  })
})

describe('rankRows', () => {
  it('orders the ladder best first, levels 1 to 4, other classes by name, no rank last', () => {
    const matches = [
      match('bronze', { result: 'loss', rank_class: 'Bronze', rank_level: 1 }),
      match('gold-w', { result: 'win', rank_class: 'Gold', rank_level: 2 }),
      match('gold-l', { result: 'loss', rank_class: 'Gold', rank_level: 2 }),
      match('spark', { result: 'win', rank_class: 'Spark', rank_level: 1 }),
      match('plat-4', { result: 'win', rank_class: 'Platinum', rank_level: 4 }),
      match('none', { result: 'win' }),
      match('plat-1', { result: 'loss', rank_class: 'Platinum', rank_level: 1 }),
      match('diamond', { result: 'draw', rank_class: 'Diamond', rank_level: 3 }),
      match('diamond-bare', { result: 'win', rank_class: 'Diamond' }),
      match('apprentice', { result: 'loss', rank_class: 'Apprentice', rank_level: 2 }),
      match('mythic', { result: 'win', rank_class: 'Mythic' }),
      // Not finished: no Silver row at all.
      match('silver', { rank_class: 'Silver', rank_level: 1 }),
    ]
    expect(rankRows(matches)).toEqual([
      { rank: 'Mythic', matches: 1, won: 1, rate: '—' },
      { rank: 'Diamond 3', matches: 1, won: 0, rate: '—' },
      { rank: 'Diamond', matches: 1, won: 1, rate: '—' },
      { rank: 'Platinum 1', matches: 1, won: 0, rate: '—' },
      { rank: 'Platinum 4', matches: 1, won: 1, rate: '—' },
      { rank: 'Gold 2', matches: 2, won: 1, rate: '—' },
      { rank: 'Bronze 1', matches: 1, won: 0, rate: '—' },
      { rank: 'Apprentice 2', matches: 1, won: 0, rate: '—' },
      { rank: 'Spark 1', matches: 1, won: 1, rate: '—' },
      { rank: 'No rank recorded', matches: 1, won: 1, rate: '—' },
    ])
  })

  it('gives a rate from ten matches, an em dash under', () => {
    // 7 of 12 is 58.3, 58; the draw is finished and counted, not won.
    const matches = [
      ...results('p-w', 'win', 7, { rank_class: 'Platinum', rank_level: 2 }),
      ...results('p-l', 'loss', 4, { rank_class: 'Platinum', rank_level: 2 }),
      ...results('p-d', 'draw', 1, { rank_class: 'Platinum', rank_level: 2 }),
      ...results('g-w', 'win', 9, { rank_class: 'Gold', rank_level: 1 }),
    ]
    expect(rankRows(matches)).toEqual([
      { rank: 'Platinum 2', matches: 12, won: 7, rate: '58%' },
      { rank: 'Gold 1', matches: 9, won: 9, rate: '—' },
    ])
  })
})

describe('mergeNewestFirst', () => {
  it('merges two versions newest first, a match with no start last', () => {
    const first = [match('m1', { started_at: '2026-09-10T12:00:00' }), match('m3', { started_at: '2026-09-01T12:00:00' })]
    const second = [
      match('m2', { started_at: '2026-09-05T12:00:00' }),
      match('m4'),
      match('m5', { started_at: '2026-09-12T12:00:00' }),
    ]
    expect(mergeNewestFirst([first, second]).map((row) => row.match_id)).toEqual(['m5', 'm1', 'm2', 'm3', 'm4'])
  })
})

describe('matchesCaption', () => {
  it('counts every match when all are shown', () => {
    expect(matchesCaption(12, 12)).toBe(`12${NBSP}matches, newest first`)
  })

  it('says one match alone', () => {
    expect(matchesCaption(1, 1)).toBe(`1${NBSP}match`)
  })

  it('says how many of how many when some are shown', () => {
    expect(matchesCaption(121, 10)).toBe(`Showing 10 of 121${NBSP}matches, newest first`)
  })
})
