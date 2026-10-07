import { describe, expect, it } from 'vitest'
import type { FormatEntry, FormatsOut, Match, MetaMatchup, MetaPresence, MetaWinrate, MetagameStatus } from '../api'
import {
  ageWords,
  anyFormatData,
  defaultPairs,
  defaultTier,
  eventCaption,
  eventHref,
  formatCaption,
  formatChoices,
  formatOf,
  holdLines,
  isStale,
  listShort,
  matchupRows,
  metaWindowOf,
  nextPairs,
  noPairsMessage,
  pairsOf,
  paramFor,
  matchesInFormat,
  ownCounts,
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

function entry(format: FormatEntry['format'], log: number, pick: number, inferred: number, corpus: number): FormatEntry {
  return {
    format,
    matches: { log, pick, inferred, total: log + pick + inferred },
    has_rules: true,
    corpus_events: corpus,
  }
}

const FORMATS: FormatsOut = {
  default: 'Standard',
  formats: [
    entry('Standard', 3, 0, 0, 10),
    entry('Pioneer', 0, 0, 0, 0),
    entry('Modern', 1, 2, 4, 5),
    entry('Pauper', 0, 0, 0, 7),
    entry('Legacy', 1, 0, 0, 0),
  ],
}

describe('the format', () => {
  it('reads one the API lists, else the default', () => {
    expect(formatOf('Modern', FORMATS)).toBe('Modern')
    expect(formatOf(null, FORMATS)).toBe('Standard')
    expect(formatOf('Dandan', FORMATS)).toBe('Standard')
  })

  it('offers the formats with matches or events, in order, and the address\'s always', () => {
    expect(formatChoices(FORMATS, 'Standard').map((e) => e.format)).toEqual([
      'Standard',
      'Modern',
      'Pauper',
      'Legacy',
    ])
    expect(formatChoices(FORMATS, 'Pioneer').map((e) => e.format)).toEqual([
      'Standard',
      'Pioneer',
      'Modern',
      'Pauper',
      'Legacy',
    ])
  })

  it('knows when no format holds anything', () => {
    expect(anyFormatData(FORMATS)).toBe(true)
    expect(anyFormatData({ default: 'Standard', formats: [entry('Standard', 0, 0, 0, 0)] })).toBe(false)
  })

  it('says where the matches were read from, leaving out parts at 0', () => {
    expect(formatCaption(entry('Modern', 1, 2, 4, 5))).toBe(
      "7 of your matches are Modern: 1 from Arena's log, 2 you confirmed, 4 inferred from the cards revealed.",
    )
    expect(formatCaption(entry('Pauper', 0, 1, 0, 7))).toBe('1 of your matches is Pauper: 1 you confirmed.')
    expect(formatCaption(entry('Pioneer', 0, 0, 0, 0))).toBe('None of your matches are Pioneer.')
    expect(formatCaption(entry('Standard', 1200, 0, 0, 0))).toBe(
      "1,200 of your matches are Standard: 1,200 from Arena's log.",
    )
  })
})

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

describe('the viewer\'s own matches by format', () => {
  it('keeps the selected format\'s matches, and counts one with no format toward none', () => {
    const rows = [
      match('s1', '2026-09-01T20:00:00', 'win', { format: 'Standard' }),
      match('m1', '2026-09-02T20:00:00', 'win', { format: 'Modern' }),
      match('n1', '2026-09-03T20:00:00', 'win', { format: null }),
    ]
    expect(matchesInFormat(rows, 'Modern').map((m) => m.match_id)).toEqual(['m1'])
    expect(matchesInFormat(rows, 'Standard').map((m) => m.match_id)).toEqual(['s1'])
    expect(matchesInFormat(rows, 'Pioneer')).toEqual([])
  })
})

describe('the viewer\'s own counts', () => {
  const tempo = presence('tempo', 'B', 5, 'Izzet Tempo')
  const start = Date.UTC(2026, 7, 11)
  const vs = { opponent_key: 'archetype:tempo', opponent_label: 'Izzet Tempo' }

  it('counts only the selected format\'s matches, not another\'s or one with none', () => {
    const rows = [
      match('s', '2026-09-01T20:00:00', 'win', { format: 'Standard', ...vs }),
      match('m', '2026-09-02T20:00:00', 'win', { format: 'Modern', ...vs }),
      match('n', '2026-09-03T20:00:00', 'win', { format: null, ...vs }),
    ]
    const counts = ownCounts(rows, [tempo], 'Standard', start, undefined)
    expect(counts.records).toEqual([{ played: 1, won: 1 }])
    expect(counts.topTwo).toEqual({ played: 1, won: 1 })
  })

  it('is short for a full list of mixed formats none of which is before the window', () => {
    const full = Array.from({ length: 500 }, (_, index) =>
      match(`m${index}`, '2026-09-01T20:00:00', 'win', { format: index % 2 ? 'Modern' : 'Standard' }),
    )
    expect(ownCounts(full, [tempo], 'Standard', start, 900).short).toBe(true)
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

describe('the events', () => {
  const count = (n: number) => (n === 1032 ? '1,032' : String(n))

  it('captions an event: source, lists, winner', () => {
    expect(eventCaption({ source: 'MTGO', lists: 32, winner: 'Izzet Prowess' }, count)).toBe(
      'mtgo.com · 32 decklists · won by Izzet Prowess',
    )
    expect(eventCaption({ source: 'MTGmelee', lists: 1, winner: null }, count)).toBe('melee.gg · 1 decklist')
    expect(eventCaption({ source: 'Topdeck', lists: 0 }, count)).toBe('TopDeck.gg · standings only')
    expect(eventCaption({ source: 'MTGO', lists: 1032, winner: null }, count)).toBe('mtgo.com · 1,032 decklists')
  })

  it('leaves out a source it does not know', () => {
    expect(eventCaption({ source: 'Elsewhere', lists: 2, winner: 'Burn' }, count)).toBe('2 decklists · won by Burn')
  })

  it('encodes each segment of an event key and keeps the slashes', () => {
    expect(eventHref('mtgo/a b#c')).toBe('/field/events/mtgo/a%20b%23c')
  })
})

describe('the hold lines', () => {
  const since = '2026-10-05T09:00:00Z'
  const status = (sources: unknown[]) => ({ corpus_sources: sources }) as unknown as MetagameStatus
  const NOW = Date.parse('2026-10-05T13:00:00Z')
  const sources = status([
    { source: 'mtgo', hold: { status: 'paused', http_status: 403, since, not_before: null } },
    { source: 'topdeck', hold: { status: 'waiting', http_status: 429, since, not_before: '2026-10-05T14:02:30Z' } },
    { source: 'fbettega', hold: { status: 'paused', http_status: 403, since, not_before: null } },
    { source: 'mtgo' },
  ])

  it('gives a paused source its line', () => {
    expect(holdLines(sources, 'paused', NOW)).toEqual([
      "mtgo.com — paused since 2026-10-05: the site refused the fetch (HTTP 403). Nothing more is read until you run `sensei-top meta`; re-read Daybreak's Terms of Service before you do.",
    ])
  })

  it('gives a waiting source its line', () => {
    expect(holdLines(sources, 'waiting', NOW)).toEqual([
      'TopDeck.gg — waiting: the site asked for a pause (HTTP 429). The next fetch is after 14:03 UTC.',
    ])
  })

  it('gives nothing when no source holds', () => {
    expect(holdLines(status([{ source: 'mtgo' }]), 'paused', NOW)).toEqual([])
    expect(holdLines({} as MetagameStatus, 'waiting', NOW)).toEqual([])
  })
})
