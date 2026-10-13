import { describe, expect, it } from 'vitest'
import type { FormatsOut } from '../api'
import { translator } from '../i18n'
import { bodyDeckId, canConfirm, formatAfterChoosing, MTGO_FORMATS, mtgoFormatsOf, NO_LIST, prefillCaptionIn } from './mtgoPick'

describe('MTGO_FORMATS', () => {
  it('is the seven formats of D9, with no "other"', () => {
    expect([...MTGO_FORMATS]).toEqual([
      'Standard',
      'Pioneer',
      'Modern',
      'Pauper',
      'Legacy',
      'Vintage',
      'Premodern',
    ])
  })
})

describe('mtgoFormatsOf', () => {
  it("takes the API's order, and the seven of D9 before it answers", () => {
    const formats = { default: 'Modern', formats: [{ format: 'Pauper' }, { format: 'Modern' }] } as FormatsOut
    expect(mtgoFormatsOf(formats)).toEqual(['Pauper', 'Modern'])
    expect(mtgoFormatsOf(undefined)).toBe(MTGO_FORMATS)
  })
})

describe('prefillCaptionIn', () => {
  const t = translator('en')
  it('says where the pre-fill came from, by source', () => {
    expect(prefillCaptionIn('Modern', 'deck_store', 'Modern', t)).toBe('Pre-filled from the format MTGO files this deck under.')
    expect(prefillCaptionIn('Modern', 'last_pick', 'Modern', t)).toBe('Pre-filled from your last pick for this deck.')
    expect(prefillCaptionIn('Modern', 'inferred', 'Modern', t)).toBe(
      'Pre-filled: inferred from the cards revealed in this match.',
    )
  })

  it('is gone once another format is chosen, and without a source', () => {
    expect(prefillCaptionIn('Modern', 'inferred', 'Pauper', t)).toBeNull()
    expect(prefillCaptionIn('Modern', 'inferred', null, t)).toBeNull()
    expect(prefillCaptionIn('Modern', null, 'Modern', t)).toBeNull()
    expect(prefillCaptionIn(null, null, null, t)).toBeNull()
  })
})

describe('formatAfterChoosing', () => {
  it("sets a deck's format to its pre-fill", () => {
    expect(formatAfterChoosing('deck-a', 'Modern', null)).toBe('Modern')
    expect(formatAfterChoosing('deck-a', 'Modern', 'Pauper')).toBe('Modern')
  })

  it('clears the format for a deck with no pre-fill (D10: none)', () => {
    expect(formatAfterChoosing('deck-a', null, 'Pauper')).toBeNull()
    expect(formatAfterChoosing('deck-a', undefined, 'Pauper')).toBeNull()
  })

  it('keeps the chosen format for "No list"', () => {
    expect(formatAfterChoosing(NO_LIST, null, 'Legacy')).toBe('Legacy')
    expect(formatAfterChoosing(NO_LIST, null, null)).toBeNull()
  })
})

describe('canConfirm', () => {
  it('refuses a choice of nothing: the route 400s on a body with neither field', () => {
    expect(canConfirm(null, null)).toBe(false)
  })

  it('does not take a format alone as an answer until "No list" is chosen (D1)', () => {
    expect(canConfirm(null, 'Modern')).toBe(false)
  })

  it('needs a format for "No list", since it sends no deck', () => {
    expect(canConfirm(NO_LIST, null)).toBe(false)
    expect(canConfirm(NO_LIST, 'Pioneer')).toBe(true)
  })

  it('allows a deck with no format: MtgoPickIn allows either field null, not both', () => {
    expect(canConfirm('deck-a', null)).toBe(true)
    expect(canConfirm('deck-a', 'Standard')).toBe(true)
  })
})

describe('bodyDeckId', () => {
  it('sends no deck for "No list" and the deck otherwise', () => {
    expect(bodyDeckId(NO_LIST)).toBeNull()
    expect(bodyDeckId('deck-a')).toBe('deck-a')
  })
})
