import { describe, expect, it } from 'vitest'
import type {
  CoachModelOption,
  CoachReportSummary,
  CoachSource,
  FormatEntry,
  FormatsOut,
  RateModel,
  TurningBucketOut,
} from '../api'
import {
  citationOf,
  coachDay,
  deckName,
  deckPatternsSummary,
  historyDetail,
  hostOf,
  listsWords,
  modelCostNote,
  modelLabel,
  mulliganRates,
  overallTiles,
  patternDirection,
  profileCaption,
  rateTile,
  rateWords,
  readingOrder,
  coachAddress,
  coachFormatChoices,
  latestOfFormat,
  reportByline,
  reportFormat,
  reportLink,
  reportParam,
  reportTitle,
  showHistory,
  roleRates,
  turningSubtitle,
  turningTiles,
  variantsWords,
} from './coach'
import { translator } from '../i18n'
import { WORD_JOINER } from './format'
import { NBSP } from './matchups'

const t = translator('en')

// Every label, title, url and model id is invented, but for "Opus 5.5",
// one of the public model names.

const reading = (label: string, title: string | null = null): CoachSource =>
  ({ kind: 'reading', label, url: `https://example.com/${label.toLowerCase()}`, title }) as CoachSource
const web = (label: string): CoachSource =>
  ({ kind: 'web', label, url: `https://example.com/${label}`, title: label }) as CoachSource

describe('readingOrder', () => {
  it('orders the reading entries by number, R2 before R10, and keeps the web entries last in their order', () => {
    // Stored order: R10, a web page, R2, another web page, R1.
    const ordered = readingOrder([reading('R10'), web('page-b'), reading('R2'), web('page-a'), reading('R1')])
    expect(ordered.map((s) => s.label)).toEqual(['R1', 'R2', 'R10', 'page-b', 'page-a'])
  })
})

describe('hostOf', () => {
  it('drops a leading www.', () => {
    expect(hostOf('https://www.example.com/articles/one')).toBe('example.com')
    expect(hostOf('https://news.example.org/a')).toBe('news.example.org')
  })

  it('is null for a string that is not a url', () => {
    expect(hostOf('not a url')).toBeNull()
  })
})

describe('citationOf', () => {
  it('points a label at its reading entry, named label then title', () => {
    const sources = [web('R4'), reading('R4', 'An Author — A Title')]
    // The web entry labelled "R4" is not a reading entry: skipped.
    expect(citationOf('R4', sources)).toEqual({ url: 'https://example.com/r4', name: 'R4: An Author — A Title' })
  })

  it('names an entry with no title by its url', () => {
    expect(citationOf('R7', [reading('R7')])).toEqual({ url: 'https://example.com/r7', name: 'R7: https://example.com/r7' })
  })

  it('is null for a label no reading entry carries, compared exactly', () => {
    expect(citationOf('R9', [reading('R4')])).toBeNull()
    expect(citationOf('r4', [reading('R4')])).toBeNull()
  })
})

describe('reportParam', () => {
  it('is the latest report with no parameter', () => {
    expect(reportParam(undefined)).toBe('latest')
  })

  it('is the number for a positive integer', () => {
    expect(reportParam('3')).toBe(3)
  })

  it('is unknown for zero, a negative, a fraction, words, and a leading zero', () => {
    expect(reportParam('0')).toBe('unknown')
    expect(reportParam('-1')).toBe('unknown')
    expect(reportParam('3.5')).toBe('unknown')
    expect(reportParam('abc')).toBe('unknown')
    // "03" would be a second address for report 3.
    expect(reportParam('03')).toBe('unknown')
  })
})

const models = [
  { id: 'model-a', label: 'Model A', input_per_mtok: 10, output_per_mtok: 50 },
  { id: 'model-b', label: 'Model B', input_per_mtok: 2.5, output_per_mtok: 12.5 },
  { id: 'model-c', label: 'Model C', input_per_mtok: null, output_per_mtok: null },
] as CoachModelOption[]

