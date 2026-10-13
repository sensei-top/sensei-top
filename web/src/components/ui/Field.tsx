import { useId } from 'react'
import { useTranslation } from 'react-i18next'

/** One line of text with its label over it: a name, a folder, a key. The
 *  label is joined to the input by `htmlFor`; under the input, `hint` says
 *  what the field is for in one sentence, and `error`, when there is one,
 *  takes its place and says what is wrong. The error also turns the border
 *  to `loss` and sets `aria-invalid`, but its sentence is what carries it.
 *
 *  With no `onChange` it is read-only and draws no input: the label, then
 *  the value as text, wrapping, or "Not set" when it is empty. A
 *  `password` field never shows its value, read-only or not: read-only, it
 *  shows its label and its hint and nothing else. */
export function Field({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  hint,
  error,
  disabled = false,
  autoComplete = 'off',
}: {
  label: string
  value: string
  onChange?: (value: string) => void
  type?: 'text' | 'password'
  placeholder?: string
  /** One sentence under the input. */
  hint?: string
  /** One sentence that says what is wrong; shown in place of `hint`. */
  error?: string
  disabled?: boolean
  autoComplete?: string
}) {
  const { t } = useTranslation()
  const id = useId()
  const noteId = `${id}-note`
  const note = error ?? hint
  const noteLine = note && (
    <p id={noteId} className={`break-words text-caption ${error ? 'text-loss' : 'text-muted'}`}>
      {note}
    </p>
  )

  if (!onChange) {
    return (
      <div className="flex min-w-0 flex-col gap-1.5">
        <span className="text-caption font-medium text-ink2">{label}</span>
        {type === 'password' ? null : value ? (
          <p className="break-words text-body text-ink">{value}</p>
        ) : (
          <p className="text-body text-muted">{t('common.notSet')}</p>
        )}
        {noteLine}
      </div>
    )
  }

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-caption font-medium text-ink2">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete={autoComplete}
        spellCheck={false}
        aria-invalid={error ? true : undefined}
        aria-describedby={note ? noteId : undefined}
        className={`min-h-[44px] w-full rounded-control border bg-surface px-3 text-body text-ink placeholder:text-muted disabled:opacity-50 ${
          error ? 'border-loss' : 'border-edge'
        }`}
      />
      {noteLine}
    </div>
  )
}
