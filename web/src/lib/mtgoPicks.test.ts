import { describe, expect, it } from 'vitest'
import type { MtgoPickGroup } from '../api'
import { translator } from '../i18n'
import {
  chooseFormat,
  chooseList,
  initialGroupState,
  itemsToSend,
  matchesWord,
  resultWords,
  toggleRemoved,
} from './mtgoPicks'

const t = translator('en')

const match = (id: string) => ({ match_id: id, cards_seen: 10, scores: {} })
const list = (deck_id: string, format_prefill: 'Modern' | 'Pioneer' | null) => ({
  deck_id, name: deck_id, top: true, close_in: 0, format_prefill,
  format_prefill_source: null, card_names: [], missing: [],
})
const group = (proposed: string | null): MtgoPickGroup => ({
  key: 'k', fit: 'sure', proposed,
  lists: [list('a', 'Modern'), list('b', null)],
  matches: [match('m1'), match('m2'), match('m3')],
  first_started: null, last_started: null,
})

describe('itemsToSend', () => {
  it('sends one item per match with the proposed list and its pre-fill', () => {
    const g = group('a')
    expect(itemsToSend(g, initialGroupState(g))).toEqual([
      { match_id: 'm1', deck_id: 'a', format: 'Modern' },
      { match_id: 'm2', deck_id: 'a', format: 'Modern' },
      { match_id: 'm3', deck_id: 'a', format: 'Modern' },
    ])
  })

  it('leaves out removed matches and uses the chosen format', () => {
    const g = group('a')
    const s = chooseFormat(toggleRemoved(initialGroupState(g), 'm2'), 'Pioneer')
    expect(itemsToSend(g, s).map((i) => [i.match_id, i.format])).toEqual([
      ['m1', 'Pioneer'],
      ['m3', 'Pioneer'],
    ])
  })

  it('sends nothing on a tie until a list is chosen, then clears a format the list lacks', () => {
    const g = group(null)
    const s = initialGroupState(g)
    expect(itemsToSend(g, s)).toEqual([])
    expect(itemsToSend(g, chooseList(g, s, 'b'))[0]).toEqual({
      match_id: 'm1', deck_id: 'b', format: null,
    })
  })
})

describe('matchesWord', () => {
  it('says one match and many matches', () => {
    expect(matchesWord(1, t)).toBe('1 match')
    expect(matchesWord(2, t)).toBe('2 matches')
    expect(matchesWord(1200, t)).toBe('1,200 matches')
  })
})

describe('resultWords', () => {
  it('joins the result and the score, whichever are known', () => {
    expect(resultWords({ result: 'win', games_won: 2, games_lost: 1 }, t)).toBe('Win 2\u2060–\u20601')
    expect(resultWords({ result: 'loss', games_won: 0, games_lost: 0 }, t)).toBe('Loss')
    expect(resultWords({ result: null, games_won: 1, games_lost: 2 }, t)).toBe('1\u2060–\u20602')
    expect(resultWords({ result: 'draw' }, t)).toBe('Draw')
    expect(resultWords({}, t)).toBe('')
  })
})
