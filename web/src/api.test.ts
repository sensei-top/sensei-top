import { describe, expect, it } from 'vitest'
import { pasteRequest } from './api'

// The seven PUT routes, as the API declares them: each on its
// generate route's address, each taking `{ answer }`, the RCQ guide's with
// the generate route's fields beside it.

describe('pasteRequest', () => {
  const answer = '{"for": "leaks", "prose": "Mulligan less."}'

  it('sends the answer alone to each card but the RCQ guide', () => {
    expect(pasteRequest({ card: 'match', matchId: 'm-1' }, answer)).toEqual({
      path: '/api/matches/m-1/report/narrative',
      body: { answer },
    })
    expect(pasteRequest({ card: 'leaks' }, answer)).toEqual({
      path: '/api/review/leaks/narrative',
      body: { answer },
    })
    expect(pasteRequest({ card: 'guide', key: 'mono-red' }, answer)).toEqual({
      path: '/api/guide/mono-red/narrative',
      body: { answer },
    })
    expect(pasteRequest({ card: 'brief', key: 'mono-red', archetypeKey: 'azorius-control' }, answer)).toEqual({
      path: '/api/guide/mono-red/briefs/azorius-control',
      body: { answer },
    })
    expect(pasteRequest({ card: 'coverage', key: 'mono-red' }, answer)).toEqual({
      path: '/api/guide/mono-red/coverage',
      body: { answer },
    })
  })

  it('sends the RCQ guide the 75 and the picks with the answer', () => {
    const inputs = { decklist: '4 Lightning Bolt', expected: ['azorius-control'], own: 'mono-red' }
    expect(pasteRequest({ card: 'rcq', key: 'mono-red', inputs }, answer)).toEqual({
      path: '/api/guide/mono-red/rcq/narrative',
      body: { decklist: '4 Lightning Bolt', expected: ['azorius-control'], own: 'mono-red', answer },
    })
  })

  it('lets the answer win over a field of the same name in the RCQ inputs', () => {
    const inputs = { decklist: '', expected: [], answer: 'stale' } as unknown as {
      decklist: string
      expected: string[]
    }
    expect(pasteRequest({ card: 'rcq', key: 'k', inputs }, answer).body).toMatchObject({ answer })
  })

  it('always names the coach\'s format in the address', () => {
    expect(pasteRequest({ card: 'coach', format: 'Pioneer' }, answer)).toEqual({
      path: '/api/coach/narrative?format=Pioneer',
      body: { answer },
    })
  })

  it('escapes every part of the address it fills in', () => {
    expect(pasteRequest({ card: 'brief', key: 'a/b', archetypeKey: 'c d' }, answer).path).toBe(
      '/api/guide/a%2Fb/briefs/c%20d',
    )
    expect(pasteRequest({ card: 'match', matchId: 'x?y' }, answer).path).toBe('/api/matches/x%3Fy/report/narrative')
    expect(pasteRequest({ card: 'coach', format: 'A&B' }, answer).path).toBe('/api/coach/narrative?format=A%26B')
  })
})