describe('modelLabel', () => {
  it('is the label of a listed model', () => {
    expect(modelLabel('model-b', models)).toBe('Model B')
  })

  it('is the id as stored for a model not in the list', () => {
    expect(modelLabel('model-z', models)).toBe('model-z')
  })
})

describe('reportTitle', () => {
  // Noon UTC on Sep 29 2026; the zone is New York (vitest.config.ts).
  const now = Date.parse('2026-09-29T12:00:00Z')

  it('is the format and the short day in this year', () => {
    // generated_at is the server's own UTC stamp, so it carries Z.
    // 18:00 UTC is 14:00 in New York, the same day.
    expect(reportTitle('Modern', '2026-09-22T18:00:00Z', now, t)).toBe('Modern report of Sep 22')
    // 02:00 UTC on the 23rd is 22:00 on the 22nd in New York.
    expect(reportTitle('Standard', '2026-09-23T02:00:00Z', now, t)).toBe('Standard report of Sep 22')
  })

  it('adds the year in another year', () => {
    expect(reportTitle('Modern', '2025-09-22T18:00:00Z', now, t)).toBe('Modern report of Sep 22, 2025')
  })

  it('is "{format} report" when the day cannot be read', () => {
    expect(reportTitle('Modern', 'not a day', now, t)).toBe('Modern report')
    expect(reportTitle('Pioneer', null, now, t)).toBe('Pioneer report')
  })
})

describe('the format of a report and its page', () => {
  const entry = (format: string, total: number) =>
    ({ format, matches: { total, log: total, pick: 0, inferred: 0 }, has_rules: true, corpus_events: 0 }) as FormatEntry
  const formats = {
    default: 'Modern',
    formats: [entry('Standard', 0), entry('Pioneer', 0), entry('Modern', 12), entry('Pauper', 3)],
  } as FormatsOut
  // Newest first, as /api/coach sends them. A null format is Standard's.
  const reports = [
    { id: 9, format: 'Modern' },
    { id: 7, format: 'Pauper' },
    { id: 5, format: null },
    { id: 3, format: 'Modern' },
  ] as CoachReportSummary[]

  it('reads a report with no format as Standard', () => {
    expect(reportFormat(reports[2])).toBe('Standard')
    expect(reportFormat(reports[0])).toBe('Modern')
  })

  it('offers formats with matches or a report, in the API order, and the selected one', () => {
    expect(coachFormatChoices(formats, 'Modern', reports).map((e) => e.format)).toEqual([
      'Standard',
      'Modern',
      'Pauper',
    ])
    expect(coachFormatChoices(formats, 'Pioneer', reports).map((e) => e.format)).toEqual([
      'Standard',
      'Pioneer',
      'Modern',
      'Pauper',
    ])
  })

  it('offers the formats with matches before the report list arrives', () => {
    expect(coachFormatChoices(formats, 'Modern', []).map((e) => e.format)).toEqual(['Modern', 'Pauper'])
    expect(coachFormatChoices(formats, 'Pioneer', []).map((e) => e.format)).toEqual(['Pioneer', 'Modern', 'Pauper'])
  })

  it('draws the history when a stored report is not the one on the page', () => {
    expect(showHistory([], null)).toBe(false)
    expect(showHistory([{ id: 4 }], 4)).toBe(false)
    expect(showHistory([{ id: 4 }], null)).toBe(true)
    expect(showHistory([{ id: 4 }, { id: 2 }], 4)).toBe(true)
  })

  it('offers one format when one qualifies', () => {
    expect(coachFormatChoices(formats, 'Modern', [])).toHaveLength(2)
    const only = { default: 'Modern', formats: [entry('Standard', 0), entry('Modern', 4)] } as FormatsOut
    expect(coachFormatChoices(only, 'Modern', [])).toHaveLength(1)
  })

  it('writes the default as a bare address', () => {
    expect(coachAddress('Modern', 'Modern')).toBe('/coach')
    expect(coachAddress('Pauper', 'Modern')).toBe('/coach?format=Pauper')
  })

  it('finds the newest report of a format', () => {
    expect(latestOfFormat(reports, 'Modern')?.id).toBe(9)
    expect(latestOfFormat(reports, 'Standard')?.id).toBe(5)
    expect(latestOfFormat(reports, 'Pioneer')).toBeUndefined()
  })

  it('links the newest of the page format to the page, every other report to its id', () => {
    expect(reportLink(reports[0], reports, 'Modern', 'Modern')).toBe('/coach')
    expect(reportLink(reports[3], reports, 'Modern', 'Modern')).toBe('/coach/3')
    expect(reportLink(reports[1], reports, 'Modern', 'Modern')).toBe('/coach/7')
    expect(reportLink(reports[1], reports, 'Pauper', 'Modern')).toBe('/coach?format=Pauper')
    expect(reportLink(reports[0], reports, 'Pauper', 'Modern')).toBe('/coach/9')
  })
})

