import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import type { Deck, Match, PlayDrawWinrate } from '../api'
import {
  chosenVersion,
  deckKeyNumbers,
  matchesCaption,
  mergeNewestFirst,
  playDrawTile,
  playDrawTotals,
  rankRows,
  versionDays,
  versionLabel,
  versionRecord,
  versionsInOrder,
} from './deckOverview'
import { NBSP } from './matchups'

const t = translator('en')

// The zone is America/New_York (vitest.config.ts). Every timestamp below is
// bare, so the log's own local clock. Ids are invented. The minus sign is
// written as an escape, as the source writes it; the no-break space is the
// source's own `NBSP`.

const MINUS = '\u2212'

/** A record as D6 writes it, wins–losses with an en dash, a word joiner
 *  each side so it never wraps at the dash. */
const rec = (wins: number, losses: number) => `${wins}\u2060–\u2060${losses}`
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

function side(deckId: string, onPlay: boolean, games: number, won: number, drawn = 0): PlayDrawWinrate {
  return {
    deck_id: deckId,
    on_play: onPlay,
    games_completed: games + drawn,
    games_won: won,
    games_lost: games - won,
  } as PlayDrawWinrate
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
    // 09:00 and 22:00 on the log's own clock, both Sep 14; in UTC the second
    // is Sep 15, so a UTC day would name two.
    const row = version('a', { first_seen: '2026-09-14T09:00:00', last_played: '2026-09-14T22:00:00', matches_played: 1 })
    expect(versionLabel(row, NOW, t)).toBe(`Sep 14 · 1${NBSP}match`)
  })

  it('names the month once for two days in it', () => {
    const row = version('a', { first_seen: '2026-09-03T15:00:00', last_played: '2026-09-14T20:00:00', matches_played: 37 })
    expect(versionLabel(row, NOW, t)).toBe(`Sep 3 to 14 · 37${NBSP}matches`)
  })

  it('names both months for days in two', () => {
    const row = version('a', { first_seen: '2026-08-28T15:00:00', last_played: '2026-09-03T15:00:00', matches_played: 12 })
    expect(versionLabel(row, NOW, t)).toBe(`Aug 28 to Sep 3 · 12${NBSP}matches`)
  })

  it('says undated with no date', () => {
    expect(versionLabel(version('a', { matches_played: 2 }), NOW, t)).toBe(`Undated · 2${NBSP}matches`)
  })

  it('names the first day alone when the version was never played', () => {
    expect(versionLabel(version('a', { first_seen: '2026-09-03T15:00:00' }), NOW, t)).toBe(`Sep 3 · 0${NBSP}matches`)
  })
})

describe('versionDays', () => {
  it('writes a year other than now’s once, at the end', () => {
    const row = version('a', { first_seen: '2025-09-03T15:00:00', last_played: '2025-09-14T20:00:00' })
    expect(versionDays(row, NOW, t)).toBe('Sep 3 to 14, 2025')
  })

  it('starts at the first played match, not the day the deck was saved', () => {
    const row = version('a', {
      first_seen: '2026-09-01T15:00:00',
      first_played: '2026-09-10T15:00:00',
      last_played: '2026-09-14T20:00:00',
    })
    expect(versionDays(row, NOW, t)).toBe('Sep 10 to 14')
  })

  it('falls back to first_seen when first_played is null', () => {
    const row = version('a', { first_seen: '2026-09-01T15:00:00', last_played: '2026-09-14T20:00:00' })
    expect(versionDays(row, NOW, t)).toBe('Sep 1 to 14')
  })

  it('is null with no date', () => {
    expect(versionDays(version('a'), NOW, t)).toBeNull()
  })
})

describe('versionRecord', () => {
  it('gives the rate and the record from ten finished matches', () => {
    // 21 of 37 is 0.5676, 57 in whole percent.
    const matches = [...results('w', 'win', 21), ...results('l', 'loss', 16)]
    expect(versionRecord(matches, t)).toBe(`57% win rate · ${rec(21, 16)}`)
  })

  it('gives the record alone from one to nine, a draw and a match in progress counting toward neither', () => {
    const matches = [...results('w', 'win', 3), ...results('l', 'loss', 3), ...results('d', 'draw', 1), match('open')]
    expect(versionRecord(matches, t)).toBe(rec(3, 3))
  })

  it('says so with no finished match', () => {
    expect(versionRecord([], t)).toBe('no finished match yet')
    expect(versionRecord([match('open')], t)).toBe('no finished match yet')
  })
})

