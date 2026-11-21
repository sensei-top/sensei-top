import { useTranslation } from 'react-i18next'
import type { DeckGuideOut } from '../../api'
import { archetypeName, deckRecord } from '../../lib/decks'
import { focusOptions } from '../../lib/guide'
import { MIN_TRUSTED_FIELD_SAMPLE } from '../../lib/sample'
import { formatPercent } from '../../lib/format'
import { formatCount } from '../../lib/time'
import { Select, StatTile } from '../ui'

const ALL = ''

/** The opponent picker above the sideboard plans: "All matchups" first, then
 *  each archetype with a written plan, most played first. `value` is the
 *  archetype in focus, `null` for all. */
export function OpponentPicker({
  plans,
  deck,
  value,
  onChange,
}: {
  plans: readonly { archetype: string }[]
  deck: DeckGuideOut
  value: string | null
  onChange: (archetype: string | null) => void
}) {
  const { t } = useTranslation()
  const options = focusOptions(plans, deck.field.shares).map(({ archetype, share }) => ({
    value: archetype,
    label:
      share == null
        ? archetypeName(archetype)
        : t('decks.guide.focus.option', { archetype: archetypeName(archetype), share: formatPercent(share) }),
  }))
  return (
    <Select
      label={t('decks.guide.focus.label')}
      value={value ?? ALL}
      options={options}
      onChange={(next) => onChange(next === ALL ? null : next)}
      placement="beside"
    >
      <option value={ALL}>{t('decks.guide.focus.overview')}</option>
    </Select>
  )
}

/** The two figures a focused archetype card opens with: its share of the
 *  tournament field, and the player's record against it, both from the
 *  guide's Field data. An archetype with no row in the field shows the
 *  words the Field card uses for that, and one never met shows a line that
 *  says so. */
export function FocusStats({ deck, archetype }: { deck: DeckGuideOut; archetype: string }) {
  const { t } = useTranslation()
  const { field } = deck
  const share = field.shares.find((s) => s.archetype === archetype)
  const personal = field.personal_rates.find((r) => r.archetype === archetype)
  const record = personal && personal.wins + personal.losses > 0
    ? deckRecord({ finished: personal.wins + personal.losses, wins: personal.wins }, t)
    : null
  const reset = deck.provenance.reset != null
  const thinShare = share != null && share.decks < MIN_TRUSTED_FIELD_SAMPLE
  const voided = personal != null && !personal.carryable
  const shareDetail = !share
    ? t('decks.guide.field.notFound')
    : thinShare
      ? t('decks.guide.fieldCaption.tooFew', { count: share.decks, n: formatCount(share.decks) })
      : t(reset ? 'decks.guide.focus.shareDetailReset' : 'decks.guide.focus.shareDetail')
  const recordDetail = voided
    ? t('decks.guide.field.noCarryOver')
    : record
      ? record.line
      : t('decks.guide.focus.noRecord')
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <StatTile
        label={t('decks.guide.focus.share')}
        value={share ? formatPercent(share.share) : '—'}
        detail={shareDetail}
        muted={thinShare}
      />
      <StatTile
        label={t('decks.guide.focus.record')}
        value={record?.figure ?? '—'}
        detail={recordDetail}
        muted={record?.thin || voided}
      />
    </div>
  )
}