describe('reportByline', () => {
  const label = 'Opus 5.5'

  it('says a pasted report was pasted in, never its stored word', () => {
    expect(reportByline({ label: 'pasted', costUsd: null, searches: null, pasted: true }, t)).toBe('Pasted in.')
  })

  it('says the cost and the searches', () => {
    expect(reportByline({ label, costUsd: 1.038, searches: 8 }, t)).toBe(
      'Written by Opus 5.5. It cost $1.038 and searched the web 8 times.',
    )
  })

  it('says one search as once', () => {
    expect(reportByline({ label, costUsd: 1.038, searches: 1 }, t)).toBe(
      'Written by Opus 5.5. It cost $1.038 and searched the web once.',
    )
  })

  it('says the cost alone with no searches, null or 0, to three places', () => {
    expect(reportByline({ label, costUsd: 1.038, searches: null }, t)).toBe('Written by Opus 5.5. It cost $1.038.')
    // 0.5 to three places is 0.500.
    expect(reportByline({ label, costUsd: 0.5, searches: 0 }, t)).toBe('Written by Opus 5.5. It cost $0.500.')
  })

  it('says the searches alone with no cost', () => {
    expect(reportByline({ label, costUsd: null, searches: 8 }, t)).toBe('Written by Opus 5.5. It searched the web 8 times.')
    expect(reportByline({ label, costUsd: null, searches: 1 }, t)).toBe('Written by Opus 5.5. It searched the web once.')
  })

  it('says who wrote it alone with neither', () => {
    expect(reportByline({ label, costUsd: null, searches: null }, t)).toBe('Written by Opus 5.5.')
  })
})

describe('historyDetail', () => {
  const label = 'Opus 5.5'

  it('never shows the stored word for a pasted report', () => {
    expect(historyDetail({ label: 'pasted', costUsd: null, searches: null, pasted: true }, t)).toBe('Pasted in.')
  })

  it('is the label, the cost and the searches', () => {
    expect(historyDetail({ label, costUsd: 1.038, searches: 8 }, t)).toBe('Opus 5.5 · $1.038 · 8 web searches')
  })

  it('says one search in the singular', () => {
    expect(historyDetail({ label, costUsd: 1.038, searches: 1 }, t)).toBe('Opus 5.5 · $1.038 · 1 web search')
  })

  it('leaves out a part with no value, with its separator', () => {
    expect(historyDetail({ label, costUsd: null, searches: 8 }, t)).toBe('Opus 5.5 · 8 web searches')
    expect(historyDetail({ label, costUsd: 1.038, searches: null }, t)).toBe('Opus 5.5 · $1.038')
    expect(historyDetail({ label, costUsd: null, searches: null }, t)).toBe('Opus 5.5')
  })
})

