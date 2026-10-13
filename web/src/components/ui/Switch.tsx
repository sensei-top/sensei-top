import { useId, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

/** One thing that is on or off: a row with the label and, under it, an
 *  optional description at the left, and at the right the state as a word
 *  ("On" or "Off") and the switch. Only the switch is pressed, never the
 *  row, so the description's text can be selected and can hold a link. The
 *  switch is a `button` with `role="switch"`, so Space and Enter turn it;
 *  its name is the label and its description the description, and the word
 *  beside it is hidden from a screen reader, which hears the state from
 *  the switch itself. Sizes are in pixels, since density scales spacing.
 *
 *  With no `onChange` it is read-only: the row with the word and no
 *  switch, and the word is then read aloud. */
export function Switch({
  label,
  checked,
  onChange,
  description,
  disabled = false,
}: {
  label: string
  checked: boolean
  onChange?: (checked: boolean) => void
  description?: ReactNode
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const id = useId()
  const labelId = `${id}-label`
  const descriptionId = `${id}-description`

  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p id={labelId} className="break-words text-body text-ink">
          {label}
        </p>
        {description && (
          <p id={descriptionId} className="break-words text-caption text-muted">
            {description}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span aria-hidden={onChange ? true : undefined} className="text-caption text-ink2">
          {checked ? t('common.on') : t('common.off')}
        </span>
        {onChange && (
          <button
            type="button"
            role="switch"
            aria-checked={checked}
            aria-labelledby={labelId}
            aria-describedby={description ? descriptionId : undefined}
            disabled={disabled}
            onClick={() => onChange(!checked)}
            className="flex min-h-[44px] items-center disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span
              className={`flex h-[24px] w-[44px] items-center rounded-pill p-[3px] transition-chrome ${
                checked ? 'bg-accent' : 'bg-surface3'
              }`}
            >
              {/* 44 less the disc's 18 and the track's 3 at either end. */}
              <span
                className={`size-[18px] rounded-pill transition-[translate,background-color] duration-[120ms] ease-out motion-reduce:transition-none ${
                  checked ? 'translate-x-[20px] bg-on-accent' : 'bg-muted'
                }`}
              />
            </span>
          </button>
        )}
      </div>
    </div>
  )
}
