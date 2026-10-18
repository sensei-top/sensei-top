import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import type { DeckIdentityOut, LeakOut, Match, MetaPresence } from '../api'
import type { DetailedLogs } from '../bridge'
import {
  detailedLogsNag,
  fieldWindowStart,
  firstPattern,
  firstRunSteps,
  homeDecks,
  homeField,
  isFirstRun,
  lastFinished,
  lastSession,
  lastThirtyDays,
  liveState,
  mtgoOnly,
  opponentNamed,
  ownScore,
  recentMatches,
  sessionHeadline,
  threeThings,
  weekStart,
  weeklyWinrate,
  winnerScore,
} from './home'

// The zone is America/New_York (vitest.config.ts). Every timestamp below is
// bare, so the log's own local clock: 04:00 UTC is midnight in New York
// until November 1, 2026, and 05:00 UTC after it. September 28, 2026 is a Monday.

const HOUR = 3_600_000
const DAY = 24 * HOUR

/** A row of `/api/matches` with only what Home reads. */
function match(id: string, startedAt: string | null, result: string | null, rest: Partial<Match> = {}): Match {
  return { match_id: id, started_at: startedAt, ended_at: null, result, ...rest } as Match
}

const ids = (matches: Match[]) => matches.map((row) => row.match_id)

describe('lastSession', () => {
  const izzet = { deck_id: 'd1', deck_name: 'Izzet' }
  const boros = { deck_id: 'd2', deck_name: 'Boros' }
  const evening = [
    match('m1', '2026-09-27T20:00:00', 'win', { ended_at: '2026-09-27T20:30:00', ...izzet }),
    match('m2', '2026-09-27T21:00:00', 'loss', { ended_at: '2026-09-27T21:40:00', ...izzet }),
    // 2h50 after m2 ended.
    match('m3', '2026-09-28T00:30:00', 'win', { ended_at: '2026-09-28T01:00:00', ...boros }),
  ]

  it('is null with no finished match', () => {
    expect(lastSession([])).toBeNull()
    expect(lastSession([match('m1', '2026-09-27T20:00:00', null)])).toBeNull()
  })

  it('ends at a gap of more than three hours, measured from the older match’s end', () => {
    const afternoon = match('m0', '2026-09-27T16:00:00', 'loss', { ended_at: '2026-09-27T16:59:59' })
    const session = lastSession([afternoon, ...evening])
    expect(ids(session!.matches)).toEqual(['m3', 'm2', 'm1'])
    expect(session!.start).toBe(new Date(2026, 8, 27, 20, 0, 0).getTime())
    expect(session!.tally).toEqual({ played: 3, wins: 2, losses: 1, draws: 0 })
  })

  it('keeps a match that ended exactly three hours before the next began', () => {
    const afternoon = match('m0', '2026-09-27T16:00:00', 'loss', { ended_at: '2026-09-27T17:00:00' })
    expect(ids(lastSession([afternoon, ...evening])!.matches)).toEqual(['m3', 'm2', 'm1', 'm0'])
  })

  it('measures from the start of a match with no end', () => {
    const rows = [
      match('a', '2026-09-27T16:00:00', 'win'),
      match('b', '2026-09-27T19:00:00', 'win'),
      match('c', '2026-09-27T22:00:01', 'win'),
    ]
    expect(ids(lastSession(rows)!.matches)).toEqual(['c'])
    expect(ids(lastSession(rows.slice(0, 2))!.matches)).toEqual(['b', 'a'])
  })

  it('leaves out a match still in progress and one with no start', () => {
    const session = lastSession([
      ...evening,
      match('live', '2026-09-28T01:10:00', null, izzet),
      match('lost', null, 'win', izzet),
    ])
    expect(ids(session!.matches)).toEqual(['m3', 'm2', 'm1'])
  })

  it('lists its decks, the most played first', () => {
    expect(lastSession(evening)!.decks).toEqual([
      { name: 'Izzet', count: 2 },
      { name: 'Boros', count: 1 },
    ])
  })

  it('puts the deck played last first when two were played as often', () => {
    expect(lastSession(evening.slice(1))!.decks).toEqual([
      { name: 'Boros', count: 1 },
      { name: 'Izzet', count: 1 },
    ])
  })

  it('counts no deck for a match without one, and keeps a deck with no name', () => {
    const session = lastSession([
      match('a', '2026-09-27T20:00:00', 'win'),
      match('b', '2026-09-27T20:30:00', 'draw', { deck_id: 'd3', deck_name: null }),
    ])
    expect(session!.decks).toEqual([{ name: null, count: 1 }])
    expect(session!.tally).toEqual({ played: 2, wins: 1, losses: 0, draws: 1 })
  })
})

