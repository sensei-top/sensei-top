import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import type { CardVerdictOut, ListDiffOut, MetaPresence } from '../api'
import {
  expectedOptions,
  MAIN_SHARE,
  splitOptions,
  freshnessSentence,
  markdownFileName,
  prefillText,
  previewKey,
  readInputs,
  storageKey,
  writeInputs,
  type InputStorage,
} from './rcq'

const t = translator('en')

const now = Date.parse('2026-10-03T12:00:00Z')

const row = (card: string, yours: number, board: 'main' | 'side'): CardVerdictOut => ({
  card,
  yours,
  board,
  consensus_copies: null,
  consensus_share: null,
  recommended: yours,
  verdict: 'correct',
})

const diff = (maindeck: CardVerdictOut[], sideboard: CardVerdictOut[]): ListDiffOut => ({
  archetype_key: 'archetype:test',
  archetype_name: 'Test Deck',
  winning_decks: 0,
  min_wins: 0,
  maindeck,
  sideboard,
  duplicate_warnings: [],
})

describe('prefillText', () => {
  it('writes Arena export, the sideboard after a blank line', () => {
    const text = prefillText(
      diff([row('Island', 20, 'main'), row('Opt', 4, 'main')], [row('Negate', 2, 'side')]),
    )
    expect(text).toBe('Deck\n20 Island\n4 Opt\n\nSideboard\n2 Negate')
  })

  it("leaves out a card only the field runs", () => {
    const text = prefillText(diff([row('Island', 20, 'main'), row('Shock', 0, 'main')], [row('Duress', 0, 'side')]))
    expect(text).toBe('Deck\n20 Island')
  })

  it('is empty with no list diff', () => {
    expect(prefillText(null)).toBe('')
    expect(prefillText(undefined)).toBe('')
    expect(prefillText(diff([], []))).toBe('')
  })
})

describe('previewKey', () => {
  it('asks the same question for the same chips in another order', () => {
    const a = previewKey({ decklist: '4 Opt', expected: ['b', 'a'], own: null })
    const b = previewKey({ decklist: '4 Opt', expected: ['a', 'b', 'a'], own: null })
    expect(a).toBe(b)
  })

  it('ignores whitespace around the list but not inside it', () => {
    const a = previewKey({ decklist: '  4 Opt\n', expected: [], own: null })
    expect(a).toBe(previewKey({ decklist: '4 Opt', expected: [], own: null }))
    expect(a).not.toBe(previewKey({ decklist: '4  Opt', expected: [], own: null }))
  })

  it('tells a chosen archetype from none', () => {
    expect(previewKey({ decklist: '4 Opt', expected: [], own: 'k' })).not.toBe(
      previewKey({ decklist: '4 Opt', expected: [], own: null }),
    )
  })
})

describe('freshnessSentence', () => {
  it('names the newest day and how long since the fetch', () => {
    expect(
      freshnessSentence({ source: 'mtgo.com', newest_event: '2026-10-03', fetched_at: '2026-10-03T10:00:00Z' }, now, t),
    ).toBe('mtgo.com: newest event Oct 3, fetched 2h ago')
  })

  it('reads a timestamp as its day', () => {
    expect(
      freshnessSentence({ source: 'x', newest_event: '2026-10-02T15:00:00Z', fetched_at: '2026-10-01T12:00:00Z' }, now, t),
    ).toBe('x: newest event Oct 2, fetched 2d ago')
  })

  it('says when there is no event and no fetch', () => {
    expect(freshnessSentence({ source: 'x', newest_event: null, fetched_at: null }, now, t)).toBe(
      'x: no event yet, never fetched',
    )
  })

  it('shows a day it cannot read as sent', () => {
    expect(freshnessSentence({ source: 'x', newest_event: 'soon', fetched_at: null }, now, t)).toBe(
      'x: newest event soon, never fetched',
    )
  })
})

const presence = (archetype_key: string, label: string, tier: string, decks: number, share: number): MetaPresence => ({
  archetype_key,
  label,
  colors: null,
  tier,
  decks,
  share,
})

