import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import { confidenceLabel, headlineOpponentText } from './opponent'

describe('confidenceLabel', () => {
  const t = translator('en')

  it('reads each confidence the classifier names as its own word', () => {
    expect(confidenceLabel('high', t)).toBe('high')
    expect(confidenceLabel('medium', t)).toBe('medium')
    expect(confidenceLabel('low', t)).toBe('low')
    expect(confidenceLabel('unknown', t)).toBe('unknown')
  })

  it('shows a word it does not know as it arrived', () => {
    expect(confidenceLabel('certain', t)).toBe('certain')
  })
})

describe('headlineOpponentText', () => {
  const label = 'WUBG · The Theorist, Jace Beleren'

  it('shows the opponent as the Opponent row does', () => {
    expect(headlineOpponentText(`Lost 1–2 to ${label}`, label, 'WUBG')).toBe(
      'Lost 1–2 to The Theorist, Jace Beleren',
    )
  })

  it('leaves a matched archetype label alone', () => {
    const h = 'Won 2–0 vs Izzet Prowess'
    expect(headlineOpponentText(h, 'Izzet Prowess', 'UR')).toBe(h)
  })

  it('leaves the headline alone with no colours', () => {
    const h = `Lost 1–2 to ${label}`
    expect(headlineOpponentText(h, label, null)).toBe(h)
  })
})