describe('sessionHeadline', () => {
  const headline = (wins: number, losses: number, draws = 0) =>
    sessionHeadline({ played: wins + losses + draws, wins, losses, draws }, translator('en'))

  it('writes the record in words', () => {
    expect(headline(15, 10)).toBe('15 wins, 10 losses')
    expect(headline(1, 1)).toBe('1 win, 1 loss')
    expect(headline(0, 3)).toBe('No wins, 3 losses')
    expect(headline(15, 0)).toBe('15 wins, no losses')
  })

  it('names the draws only when there was one', () => {
    expect(headline(2, 1, 1)).toBe('2 wins, 1 loss, 1 draw')
    expect(headline(2, 1, 2)).toBe('2 wins, 1 loss, 2 draws')
  })
})

describe('lastThirtyDays', () => {
  const now = new Date(2026, 8, 28, 12, 0, 0).getTime()
  const rows = [
    match('today', '2026-09-28T10:00:00', 'win'),
    match('edge', '2026-08-29T12:00:00', 'loss'),
    match('before', '2026-08-29T11:59:59', 'win'),
    match('live', '2026-09-28T11:30:00', null),
  ]

  it('counts the finished matches that started in the window, its first instant included', () => {
    expect(lastThirtyDays(rows, lastSession(rows), now)).toEqual({ played: 2, won: 1, losses: 1, outsideSession: true })
  })

  it('says when the session is the whole window', () => {
    const only = rows.slice(0, 1)
    expect(lastThirtyDays(only, lastSession(only), now)).toEqual({ played: 1, won: 1, losses: 0, outsideSession: false })
  })
})

describe('first run', () => {
  it('is no match', () => {
    expect(isFirstRun([])).toBe(true)
    expect(isFirstRun([match('a', null, null)])).toBe(false)
  })

  it('makes the first step not done the next one', () => {
    expect(firstRunSteps(undefined)).toEqual(['next', 'later', 'later'])
    expect(firstRunSteps({ watching: false, events: 0 })).toEqual(['next', 'later', 'later'])
    expect(firstRunSteps({ watching: true, events: 0 })).toEqual(['done', 'next', 'later'])
    expect(firstRunSteps({ watching: true, events: 12 })).toEqual(['done', 'done', 'next'])
    expect(firstRunSteps({ watching: false, events: 12 })).toEqual(['next', 'done', 'later'])
    // The Arena path ignores MTGO's watching.
    expect(firstRunSteps({ watching: true, events: 0, mtgo_watching: true })).toEqual(['done', 'next', 'later'])
  })

  it('reads the second step as MTGO watching for an MTGO-only player', () => {
    const live = (watching: boolean, mtgo: boolean, events = 0) => ({ watching, events, mtgo_watching: mtgo })
    expect(firstRunSteps(live(true, false, 40), true)).toEqual(['done', 'next', 'later'])
    expect(firstRunSteps(live(true, true), true)).toEqual(['done', 'done', 'next'])
    expect(firstRunSteps(live(false, false, 3), true)).toEqual(['next', 'later', 'later'])
    expect(firstRunSteps(undefined, true)).toEqual(['next', 'later', 'later'])
  })

  it('is MTGO-only only when plays is exactly mtgo', () => {
    expect(mtgoOnly(['mtgo'])).toBe(true)
    expect(mtgoOnly(['arena'])).toBe(false)
    expect(mtgoOnly(['arena', 'mtgo'])).toBe(false)
    expect(mtgoOnly(undefined)).toBe(false)
  })
})