describe('expectedOptions', () => {
  it('reads every share at the tier with the most decks, most played first', () => {
    const { tier, options } = expectedOptions([
      presence('a', 'Alpha', 'A', 9, 0.9),
      presence('a', 'Alpha', 'B', 10, 0.2),
      presence('b', 'Beta', 'B', 30, 0.6),
      presence('c', 'Gamma', 'B', 10, 0.2),
    ])
    expect(tier).toBe('B')
    expect(options).toEqual([
      { key: 'b', label: 'Beta', share: 0.6 },
      { key: 'a', label: 'Alpha', share: 0.2 },
      { key: 'c', label: 'Gamma', share: 0.2 },
    ])
  })

  it('puts an archetype that tier never saw after, with no share', () => {
    const { options } = expectedOptions([
      presence('a', 'Alpha', 'B', 20, 1),
      presence('z', 'Zeta', 'A', 3, 1),
    ])
    expect(options.map((option) => [option.key, option.share])).toEqual([
      ['a', 1],
      ['z', null],
    ])
  })

  it('sums every label of one key at the tier, named by the key', () => {
    const { options } = expectedOptions([
      presence('Control', 'Azorius Control', 'B', 21, 0.3),
      presence('Control', 'Jeskai Control', 'B', 21, 0.3),
      presence('UBMidrange', 'Dimir Midrange', 'B', 28, 0.4),
    ])
    expect(options).toEqual([
      { key: 'Control', label: 'Control', share: 0.6 },
      { key: 'UBMidrange', label: 'Dimir Midrange', share: 0.4 },
    ])
  })

  it('spaces a name run together', () => {
    expect(expectedOptions([presence('a', 'IzzetProwess', 'B', 1, 1)]).options[0].label).toBe('Izzet Prowess')
  })

  it('offers nothing for an empty field', () => {
    expect(expectedOptions([])).toEqual({ tier: null, options: [] })
  })
})

describe('splitOptions', () => {
  it('keeps a share under MAIN_SHARE, and no share, behind Other', () => {
    const { main, other } = splitOptions([
      { key: 'a', label: 'A', share: 0.5 },
      { key: 'b', label: 'B', share: MAIN_SHARE },
      { key: 'c', label: 'C', share: 0.01 },
      { key: 'd', label: 'D', share: null },
    ])
    expect(main.map((option) => option.key)).toEqual(['a', 'b'])
    expect(other.map((option) => option.key)).toEqual(['c', 'd'])
  })
})

const memory = (): InputStorage & { items: Map<string, string> } => {
  const items = new Map<string, string>()
  return {
    items,
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => void items.set(key, value),
  }
}

describe('readInputs and writeInputs', () => {
  it('keep one deck apart from another', () => {
    const storage = memory()
    writeInputs(storage, 'guid:one', { decklist: '4 Opt', expected: ['k'], own: null })
    expect(readInputs(storage, 'guid:one')).toEqual({ decklist: '4 Opt', expected: ['k'], own: null })
    expect(readInputs(storage, 'guid:two')).toBeNull()
  })

  it('read nothing from what is not inputs', () => {
    const storage = memory()
    storage.items.set(storageKey('d'), 'not json')
    expect(readInputs(storage, 'd')).toBeNull()
    storage.items.set(storageKey('d'), JSON.stringify({ expected: [] }))
    expect(readInputs(storage, 'd')).toBeNull()
  })

  it('drop a value of the wrong kind', () => {
    const storage = memory()
    storage.items.set(storageKey('d'), JSON.stringify({ decklist: 'x', expected: ['a', 3], own: 7 }))
    expect(readInputs(storage, 'd')).toEqual({ decklist: 'x', expected: ['a'], own: null })
  })

  it('survive a storage that refuses', () => {
    const refusing: InputStorage = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
    }
    expect(readInputs(refusing, 'd')).toBeNull()
    expect(() => writeInputs(refusing, 'd', { decklist: '', expected: [], own: null })).not.toThrow()
    expect(readInputs(null, 'd')).toBeNull()
  })
})

describe('markdownFileName', () => {
  it('names the file by the day it was written', () => {
    expect(markdownFileName('2026-10-03T11:20:00')).toBe('rcq-guide-2026-10-03.md')
  })

  it('falls back with no day', () => {
    expect(markdownFileName(null)).toBe('rcq-guide.md')
    expect(markdownFileName('later')).toBe('rcq-guide.md')
  })
})
