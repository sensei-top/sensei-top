import { describe, expect, it } from 'vitest'
import { eventLabel } from './events'
import { opponentLabelText } from './opponent'

describe('eventLabel', () => {
  it('writes out the names it knows', () => {
    expect(eventLabel('Ladder')).toBe('Ranked')
    expect(eventLabel('Traditional_Ladder')).toBe('Ranked, best of three')
    expect(eventLabel('DirectGame')).toBe('Direct challenge')
  })

  it('reads the Traditional Constructed event the same with a year or a date', () => {
    expect(eventLabel('Traditional_Cons_Event_2026')).toBe('Traditional Constructed event')
    expect(eventLabel('Traditional_Cons_Event_20260831')).toBe('Traditional Constructed event')
  })

  it('respells any other id: the date goes, the set code stays', () => {
    expect(eventLabel('QuickDraft_SOS_20260831')).toBe('Quick Draft, SOS')
    expect(eventLabel('PremierDraft_SOS_20260831')).toBe('Premier Draft, SOS')
    expect(eventLabel('QuickDraft')).toBe('Quick Draft')
  })

  it('keeps a part in capitals whole', () => {
    expect(eventLabel('SOS_Sealed')).toBe('SOS, Sealed')
  })

  it('is null without an event', () => {
    expect(eventLabel(null)).toBeNull()
    expect(eventLabel(undefined)).toBeNull()
    expect(eventLabel('')).toBeNull()
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