describe('the matches Home names', () => {
  const rows = [
    match('old', '2026-09-20T10:00:00', 'win'),
    match('live', '2026-09-28T11:00:00', null),
    match('new', '2026-09-28T10:00:00', 'loss'),
    match('lost', null, 'win'),
  ]

  it('takes the newest finished match as the last one', () => {
    expect(lastFinished(rows)!.match_id).toBe('new')
    expect(lastFinished([rows[1]])).toBeNull()
  })

  it('lists the newest matches, finished or not', () => {
    expect(ids(recentMatches(rows))).toEqual(['live', 'new', 'old'])
    expect(ids(recentMatches(rows, 2))).toEqual(['live', 'new'])
  })

  it('calls an opponent named unless only colours or nothing were seen', () => {
    expect(opponentNamed({ opponent_source: 'corpus' } as Match)).toBe(true)
    expect(opponentNamed({ opponent_source: 'colors' } as Match)).toBe(false)
    expect(opponentNamed({ opponent_source: 'unknown' } as Match)).toBe(false)
    expect(opponentNamed({ opponent_source: null } as Match)).toBe(false)
  })
})

describe('scores', () => {
  it('puts the viewer’s games first on a row', () => {
    expect(ownScore({ games_won: 1, games_lost: 2 })).toBe('1–2')
  })

  it('puts the winner’s games first in a sentence', () => {
    expect(winnerScore({ games_won: 1, games_lost: 2, result: 'loss' })).toBe('2–1')
    expect(winnerScore({ games_won: 2, games_lost: 0, result: 'win' })).toBe('2–0')
  })

  it('has none without both counts, or with no game played', () => {
    expect(ownScore({ games_won: null, games_lost: 2 })).toBeNull()
    expect(ownScore({ games_won: 0, games_lost: 0 })).toBeNull()
    expect(winnerScore({ games_won: 0, games_lost: 0, result: 'loss' })).toBeNull()
  })
})

describe('threeThings', () => {
  it('takes the match, the pattern and the field, in that order', () => {
    expect(threeThings({ match: true, pattern: true, field: true })).toEqual(['match', 'pattern', 'field'])
    expect(threeThings({ match: true, pattern: false, field: true })).toEqual(['match', 'field'])
  })

  it('shows fewer than three rather than a filler', () => {
    expect(threeThings({ match: true, pattern: false, field: false })).toEqual(['match'])
    expect(threeThings({ match: false, pattern: false, field: false })).toEqual([])
  })
})

describe('firstPattern', () => {
  const leak = (key: string, nWith: number, rateWith: number, nWithout: number, rateWithout: number) =>
    ({ key, n_with: nWith, win_rate_with: rateWith, n_without: nWithout, win_rate_without: rateWithout }) as unknown as LeakOut

  it('is the first that costs the viewer, with its wins counted back from the rates', () => {
    const helps = leak('helps', 10, 0.6, 20, 0.5)
    const costs = leak('costs', 12, 0.25, 30, 0.6)
    const costsToo = leak('costs-too', 8, 0.125, 30, 0.6)
    expect(firstPattern([helps, costs, costsToo])).toEqual({ leak: costs, wonWith: 3, wonWithout: 18 })
  })

  it('is null when none does', () => {
    expect(firstPattern([leak('helps', 10, 0.6, 20, 0.5), leak('even', 10, 0.5, 20, 0.5)])).toBeNull()
    expect(firstPattern([])).toBeNull()
  })
})

describe('weekStart', () => {
  const monday21 = Date.UTC(2026, 8, 21, 4, 0, 0)
  const monday28 = Date.UTC(2026, 8, 28, 4, 0, 0)

  it('is the Monday at midnight, the viewer’s zone', () => {
    // 03:30 UTC on Monday the 28th is still Sunday night in New York.
    expect(weekStart(Date.UTC(2026, 8, 28, 3, 30, 0))).toBe(monday21)
    expect(weekStart(Date.UTC(2026, 8, 28, 4, 0, 0))).toBe(monday28)
    expect(weekStart(Date.UTC(2026, 9, 1, 18, 0, 0))).toBe(monday28)
  })
})

