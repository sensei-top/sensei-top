import { useState } from 'react'
import type { Saved, UpdateStatus } from '../bridge'
import { ago } from './time'

/** The sentence under a field when a save failed and the shell gave none. */
export const SAVE_FAILED = 'It was not saved. Try again.'

/** A card's last line after a save that needs the app to start again. */
export const RESTART_NEEDED = 'This takes effect the next time the app starts.'

/** What a typed value saves as: trimmed, and `null` once nothing is left. */
export function typedValue(typed: string): string | null {
  const value = typed.trim()
  return value === '' ? null : value
}

/** The fields of `typed` whose value, trimmed, differs from what is saved,
 *  in `typed`'s order. An empty field and a value that is not set are the
 *  same. */
export function changedFields<K extends string>(saved: Record<K, string | null>, typed: Record<K, string>): K[] {
  return (Object.keys(typed) as K[]).filter((field) => typedValue(typed[field]) !== saved[field])
}

/** The change to send: the fields that differ and nothing else, each
 *  trimmed, and an emptied field as `null`, never an empty string. */
export function changeToSend<K extends string>(
  saved: Record<K, string | null>,
  typed: Record<K, string>,
): Partial<Record<K, string | null>> {
  const change: Partial<Record<K, string | null>> = {}
  for (const field of changedFields(saved, typed)) change[field] = typedValue(typed[field])
  return change
}

/** The sentence a failed save leaves under its control, `null` for one
 *  that worked. */
export function failureOf(saved: Saved): string | null {
  return saved.ok ? null : saved.error.trim() || SAVE_FAILED
}

/** A save's answer, with a promise that was refused read as a failure. */
export function settle(saving: Promise<Saved>): Promise<Saved> {
  return saving.catch((): Saved => ({ ok: false, error: SAVE_FAILED }))
}

/** A press whose answer is refused, read as a failure with no sentence
 *  of the shell's own. */
export function answerOf(pressing: Promise<Saved>): Promise<Saved> {
  return pressing.catch((): Saved => ({ ok: false, error: '' }))
}

/** The sentence under a press that failed: the shell's own, or `plain`
 *  when it gave none. `null` for one that worked. */
export function pressFailure(saved: Saved, plain: string): string | null {
  return saved.ok ? null : saved.error.trim() || plain
}

/** Whether a save in this card asked for a restart, and the function that
 *  passes each save through to find out. Once set it stays until the page
 *  is left. */
export function useRestart(): { restart: boolean; watch: (saving: Promise<Saved>) => Promise<Saved> } {
  const [restart, setRestart] = useState(false)
  const watch = (saving: Promise<Saved>) =>
    settle(saving).then((saved) => {
      if (saved.ok && saved.restart) setRestart(true)
      return saved
    })
  return { restart, watch }
}

/** A card's text fields, saved by its one button: what is typed, whether
 *  it differs from what is saved, the save itself, and the sentence under
 *  a field when a save failed. The sentence goes under the first field of
 *  the change that failed, and goes away at the next save. */
export function useTextSave<K extends string>(
  saved: Record<K, string | null>,
  save: ((change: Partial<Record<K, string | null>>) => Promise<Saved>) | undefined,
) {
  const [typed, setTyped] = useState<Record<K, string>>(() => {
    const start = {} as Record<K, string>
    for (const field of Object.keys(saved) as K[]) start[field] = saved[field] ?? ''
    return start
  })
  const [error, setError] = useState<{ field: K; sentence: string } | null>(null)

  const type = (field: K, value: string) => setTyped((current) => ({ ...current, [field]: value }))

  const submit = async (): Promise<boolean> => {
    const change = changeToSend(saved, typed)
    const fields = Object.keys(change) as K[]
    if (!save || fields.length === 0) return false
    setError(null)
    const sentence = failureOf(await settle(save(change)))
    if (sentence !== null) setError({ field: fields[0], sentence })
    return sentence === null
  }

  return {
    typed,
    type,
    dirty: changedFields(saved, typed).length > 0,
    submit,
    errorOf: (field: K) => (error?.field === field ? error.sentence : undefined),
  }
}

/** The one sentence that says where the shell's update stands, or `null`
 *  when there is nothing to say. The clause naming when is dropped when the
 *  time cannot be read. */
export function updateSentence(update: UpdateStatus, now: number): string | null {
  switch (update.state) {
    case 'unavailable':
      if (update.reason === 'store') return 'The Microsoft Store keeps this copy up to date.'
      if (update.reason === 'development') return 'A development run never updates itself.'
      return 'This copy does not update itself.'
    case 'idle':
      return null
    case 'checking':
      return 'Checking for a new version.'
    case 'current': {
      const when = ago(update.checkedAt, now)
      return when ? `This is the newest version, checked ${when}.` : 'This is the newest version.'
    }
    case 'downloading':
      return `Version ${update.version} is downloading.`
    case 'ready':
      return `Version ${update.version} is ready. It installs the next time you quit the app.`
    case 'failed': {
      const when = ago(update.checkedAt, now)
      return `The last check failed${when ? ` ${when}` : ''}. The reason is in the log.`
    }
  }
}