describe('modelCostNote', () => {
  // Newest first, as /api/coach sends them. The newest with model-a has no
  // cost, so the one before it answers.
  const reports = [
    { id: 4, model: 'model-z', cost_usd: 0.5 },
    { id: 3, model: 'model-a', cost_usd: null },
    { id: 2, model: 'model-a', cost_usd: 3.229 },
    { id: 1, model: 'model-a', cost_usd: 0.848 },
  ] as CoachReportSummary[]

  it("says the newest priced report's cost with that model", () => {
    expect(modelCostNote('model-a', models, reports, t)).toBe('Your last report with Model A cost $3.229.')
    // An unlisted model is named by its id.
    expect(modelCostNote('model-z', models, reports, t)).toBe('Your last report with model-z cost $0.500.')
  })

  it("says the model's price as the API sends it when no report with it has a cost", () => {
    expect(modelCostNote('model-b', models, reports, t)).toBe(
      'Model B costs $2.5 per million tokens it reads and $12.5 per million it writes, plus its web searches.',
    )
  })

  it('is null for an unpriced model with no report, and for no model', () => {
    expect(modelCostNote('model-c', models, reports, t)).toBeNull()
    expect(modelCostNote(null, models, reports, t)).toBeNull()
  })
})

const rate = (wins: number, n: number, value: number | null, low: number, high: number): RateModel => ({
  wins,
  n,
  rate: value,
  ci_low: low,
  ci_high: high,
  // The server's rule: under ten matches is anecdotal.
  anecdotal: n < 10,
})

// 174 of 385 is 45.19%; the range 40.35%–50.25% rounds to 40 and 50.
const tenOrMore = rate(174, 385, 174 / 385, 0.4035, 0.5025)
const underTen = rate(3, 7, 3 / 7, 0.1, 0.8)
const none = rate(0, 0, null, 0, 1)

/** A range as `rateWords` writes it: a word joiner each side of the dash. */
const range = (low: number, high: number) => `${low}%${WORD_JOINER}–${WORD_JOINER}${high}%`

/** A record as `formatRecord` writes it. */
const record = (wins: number, losses: number) => `${wins}${WORD_JOINER}–${WORD_JOINER}${losses}`

describe('rateWords', () => {
  it('is the record, the percent and the range for ten matches or more', () => {
    expect(rateWords(tenOrMore)).toEqual({ record: record(174, 211), percent: '45%', range: range(40, 50) })
  })

  it("rounds the range's two ends as the percent rounds", () => {
    // 49.51% rounds up to 50; 44.49% down to 44, 55.51% up to 56.
    expect(rateWords(rate(1000, 2020, 0.4951, 0.4449, 0.5551))).toEqual({
      record: `1,000${WORD_JOINER}–${WORD_JOINER}1,020`,
      percent: '50%',
      range: range(44, 56),
    })
  })

  it('is the record alone under ten', () => {
    expect(rateWords(underTen)).toEqual({ record: record(3, 4), percent: null, range: null })
  })

  it('reads the anecdotal flag, not the count', () => {
    // Twelve matches flagged anecdotal: the record alone. 7 of 12 is 58.3%.
    expect(rateWords({ ...rate(7, 12, 7 / 12, 0.3, 0.8), anecdotal: true })).toEqual({
      record: record(7, 5),
      percent: null,
      range: null,
    })
    // Eight matches not flagged: a percent and a range. 5 of 8 is 62.5%, rounded up to 63.
    expect(rateWords({ ...rate(5, 8, 5 / 8, 0.3, 0.9), anecdotal: false })).toEqual({
      record: record(5, 3),
      percent: '63%',
      range: range(30, 90),
    })
  })

  it('is nothing with no match', () => {
    expect(rateWords(none)).toEqual({ record: null, percent: null, range: null })
  })
})

describe('rateTile', () => {
  it('shows the percent over the record and the range', () => {
    expect(rateTile('Matches', tenOrMore, t)).toEqual({
      label: 'Matches',
      value: '45%',
      detail: `${record(174, 211)} · ${range(40, 50)}`,
    })
  })

  it('shows the record, muted, over the "too few" line under ten', () => {
    expect(rateTile('Matches', underTen, t)).toEqual({
      label: 'Matches',
      value: record(3, 4),
      detail: `too few for a rate, under 10${NBSP}matches`,
      muted: true,
    })
    expect(rateTile('On the draw', underTen, t, 'games')).toEqual({
      label: 'On the draw',
      value: record(3, 4),
      detail: `too few for a rate, under 10${NBSP}games`,
      muted: true,
    })
  })

  it('shows a dash over "None played" with no match', () => {
    expect(rateTile('Game 1', none, t)).toEqual({ label: 'Game 1', value: '—', detail: 'None played' })
  })
})

