import { describe, expect, it } from 'vitest'
import { answerOf, changeToSend, changedFields, failureOf, pressFailure } from './settings'

const saved = { mtgoHandle: 'Sample Player', mtgoDir: '/games/mtgo/logs' }

describe('changedFields and changeToSend', () => {
  it('finds no change when nothing was typed', () => {
    const typed = { mtgoHandle: 'Sample Player', mtgoDir: '/games/mtgo/logs' }
    expect(changedFields(saved, typed)).toEqual([])
    expect(changeToSend(saved, typed)).toEqual({})
  })

  it('sends the one field that changed and no other', () => {
    const typed = { mtgoHandle: 'Sample Player', mtgoDir: '/games/chosen' }
    expect(changedFields(saved, typed)).toEqual(['mtgoDir'])
    expect(changeToSend(saved, typed)).toEqual({ mtgoDir: '/games/chosen' })
  })

  it('sends an emptied field as null, never an empty string', () => {
    const typed = { mtgoHandle: '', mtgoDir: '/games/mtgo/logs' }
    expect(changeToSend(saved, typed)).toEqual({ mtgoHandle: null })
  })

  it('reads a field of white space alone as emptied', () => {
    const typed = { mtgoHandle: '   ', mtgoDir: '/games/mtgo/logs' }
    expect(changeToSend(saved, typed)).toEqual({ mtgoHandle: null })
  })

  it('finds no change in an empty field over a value that is not set', () => {
    const unset = { mtgoHandle: null, mtgoDir: null }
    expect(changeToSend(unset, { mtgoHandle: '', mtgoDir: '  ' })).toEqual({})
  })

  it('trims what it sends', () => {
    const typed = { mtgoHandle: '  Another Player ', mtgoDir: '/games/mtgo/logs' }
    expect(changeToSend(saved, typed)).toEqual({ mtgoHandle: 'Another Player' })
  })

  it('finds no change in a value that differs only by white space around it', () => {
    const typed = { mtgoHandle: ' Sample Player  ', mtgoDir: '\t/games/mtgo/logs\n' }
    expect(changedFields(saved, typed)).toEqual([])
    expect(changeToSend(saved, typed)).toEqual({})
  })
})

describe('failureOf', () => {
  it('says nothing of a save that worked', () => {
    expect(failureOf({ ok: true })).toBeNull()
    expect(failureOf({ ok: true, restart: true })).toBeNull()
  })

  it("keeps the shell's own sentence", () => {
    expect(failureOf({ ok: false, error: 'The folder could not be written to.' })).toBe(
      'The folder could not be written to.',
    )
  })

  it('gives the plain sentence when the shell gave none', () => {
    expect(failureOf({ ok: false, error: '' })).toBe('It was not saved. Try again.')
    expect(failureOf({ ok: false, error: '  ' })).toBe('It was not saved. Try again.')
  })
})

describe('pressFailure and answerOf', () => {
  const plain = 'No new id was made. Try again.'

  it('says nothing of a press that worked', () => {
    expect(pressFailure({ ok: true }, plain)).toBeNull()
  })

  it("keeps the shell's own sentence", () => {
    expect(pressFailure({ ok: false, error: 'The server did not answer.' }, plain)).toBe('The server did not answer.')
  })

  it('gives the plain sentence when the shell gave none', () => {
    expect(pressFailure({ ok: false, error: ' ' }, plain)).toBe(plain)
    expect(pressFailure({ ok: false, error: '' }, plain)).toBe(plain)
  })

  it('reads a refused answer as a failure with no sentence', async () => {
    expect(await answerOf(Promise.reject(new Error('gone')))).toEqual({ ok: false, error: '' })
    expect(pressFailure(await answerOf(Promise.reject(new Error('gone'))), plain)).toBe(plain)
  })

  it('passes an answer through', async () => {
    expect(await answerOf(Promise.resolve({ ok: true }))).toEqual({ ok: true })
  })
})
