import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { translator } from '../../i18n'
import { formatDayTime } from '../../lib/time'
import { AfterRestore, SnapshotChoices } from './BackupSection'
import { restoreStart } from './restoreStart'

const t = translator('en')

const newer = { path: '/b/sensei-top.db.backup', at: '2026-11-06T10:00:00.000Z', bytes: 2048 }
const older = { path: '/b/sensei-top.db.backup.1', at: '2026-11-05T10:00:00.000Z', bytes: 4096 }

describe('the restore list', () => {
  it('shows each copy by its date and time, in the order given, never as an age', () => {
    const html = renderToStaticMarkup(createElement(SnapshotChoices, { snapshots: [newer, older], onChoose: () => {} }))
    const first = formatDayTime(Date.parse(newer.at))
    const second = formatDayTime(Date.parse(older.at))
    expect(html).toContain(first)
    expect(html).toContain(second)
    expect(html.indexOf(first)).toBeLessThan(html.indexOf(second))
    expect(html).not.toContain(' ago')
    expect(html).not.toContain('sensei-top.db')
  })

  it('names a copy by its file when its time cannot be read', () => {
    const html = renderToStaticMarkup(createElement(SnapshotChoices, { snapshots: [{ path: '/b/sensei-top.db.backup', at: 'not a time', bytes: 1 }], onChoose: () => {} }))
    expect(html).toContain('>sensei-top.db.backup<')
  })
})

describe('where a restore starts', () => {
  it('lists the copies when there are some', async () => {
    expect(await restoreStart(() => Promise.resolve([newer]))).toEqual({ kind: 'list', snapshots: [newer] })
  })

  it('goes to the picker with no list call, an empty list or a rejected one', async () => {
    expect(await restoreStart()).toEqual({ kind: 'picker' })
    expect(await restoreStart(() => Promise.resolve([]))).toEqual({ kind: 'picker' })
    expect(await restoreStart(() => Promise.reject(new Error('x')))).toEqual({ kind: 'picker' })
  })

  it('offers Choose another file under the list, only when it can be acted on', () => {
    const render = (onOther?: () => void) =>
      renderToStaticMarkup(createElement(SnapshotChoices, { snapshots: [newer], onChoose: () => {}, onOther }))
    expect(render(() => {})).toContain(t('settings.backup.chooseOther'))
    expect(render()).not.toContain(t('settings.backup.chooseOther'))
  })
})

describe('after a restore', () => {
  it('offers Restart now only once restored, and only with a relaunch', () => {
    const relaunch = () => Promise.resolve({ ok: true } as const)
    const render = (restored: boolean, withRelaunch: boolean) =>
      renderToStaticMarkup(createElement(AfterRestore, { restored, relaunch: withRelaunch ? relaunch : undefined, onFailure: () => {} }))
    expect(render(false, true)).toBe('')
    expect(render(true, true)).toContain(t('settings.backup.restartNow'))
    expect(render(true, false)).not.toContain(t('settings.backup.restartNow'))
  })
})
