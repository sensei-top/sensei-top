/**
 * A shell made up for the reference page, `/design/surfaces`, and for
 * nothing else: every path, name, model and day in it is invented. Its state
 * lives in the page's memory, so a save shows on the page and is gone on
 * a reload.
 */
import { useState } from 'react'
import type { DeepPartial, Saved, Shell, ShellSettings } from '../bridge'
import type { WritingStatusAnswer } from '../components/settings/WritingSection'

export type SampleId =
  | 'no-shell'
  | 'no-shell-no-key'
  | 'nothing'
  | 'everything'
  | 'fails'
  | 'restart'
  | 'backup-failed'
  | 'first-backup-failed'

export const SAMPLE_OPTIONS: { value: SampleId; label: string }[] = [
  { value: 'no-shell', label: 'No shell' },
  { value: 'no-shell-no-key', label: 'No shell, no key' },
  { value: 'nothing', label: 'Nothing set' },
  { value: 'everything', label: 'Everything set' },
  { value: 'fails', label: 'A save fails' },
  { value: 'restart', label: 'A restart is needed' },
  { value: 'backup-failed', label: 'The last backup failed' },
  { value: 'first-backup-failed', label: 'The first backup failed' },
]

const MODELS = [
  { value: 'opus-5.5', label: 'Opus 5.5' },
  { value: 'sonnet-5', label: 'Sonnet 5' },
  { value: 'fable-5.1', label: 'Fable 5.1' },
]

const BACKUP_DIR = '/home/sample/sensei-top/backups'

/** 41.3 MB, the size of every invented backup. */
const BACKUP_BYTES = 41_300_000

/** Two hours before the page opened: the invented last backup. */
const LAST_BACKUP_AT = new Date(Date.now() - 2 * 3_600_000).toISOString()

const NOTHING_SET: ShellSettings = {
  sources: {
    arenaLog: { path: null, found: false, detailedLogs: 'unknown' },
    dateOrder: 'auto',
    mtgoHandle: null,
    mtgoDir: null,
    mtgoDeckDir: null,
    mtgoFound: null,
    dataDir: '/home/sample/sensei-top',
  },
  writing: { claudeKey: false, topdeckKey: false, model: MODELS[0].value, models: MODELS },
  backup: { dir: BACKUP_DIR, keep: 7, last: null, inFolder: 0 },
}

const EVERYTHING_SET: ShellSettings = {
  sources: {
    arenaLog: { path: '/games/arena/Player.log', found: true, detailedLogs: 'enabled' },
    dateOrder: 'mdy',
    mtgoHandle: 'Sample Player',
    mtgoDir: '/games/mtgo/logs',
    mtgoDeckDir: '/games/mtgo/decks',
    mtgoFound: '/games/mtgo/logs',
    dataDir: '/home/sample/sensei-top',
  },
  writing: { claudeKey: true, topdeckKey: true, model: MODELS[0].value, models: MODELS },
  backup: { dir: BACKUP_DIR, keep: 14, last: { at: LAST_BACKUP_AT, ok: true, bytes: BACKUP_BYTES }, inFolder: 14 },
}

const BACKUP_FAILED: ShellSettings = {
  ...EVERYTHING_SET,
  backup: { ...EVERYTHING_SET.backup, last: { at: LAST_BACKUP_AT, ok: false, bytes: null } },
}

/** The only backup tried failed, and the folder holds none. */
const FIRST_BACKUP_FAILED: ShellSettings = {
  ...EVERYTHING_SET,
  backup: { ...EVERYTHING_SET.backup, last: { at: LAST_BACKUP_AT, ok: false, bytes: null }, inFolder: 0 },
}

const INITIAL: Partial<Record<SampleId, ShellSettings>> = {
  nothing: NOTHING_SET,
  'backup-failed': BACKUP_FAILED,
  'first-backup-failed': FIRST_BACKUP_FAILED,
}

const CHOSEN_FOLDER = '/games/chosen'
const CHOSEN_FILE = '/home/sample/backups/matches-2026-01-15.db.backup'
const ANSWER_MS = 400

/** What the API would say of writing, for the two samples with no shell.
 *  The model is its label, as an id that came with no list to name it. */
export function sampleWriting(sample: SampleId): WritingStatusAnswer {
  if (sample === 'no-shell-no-key') return { configured: false, model: null }
  return { configured: true, model: MODELS[0].label }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** `base` with `change` laid over it, object by object. */
function merged<T>(base: T, change: DeepPartial<T>): T {
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) }
  for (const [field, value] of Object.entries(change as Record<string, unknown>)) {
    if (value === undefined) continue
    const under = out[field]
    out[field] = isRecord(value) && isRecord(under) ? merged(under, value) : value
  }
  return out as T
}

function afterAWhile<T>(answer: () => T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(answer()), ANSWER_MS))
}

/** The sample's shell, or `null` for the two samples with no shell. Its
 *  state starts again whenever the component holding it does, so the page
 *  keys that component by the sample. `save`, `setKey`, `backUpNow` and
 *  `restoreFrom` answer after 400 ms;
 *  `pickFolder` answers an invented folder and `pickFile` an invented
 *  backup file. A backup made here is one more in the folder, up to the
 *  count kept; a restore changes nothing on the page. */
export function useSampleShell(sample: SampleId): Shell | null {
  const [settings, setSettings] = useState<ShellSettings>(() => INITIAL[sample] ?? EVERYTHING_SET)
  if (sample === 'no-shell' || sample === 'no-shell-no-key') return null

  const answer = (): Saved =>
    sample === 'fails'
      ? { ok: false, error: 'The folder could not be written to.' }
      : sample === 'restart'
        ? { ok: true, restart: true }
        : { ok: true }

  return {
    settings,
    save: (change) =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) {
          setSettings((current) => {
            const next = merged(current, change)
            // A path the viewer gave is one nobody found.
            return change.sources?.arenaLog?.path === undefined
              ? next
              : merged(next, { sources: { arenaLog: { found: false } } })
          })
        }
        return saved
      }),
    setKey: (which, key) =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) {
          const set = key !== null
          setSettings((current) =>
            merged(current, { writing: which === 'claude' ? { claudeKey: set } : { topdeckKey: set } }),
          )
        }
        return saved
      }),
    pickFolder: () => Promise.resolve(CHOSEN_FOLDER),
    pickFile: () => Promise.resolve(CHOSEN_FILE),
    backUpNow: () =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) {
          const at = new Date().toISOString()
          setSettings((current) =>
            merged(current, {
              backup: {
                last: { at, ok: true, bytes: BACKUP_BYTES },
                inFolder: Math.min(current.backup.inFolder + 1, current.backup.keep),
              },
            }),
          )
        }
        return saved
      }),
    restoreFrom: () => afterAWhile(answer),
  }
}
