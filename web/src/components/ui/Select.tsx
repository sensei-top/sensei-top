import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

export type SelectOption = { value: string; label: string }

export type SelectPlacement = 'beside' | 'above' | 'beside-from-md'

/** The label element's layout and its word's look, by placement. */
const LABEL_CLASS: Record<SelectPlacement, { row: string; word: string }> = {
  beside: {
    row: 'flex max-w-full min-w-0 items-center gap-2',
    word: 'shrink-0 text-caption text-muted',
  },
  above: {
    row: 'flex max-w-full min-w-0 flex-col items-start gap-1.5',
    word: 'text-caption font-medium text-ink2',
  },
  // The classes of `CONTROL_ROW` in `components/field/FieldControls.tsx`,
  // which the control beside this one uses; the two change together.
  'beside-from-md': {
    row: 'flex max-w-full min-w-0 flex-col items-start gap-1 md:flex-row md:items-center md:gap-2',
    word: 'shrink-0 text-caption text-muted',
  },
}

const SIZE_CLASS = { body: 'text-body', caption: 'text-caption' } as const

/** The native `select` with its label, for a filter beside a list or a
 *  choice in a form. `placement` puts the label beside it (the default, as
 *  a filter has it), above it (as a form has it), or above it under 48rem
 *  and beside it from there. The label is capped at the row it sits in and
 *  the select may shrink inside it, so a long option is cut inside the
 *  select and never widens the page. `children` are extra `option`s drawn
 *  before `options`, for a first option that is not in the list ("All
 *  decks").
 *
 *  With no `onChange` it is read-only and draws no select: the label, then
 *  the chosen option's label as text, or "Not set" when no option in
 *  `options` holds the value (`children` are not searched). */
export function Select({
  label,
  value,
  options,
  onChange,
  disabled = false,
  placement = 'beside',
  size = 'body',
  children,
}: {
  label: string
  value: string
  options: readonly SelectOption[]
  onChange?: (value: string) => void
  disabled?: boolean
  placement?: SelectPlacement
  size?: keyof typeof SIZE_CLASS
  children?: ReactNode
}) {
  const { t } = useTranslation()
  const look = LABEL_CLASS[placement]

  if (!onChange) {
    const chosen = options.find((option) => option.value === value)
    return (
      <div className={look.row}>
        <span className={look.word}>{label}</span>
        <span className={`min-w-0 break-words ${SIZE_CLASS[size]} ${chosen ? 'text-ink' : 'text-muted'}`}>
          {chosen ? chosen.label : t('common.notSet')}
        </span>
      </div>
    )
  }

  return (
    <label className={look.row}>
      <span className={look.word}>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className={`min-h-[44px] max-w-full min-w-0 truncate rounded-control border border-edge bg-surface px-2 py-1.5 text-ink disabled:opacity-50 ${SIZE_CLASS[size]}`}
      >
        {children}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}
