import { describe, expect, it } from 'vitest'
import type { MetaEventDetail } from '../api'
import { translator, type TFunction } from '../i18n'
import { groupHeading, kindWords, ordinal, readLine, sideboardHeading, sourceLines, standing } from './fieldEvent'

const card = { count: 1, name: 'Island' }
const listed = [{ placement: 1, record: null, archetype: null, main: [{ type: 'Land', count: 1, cards: [card] }], side: [] }]
const unlisted = [{ placement: 1, record: null, archetype: null, main: [], side: [] }]

type ReadFields = Pick<MetaEventDetail, 'decks' | 'lists_read_at' | 'empty_read_at' | 'empty_read_kind'>
const t = translator('en')

const read = (fields: Partial<ReadFields>): ReadFields => ({
  decks: listed,
  lists_read_at: null,
  empty_read_at: null,
  empty_read_kind: null,
  ...fields,
})

describe('sourceLines', () => {
  it('credits mtgo.com and links the event page', () => {
    const uri = 'https://www.mtgo.com/decklist/x'
    expect(sourceLines({ source: 'MTGO', uri })).toEqual([{ sentence: 'results', site: 'mtgo.com', href: uri }])
  })

  it('credits melee.gg and links the event page', () => {
    const uri = 'https://melee.gg/Tournament/View/1'
    expect(sourceLines({ source: 'MTGmelee', uri })).toEqual([{ sentence: 'results', site: 'melee.gg', href: uri }])
  })

  it('credits TopDeck.gg, linked to its home, then links the event', () => {
    const uri = 'https://topdeck.gg/event/abc123'
    expect(sourceLines({ source: 'Topdeck', uri })).toEqual([
      { sentence: 'topdeck', site: 'TopDeck.gg', href: 'https://topdeck.gg' },
      { sentence: 'topdeckEvent', site: 'TopDeck.gg', href: uri },
    ])
  })

  it('draws no event link for a TopDeck event without an address', () => {
    expect(sourceLines({ source: 'Topdeck', uri: null }).map((line) => line.sentence)).toEqual(['topdeck'])
  })

  it('says nothing for a source it has no line for', () => {
    expect(sourceLines({ source: 'Other', uri: null })).toEqual([])
  })

  it('writes each sentence around its link', () => {
    expect(t('field.event.sourceTopdeck', { site: 'TopDeck.gg' })).toBe('Data provided by <site>TopDeck.gg</site>.')
    expect(t('field.event.sourceTopdeckEvent', { site: 'TopDeck.gg' })).toBe('<site>This event on TopDeck.gg</site>')
    expect(t('field.event.sourceResults', { site: 'mtgo.com' })).toBe('Results from <site>mtgo.com</site>')
  })
})