describe('overallTiles', () => {
  it('labels the six rates in order', () => {
    const tiles = overallTiles({
      overall: tenOrMore,
      overall_games: tenOrMore,
      g1: tenOrMore,
      post_board: tenOrMore,
      on_play: tenOrMore,
      on_draw: tenOrMore,
    }, t)
    expect(tiles.map((t) => t.label)).toEqual([
      'Matches',
      'Games',
      'Game 1',
      'Games 2–3',
      'On the play',
      'On the draw',
    ])
  })
})

describe('coachDay and profileCaption', () => {
  // Noon UTC on Sep 29 2026; the zone is New York (vitest.config.ts).
  const now = Date.parse('2026-09-29T12:00:00Z')

  it('reads a bare date from its own parts, and a timestamp in the zone', () => {
    expect(coachDay('2026-08-11', now)).toBe('Aug 11')
    // A bare as_of is the log's own clock: 02:00 on the 12th stays the 12th.
    expect(coachDay('2026-08-12T02:00:00', now)).toBe('Aug 12')
    // 02:00 UTC on the 12th is 22:00 on the 11th in New York.
    expect(coachDay('2026-08-12T02:00:00Z', now)).toBe('Aug 11')
    expect(coachDay('not a day', now)).toBeNull()
    expect(coachDay(null, now)).toBeNull()
  })

  it('counts the matches to the day', () => {
    expect(profileCaption(385, '2026-08-11T18:00:00', now, t)).toBe('385 finished constructed matches, to Aug 11.')
    expect(profileCaption(1234, '2026-08-11T18:00:00', now, t)).toBe('1,234 finished constructed matches, to Aug 11.')
  })

  it('says one match in the singular, and leaves out a day it does not have', () => {
    expect(profileCaption(1, '2026-08-11T18:00:00', now, t)).toBe('1 finished constructed match, to Aug 11.')
    expect(profileCaption(385, null, now, t)).toBe('385 finished constructed matches.')
  })
})

describe('deckName and deckPatternsSummary', () => {
  it('names a deck with no name typed "Unnamed deck"', () => {
    expect(deckName('Deck one', t)).toBe('Deck one')
    expect(deckName('  ', t)).toBe('Unnamed deck')
  })

  it('counts the patterns, one in the singular', () => {
    expect(deckPatternsSummary('Deck one', 3, t)).toBe(`Deck one, 3${NBSP}patterns`)
    expect(deckPatternsSummary('Deck two', 1, t)).toBe(`Deck two, 1${NBSP}pattern`)
    expect(deckPatternsSummary('', 2, t)).toBe(`Unnamed deck, 2${NBSP}patterns`)
  })
})

describe('roleRates and mulliganRates', () => {
  it("puts the roles in the table's order and words, and a role it does not know last, as stored", () => {
    // Stored in another order, with no control and a role the table lacks.
    const rows = roleRates({ tempo: underTen, unknown: underTen, mixed: underTen, beatdown: underTen }, t)
    expect(rows.map((r) => [r.key, r.label])).toEqual([
      ['beatdown', 'Beatdown'],
      ['mixed', 'Mixed'],
      ['unknown', 'No role found'],
      ['tempo', 'tempo'],
    ])
  })

  it('puts kept seven before mulliganed', () => {
    const rows = mulliganRates({ mulliganed: underTen, kept_seven: tenOrMore }, t)
    expect(rows.map((r) => r.label)).toEqual(['Kept seven', 'Mulliganed'])
  })
})

