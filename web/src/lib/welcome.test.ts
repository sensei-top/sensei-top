import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import { WELCOME_STEPS, agePhrase, neighbour, stepHref, stepNumber, stepOf, withStop } from './welcome'

describe('stepOf', () => {
  it('reads each step the address can name', () => {
    expect(stepOf('language')).toBe('language')
    expect(stepOf('welcome')).toBe('welcome')
    expect(stepOf('arena')).toBe('arena')
    expect(stepOf('cards')).toBe('cards')
    expect(stepOf('mtgo')).toBe('mtgo')
    expect(stepOf('done')).toBe('done')
  })

  it('shows step 1 for a missing or unknown value', () => {
    expect(stepOf(null)).toBe('language')
    expect(stepOf('')).toBe('language')
    expect(stepOf('Arena')).toBe('language')
    expect(stepOf('7')).toBe('language')
  })
})

describe('the run of steps', () => {
  it('numbers them from 1 and links each by its address', () => {
    expect(WELCOME_STEPS).toHaveLength(6)
    expect(WELCOME_STEPS[0]).toBe('language')
    expect(stepNumber('language')).toBe(1)
    expect(stepNumber('welcome')).toBe(2)
    expect(stepNumber('done')).toBe(6)
    expect(stepHref('cards')).toBe('/welcome?step=cards')
  })

  it('has no step before the first or after the last', () => {
    expect(neighbour('language', -1)).toBeNull()
    expect(neighbour('language', 1)).toBe('welcome')
    expect(neighbour('welcome', -1)).toBe('language')
    expect(neighbour('done', 1)).toBeNull()
    expect(neighbour('arena', -1)).toBe('welcome')
    expect(neighbour('arena', 1)).toBe('cards')
  })
})

describe('agePhrase', () => {
  const t = translator('en')

  it('says less than an hour under an hour', () => {
    expect(agePhrase(0, t)).toBe('less than an hour')
    expect(agePhrase(0.9, t)).toBe('less than an hour')
  })

  it('counts hours under 48, one hour in the singular', () => {
    expect(agePhrase(1, t)).toBe('1 hour')
    expect(agePhrase(1.9, t)).toBe('1 hour')
    expect(agePhrase(5, t)).toBe('5 hours')
    expect(agePhrase(47.9, t)).toBe('47 hours')
  })

  it('counts days from 48 hours', () => {
    expect(agePhrase(48, t)).toBe('2 days')
    expect(agePhrase(100, t)).toBe('4 days')
  })
})

describe('withStop', () => {
  it('adds a full stop only where there is none', () => {
    expect(withStop('The download was stopped')).toBe('The download was stopped.')
    expect(withStop('The download was stopped.')).toBe('The download was stopped.')
  })
})
