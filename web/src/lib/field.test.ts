import { describe, expect, it } from 'vitest'
import type { Match, MetaMatchup, MetaPresence, MetaWinrate } from '../api'
import {
  ageWords,
  defaultPairs,
  defaultTier,
  isStale,
  listShort,
  matchupRows,
  metaWindowOf,
  nextPairs,
  noPairsMessage,
  pairsOf,
  paramFor,
  recordAgainstRows,
  shareAction,
  shareRows,
  shownRows,
  tierOf,
  windowOf,
  windowOptions,
  windowStartOf,
  windowWords,
  winrateRows,
} from './field'

// The zone is America/New_York (vitest.config.ts). Timestamps below are
// bare, so UTC.

const DAY = 24 * 3_600_000
const RESET = '2026-08-11'
const NOW = Date.UTC(2026, 8, 29, 12) // Sep 29, 2026, 12:00 UTC

function presence(key: string, tier: string, decks: number, label = key): MetaPresence {
  return { archetype_key: key, label, colors: null, tier, decks, share: 0 }
}

function winrate(label: string, won: number, lost: number, drawn: number, rate: number | null): MetaWinrate {
  return {
    archetype_key: label.toLowerCase(),
    label,
    colors: null,
    entries: 1,
    matches_won: won,
    matches_lost: lost,
    matches_drawn: drawn,
    winrate: rate,
  }
}

function matchup(label: string, opponent: string, n: number): MetaMatchup {
  return {
    archetype_key: label.toLowerCase(),
    label,
    opponent_key: opponent.toLowerCase(),
    opponent_label: opponent,
    tier: 'B',
    n,
    matches_won: 0,
    matches_lost: 0,
    matches_drawn: 0,
    games_won: 0,
    games_lost: 0,
    winrate: null,
  }
}

function match(id: string, startedAt: string, result: string | null, rest: Partial<Match> = {}): Match {
  return { match_id: id, started_at: startedAt, ended_at: null, result, ...rest } as Match
}

describe('the window', () => {
  it('opens on the reset when one is known, else on 90 days', () => {
    expect(windowOf(null, RESET)).toBe('reset')
    expect(windowOf(null, null)).toBe(90)
  })

  it('reads a day count the select offers', () => {
    expect(windowOf('30', RESET)).toBe(30)
    expect(windowOf('365', null)).toBe(365)
  })

  it('takes ?window=reset with no reset known as 90 days', () => {
    expect(windowOf('reset', null)).toBe(90)
    expect(metaWindowOf(windowOf('reset', null), null)).toEqual({ days: 90 })
  })

  it('falls back to the default on a value it does not know', () => {
    expect(windowOf('14', RESET)).toBe('reset')
    expect(windowOf('forever', null)).toBe(90)
    expect(windowOf('', RESET)).toBe('reset')
  })

  it('asks the API for the reset as since and a day count as days', () => {
    expect(metaWindowOf('reset', RESET)).toEqual({ since: RESET })
    expect(metaWindowOf(15, RESET)).toEqual({ days: 15 })
  })

  it('starts at the reset, 00:00 UTC, or the day count before now', () => {
    expect(windowStartOf('reset', RESET, NOW)).toBe(Date.UTC(2026, 7, 11))
    expect(windowStartOf(30, RESET, NOW)).toBe(NOW - 30 * DAY)
  })

  it('says the window in words', () => {
    expect(windowWords('reset', RESET, NOW)).toEqual({ when: 'since Aug 11', short: 'since Aug 11' })
    expect(windowWords(30, RESET, NOW)).toEqual({ when: 'in the last 30 days', short: 'last 30 days' })
  })

  it('offers the reset first only when one is known', () => {
    expect(windowOptions(RESET, NOW).map((option) => option.label)).toEqual([
      'Since the last reset (Aug 11)',
      'Last 7 days',
      'Last 15 days',
      'Last 30 days',
      'Last 90 days',
      'Last 180 days',
      'Last 365 days',
    ])
    expect(windowOptions(null, NOW)[0]).toEqual({ value: '7', label: 'Last 7 days' })
  })
})

