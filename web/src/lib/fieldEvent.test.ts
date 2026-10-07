import { describe, expect, it } from 'vitest'
import type { MetaEventDetail } from '../api'
import { groupHeading, kindWords, ordinal, readLine, sideboardHeading, sourceLines, standing } from './fieldEvent'

const card = { count: 1, name: 'Island' }
const listed = [{ placement: 1, record: null, archetype: null, main: [{ type: 'Land', count: 1, cards: [card] }], side: [] }]
const unlisted = [{ placement: 1, record: null, archetype: null, main: [], side: [] }]

type ReadFields = Pick<MetaEventDetail, 'decks' | 'lists_read_at' | 'empty_read_at' | 'empty_read_kind'>
const read = (fields: Partial<ReadFields>): ReadFields => ({
  decks: listed,
  lists_read_at: null,
  empty_read_at: null,
  empty_read_kind: null,
  ...fields,
})

const text = (line: { text: string }[]) => line.map((part) => part.text).join('')

describe('sourceLines', () => {
  it('credits mtgo.com and links the event page', () => {
    const lines = sourceLines({ source: 'MTGO', uri: 'https://www.mtgo.com/decklist/x' })
    expect(lines.map(text)).toEqual(['Results from mtgo.com'])
    expect(lines[0][1]).toEqual({ text: 'mtgo.com', href: 'https://www.mtgo.com/decklist/x' })
  })

  it('credits melee.gg and links the event page', () => {
    const lines = sourceLines({ source: 'MTGmelee', uri: 'https://melee.gg/Tournament/View/1' })
    expect(lines.map(text)).toEqual(['Results from melee.gg'])
    expect(lines[0][1]).toEqual({ text: 'melee.gg', href: 'https://melee.gg/Tournament/View/1' })
  })

  it('credits TopDeck.gg, linked to its home, then links the event', () => {
    const uri = 'https://topdeck.gg/event/abc123'
    const lines = sourceLines({ source: 'Topdeck', uri })
    expect(lines.map(text)).toEqual(['Data provided by TopDeck.gg.', 'This event on TopDeck.gg'])
    expect(lines[0][1]).toEqual({ text: 'TopDeck.gg', href: 'https://topdeck.gg' })
    expect(lines[1]).toEqual([{ text: 'This event on TopDeck.gg', href: uri }])
  })

  it('draws no event link for a TopDeck event without an address', () => {
    expect(sourceLines({ source: 'Topdeck', uri: null }).map(text)).toEqual(['Data provided by TopDeck.gg.'])
  })

  it('says nothing for a source it has no line for', () => {
    expect(sourceLines({ source: 'Other', uri: null })).toEqual([])
  })
})

describe('readLine', () => {
  it('says an empty read of an event whose lists were read on a known date', () => {
    const line = read({ lists_read_at: '2026-10-03T08:00:00Z', empty_read_at: '2026-10-05T17:10:00Z', empty_read_kind: 'empty' })
    expect(readLine(line)).toBe('Decklists as read on 2026-10-03; none were returned when this event was last read, on 2026-10-05.')
  })

  it('says a gone page of an event whose lists were read on a known date', () => {
    const line = read({ lists_read_at: '2026-10-03T08:00:00Z', empty_read_at: '2026-10-05T17:10:00Z', empty_read_kind: 'gone' })
    expect(readLine(line)).toBe("Decklists as read on 2026-10-03; the event's page was not found when it was last read, on 2026-10-05.")
  })

  it('says an empty read when the lists were read on no recorded date', () => {
    expect(readLine(read({ empty_read_at: '2026-10-07T01:00:00Z', empty_read_kind: 'empty' }))).toBe(
      'The decklists shown were read on a date that was not recorded; none were returned when this event was last read, on 2026-10-07.',
    )
  })

  it('says a gone page when the lists were read on no recorded date', () => {
    expect(readLine(read({ empty_read_at: '2026-10-07T01:00:00Z', empty_read_kind: 'gone' }))).toBe(
      "The decklists shown were read on a date that was not recorded; the event's page was not found when it was last read, on 2026-10-07.",
    )
  })

  it('says standings only with the read date when one is recorded', () => {
    expect(readLine(read({ decks: unlisted, empty_read_at: '2026-10-05T17:10:00Z', empty_read_kind: 'empty' }))).toBe(
      'Standings only: no decklists were returned for this event when it was last read, on 2026-10-05.',
    )
    expect(readLine(read({ decks: unlisted, empty_read_at: '2026-10-05T17:10:00Z', empty_read_kind: 'gone' }))).toBe(
      'Standings only: no decklists were returned for this event when it was last read, on 2026-10-05.',
    )
  })

  it('says standings only without a date when none is recorded', () => {
    expect(readLine(read({ decks: unlisted }))).toBe('Standings only: no decklists were returned for this event when it was last read.')
  })

  it('says nothing of an event with lists and no empty read', () => {
    expect(readLine(read({ lists_read_at: '2026-10-03T08:00:00Z' }))).toBeNull()
    expect(readLine(read({}))).toBeNull()
  })
})

