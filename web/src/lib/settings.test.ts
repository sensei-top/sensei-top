import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import {
  changeToSend,
  changedFields,
  failureOf,
  groupOfHash,
  inGroup,
  settingsRedirect,
  shownGroups,
  updateSentence,
} from './settings'

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
  const t = translator('en')
  it('says nothing of a save that worked', () => {
    expect(failureOf({ ok: true }, t)).toBeNull()
    expect(failureOf({ ok: true, restart: true }, t)).toBeNull()
  })

  it("keeps the shell's own sentence", () => {
    expect(failureOf({ ok: false, error: 'The folder could not be written to.' }, t)).toBe(
      'The folder could not be written to.',
    )
  })

  it('gives the plain sentence when the shell gave none', () => {
    expect(failureOf({ ok: false, error: '' }, t)).toBe('It was not saved. Try again.')
    expect(failureOf({ ok: false, error: '  ' }, t)).toBe('It was not saved. Try again.')
  })
})

describe('updateSentence', () => {
  const t = translator('en')
  const now = Date.parse('2026-10-08T12:00:00Z')
  const at = (ms: number) => new Date(now - ms).toISOString()

  it('says why an unavailable copy does not update', () => {
    expect(updateSentence({ state: 'unavailable', reason: 'store' }, now, t)).toBe(
      'The Microsoft Store keeps this copy up to date.',
    )
    expect(updateSentence({ state: 'unavailable', reason: 'development' }, now, t)).toBe(
      'A development run never updates itself.',
    )
    expect(updateSentence({ state: 'unavailable', reason: 'unsupported' }, now, t)).toBe(
      'This copy does not update itself.',
    )
  })

  it('says nothing when idle', () => {
    expect(updateSentence({ state: 'idle' }, now, t)).toBeNull()
  })

  it('names a check in progress', () => {
    expect(updateSentence({ state: 'checking' }, now, t)).toBe('Checking for a new version.')
  })

  it('names when the newest version was confirmed, and drops the clause when the time is unreadable', () => {
    expect(updateSentence({ state: 'current', checkedAt: at(3 * 60_000) }, now, t)).toBe(
      'This is the newest version, checked 3m ago.',
    )
    expect(updateSentence({ state: 'current', checkedAt: 'not a date' }, now, t)).toBe('This is the newest version.')
  })

  it('names the version while it downloads and when it is ready', () => {
    expect(updateSentence({ state: 'downloading', version: '1.2.3' }, now, t)).toBe('Version 1.2.3 is downloading.')
    expect(updateSentence({ state: 'ready', version: '1.2.3' }, now, t)).toBe(
      'Version 1.2.3 is ready. It installs the next time you quit the app.',
    )
  })

  it('names when the last check failed, and drops the clause when the time is unreadable', () => {
    expect(updateSentence({ state: 'failed', checkedAt: at(2 * 3_600_000) }, now, t)).toBe(
      'The last check failed 2h ago. The reason is in the log.',
    )
    expect(updateSentence({ state: 'failed', checkedAt: 'not a date' }, now, t)).toBe(
      'The last check failed. The reason is in the log.',
    )
  })
})

describe('Settings groups', () => {
  const browser = { shell: false, account: false }
  const noAccount = { shell: true, account: false }
  const withAccount = { shell: true, account: true }

  it('puts every section a hash can name in its group', () => {
    expect(groupOfHash('#language')).toBe('general')
    expect(groupOfHash('#appearance')).toBe('general')
    expect(groupOfHash('#live-settings')).toBe('general')
    expect(groupOfHash('#app')).toBe('general')
    expect(groupOfHash('#app-about')).toBe('about')
    expect(groupOfHash('#sources')).toBe('sources')
    expect(groupOfHash('#backup')).toBe('backup')
    expect(groupOfHash('#account')).toBe('account')
    expect(groupOfHash('#contribute')).toBe('account')
    expect(groupOfHash('#writing')).toBe('writing')
    expect(groupOfHash('#ai-settings')).toBe('writing')
    expect(groupOfHash('#credits')).toBe('about')
  })

  it('names no group for a hash that names no section', () => {
    expect(groupOfHash('')).toBeNull()
    expect(groupOfHash('#')).toBeNull()
    expect(groupOfHash('#nowhere')).toBeNull()
    expect(groupOfHash('#toString')).toBeNull()
  })

  it('shows each build its groups, in order', () => {
    expect(shownGroups(browser)).toEqual(['general', 'writing', 'about'])
    expect(shownGroups(noAccount)).toEqual(['general', 'sources', 'backup', 'writing', 'about'])
    expect(shownGroups(withAccount)).toEqual(['general', 'sources', 'backup', 'account', 'writing', 'about'])
  })

  it('sends bare /settings to General, or to the group of its hash with the hash kept', () => {
    expect(settingsRedirect('/settings', '', browser)).toBe('/settings/general')
    expect(settingsRedirect('/settings/', '', browser)).toBe('/settings/general')
    expect(settingsRedirect('/settings', '#credits', browser)).toBe('/settings/about#credits')
    expect(settingsRedirect('/settings', '#app', withAccount)).toBe('/settings/general#app')
    expect(settingsRedirect('/settings', '#contribute', withAccount)).toBe('/settings/account#contribute')
    expect(settingsRedirect('/settings', '#nowhere', browser)).toBe('/settings/general#nowhere')
  })

  it('sends a hash whose group this build does not show to General', () => {
    expect(settingsRedirect('/settings', '#backup', browser)).toBe('/settings/general#backup')
    expect(settingsRedirect('/settings', '#account', noAccount)).toBe('/settings/general#account')
  })

  it('sends a group this build does not show to General, and leaves a shown one', () => {
    expect(settingsRedirect('/settings/sources', '', browser)).toBe('/settings/general')
    expect(settingsRedirect('/settings/account', '', noAccount)).toBe('/settings/general')
    expect(settingsRedirect('/settings/account', '', withAccount)).toBeNull()
    expect(settingsRedirect('/settings/writing', '', browser)).toBeNull()
    expect(settingsRedirect('/settings/about', '#credits', browser)).toBeNull()
  })

  it('keeps a section in its own group, and every section without one', () => {
    expect(inGroup('credits', 'about')).toBe(true)
    expect(inGroup('credits', 'general')).toBe(false)
    expect(inGroup('contribute', 'account')).toBe(true)
    expect(inGroup('nowhere', 'general')).toBe(false)
    expect(inGroup('credits', undefined)).toBe(true)
    expect(inGroup('nowhere', undefined)).toBe(true)
  })
})