describe('playDrawTotals', () => {
  it('adds every version’s rows by side', () => {
    const rows = [side('a', true, 50, 30), side('a', false, 40, 20), side('b', true, 31, 17), side('b', false, 37, 20)]
    expect(playDrawTotals(rows)).toEqual({ play: { games: 81, won: 47 }, draw: { games: 77, won: 40 } })
  })

  it('counts a drawn game toward neither the games nor the wins', () => {
    const rows = [side('a', true, 9, 5, 1), side('a', false, 10, 4)]
    expect(playDrawTotals(rows)).toEqual({ play: { games: 9, won: 5 }, draw: { games: 10, won: 4 } })
  })
})

describe('deckKeyNumbers', () => {
  it('gives rates, records and the gap on thick sides', () => {
    // Matches: 21 won, 16 lost, the draw neither; 21 of 37 is 0.5676, 57.
    // Games: 42 + 16 + 1 won and 21 + 32 + 1 lost, 59 of 113 is 0.522, 52.
    // Play 47 of 81 is 0.580, 58; draw 40 of 77 is 0.519, 52; 58 - 52 = 6.
    const matches = [
      ...results('w', 'win', 21, { games_won: 2, games_lost: 1 }),
      ...results('l', 'loss', 16, { games_won: 1, games_lost: 2 }),
      ...results('d', 'draw', 1, { games_won: 1, games_lost: 1 }),
    ]
    const totals = { play: { games: 81, won: 47 }, draw: { games: 77, won: 40 } }
    expect(deckKeyNumbers(matches, totals, t)).toEqual([
      { label: 'Matches', value: '57%', detail: rec(21, 16), thin: false },
      { label: 'Games', value: '52%', detail: rec(59, 54), thin: false },
      { label: 'Play vs draw', value: `+6${NBSP}points`, detail: '58% on the play · 52% on the draw', thin: false },
    ])
  })

  it('gives records, muted, on a thin side', () => {
    // Six won, three lost, a draw and a match in progress, which counts
    // toward neither, though its one game won counts. Nine matches is a
    // rough rate, 6 of 9 is 0.667, 67; one game is too few for one. Play
    // has nine games, too few for the play/draw line's rate: its record, 6
    // won and 3 not; draw 7 of 12 is 58.
    const matches = [
      ...results('w', 'win', 6),
      ...results('l', 'loss', 3),
      ...results('d', 'draw', 1),
      match('open', { games_won: 1, games_lost: 0 }),
    ]
    const totals = { play: { games: 9, won: 6 }, draw: { games: 12, won: 7 } }
    expect(deckKeyNumbers(matches, totals, t)).toEqual([
      { label: 'Matches', value: '67%', detail: `${rec(6, 3)} · rough, under 10${NBSP}matches`, thin: true },
      { label: 'Games', value: rec(1, 0), detail: `too few for a rate, under 5${NBSP}games`, thin: true },
      { label: 'Play vs draw', value: 'too few', detail: `${rec(6, 3)} on the play · 58% on the draw`, thin: true },
    ])
  })

  it('says so with no games at all', () => {
    expect(deckKeyNumbers([], playDrawTotals([]), t)).toEqual([
      { label: 'Matches', value: '—', detail: 'no finished match yet', thin: false },
      { label: 'Games', value: '—', detail: 'no finished game yet', thin: false },
      { label: 'Play vs draw', value: '—', detail: 'no games on the play · no games on the draw', thin: false },
    ])
  })

  it('names a side with no game beside one with games', () => {
    const [, , playDraw] = deckKeyNumbers([], { play: { games: 4, won: 3 }, draw: { games: 0, won: 0 } }, t)
    expect(playDraw).toEqual({
      label: 'Play vs draw',
      value: 'too few',
      detail: `${rec(3, 1)} on the play · no games on the draw`,
      thin: true,
    })
  })

  it('gives the draw ahead with a minus sign', () => {
    // 5 of 10 is 50, 6 of 10 is 60.
    const [, , playDraw] = deckKeyNumbers([], { play: { games: 10, won: 5 }, draw: { games: 10, won: 6 } }, t)
    expect(playDraw.value).toBe(`${MINUS}10${NBSP}points`)
    expect(playDraw.detail).toBe('50% on the play · 60% on the draw')
  })

  it('subtracts the whole percentages, so two that round alike are no gap', () => {
    // 11 of 20 is 55; 6 of 11 is 54.5, 55 in whole percent.
    const [, , playDraw] = deckKeyNumbers([], { play: { games: 20, won: 11 }, draw: { games: 11, won: 6 } }, t)
    expect(playDraw.value).toBe(`0${NBSP}points`)
  })

  it('says one point in the singular', () => {
    // 6 of 10 is 60; 10 of 17 is 58.8, 59.
    const [, , playDraw] = deckKeyNumbers([], { play: { games: 10, won: 6 }, draw: { games: 17, won: 10 } }, t)
    expect(playDraw.value).toBe(`+1${NBSP}point`)
  })
})

