import { useTranslation } from 'react-i18next'
import type { FieldWindow, Tier } from '../../lib/field'
import { TIERS, tierOption, windowOptions } from '../../lib/field'
import { Segmented, Select } from '../ui'

/** A control and its label: the label over the control under 48rem, beside
 *  it from 48rem. Shared with the matchups' "Counted from". */
export const CONTROL_ROW =
  'flex max-w-full min-w-0 flex-col items-start gap-1 text-caption md:flex-row md:items-center md:gap-2'

/** Each option of a `Segmented` 44 px high and on one line. */
export const SEGMENTED_OPTIONS = '*:min-h-[44px] *:whitespace-nowrap'

/** The window and the tier the share is counted in: one row from 48rem,
 *  each label beside its control; under it the two stack, each label over
 *  its control. The select is 44 px high, as the version switcher; each of
 *  the tier's options is too, and never wraps inside the pill. `tier` is
 *  `null` until the address or the lists say which tier it is, and the
 *  tier's control waits for it. */
export function FieldControls({
  window,
  reset,
  now,
  tier,
  onWindow,
  onTier,
}: {
  window: FieldWindow
  reset: string | null
  now: number
  tier: Tier | null
  onWindow: (value: string) => void
  onTier: (tier: Tier) => void
}) {
  const { t } = useTranslation()
  const tierOptions = TIERS.map((each) => ({ value: each, label: tierOption(each, t) }))
  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-center md:gap-6">
      <Select
        label={t('field.controls.window')}
        placement="beside-from-md"
        size="caption"
        value={String(window)}
        onChange={onWindow}
        options={windowOptions(reset, now, t)}
      />
      {tier && (
        <div className={CONTROL_ROW}>
          {/* The group's name is its `label`; the word on screen is for the
              eye, so a screen reader does not hear it twice. */}
          <span aria-hidden className="shrink-0 text-muted">
            {t('field.controls.tournaments')}
          </span>
          <Segmented
            label={t('field.controls.tournaments')}
            value={tier}
            options={tierOptions}
            onChange={onTier}
            className={SEGMENTED_OPTIONS}
          />
        </div>
      )}
    </div>
  )
}