describe('the tier and the pairs', () => {
  const allTiers = [presence('a1', 'A', 3), presence('b1', 'B', 5), presence('c1', 'C', 2), presence('d1', 'D', 4)]
  const noPaper = [presence('a1', 'A', 0), presence('b1', 'B', 5), presence('c1', 'C', 2)]
  const leaguesAndSmallPaper = [presence('c1', 'C', 2), presence('d1', 'D', 7)]
  const smallPaperOnly = [presence('a1', 'A', 0), presence('d1', 'D', 7)]

  it('defaults to paper 64+ when it has lists', () => {
    expect(defaultTier(allTiers)).toBe('A')
    expect(tierOf(null, allTiers)).toBe('A')
  })

  it('defaults to challenges when paper 64+ has none', () => {
    expect(defaultTier(noPaper)).toBe('B')
  })

  it('defaults to leagues before smaller paper', () => {
    expect(defaultTier(leaguesAndSmallPaper)).toBe('C')
  })

  it('defaults to smaller paper when no other tier has lists', () => {
    expect(defaultTier(smallPaperOnly)).toBe('D')
  })

  it('keeps a tier the address names, even one without lists', () => {
    expect(tierOf('C', allTiers)).toBe('C')
    expect(tierOf('A', noPaper)).toBe('A')
    expect(tierOf('D', noPaper)).toBe('D')
  })

  it('falls back to the default on a tier it does not know', () => {
    expect(tierOf('E', noPaper)).toBe('B')
    expect(tierOf('a', allTiers)).toBe('A')
  })

  it('counts pairs from the first step with lists: paper 64+, then challenges, then smaller paper', () => {
    expect(defaultPairs(allTiers)).toBe('A')
    expect(defaultPairs(noPaper)).toBe('AB')
    expect(defaultPairs(smallPaperOnly)).toBe('ABD')
    expect(pairsOf(null, noPaper)).toBe('AB')
  })

  it('reads every step the address can name, old and new', () => {
    expect(pairsOf('A', noPaper)).toBe('A')
    expect(pairsOf('AB', allTiers)).toBe('AB')
    expect(pairsOf('ABD', allTiers)).toBe('ABD')
    expect(pairsOf('B', allTiers)).toBe('A')
    expect(pairsOf('AD', smallPaperOnly)).toBe('ABD')
  })

  it('offers the next step with lists, skipping challenges when they have none', () => {
    expect(nextPairs('A', allTiers)).toBe('AB')
    expect(nextPairs('A', smallPaperOnly)).toBe('ABD')
    expect(nextPairs('A', [presence('c1', 'C', 2)])).toBeNull()
    expect(nextPairs('AB', allTiers)).toBe('ABD')
    expect(nextPairs('AB', noPaper)).toBeNull()
    expect(nextPairs('ABD', allTiers)).toBeNull()
  })

  it('names the tiers counted when no round is found', () => {
    expect(noPairsMessage('A', 'since Aug 11')).toBe(
      'No rounds between two named decks in paper tournaments of 64+ players since Aug 11.',
    )
    expect(noPairsMessage('AB', 'in the last 30 days')).toBe(
      'No rounds between two named decks in paper tournaments of 64+ players or MTGO challenges in the last 30 days.',
    )
    expect(noPairsMessage('ABD', 'since Aug 11')).toBe('No rounds between two named decks since Aug 11.')
  })

  it('leaves a default out of the address', () => {
    expect(paramFor('A', 'A')).toBeUndefined()
    expect(paramFor('AB', 'A')).toBe('AB')
    expect(paramFor('reset', 'reset')).toBeUndefined()
    expect(paramFor('30', 'reset')).toBe('30')
  })

  it('names the tier and the window in the share card\'s action', () => {
    expect(shareAction('B', 'reset', RESET, NOW)).toBe('MTGO challenges since Aug 11')
    expect(shareAction('A', 30, RESET, NOW)).toBe('Paper tournaments of 64+ players, last 30 days')
    expect(shareAction('D', 30, RESET, NOW)).toBe('Paper tournaments under 64 players, last 30 days')
  })
})

describe('the rows', () => {
  it('lists the tier\'s decks with lists, the most played first, a tie by name', () => {
    const rows = shareRows(
      [presence('z', 'B', 4, 'Zoo'), presence('a', 'B', 9, 'Azorius'), presence('m', 'B', 4, 'Mono Red'),
        presence('x', 'A', 20, 'Other tier'), presence('e', 'B', 0, 'Empty')],
      'B',
    )
    expect(rows.map((row) => row.label)).toEqual(['Azorius', 'Mono Red', 'Zoo'])
  })

  it('leaves out a win rate on one match and sorts the rest by matches, a tie by rate', () => {
    const rows = winrateRows([
      winrate('One match', 1, 0, 0, 1),
      winrate('Half', 2, 2, 0, 0.5),
      winrate('Most', 3, 1, 0, 0.75),
      winrate('Bigger half', 5, 5, 0, 0.5),
      winrate('Also most', 3, 1, 0, 0.75),
    ])
    // Ten matches first; then three rows of four matches, the higher rate
    // first, the two of 0.75 by name.
    expect(rows.map((row) => row.label)).toEqual(['Bigger half', 'Also most', 'Most', 'Half'])
  })

  it('counts a draw as a match', () => {
    expect(winrateRows([winrate('Drawn once', 1, 0, 1, 0.5)]).map((row) => row.label)).toEqual(['Drawn once'])
  })

  it('sorts pairs by matches, a tie by the archetype\'s name', () => {
    const rows = matchupRows([
      matchup('Zoo', 'Azorius', 3),
      matchup('Boros', 'Zoo', 7),
      matchup('Azorius', 'Zoo', 3),
      matchup('Azorius', 'Boros', 3),
    ])
    expect(rows.map((row) => `${row.label}/${row.opponent_label}`)).toEqual([
      'Boros/Zoo',
      'Azorius/Boros',
      'Azorius/Zoo',
      'Zoo/Azorius',
    ])
  })

  it('shows twenty pairs until the rest are asked for', () => {
    const rows = Array.from({ length: 25 }, (_, index) => index)
    expect(shownRows(rows, 20, false)).toHaveLength(20)
    expect(shownRows(rows, 20, true)).toHaveLength(25)
    expect(shownRows(rows.slice(0, 5), 12, false)).toHaveLength(5)
  })
})