describe('weeklyWinrate', () => {
  const week = (start: number, played: number, won: number, losses: number) => ({
    start,
    played,
    won,
    losses,
    rate: won + losses > 0 ? won / (won + losses) : null,
  })
  const monday14 = Date.UTC(2026, 8, 14, 4, 0, 0)
  const monday21 = Date.UTC(2026, 8, 21, 4, 0, 0)
  const monday28 = Date.UTC(2026, 8, 28, 4, 0, 0)
  const rows = [
    match('a', '2026-09-15T18:00:00', 'win'),
    match('b', '2026-09-16T18:00:00', 'loss'),
    match('c', '2026-09-29T18:00:00', 'win'),
  ]

  it('has no week with no finished match', () => {
    expect(weeklyWinrate([], false)).toEqual({ weeks: [], truncated: false })
    expect(weeklyWinrate([match('live', '2026-09-29T18:00:00', null)], false)).toEqual({ weeks: [], truncated: false })
  })

  it('runs from the first week with a match to the newest, a week with none between them', () => {
    expect(weeklyWinrate(rows, false)).toEqual({
      weeks: [week(monday14, 2, 1, 1), week(monday21, 0, 0, 0), week(monday28, 1, 1, 0)],
      truncated: false,
    })
  })

  it('counts a draw as played, and as neither a win nor a loss', () => {
    const withDraw = [...rows, match('d', '2026-09-30T18:00:00', 'draw')]
    expect(weeklyWinrate(withDraw, false).weeks.at(-1)).toEqual(week(monday28, 2, 1, 0))
  })

  it('has no rate for a week of draws alone', () => {
    const drawn = [match('d', '2026-09-29T18:00:00', 'draw')]
    expect(weeklyWinrate(drawn, false).weeks).toEqual([week(monday28, 1, 0, 0)])
  })

  it('holds twelve weeks at most', () => {
    // The twelfth week back from September 28 starts on July 13; July 8 is
    // in the week before it.
    const long = [
      match('thirteenth', '2026-07-08T18:00:00', 'win'),
      match('twelfth', '2026-07-14T18:00:00', 'loss'),
      ...rows,
    ]
    const { weeks, truncated } = weeklyWinrate(long, false)
    expect(weeks).toHaveLength(12)
    expect(weeks[0]).toEqual(week(Date.UTC(2026, 6, 13, 4, 0, 0), 1, 0, 1))
    expect(truncated).toBe(false)
  })

  it('leaves out the oldest week of a full list, which holds only part of its matches', () => {
    const full = [...rows, match('d', '2026-09-22T18:00:00', 'loss')]
    expect(weeklyWinrate(full, true)).toEqual({
      weeks: [week(monday21, 1, 0, 1), week(monday28, 1, 1, 0)],
      truncated: true,
    })
  })

  it('cuts nothing from a full list whose oldest week is before the twelve', () => {
    const full = [match('thirteenth', '2026-07-08T18:00:00', 'win'), ...rows]
    expect(weeklyWinrate(full, true)).toEqual({
      weeks: [week(monday14, 2, 1, 1), week(monday21, 0, 0, 0), week(monday28, 1, 1, 0)],
      truncated: false,
    })
  })

  it('keeps each week at its own midnight across the change of the clocks', () => {
    // The clocks go back on Sunday, November 1: the Monday before it starts
    // at 04:00 UTC, the Monday after it at 05:00.
    const autumn = [match('before', '2026-10-27T18:00:00', 'win'), match('after', '2026-11-03T18:00:00', 'loss')]
    expect(weeklyWinrate(autumn, false).weeks).toEqual([
      week(Date.UTC(2026, 9, 26, 4, 0, 0), 1, 1, 0),
      week(Date.UTC(2026, 10, 2, 5, 0, 0), 1, 0, 1),
    ])
  })
})