describe('variantsWords', () => {
  it('is null for one label', () => {
    expect(variantsWords([['Red Aggro', 12]], t)).toBeNull()
  })

  it('names three labels with their counts, no more', () => {
    expect(
      variantsWords([
        ['Red Aggro', 43],
        ['Mono Red', 4],
        ['Red Deck', 2],
      ], t),
    ).toBe('Red Aggro 43, Mono Red 4, Red Deck 2')
  })

  it('names the three most met of four, and one more', () => {
    expect(
      variantsWords([
        ['Red Aggro', 43],
        ['Mono Red', 4],
        ['Red Deck', 2],
        ['Burn', 1],
      ], t),
    ).toBe(`Red Aggro 43, Mono Red 4, Red Deck 2 and 1${NBSP}more`)
  })

  it('names the three most met of seven, and four more', () => {
    expect(
      variantsWords([
        ['Red Aggro', 1043],
        ['Mono Red', 4],
        ['Red Deck', 2],
        ['Burn', 1],
        ['Red One', 1],
        ['Red Two', 1],
        ['Red Three', 1],
      ], t),
    ).toBe(`Red Aggro 1,043, Mono Red 4, Red Deck 2 and 4${NBSP}more`)
  })
})

describe('listsWords', () => {
  it('counts the lists, one in the singular', () => {
    expect(listsWords(338, t)).toBe(`338${NBSP}lists`)
    expect(listsWords(1200, t)).toBe(`1,200${NBSP}lists`)
    expect(listsWords(1, t)).toBe(`1${NBSP}list`)
  })
})

describe('patternDirection', () => {
  const side = (value: number | null) => ({ rate: value })

  it('is better with it when the rate with it is higher', () => {
    // 57% with it, 27% without: 30 points apart.
    expect(patternDirection({ present: side(0.57), absent: side(0.27), gap: 0.3 }, t)).toBe('30 points better with it')
  })

  it('is worse with it when the rate with it is lower', () => {
    expect(patternDirection({ present: side(0.3), absent: side(0.49), gap: 0.19 }, t)).toBe('19 points worse with it')
    expect(patternDirection({ present: side(0.49), absent: side(0.502), gap: 0.012 }, t)).toBe('1 point worse with it')
  })

  it('is no difference when the points round to 0, whatever the way', () => {
    expect(patternDirection({ present: side(0.502), absent: side(0.498), gap: 0.004 }, t)).toBe('No difference')
  })
})

describe('turningTiles', () => {
  const cell = (stage: string, severity: string, games: number) => ({ stage, severity, games }) as TurningBucketOut

  it('sums each stage, counts its decisive games, and sums every cell', () => {
    const { lost, tiles } = turningTiles([
      cell('early', 'decisive', 4),
      cell('early', 'notice', 10),
      cell('mid', 'decisive', 0),
      cell('mid', 'notice', 20),
      cell('late', 'decisive', 1),
      cell('late', 'notice', 5),
    ], t)
    // 4 + 10 + 0 + 20 + 1 + 5 = 40.
    expect(lost).toBe(40)
    expect(tiles).toEqual([
      { label: 'Early, turns 1 to 3', value: '14', detail: '4 of them decisive' },
      { label: 'Mid, turns 4 to 6', value: '20', detail: 'None of them decisive' },
      { label: 'Late, turn 7 on', value: '6', detail: '1 of them decisive' },
    ])
  })
})

describe('turningSubtitle', () => {
  it('counts the lost games, over 999 with a comma', () => {
    expect(turningSubtitle(359, t)).toBe(
      'The turn of yours on which a lost game first slipped, over the 359 lost games where one was found.',
    )
    expect(turningSubtitle(1200, t)).toBe(
      'The turn of yours on which a lost game first slipped, over the 1,200 lost games where one was found.',
    )
  })

  it('says one lost game in the singular', () => {
    expect(turningSubtitle(1, t)).toBe(
      'The turn of yours on which a lost game first slipped, over the 1 lost game where one was found.',
    )
  })
})
