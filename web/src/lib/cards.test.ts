import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import { cardName } from './cards'

describe('cardName', () => {
  const t = translator('en')

  it('is the card’s name when it has one', () => {
    expect(cardName({ card_name: 'Island', grp_id: 1 }, t)).toBe('Island')
  })

  it('says a card with no id at all is hidden', () => {
    expect(cardName({ card_name: null, grp_id: null }, t)).toBe('Hidden card')
  })

  it('says a card with an id and no name is unknown, never the id', () => {
    expect(cardName({ card_name: null, grp_id: 12345 }, t)).toBe('Unknown card')
  })
})