describe('playDrawTile', () => {
  it('gives the gap with ten games on each side', () => {
    // 7 of 10 is 70, 4 of 10 is 40: 70 - 40 = 30.
    expect(playDrawTile({ play: { games: 10, won: 7 }, draw: { games: 10, won: 4 } }, t)).toEqual({
      label: 'Play vs draw',
      value: `+30${NBSP}points`,
      detail: '70% on the play · 40% on the draw',
      thin: false,
    })
  })

  it('says too few, muted, with under ten games on one side', () => {
    // 9 of 12 is 75; the draw's 3 games, 1 won and 2 not, are its record.
    expect(playDrawTile({ play: { games: 12, won: 9 }, draw: { games: 3, won: 1 } }, t)).toEqual({
      label: 'Play vs draw',
      value: 'too few',
      detail: `75% on the play · ${rec(1, 2)} on the draw`,
      thin: true,
    })
  })

  it('gives an em dash with no game on either side', () => {
    expect(playDrawTile(playDrawTotals([]), t)).toEqual({
      label: 'Play vs draw',
      value: '—',
      detail: 'no games on the play · no games on the draw',
      thin: false,
    })
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
    // One to nine wins and losses: "too few"; a row of draws alone has none
    // and reads an em dash.
    const few = { rate: 'too few', thin: true }
    expect(rankRows(matches, t)).toEqual([
      { rank: 'Mythic', matches: 1, record: rec(1, 0), ...few },
      { rank: 'Diamond 3', matches: 1, record: rec(0, 0), rate: '—', thin: false },
      { rank: 'Diamond', matches: 1, record: rec(1, 0), ...few },
      { rank: 'Platinum 1', matches: 1, record: rec(0, 1), ...few },
      { rank: 'Platinum 4', matches: 1, record: rec(1, 0), ...few },
      { rank: 'Gold 2', matches: 2, record: rec(1, 1), ...few },
      { rank: 'Bronze 1', matches: 1, record: rec(0, 1), ...few },
      { rank: 'Apprentice 2', matches: 1, record: rec(0, 1), ...few },
      { rank: 'Spark 1', matches: 1, record: rec(1, 0), ...few },
      { rank: 'No rank recorded', matches: 1, record: rec(1, 0), ...few },
    ])
  })

  it('gives a rate from ten wins and losses, muted from five, "too few" under, a draw counting toward neither', () => {
    // 7 won and 4 lost is 11, 7 of 11 is 0.636, 64; the draw is a finished
    // match, in Matches, but in neither the record nor the rate. Nine won
    // is a rough 100%, muted; two won is too few.
    const matches = [
      ...results('p-w', 'win', 7, { rank_class: 'Platinum', rank_level: 2 }),
      ...results('p-l', 'loss', 4, { rank_class: 'Platinum', rank_level: 2 }),
      ...results('p-d', 'draw', 1, { rank_class: 'Platinum', rank_level: 2 }),
      ...results('g-w', 'win', 9, { rank_class: 'Gold', rank_level: 1 }),
      ...results('s-w', 'win', 2, { rank_class: 'Silver', rank_level: 1 }),
    ]
    expect(rankRows(matches, t)).toEqual([
      { rank: 'Platinum 2', matches: 12, record: rec(7, 4), rate: '64%', thin: false },
      { rank: 'Gold 1', matches: 9, record: rec(9, 0), rate: '100%', thin: true },
      { rank: 'Silver 1', matches: 2, record: rec(2, 0), rate: 'too few', thin: true },
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
    expect(matchesCaption(12, 12, t)).toBe(`12${NBSP}matches, newest first`)
  })

  it('says one match alone', () => {
    expect(matchesCaption(1, 1, t)).toBe(`1${NBSP}match`)
  })

  it('says how many of how many when some are shown', () => {
    expect(matchesCaption(121, 10, t)).toBe(`Showing 10 of 121${NBSP}matches, newest first`)
  })
})