describe('ordinal', () => {
  it.each([
    [1, '1st'],
    [2, '2nd'],
    [3, '3rd'],
    [4, '4th'],
    [11, '11th'],
    [12, '12th'],
    [13, '13th'],
    [21, '21st'],
    [22, '22nd'],
    [23, '23rd'],
    [101, '101st'],
    [111, '111th'],
  ])('writes %i as %s', (n, expected) => {
    expect(ordinal(n)).toBe(expected)
  })
})

describe('standing', () => {
  it('joins the placement and the record', () => {
    expect(standing({ placement: 1, record: { wins: 6, losses: 1, draws: 0 } })).toBe('1st · 6–1')
  })

  it('adds draws only when there are some', () => {
    expect(standing({ placement: 9, record: { wins: 5, losses: 2, draws: 1 } })).toBe('9th · 5–2–1')
  })

  it('shows the part it knows, or nothing', () => {
    expect(standing({ placement: 2, record: null })).toBe('2nd')
    expect(standing({ placement: null, record: { wins: 5, losses: 0, draws: 0 } })).toBe('5–0')
    expect(standing({ placement: null, record: null })).toBeNull()
  })
})

describe('kindWords', () => {
  it('names each tier and nothing else', () => {
    expect(kindWords('A')).toBe('paper tournament of 64+ players')
    expect(kindWords('B')).toBe('MTGO challenge')
    expect(kindWords('C')).toBe('MTGO league')
    expect(kindWords('D')).toBe('paper tournament under 64 players')
    expect(kindWords(null)).toBeNull()
    expect(kindWords('E')).toBeNull()
  })
})

describe('headings', () => {
  it('pluralises each type and counts copies', () => {
    expect(groupHeading('Creature', 12)).toBe('Creatures (12)')
    expect(groupHeading('Planeswalker', 2)).toBe('Planeswalkers (2)')
    expect(groupHeading('Battle', 1)).toBe('Battles (1)')
    expect(groupHeading('Instant', 8)).toBe('Instants (8)')
    expect(groupHeading('Sorcery', 4)).toBe('Sorceries (4)')
    expect(groupHeading('Artifact', 3)).toBe('Artifacts (3)')
    expect(groupHeading('Enchantment', 2)).toBe('Enchantments (2)')
    expect(groupHeading('Land', 24)).toBe('Lands (24)')
  })

  it('names the null group without a plural', () => {
    expect(groupHeading(null, 3)).toBe('Unknown type (3)')
  })

  it('counts the sideboard in copies, and has no heading when empty', () => {
    expect(sideboardHeading([{ count: 3, name: 'Island' }, { count: 2, name: 'Mountain' }])).toBe('Sideboard (5)')
    expect(sideboardHeading([])).toBeNull()
  })
})