describe('readLine', () => {
  it('says an empty read of an event whose lists were read on a known date', () => {
    const line = read({ lists_read_at: '2026-10-03T08:00:00Z', empty_read_at: '2026-10-05T17:10:00Z', empty_read_kind: 'empty' })
    expect(readLine(line, t)).toBe('Decklists as read on 2026-10-03; none were returned when this event was last read, on 2026-10-05.')
  })

  it('says a gone page of an event whose lists were read on a known date', () => {
    const line = read({ lists_read_at: '2026-10-03T08:00:00Z', empty_read_at: '2026-10-05T17:10:00Z', empty_read_kind: 'gone' })
    expect(readLine(line, t)).toBe("Decklists as read on 2026-10-03; the event's page was not found when it was last read, on 2026-10-05.")
  })

  it('says an empty read when the lists were read on no recorded date', () => {
    expect(readLine(read({ empty_read_at: '2026-10-07T01:00:00Z', empty_read_kind: 'empty' }), t)).toBe(
      'The decklists shown were read on a date that was not recorded; none were returned when this event was last read, on 2026-10-07.',
    )
  })

  it('says a gone page when the lists were read on no recorded date', () => {
    expect(readLine(read({ empty_read_at: '2026-10-07T01:00:00Z', empty_read_kind: 'gone' }), t)).toBe(
      "The decklists shown were read on a date that was not recorded; the event's page was not found when it was last read, on 2026-10-07.",
    )
  })

  it('says standings only with the read date when one is recorded', () => {
    expect(readLine(read({ decks: unlisted, empty_read_at: '2026-10-05T17:10:00Z', empty_read_kind: 'empty' }), t)).toBe(
      'Standings only: no decklists were returned for this event when it was last read, on 2026-10-05.',
    )
    expect(readLine(read({ decks: unlisted, empty_read_at: '2026-10-05T17:10:00Z', empty_read_kind: 'gone' }), t)).toBe(
      'Standings only: no decklists were returned for this event when it was last read, on 2026-10-05.',
    )
  })

  it('says standings only without a date when none is recorded', () => {
    expect(readLine(read({ decks: unlisted }), t)).toBe('Standings only: no decklists were returned for this event when it was last read.')
  })

  it('says nothing of an event with lists and no empty read', () => {
    expect(readLine(read({ lists_read_at: '2026-10-03T08:00:00Z' }), t)).toBeNull()
    expect(readLine(read({}), t)).toBeNull()
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
    expect(ordinal(n, t)).toBe(expected)
  })

  it('takes its plural case from the t it is given, not the dashboard’s language', () => {
    // A t that answers in Portuguese, whose ordinal rule is `other` for every
    // number, while the dashboard's own language stays English (where 2 is `two`).
    const asked: string[] = []
    const portuguese = ((key: string, options: { returnDetails?: boolean }) => {
      asked.push(key)
      return options.returnDetails ? { res: key, usedLng: 'pt-BR' } : key
    }) as unknown as TFunction
    ordinal(2, portuguese)
    expect(asked.at(-1)).toBe('field.event.ordinal.other')
    expect(ordinal(2, t)).toBe('2nd')
  })
})

describe('standing', () => {
  it('joins the placement and the record', () => {
    expect(standing({ placement: 1, record: { wins: 6, losses: 1, draws: 0 } }, t)).toBe('1st · 6–1')
  })

  it('adds draws only when there are some', () => {
    expect(standing({ placement: 9, record: { wins: 5, losses: 2, draws: 1 } }, t)).toBe('9th · 5–2–1')
  })

  it('shows the part it knows, or nothing', () => {
    expect(standing({ placement: 2, record: null }, t)).toBe('2nd')
    expect(standing({ placement: null, record: { wins: 5, losses: 0, draws: 0 } }, t)).toBe('5–0')
    expect(standing({ placement: null, record: null }, t)).toBeNull()
  })
})

describe('kindWords', () => {
  it('names each tier and nothing else', () => {
    expect(kindWords('A', t)).toBe('paper tournament of 64+ players')
    expect(kindWords('B', t)).toBe('MTGO challenge')
    expect(kindWords('C', t)).toBe('MTGO league')
    expect(kindWords('D', t)).toBe('paper tournament under 64 players')
    expect(kindWords(null, t)).toBeNull()
    expect(kindWords('E', t)).toBeNull()
  })
})

describe('headings', () => {
  it('pluralises each type and counts copies', () => {
    expect(groupHeading('Creature', 12, t)).toBe('Creatures (12)')
    expect(groupHeading('Planeswalker', 2, t)).toBe('Planeswalkers (2)')
    expect(groupHeading('Battle', 1, t)).toBe('Battles (1)')
    expect(groupHeading('Instant', 8, t)).toBe('Instants (8)')
    expect(groupHeading('Sorcery', 4, t)).toBe('Sorceries (4)')
    expect(groupHeading('Artifact', 3, t)).toBe('Artifacts (3)')
    expect(groupHeading('Enchantment', 2, t)).toBe('Enchantments (2)')
    expect(groupHeading('Land', 24, t)).toBe('Lands (24)')
  })

  it('names the null group without a plural', () => {
    expect(groupHeading(null, 3, t)).toBe('Unknown type (3)')
  })

  it('counts the sideboard in copies, and has no heading when empty', () => {
    expect(sideboardHeading([{ count: 3, name: 'Island' }, { count: 2, name: 'Mountain' }], t)).toBe('Sideboard (5)')
    expect(sideboardHeading([], t)).toBeNull()
  })
})