describe('homeDecks', () => {
  const now = new Date(2026, 8, 28, 12, 0, 0).getTime()
  const identity = (key: string, deckIds: string[], rest: Partial<DeckIdentityOut>) =>
    ({ key, name: key, deck_ids: deckIds, matches: 0, match_wins: 0, match_losses: 0, last_played: null, ...rest }) as DeckIdentityOut

  const identities = [
    identity('Izzet', ['a1', 'a2'], {
      matches: 10,
      match_wins: 6,
      match_losses: 3,
      last_played: '2026-09-27T20:00:00',
    }),
    identity('Boros', ['b1'], { matches: 4, match_wins: 1, match_losses: 3, last_played: '2026-09-26T20:00:00' }),
    identity('Never played', ['c1'], {}),
    identity('Long ago', ['e1'], { matches: 2, match_wins: 2, last_played: '2026-06-01T20:00:00' }),
  ]
  const matches = [
    match('a-live', '2026-09-28T11:00:00', null, { deck_id: 'a2' }),
    match('a-old', '2026-08-01T20:00:00', 'win', { deck_id: 'a1' }),
    match('b-1', '2026-09-25T20:00:00', 'loss', { deck_id: 'b1' }),
    match('b-2', '2026-09-26T20:00:00', 'win', { deck_id: 'b1' }),
    match('e-1', '2026-06-01T20:00:00', 'win', { deck_id: 'e1' }),
  ]

  const decks = homeDecks(identities, matches, now)

  it('orders by the matches of the last 30 days, then by last played, and leaves out a deck never played', () => {
    // Boros has two in the window; Izzet one, the match in progress; the
    // deck of June none.
    expect(decks.map((deck) => deck.key)).toEqual(['Boros', 'Izzet', 'Long ago'])
  })

  it('counts a deck’s finished matches as its wins and losses, draws aside', () => {
    expect(decks[1]).toMatchObject({ finished: 9, wins: 6, lastPlayed: new Date(2026, 8, 27, 20, 0, 0).getTime() })
  })

  it('takes its art from the newest finished match, never the one in progress', () => {
    expect(decks[1]).toMatchObject({ artMatchId: 'a-old' })
    expect(decks[0]).toMatchObject({ artMatchId: 'b-2' })
    expect(decks[2]).toMatchObject({ artMatchId: 'e-1' })
  })

  it('holds as many as it is asked for', () => {
    expect(homeDecks(identities, matches, now, 1).map((deck) => deck.key)).toEqual(['Boros'])
  })
})

describe('fieldWindowStart', () => {
  const now = new Date(2026, 8, 28, 12, 0, 0).getTime()

  it('is the reset’s date at the viewer’s midnight', () => {
    expect(fieldWindowStart('2026-09-01', now)).toBe(new Date(2026, 8, 1).getTime())
  })

  it('is 90 days before the clock without a reset', () => {
    expect(fieldWindowStart(null, now)).toBe(now - 90 * DAY)
    expect(fieldWindowStart('last month', now)).toBe(now - 90 * DAY)
  })
})

