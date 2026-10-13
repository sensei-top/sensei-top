import { useState } from 'react'
import type { Saved, UpdateStatus } from '../bridge'
import { useTranslation } from 'react-i18next'
import type { TFunction } from '../i18n'
import { ago } from './time'

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
export function failureOf(saved: Saved, t: TFunction): string | null {
  return saved.ok ? null : saved.error.trim() || t('settings.saveFailed')
}

/** A save's answer, with a promise that was refused read as a failure. */
export function settle(saving: Promise<Saved>, t: TFunction): Promise<Saved> {
  return saving.catch((): Saved => ({ ok: false, error: t('settings.saveFailed') }))
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
  const { t } = useTranslation()
  const [restart, setRestart] = useState(false)
  const watch = (saving: Promise<Saved>) =>
    settle(saving, t).then((saved) => {
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
  const { t } = useTranslation()
  const [error, setError] = useState<{ field: K; sentence: string } | null>(null)

  const type = (field: K, value: string) => setTyped((current) => ({ ...current, [field]: value }))

  const submit = async (): Promise<boolean> => {
    const change = changeToSend(saved, typed)
    const fields = Object.keys(change) as K[]
    if (!save || fields.length === 0) return false
    setError(null)
    const sentence = failureOf(await settle(save(change), t), t)
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
export function updateSentence(update: UpdateStatus, now: number, t: TFunction): string | null {
  switch (update.state) {
    case 'unavailable':
      if (update.reason === 'store') return t('settings.app.update.store')
      if (update.reason === 'development') return t('settings.app.update.development')
      return t('settings.app.update.unsupported')
    case 'idle':
      return null
    case 'checking':
      return t('settings.app.update.checking')
    case 'current': {
      const when = ago(update.checkedAt, now)
      return when ? t('settings.app.update.currentChecked', { when }) : t('settings.app.update.current')
    }
    case 'downloading':
      return t('settings.app.update.downloading', { version: update.version })
    case 'ready':
      return t('settings.app.update.ready', { version: update.version })
    case 'failed': {
      const when = ago(update.checkedAt, now)
      return when ? t('settings.app.update.failedWhen', { when }) : t('settings.app.update.failed')
    }
  }
}
