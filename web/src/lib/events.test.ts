import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import { eventLabel, resultWord } from './events'
import { opponentLabelText } from './opponent'

const t = translator('en')

describe('eventLabel', () => {
  it('writes out the names it knows', () => {
    expect(eventLabel('Ladder', t)).toBe('Ranked')
    expect(eventLabel('Traditional_Ladder', t)).toBe('Ranked, best of three')
    expect(eventLabel('DirectGame', t)).toBe('Direct challenge')
  })

  it('reads the Traditional Constructed event the same with a year or a date', () => {
    expect(eventLabel('Traditional_Cons_Event_2026', t)).toBe('Traditional Constructed event')
    expect(eventLabel('Traditional_Cons_Event_20260831', t)).toBe('Traditional Constructed event')
  })

  it('respells any other id: the date goes, the set code stays', () => {
    expect(eventLabel('QuickDraft_SOS_20260831', t)).toBe('Quick Draft, SOS')
    expect(eventLabel('PremierDraft_SOS_20260831', t)).toBe('Premier Draft, SOS')
    expect(eventLabel('QuickDraft', t)).toBe('Quick Draft')
  })

  it('keeps a part in capitals whole', () => {
    expect(eventLabel('SOS_Sealed', t)).toBe('SOS, Sealed')
  })

  it('is null without an event', () => {
    expect(eventLabel(null, t)).toBeNull()
    expect(eventLabel(undefined, t)).toBeNull()
    expect(eventLabel('', t)).toBeNull()
  })
})

describe('opponentLabelText', () => {
  it('takes the colours off a label that starts with them', () => {
    expect(opponentLabelText('UR · Mox Opal', 'UR')).toBe('Mox Opal')
  })

  it('leaves any other label as it is', () => {
    expect(opponentLabelText('Izzet Prowess', 'UR')).toBe('Izzet Prowess')
    expect(opponentLabelText('UR · Mox Opal', null)).toBe('UR · Mox Opal')
    expect(opponentLabelText('UR · Mox Opal', 'WB')).toBe('UR · Mox Opal')
  })
})

describe('resultWord', () => {
  it('words the four results the API sends', () => {
    expect(resultWord('win', t)).toBe('Win')
    expect(resultWord('loss', t)).toBe('Loss')
    expect(resultWord('draw', t)).toBe('Draw')
    expect(resultWord('incomplete', t)).toBe('Incomplete')
  })

  it('has no word for any other', () => {
    expect(resultWord('toString', t)).toBeUndefined()
    expect(resultWord(null, t)).toBeUndefined()
  })
})