describe('homeField', () => {
  const now = new Date(2026, 8, 28, 12, 0, 0).getTime()
  // A row and a match name a deck by its key and its label together; here
  // the label is the key's own, one label to a key.
  const row = (tier: string, key: string, decks: number) =>
    ({ tier, archetype_key: key, label: key, decks }) as unknown as MetaPresence
  const identities = [
    { key: 'Izzet', name: 'Izzet', deck_ids: ['a1', 'a2'] } as DeckIdentityOut,
    { key: 'Boros', name: 'Boros', deck_ids: ['b1'] } as DeckIdentityOut,
  ]
  const presence = [
    row('A', 'small', 5),
    row('A', 'big', 10),
    row('A', 'none', 0),
    row('B', 'league', 50),
    row('C', 'undefeated', 90),
  ]
  const against = (id: string, startedAt: string, result: string | null, deckId: string | null, key: string) =>
    match(id, startedAt, result, { deck_id: deckId, format: 'Standard', opponent_key: `archetype:${key}`, opponent_label: key })
  const matches = [
    against('1', '2026-09-27T20:00:00', 'win', 'a2', 'big'),
    against('2', '2026-09-20T20:00:00', 'loss', 'a1', 'big'),
    against('3', '2026-09-19T20:00:00', 'win', 'a1', 'small'),
    against('4', '2026-09-18T20:00:00', 'win', 'b1', 'big'),
    against('5', '2026-08-31T23:59:59', 'win', 'a1', 'big'),
    against('6', '2026-09-28T11:00:00', null, 'a2', 'big'),
  ]

  it('is null with no lists in any tier', () => {
    expect(homeField([], matches, identities, null, false, now, 'Standard')).toBeNull()
    expect(homeField([row('A', 'none', 0), row('D', 'empty', 0)], matches, identities, null, false, now, 'Standard')).toBeNull()
  })

  it('reads leagues before smaller paper, and smaller paper when it alone has lists', () => {
    const leaguesAndSmallPaper = [row('D', 'small-paper', 12), row('C', 'undefeated', 90), row('A', 'none', 0)]
    expect(homeField(leaguesAndSmallPaper, matches, identities, null, false, now, 'Standard')!.tier).toBe('C')
    const smallPaperOnly = [row('A', 'none', 0), row('D', 'small-paper', 12)]
    const field = homeField(smallPaperOnly, matches, identities, null, false, now, 'Standard')!
    expect(field.tier).toBe('D')
    expect(field.lists).toBe(12)
  })

  it('ignores a newer match in another format, for the deck and for the record', () => {
    const other = { ...against('7', '2026-09-28T10:00:00', 'loss', 'b1', 'big'), format: 'Modern' as const }
    const field = homeField(presence, [other, ...matches], identities, '2026-09-01', false, now, 'Standard')!
    expect(field.deck).toEqual({ name: 'Izzet', deckIds: new Set(['a1', 'a2']) })
    expect(field.rows[0].record).toEqual({ played: 2, won: 1, losses: 1 })
    expect(field.topTwo).toEqual({ played: 3, won: 2, losses: 1 })
    expect(field.artMatchId).toBe('1')
  })

  it('is not short when the whole list reaches back past the window, whatever its oldest match\'s format', () => {
    // With the reset at Aug 15 every Standard match is inside the window and
    // only the Modern one is older.
    const full = [
      ...matches,
      { ...against('old', '2026-08-01T20:00:00', 'win', 'a1', 'big'), format: 'Modern' as const },
    ]
    expect(homeField(presence, full, identities, '2026-08-15', true, now, 'Standard')!.listShort).toBe(false)
  })

  it('reads the highest tier with lists, its decks the most played first', () => {
    const field = homeField(presence, matches, identities, '2026-09-01', false, now, 'Standard')!
    expect(field.tier).toBe('A')
    expect(field.rows.map((entry) => entry.presence.archetype_key)).toEqual(['big', 'small'])
    expect(field.lists).toBe(15)
    expect(homeField(presence.slice(2), matches, identities, null, false, now, 'Standard')!.tier).toBe('B')
  })

  it('counts every list of the tier, not only the rows shown', () => {
    const field = homeField(presence, matches, identities, null, false, now, 'Standard', 1)!
    expect(field.rows).toHaveLength(1)
    expect(field.lists).toBe(15)
  })

  it('gives the record of the newest match’s deck, every version of it, inside the window', () => {
    const field = homeField(presence, matches, identities, '2026-09-01', false, now, 'Standard')!
    expect(field.deck).toEqual({ name: 'Izzet', deckIds: new Set(['a1', 'a2']) })
    // Against "big": matches 1 and 2. Match 4 was another deck's, 5 began
    // 23:59:59 local the day before the reset (one second outside the
    // window), 6 is not finished.
    expect(field.rows[0].record).toEqual({ played: 2, won: 1, losses: 1 })
    expect(field.rows[1].record).toEqual({ played: 1, won: 1, losses: 0 })
    expect(field.topTwo).toEqual({ played: 3, won: 2, losses: 1 })
    expect(field.windowStart).toBe(new Date(2026, 8, 1).getTime())
    expect(field.reset).toBe('2026-09-01')
  })

  it('reaches back 90 days without a reset', () => {
    const field = homeField(presence, matches, identities, null, false, now, 'Standard')!
    expect(field.reset).toBeNull()
    expect(field.windowStart).toBe(now - 90 * DAY)
    expect(field.rows[0].record).toEqual({ played: 3, won: 2, losses: 1 })
  })

  it('counts every deck’s matches when no match has a deck', () => {
    const deckless = matches.map((entry) => ({ ...entry, deck_id: null }))
    const field = homeField(presence, deckless, identities, '2026-09-01', false, now, 'Standard')!
    expect(field.deck).toBeNull()
    expect(field.rows[0].record).toEqual({ played: 3, won: 2, losses: 1 })
  })

  it('takes a deck of no identity by its own id and name', () => {
    const stray = [match('s', '2026-09-28T11:30:00', 'win', { deck_id: 'z9', deck_name: 'Stray', format: 'Standard' }), ...matches]
    expect(homeField(presence, stray, identities, null, false, now, 'Standard')!.deck).toEqual({
      name: 'Stray',
      deckIds: new Set(['z9']),
    })
  })

  it('takes the art from the match against the row’s own label, not another label of its key', () => {
    const labelled = (id: string, startedAt: string, label: string) =>
      match(id, startedAt, 'win', { deck_id: 'a1', format: 'Standard', opponent_key: 'archetype:control', opponent_label: label })
    const rows = [{ tier: 'C', archetype_key: 'control', label: 'Jeskai Control', decks: 9 } as unknown as MetaPresence]
    const pair = [
      labelled('newer-other', '2026-09-27T20:00:00', 'Sultai Control'),
      labelled('older-own', '2026-09-20T20:00:00', 'Jeskai Control'),
    ]
    expect(homeField(rows, pair, identities, null, false, now, 'Standard')!.artMatchId).toBe('older-own')
  })

  it('takes the first row’s art from the newest finished match against it, whatever the deck', () => {
    expect(homeField(presence, matches, identities, '2026-09-01', false, now, 'Standard')!.artMatchId).toBe('1')
    expect(homeField(presence, matches.slice(3), identities, '2026-09-01', false, now, 'Standard')!.artMatchId).toBe('4')
  })

  it('says when a full list does not reach back to the window’s start', () => {
    // The oldest match listed is August 31, before the reset of September 1
    // and after the start of a window of 90 days.
    expect(homeField(presence, matches, identities, '2026-09-01', true, now, 'Standard')!.listShort).toBe(false)
    expect(homeField(presence, matches, identities, null, true, now, 'Standard')!.listShort).toBe(true)
    expect(homeField(presence, matches, identities, null, false, now, 'Standard')!.listShort).toBe(false)
  })
})

