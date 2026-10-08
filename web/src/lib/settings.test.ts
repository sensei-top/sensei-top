import { describe, expect, it } from 'vitest'
import { answerOf, changeToSend, changedFields, failureOf, pressFailure, updateSentence } from './settings'

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

describe('updateSentence', () => {
  const now = Date.parse('2026-10-08T12:00:00Z')
  const at = (ms: number) => new Date(now - ms).toISOString()

  it('says why an unavailable copy does not update', () => {
    expect(updateSentence({ state: 'unavailable', reason: 'store' }, now)).toBe(
      'The Microsoft Store keeps this copy up to date.',
    )
    expect(updateSentence({ state: 'unavailable', reason: 'development' }, now)).toBe(
      'A development run never updates itself.',
    )
    expect(updateSentence({ state: 'unavailable', reason: 'unsupported' }, now)).toBe(
      'This copy does not update itself.',
    )
  })

  it('says nothing when idle', () => {
    expect(updateSentence({ state: 'idle' }, now)).toBeNull()
  })

  it('names a check in progress', () => {
    expect(updateSentence({ state: 'checking' }, now)).toBe('Checking for a new version.')
  })

  it('names when the newest version was confirmed, and drops the clause when the time is unreadable', () => {
    expect(updateSentence({ state: 'current', checkedAt: at(3 * 60_000) }, now)).toBe(
      'This is the newest version, checked 3m ago.',
    )
    expect(updateSentence({ state: 'current', checkedAt: 'not a date' }, now)).toBe('This is the newest version.')
  })

  it('names the version while it downloads and when it is ready', () => {
    expect(updateSentence({ state: 'downloading', version: '1.2.3' }, now)).toBe('Version 1.2.3 is downloading.')
    expect(updateSentence({ state: 'ready', version: '1.2.3' }, now)).toBe(
      'Version 1.2.3 is ready. It installs the next time you quit the app.',
    )
  })

  it('names when the last check failed, and drops the clause when the time is unreadable', () => {
    expect(updateSentence({ state: 'failed', checkedAt: at(2 * 3_600_000) }, now)).toBe(
      'The last check failed 2h ago. The reason is in the log.',
    )
    expect(updateSentence({ state: 'failed', checkedAt: 'not a date' }, now)).toBe(
      'The last check failed. The reason is in the log.',
    )
  })
})
