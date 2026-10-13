import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Saved } from '../../bridge'
import { failureOf, settle } from '../../lib/settings'
import { Button, Field, Select, Switch, type ButtonVariant, type SelectOption } from '../ui'

/** A button's press: `'working'` while what it started is in flight, then
 *  `'done'` for two seconds after one that worked, or `'idle'` at once
 *  after one that did not. Nothing is set after the button has left the
 *  page. */
function usePress(): { state: 'idle' | 'working' | 'done'; press: (action: () => Promise<boolean>) => Promise<void> } {
  const [state, setState] = useState<'idle' | 'working' | 'done'>('idle')
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const left = useRef(false)

  // Set back on every mount: StrictMode mounts, cleans up and mounts again,
  // and the ref outlives that.
  useEffect(() => {
    left.current = false
    return () => {
      left.current = true
      clearTimeout(timer.current)
    }
  }, [])

  const press = async (action: () => Promise<boolean>) => {
    setState('working')
    const ok = await action()
    if (left.current) return
    clearTimeout(timer.current)
    if (ok) {
      setState('done')
      timer.current = setTimeout(() => setState('idle'), 2000)
    } else {
      setState('idle')
    }
  }

  return { state, press }
}

/** A button whose press starts something that takes a while: it says
 *  `workingLabel` and is disabled while that is in flight and, when
 *  `doneLabel` is given, says it for two seconds after one that worked.
 *  What went wrong is its caller's to say. */
export function PressButton({
  variant,
  label,
  workingLabel,
  doneLabel,
  disabled = false,
  onPress,
}: {
  variant: ButtonVariant
  label: string
  workingLabel: string
  doneLabel: string | null
  disabled?: boolean
  /** Resolves `true` when what it started worked. */
  onPress: () => Promise<boolean>
}) {
  const { state, press } = usePress()
  const words = state === 'working' ? workingLabel : state === 'done' && doneLabel ? doneLabel : label
  return (
    <Button
      variant={variant}
      className="min-h-[44px]"
      disabled={disabled || state === 'working'}
      onClick={() => press(onPress)}
    >
      {words}
    </Button>
  )
}

/** A card's one button for its text fields. It is disabled until something
 *  in the card differs from what is saved, says "Saving" while the save is
 *  in flight and, when `savedLabel` is given, says it for two seconds after
 *  one that worked, as "Copy the prompt" says "Copied". What went wrong is
 *  the card's to say, under the field it is about. With no shell it is not
 *  drawn: a card with no save function has nothing to press. */
export function SaveButton({
  dirty,
  onSave,
  label,
  savedLabel,
}: {
  dirty: boolean
  /** Resolves `true` when the save worked. */
  onSave: () => Promise<boolean>
  label?: string
  savedLabel?: string | null
}) {
  const { t } = useTranslation()
  // `savedLabel` of `null` says nothing once saved; left out, it says "Saved".
  const done = savedLabel === undefined ? t('common.saved') : savedLabel
  return (
    <PressButton
      variant="primary"
      label={label ?? t('common.save')}
      workingLabel={t('common.saving')}
      doneLabel={dirty ? null : done}
      disabled={!dirty}
      onPress={onSave}
    />
  )
}

/** A choice that saves the moment it changes: the `Select`, its label
 *  above it, and one sentence under it. While the save is in flight the
 *  select is disabled, as it is whenever `disabled` says so; when it fails
 *  the select goes back to what is saved and the failure's sentence takes
 *  the hint's place. With no `onSave` it is read-only and shows the chosen
 *  option as text. */
export function SavingSelect({
  label,
  value,
  options,
  onSave,
  hint,
  disabled = false,
}: {
  label: string
  value: string
  options: readonly SelectOption[]
  onSave?: (value: string) => Promise<Saved>
  hint?: string
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const change = async (next: string) => {
    if (!onSave) return
    setPending(next)
    setError(null)
    const sentence = failureOf(await settle(onSave(next), t), t)
    setPending(null)
    setError(sentence)
  }

  const note = error ?? hint
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <Select
        label={label}
        placement="above"
        value={pending ?? value}
        options={options}
        onChange={onSave ? change : undefined}
        disabled={disabled || pending !== null}
      />
      {note && <p className={`break-words text-caption ${error ? 'text-loss' : 'text-muted'}`}>{note}</p>}
    </div>
  )
}

/** A `Switch` that saves the moment it turns. While the save is in flight
 *  it shows the new state and is disabled, as it is whenever `disabled`
 *  says so; when it fails it goes back and the failure's sentence is under
 *  it. With no `onSave` it is read-only. */
export function SavingSwitch({
  label,
  description,
  checked,
  onSave,
  disabled = false,
}: {
  label: string
  description?: string
  checked: boolean
  onSave?: (checked: boolean) => Promise<Saved>
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const [pending, setPending] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)

  const change = async (next: boolean) => {
    if (!onSave) return
    setPending(next)
    setError(null)
    const sentence = failureOf(await settle(onSave(next), t), t)
    setPending(null)
    setError(sentence)
  }

  return (
    <div className="space-y-1.5">
      <Switch
        label={label}
        description={description}
        checked={pending ?? checked}
        onChange={onSave ? change : undefined}
        disabled={disabled || pending !== null}
      />
      {error && <p className="break-words text-caption text-loss">{error}</p>}
    </div>
  )
}

/** A folder's field, with the button that asks the shell for a folder
 *  beside it from 40rem and under it, at the start of its row, below that.
 *  The answer is written into the field, which can also be typed into;
 *  nothing is saved until the card's "Save". A refused request is read as
 *  no folder chosen. With no `onChange` it is the read-only field alone. */
export function FolderField({
  label,
  value,
  onChange,
  onPick,
  hint,
  error,
}: {
  label: string
  value: string
  onChange?: (value: string) => void
  onPick?: () => Promise<string | null>
  hint: string
  error?: string
}) {
  const { t } = useTranslation()
  if (!onChange || !onPick) return <Field label={label} value={value} onChange={onChange} hint={hint} error={error} />
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-3">
      <div className="min-w-0 flex-1">
        <Field label={label} value={value} onChange={onChange} hint={hint} error={error} />
      </div>
      {/* The label's line and the gap under it, so the button sits level
          with the input rather than with the label. */}
      <Button
        variant="quiet"
        className="min-h-[44px] self-start sm:mt-[calc(var(--text-caption)*1.4_+_var(--spacing)*1.5)]"
        onClick={async () => {
          const folder = await onPick().catch(() => null)
          if (folder !== null) onChange(folder)
        }}
      >
        {t('settings.chooseFolder')}
      </Button>
    </div>
  )
}

/** A card's last line after a save that takes effect only when the app
 *  starts again. With no shell nothing is saved, and it is never drawn. */
export function RestartNote({ show }: { show: boolean }) {
  const { t } = useTranslation()
  return show ? <p className="text-caption text-ink2">{t('settings.restartNeeded')}</p> : null
}
