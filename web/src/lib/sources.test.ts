import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import type { MetaSourceHold } from '../api'
import { type HoldSource, holdLine } from './sources'

const t = translator('en')

const NOW = new Date('2026-10-05T13:00:00Z')

const hold = (fields: Partial<MetaSourceHold>): MetaSourceHold => ({
  status: 'paused',
  http_status: 403,
  since: '2026-10-05T09:00:00Z',
  not_before: null,
  ...fields,
})

const CASES: [HoldSource, MetaSourceHold, string][] = [
  [
    'mtgo',
    { status: 'waiting', http_status: 429, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T17:10:00Z' },
    "mtgo.com — waiting: the site asked for a pause (HTTP 429). The next fetch is after 17:10 UTC.",
  ],
  [
    'mtgo',
    { status: 'waiting', http_status: 503, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T17:10:00Z' },
    "mtgo.com — waiting: the site answered that it is unavailable (HTTP 503). The next fetch is after 17:10 UTC.",
  ],
  [
    'mtgo',
    { status: 'paused', http_status: 403, since: '2026-10-05T09:00:00Z', not_before: null },
    "mtgo.com — paused since 2026-10-05: the site refused the fetch (HTTP 403). Nothing more is read until you run `sensei-top meta`; re-read Daybreak's Terms of Service before you do.",
  ],
  [
    'mtgo',
    { status: 'paused', http_status: 401, since: '2026-10-05T09:00:00Z', not_before: null },
    "mtgo.com — paused since 2026-10-05: the site asked for a login (HTTP 401). Nothing more is read until you run `sensei-top meta`; Sensei Top never logs in to mtgo.com — re-read Daybreak's Terms of Service before you do.",
  ],
  [
    'mtgo',
    { status: 'paused', http_status: 451, since: '2026-10-05T09:00:00Z', not_before: null },
    "mtgo.com — paused since 2026-10-05: the site refused the fetch for legal reasons (HTTP 451). Nothing more is read until you run `sensei-top meta`; open mtgo.com in your browser and read the notice there before you do.",
  ],
  [
    'mtgo',
    { status: 'paused', http_status: 429, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T17:10:00Z' },
    "mtgo.com — paused since 2026-10-05: the site asked for a pause twice in a row (HTTP 429). Nothing more is read until you run `sensei-top meta`, and not before 17:10 UTC.",
  ],
  [
    'mtgo',
    { status: 'paused', http_status: 429, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T12:00:00Z' },
    "mtgo.com — paused since 2026-10-05: the site asked for a pause twice in a row (HTTP 429). Nothing more is read until you run `sensei-top meta`.",
  ],
  [
    'mtgo',
    { status: 'paused', http_status: 503, since: '2026-10-05T09:00:00Z', not_before: null },
    "mtgo.com — paused since 2026-10-05: the site has answered that it is unavailable (HTTP 503) for a whole day. Nothing more is read until you run `sensei-top meta`; check that mtgo.com opens in your browser before you do.",
  ],
  [
    'mtgo',
    { status: 'paused', http_status: 503, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T17:10:00Z' },
    "mtgo.com — paused since 2026-10-05: the site has answered that it is unavailable (HTTP 503) for a whole day. Nothing more is read until you run `sensei-top meta`, and not before 17:10 UTC; check that mtgo.com opens in your browser before you do.",
  ],
  [
    'topdeck',
    { status: 'waiting', http_status: 429, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T14:02:30Z' },
    "TopDeck.gg — waiting: the site asked for a pause (HTTP 429). The next fetch is after 14:03 UTC.",
  ],
  [
    'topdeck',
    { status: 'paused', http_status: 401, since: '2026-10-05T09:00:00Z', not_before: null },
    "TopDeck.gg — paused since 2026-10-05: the key was not accepted (HTTP 401). Nothing more is read until you run `sensei-top meta`; set a working key with `sensei-top config --set-topdeck-key KEY` first.",
  ],
  [
    'topdeck',
    { status: 'paused', http_status: 403, since: '2026-10-05T09:00:00Z', not_before: null },
    "TopDeck.gg — paused since 2026-10-05: the site refused the fetch (HTTP 403). Nothing more is read until you run `sensei-top meta`; re-read TopDeck.gg's API terms before you do.",
  ],
  [
    'topdeck',
    { status: 'paused', http_status: 451, since: '2026-10-05T09:00:00Z', not_before: null },
    "TopDeck.gg — paused since 2026-10-05: the site refused the fetch for legal reasons (HTTP 451). Nothing more is read until you run `sensei-top meta`; open topdeck.gg in your browser and read the notice there before you do.",
  ],
  [
    'topdeck',
    { status: 'paused', http_status: 429, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T14:03:10Z' },
    "TopDeck.gg — paused since 2026-10-05: the site asked for a pause twice in a row (HTTP 429). Nothing more is read until you run `sensei-top meta`, and not before 14:04 UTC.",
  ],
  [
    'topdeck',
    { status: 'paused', http_status: 429, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T12:00:00Z' },
    "TopDeck.gg — paused since 2026-10-05: the site asked for a pause twice in a row (HTTP 429). Nothing more is read until you run `sensei-top meta`.",
  ],
  [
    'mtgo',
    { status: 'paused', http_status: 403, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T17:10:00Z' },
    "mtgo.com — paused since 2026-10-05: the site refused the fetch (HTTP 403). Nothing more is read until you run `sensei-top meta`, and not before 17:10 UTC; re-read Daybreak's Terms of Service before you do.",
  ],
  [
    'mtgo',
    { status: 'paused', http_status: 401, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T17:10:00Z' },
    "mtgo.com — paused since 2026-10-05: the site asked for a login (HTTP 401). Nothing more is read until you run `sensei-top meta`, and not before 17:10 UTC; Sensei Top never logs in to mtgo.com — re-read Daybreak's Terms of Service before you do.",
  ],
  [
    'mtgo',
    { status: 'paused', http_status: 451, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T17:10:00Z' },
    "mtgo.com — paused since 2026-10-05: the site refused the fetch for legal reasons (HTTP 451). Nothing more is read until you run `sensei-top meta`, and not before 17:10 UTC; open mtgo.com in your browser and read the notice there before you do.",
  ],
  [
    'topdeck',
    { status: 'paused', http_status: 401, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T14:03:10Z' },
    "TopDeck.gg — paused since 2026-10-05: the key was not accepted (HTTP 401). Nothing more is read until you run `sensei-top meta`, and not before 14:04 UTC; set a working key with `sensei-top config --set-topdeck-key KEY` first.",
  ],
  [
    'topdeck',
    { status: 'paused', http_status: 403, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T14:03:10Z' },
    "TopDeck.gg — paused since 2026-10-05: the site refused the fetch (HTTP 403). Nothing more is read until you run `sensei-top meta`, and not before 14:04 UTC; re-read TopDeck.gg's API terms before you do.",
  ],
  [
    'topdeck',
    { status: 'paused', http_status: 451, since: '2026-10-05T09:00:00Z', not_before: '2026-10-05T14:03:10Z' },
    "TopDeck.gg — paused since 2026-10-05: the site refused the fetch for legal reasons (HTTP 451). Nothing more is read until you run `sensei-top meta`, and not before 14:04 UTC; open topdeck.gg in your browser and read the notice there before you do.",
  ],
  [
    'mtgo',
    { status: 'waiting', http_status: 429, since: '2026-10-05T09:00:00Z', not_before: '2026-10-07T17:10:00Z' },
    "mtgo.com — waiting: the site asked for a pause (HTTP 429). The next fetch is after 2026-10-07 17:10 UTC.",
  ],
]

describe('holdLine', () => {
  it.each(CASES)('says the catalog line for %s %j', (source, h, line) => {
    expect(holdLine(source, h, NOW, t)).toBe(line)
  })

  it('leaves "and not before" out of a paused line whose not-before is null or has passed', () => {
    const bare = holdLine('mtgo', hold({ http_status: 503, not_before: null }), NOW, t)
    expect(bare).not.toContain('not before')
    const passed = holdLine('mtgo', hold({ http_status: 429, not_before: '2026-10-05T12:00:00Z' }), NOW, t)
    expect(passed).not.toContain('not before')
  })

  it('says nothing without a hold', () => {
    expect(holdLine('mtgo', null, NOW, t)).toBeNull()
    expect(holdLine('mtgo', undefined, NOW, t)).toBeNull()
  })

  it('says nothing for a wait whose not-before has passed or is not stored', () => {
    const passed = hold({ status: 'waiting', http_status: 429, not_before: '2026-10-05T12:59:00Z' })
    expect(holdLine('mtgo', passed, NOW, t)).toBeNull()
    expect(holdLine('mtgo', hold({ ...passed, not_before: null }), NOW, t)).toBeNull()
    expect(holdLine('mtgo', hold({ ...passed, not_before: '2026-10-05T13:00:00Z' }), NOW, t)).toBeNull()
  })

  it('says nothing for a cause it has no words for', () => {
    expect(holdLine('mtgo', hold({ http_status: 500 }), NOW, t)).toBeNull()
    expect(holdLine('topdeck', hold({ status: 'waiting', http_status: 503, not_before: '2026-10-05T17:10:00Z' }), NOW, t)).toBeNull()
  })

  it('chooses the line by the hold\'s cause', () => {
    const line = holdLine('mtgo', hold({ http_status: 451 }), NOW, t)
    expect(line).toContain('(HTTP 451)')
  })

  it('rounds a time up to the minute', () => {
    const line = holdLine('mtgo', hold({ status: 'waiting', http_status: 429, not_before: '2026-10-05T17:10:01Z' }), NOW, t)
    expect(line).toContain('after 17:11 UTC.')
  })

  it('dates a time that rounds up into another UTC date', () => {
    const late = new Date('2026-10-05T23:30:00Z')
    const line = holdLine('mtgo', hold({ status: 'waiting', http_status: 429, not_before: '2026-10-05T23:59:30Z' }), late, t)
    expect(line).toContain('after 2026-10-06 00:00 UTC.')
  })

  it('puts a paused line\'s not-before in the dated form on another date', () => {
    const line = holdLine('mtgo', hold({ http_status: 403, not_before: '2026-10-07T17:10:00Z' }), NOW, t)
    expect(line).toContain('and not before 2026-10-07 17:10 UTC;')
  })
})
