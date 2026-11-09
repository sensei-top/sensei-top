import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { translator } from '../../i18n'
import { SavedNote } from './SaveButton'
import { runSave } from './useSavedFlash'

const t = translator('en')

function calls() {
  return { start: vi.fn(), settled: vi.fn(), flash: vi.fn() }
}

describe('runSave', () => {
  it('flashes Saved after a save that resolved ok', async () => {
    const on = calls()
    await runSave(async () => ({ ok: true }), t, on)
    expect(on.start).toHaveBeenCalledTimes(1)
    expect(on.settled).toHaveBeenCalledWith(null)
    expect(on.flash).toHaveBeenCalledTimes(1)
  })

  it('does not flash after a save that answered with a failure', async () => {
    const on = calls()
    await runSave(async () => ({ ok: false, error: 'It broke.' }), t, on)
    expect(on.settled).toHaveBeenCalledWith('It broke.')
    expect(on.flash).not.toHaveBeenCalled()
  })

  it('does not flash after a save that was refused', async () => {
    const on = calls()
    await runSave(() => Promise.reject(new Error('x')), t, on)
    expect(on.settled).toHaveBeenCalledWith(t('settings.saveFailed'))
    expect(on.flash).not.toHaveBeenCalled()
  })
})

describe('SavedNote', () => {
  it('says Saved in a polite status region once shown', () => {
    const html = renderToStaticMarkup(createElement(SavedNote, { shown: true }))
    expect(html).toContain('role="status"')
    expect(html).toContain('aria-live="polite"')
    expect(html).toContain(t('common.saved'))
  })

  it('stays on the page, empty, before a save', () => {
    const html = renderToStaticMarkup(createElement(SavedNote, { shown: false }))
    expect(html).toContain('role="status"')
    expect(html).not.toContain(t('common.saved'))
  })
})
