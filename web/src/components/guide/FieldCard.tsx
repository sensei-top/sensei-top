import { useTranslation } from 'react-i18next'
import type { DeckGuideOut, PersonalRateOut } from '../../api'
import { archetypeName } from '../../lib/decks'
import { fieldCaption } from '../../lib/guide'
import { formatPercent, formatRecord } from '../../lib/format'
import { formatCount } from '../../lib/time'
import { placeById } from '../../shell/places'
import { Card, DataTable, EmptyState, StatTile } from '../ui'

/** The tournament field the deck plays into, since the format reset when
 *  one was found: three tiles (the deck's own archetype in the field, the
 *  most played archetype, and with a reset how many of those shown changed
 *  at it), then every archetype's share, most played first, in the
 *  server's order. A deck whose format is unknown (`fmt` null) has no
 *  field: one empty state says so, before the empty-corpus one. The table
 *  fits a 360 px screen: the name takes what the three number columns
 *  leave and breaks inside a word if it must. */
export function FieldCard({ guide }: { guide: DeckGuideOut }) {
  const { t } = useTranslation()
  const { field } = guide
  const reset = guide.provenance.reset != null
  const personalByArchetype = new Map<string, PersonalRateOut>(field.personal_rates.map((r) => [r.archetype, r]))

  const subtitle = reset
    ? t('decks.guide.field.subtitleReset')
    : t('decks.guide.field.subtitle')

  if (field.fmt === null) {
    return (
      <Card title={t('decks.guide.field.title')} subtitle={subtitle}>
        <EmptyState
          icon={placeById('field').icon}
          title={t('decks.guide.field.noFormat.title')}
          message={t('decks.guide.field.noFormat.message')}
        />
      </Card>
    )
  }

  if (field.shares.length === 0) {
    return (
      <Card title={t('decks.guide.field.title')} subtitle={subtitle}>
        <EmptyState
          icon={placeById('field').icon}
          title={t('decks.guide.field.noResults.title')}
          message={t('decks.guide.field.noResults.message')}
        />
      </Card>
    )
  }

  const own = field.own_performance
  const ownDetail = own
    ? t('decks.guide.field.ownDetail', {
        count: own.decks,
        wins: formatCount(own.wins),
        losses: formatCount(own.losses),
        n: formatCount(own.decks),
      })
    : t('decks.guide.field.notFound')
  const top = field.shares[0]
  const changed = field.shares.filter((s) => {
    const verdict = field.changes[s.archetype]?.verdict
    return verdict === 'changed' || verdict === 'gone'
  }).length
  const shown =
    t('decks.guide.field.shown', { count: field.shares.length, n: formatCount(field.shares.length) })

  const withBefore = field.shares.some((s) => s.share_before_reset != null)
  const columns = withBefore
    ? [
        t('decks.guide.field.columns.archetype'),
        t('decks.guide.field.columns.you'),
        t('decks.guide.field.columns.share'),
        t('decks.guide.field.columns.before'),
      ]
    : [
        t('decks.guide.field.columns.archetype'),
        t('decks.guide.field.columns.you'),
        t('decks.guide.field.columns.share'),
      ]

  return (
    <Card title={t('decks.guide.field.title')} subtitle={subtitle}>
      <div className={`grid gap-4 ${reset ? 'md:grid-cols-3' : 'md:grid-cols-2'}`}>
        <StatTile label={t('decks.guide.field.yourArchetype')} value={own?.win_rate == null ? '—' : formatPercent(own.win_rate)} detail={ownDetail} />
        <StatTile label={t('decks.guide.field.mostPlayed')} value={archetypeName(top.archetype)}
          detail={t('field.tiles.mostPlayedDetail', { pct: formatPercent(top.share) })} />
        {reset && <StatTile label={t('decks.guide.field.changedAtReset')} value={formatCount(changed)} detail={shown} />}
      </div>
      <div className="mt-5">
        <DataTable
          columns={columns}
          rows={field.shares.map((s) => {
            const personal = personalByArchetype.get(s.archetype)
            const voided = personal != null && !personal.carryable
            const name = (
              // `wrap-anywhere`, not `break-words`: in a table only
              // `overflow-wrap: anywhere` lets a long word shrink the column.
              <div key="archetype" className="min-w-0 wrap-anywhere">
                <div className="text-body text-ink">{archetypeName(s.archetype)}</div>
                <div className="text-caption text-muted">{fieldCaption(s, field.changes[s.archetype], t)}</div>
                {voided && <div className="text-caption text-muted">{t('decks.guide.field.noCarryOver')}</div>}
              </div>
            )
            const you = personal ? (
              <span key="you" className={`whitespace-nowrap ${voided ? 'text-muted' : ''}`}>
                {formatRecord(personal.wins, personal.losses)}
              </span>
            ) : (
              '—'
            )
            const share = (
              <span key="share" className="whitespace-nowrap">
                {formatPercent(s.share)}
              </span>
            )
            const before = (
              <span key="before" className="whitespace-nowrap">
                {s.share_before_reset == null ? '—' : formatPercent(s.share_before_reset)}
              </span>
            )
            return withBefore ? [name, you, share, before] : [name, you, share]
          })}
        />
      </div>
    </Card>
  )
}
