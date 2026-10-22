import { useTranslation } from 'react-i18next'
import type { FieldWindow, Tier } from '../../lib/field'
import { TIERS, tierOption, windowOptions } from '../../lib/field'
import { Select, type SelectOption } from '../ui'

/** A control and its label: the label over the control under 48rem, beside
 *  it from 48rem. The matchups' "Counted from" uses it. */
export const CONTROL_ROW =
  'flex max-w-full min-w-0 flex-col items-start gap-1 text-caption md:flex-row md:items-center md:gap-2'

/** Each option of a `Segmented` 44 px high and on one line. */
export const SEGMENTED_OPTIONS = '*:min-h-[44px] *:whitespace-nowrap'

/** The format's choices, its handler and the caption drawn under the row. */
export type FormatControl = {
  value: string
  options: SelectOption[]
  caption: string | null
  onChange: (value: string) => void
}

/** The format (when `format` is given), the window (when `window` is) and
 *  the tier the share is counted in, one row from 48rem, the format's
 *  caption under the row. `window` is `null` before the status says which
 *  windows exist and over the empty state; `tier` is `null` until the
 *  address or the lists say which tier it is. The caller draws this first
 *  in every state of the page, so a change of format keeps its `<select>`,
 *  and the focus on it, while the new format's status loads. Nothing is
 *  drawn when all three are absent. */
export function FieldControls({
  format,
  window,
  reset,
  now,
  tier,
  onWindow,
  onTier,
}: {
  format: FormatControl | null
  window: FieldWindow | null
  reset: string | null
  now: number
  tier: Tier | null
  onWindow: (value: string) => void
  onTier: (tier: Tier) => void
}) {
  const { t } = useTranslation()
  if (!format && window == null && !tier) return null
  const tierOptions = TIERS.map((each) => ({ value: each, label: tierOption(each, t) }))
  return (
    <div className="space-y-1">
      <div className="flex flex-col gap-3 md:flex-row md:flex-wrap md:items-center md:gap-x-6 md:gap-y-2">
        {format && (
          <Select
            label={t('field.controls.format')}
            placement="beside-from-md"
            size="caption"
            value={format.value}
            onChange={format.onChange}
            options={format.options}
          />
        )}
        {window != null && (
          <Select
            label={t('field.controls.window')}
            placement="beside-from-md"
            size="caption"
            value={String(window)}
            onChange={onWindow}
            options={windowOptions(reset, now, t)}
          />
        )}
        {window != null && tier && (
          <Select
            label={t('field.controls.tournaments')}
            placement="beside-from-md"
            size="caption"
            value={tier}
            onChange={(value) => {
              const chosen = TIERS.find((each) => each === value)
              if (chosen) onTier(chosen)
            }}
            options={tierOptions}
          />
        )}
      </div>
      {format?.caption && <p className="text-caption text-muted">{format.caption}</p>}
    </div>
  )
}
