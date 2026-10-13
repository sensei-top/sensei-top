import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import { confidenceLabel } from './opponent'

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