describe('the pill state', () => {
  const base = { isError: false, watcherStopped: false, matchInProgress: false, watching: true }
  it('puts a failed heartbeat before a stopped watcher', () => {
    expect(liveState({ ...base, isError: true, watcherStopped: true })).toBe('down')
  })
  it('puts a stopped watcher before a match in progress', () => {
    expect(liveState({ ...base, watcherStopped: true, matchInProgress: true, watching: false })).toBe(
      'stopped',
    )
  })
  it('then a match, watching, not watching', () => {
    expect(liveState({ ...base, matchInProgress: true })).toBe('match')
    expect(liveState(base)).toBe('watching')
    expect(liveState({ ...base, watching: false })).toBe('idle')
  })
})

describe('detailedLogsNag', () => {
  const sources = (path: string | null, detailedLogs: DetailedLogs) => ({ arenaLog: { path, found: true, detailedLogs } })

  it('asks while doctor does not read them on, for a player of Arena', () => {
    expect(detailedLogsNag(sources('/log', 'disabled'), ['arena'])).toBe(true)
    expect(detailedLogsNag(sources('/log', 'unknown'), ['arena', 'mtgo'])).toBe(true)
    expect(detailedLogsNag(sources('/log', 'enabled'), ['arena'])).toBe(false)
  })

  it('reads a missing plays as both', () => {
    expect(detailedLogsNag(sources('/log', 'disabled'), undefined)).toBe(true)
  })

  it('does not ask without a log path', () => {
    expect(detailedLogsNag(sources(null, 'unknown'), ['arena'])).toBe(false)
  })

  it('never asks an MTGO-only player', () => {
    expect(detailedLogsNag(sources('/log', 'disabled'), ['mtgo'])).toBe(false)
  })
})
