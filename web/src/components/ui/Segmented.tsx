import { useRef, type KeyboardEvent, type ReactNode } from 'react'

export type SegmentedOption<T extends string | number> = { value: T; label: ReactNode }

const NEXT_KEYS = new Set(['ArrowRight', 'ArrowDown'])
const PREVIOUS_KEYS = new Set(['ArrowLeft', 'ArrowUp'])

/** The one segmented control: the field's "Counted from", the source
 *  filter and a match's games all draw it. `label` is a `ReactNode` and
 *  not a string, so a caller such as the games' control ("Game 2 · Loss")
 *  passes what it drew. `T` spans string and number, so a game's number
 *  needs no round trip through a string.
 *
 *  A radio group, since picking one option is all it does: one tab stop (the
 *  checked option), and the arrow keys move and select, wrapping at either
 *  end; Home and End go to the first and the last. */
export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  size = 'md',
  label,
  className = '',
}: {
  value: T
  options: readonly SegmentedOption<T>[]
  onChange: (value: T) => void
  size?: 'sm' | 'md'
  /** The group's accessible name, when nothing on screen already gives it
   *  one. */
  label?: string
  /** Appended after the base layout classes — e.g. `flex-col` where there
   *  is no room for a horizontal row (docs/design-system.md). A different
   *  Tailwind property than the base `flex` (display) or
   *  `gap`/`rounded-*`/`bg` utilities, so appending never fights the ones
   *  already set. */
  className?: string
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const checkedIndex = options.findIndex((option) => option.value === value)
  // With nothing checked, the first option holds the group's one tab stop.
  const tabStop = checkedIndex === -1 ? 0 : checkedIndex

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let target: number
    if (NEXT_KEYS.has(event.key)) target = (index + 1) % options.length
    else if (PREVIOUS_KEYS.has(event.key)) target = (index - 1 + options.length) % options.length
    else if (event.key === 'Home') target = 0
    else if (event.key === 'End') target = options.length - 1
    else return
    event.preventDefault()
    refs.current[target]?.focus()
    onChange(options[target].value)
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`inline-flex max-w-full flex-wrap gap-1 rounded-pill bg-surface2 p-1 ${className}`}
    >
      {options.map((option, index) => {
        const checked = option.value === value
        return (
          <button
            key={option.value}
            ref={(element) => {
              refs.current[index] = element
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={index === tabStop ? 0 : -1}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={`rounded-pill font-medium transition-chrome ${
              size === 'sm' ? 'px-2.5 py-1 text-chip' : 'px-3 py-1.5 text-caption'
            } ${checked ? 'bg-surface3 text-ink' : 'text-ink2 hover:text-ink'}`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