describe('the record against a row', () => {
  const tempo = presence('tempo', 'B', 5, 'Izzet Tempo')
  const ramp = presence('ramp', 'B', 4, 'Gruul Ramp')
  const start = Date.UTC(2026, 7, 11)
  const vs = (key: string, label: string) => ({ opponent_key: `archetype:${key}`, opponent_label: label })
  const matches = [
    // In the window, two decks of the viewer's: both count.
    match('m1', '2026-09-01T20:00:00', 'win', { deck_id: 'd1', ...vs('tempo', 'Izzet Tempo') }),
    match('m2', '2026-09-02T20:00:00', 'loss', { deck_id: 'd2', ...vs('tempo', 'Izzet Tempo') }),
    match('m3', '2026-09-03T20:00:00', 'win', { deck_id: null, ...vs('tempo', 'Izzet Tempo') }),
    // Before the window: not counted.
    match('m4', '2026-08-10T20:00:00', 'win', { deck_id: 'd1', ...vs('tempo', 'Izzet Tempo') }),
    // Not finished: not counted.
    match('m5', '2026-09-04T20:00:00', null, { deck_id: 'd1', ...vs('tempo', 'Izzet Tempo') }),
    // Another deck of the field's.
    match('m6', '2026-09-05T20:00:00', 'win', { deck_id: 'd1', ...vs('ramp', 'Gruul Ramp') }),
  ]

  it('counts every deck of the viewer\'s in the window, and nothing before it', () => {
    expect(recordAgainstRows(matches, [tempo], start)).toEqual({ played: 3, won: 2 })
  })

  it('counts the top two together', () => {
    expect(recordAgainstRows(matches, [tempo, ramp], start)).toEqual({ played: 4, won: 3 })
  })

  it('counts a match at the window\'s first moment', () => {
    const edge = [match('e', '2026-08-11T00:00:00', 'loss', vs('ramp', 'Gruul Ramp'))]
    expect(recordAgainstRows(edge, [ramp], start)).toEqual({ played: 1, won: 0 })
  })

  it('tells apart two rows of one key by their labels', () => {
    const jeskai = presence('Control', 'B', 6, 'Jeskai Control')
    const sultai = presence('Control', 'B', 3, 'Sultai Control')
    const control = [
      match('j1', '2026-09-01T20:00:00', 'win', vs('Control', 'Jeskai Control')),
      match('j2', '2026-09-02T20:00:00', 'win', vs('Control', 'Jeskai Control')),
      match('s1', '2026-09-03T20:00:00', 'loss', vs('Control', 'Sultai Control')),
      // The key of both, the label of neither: counts for neither.
      match('a1', '2026-09-04T20:00:00', 'win', vs('Control', 'Azorius Control')),
      // No label at all: counts for neither.
      match('n1', '2026-09-05T20:00:00', 'win', { opponent_key: 'archetype:Control' }),
    ]
    expect(recordAgainstRows(control, [jeskai], start)).toEqual({ played: 2, won: 2 })
    expect(recordAgainstRows(control, [sultai], start)).toEqual({ played: 1, won: 0 })
    expect(recordAgainstRows(control, [jeskai, sultai], start)).toEqual({ played: 3, won: 2 })
  })
})

describe('the list of 500', () => {
  const start = Date.UTC(2026, 7, 11)
  const full = Array.from({ length: 500 }, (_, index) =>
    match(`m${index}`, '2026-09-01T20:00:00', 'win'),
  )

  it('is short when it holds 500, more are recorded and none reaches the window', () => {
    expect(listShort(full, 900, start)).toBe(true)
    expect(listShort(full, undefined, start)).toBe(true)
  })

  it('is not short when it holds every match, or reaches back to the window', () => {
    expect(listShort(full, 500, start)).toBe(false)
    const reaching = [...full.slice(1), match('old', '2026-08-01T20:00:00', 'win')]
    expect(listShort(reaching, 900, start)).toBe(false)
    expect(listShort(full.slice(0, 20), 900, start)).toBe(false)
  })
})

describe('the sources', () => {
  it('writes an age as ago() does, without its ago', () => {
    expect(ageWords(150)).toBe('6d')
    expect(ageWords(5.5)).toBe('5h')
  })

  it('is stale after seven days, or never downloaded', () => {
    expect(isStale(null)).toBe(true)
    expect(isStale(7 * 24 + 1)).toBe(true)
    expect(isStale(7 * 24)).toBe(false)
    expect(isStale(2)).toBe(false)
  })
})
