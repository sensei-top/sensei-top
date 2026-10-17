import { describe, expect, it } from 'vitest'
import { WELCOME_STEPS, neighbour, stepHref, stepNumber, stepOf, stepsFor, withStop } from './welcome'

describe('stepOf', () => {
  it('reads each step the address can name', () => {
    expect(stepOf('start')).toBe('start')
    expect(stepOf('plays')).toBe('plays')
    expect(stepOf('arena')).toBe('arena')
    expect(stepOf('mtgo')).toBe('mtgo')
    expect(stepOf('done')).toBe('done')
  })

  it('shows Start for a missing or unknown value', () => {
    expect(stepOf(null)).toBe('start')
    expect(stepOf('')).toBe('start')
    expect(stepOf('Arena')).toBe('start')
    expect(stepOf('7')).toBe('start')
  })

  it('shows Start for an address the old steps used', () => {
    expect(stepOf('cards')).toBe('start')
    expect(stepOf('language')).toBe('start')
    expect(stepOf('welcome')).toBe('start')
  })
})

describe('stepsFor', () => {
  it('shows only Arena\'s setup to an Arena player', () => {
    expect(stepsFor(['arena'])).toEqual(['start', 'plays', 'arena', 'done'])
  })

  it('shows only Magic Online\'s setup to a Magic Online player', () => {
    expect(stepsFor(['mtgo'])).toEqual(['start', 'plays', 'mtgo', 'done'])
  })

  it('shows both to a player of both, in the same order whatever the stored order', () => {
    expect(stepsFor(['arena', 'mtgo'])).toEqual(['start', 'plays', 'arena', 'mtgo', 'done'])
    expect(stepsFor(['mtgo', 'arena'])).toEqual(['start', 'plays', 'arena', 'mtgo', 'done'])
  })

  it('reads no choice as both', () => {
    expect(stepsFor(undefined)).toEqual([...WELCOME_STEPS])
    expect(stepsFor([])).toEqual([...WELCOME_STEPS])
  })

  it('keeps the step on show in its place when the choice leaves it out', () => {
    expect(stepsFor(['arena'], 'mtgo')).toEqual(['start', 'plays', 'arena', 'mtgo', 'done'])
    expect(stepsFor(['mtgo'], 'arena')).toEqual(['start', 'plays', 'arena', 'mtgo', 'done'])
    expect(stepsFor(['arena'], 'done')).toEqual(['start', 'plays', 'arena', 'done'])
  })
})

describe('the run of steps', () => {
  it('numbers only the steps shown, from 1', () => {
    const arena = stepsFor(['arena'])
    expect(stepNumber('start', arena)).toBe(1)
    expect(stepNumber('arena', arena)).toBe(3)
    expect(stepNumber('done', arena)).toBe(4)
    const mtgo = stepsFor(['mtgo'])
    expect(stepNumber('mtgo', mtgo)).toBe(3)
    expect(stepNumber('done', mtgo)).toBe(4)
    const both = stepsFor(undefined)
    expect(stepNumber('mtgo', both)).toBe(4)
    expect(stepNumber('done', both)).toBe(5)
  })

  it('goes from the choice to the first setup chosen, and on to Ready', () => {
    expect(neighbour('plays', 1, stepsFor(['mtgo']))).toBe('mtgo')
    expect(neighbour('mtgo', -1, stepsFor(['mtgo']))).toBe('plays')
    expect(neighbour('arena', 1, stepsFor(['arena']))).toBe('done')
    expect(neighbour('done', -1, stepsFor(['arena']))).toBe('arena')
    expect(neighbour('arena', 1, stepsFor(['arena', 'mtgo']))).toBe('mtgo')
    expect(neighbour('done', -1, stepsFor(['arena', 'mtgo']))).toBe('mtgo')
  })

  it('has no step before the first or after the last', () => {
    const steps = stepsFor(undefined)
    expect(neighbour('start', -1, steps)).toBeNull()
    expect(neighbour('start', 1, steps)).toBe('plays')
    expect(neighbour('done', 1, steps)).toBeNull()
  })

  it('links each step by its address', () => {
    expect(stepHref('plays')).toBe('/welcome?step=plays')
  })
})

describe('withStop', () => {
  it('adds a full stop only where there is none', () => {
    expect(withStop('The download was stopped')).toBe('The download was stopped.')
    expect(withStop('The download was stopped.')).toBe('The download was stopped.')
  })
})
