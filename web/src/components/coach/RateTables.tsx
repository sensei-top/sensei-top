import { useTranslation } from 'react-i18next'
import type { FieldLineOut, MatchupLineOut, RateModel } from '../../api'
import { coachDay, listsWords, mulliganRates, roleRates, variantsWords, type LabelledRate } from '../../lib/coach'
import { archetypeName } from '../../lib/decks'
import { formatPercent } from '../../lib/time'
import { MIN_TRUSTED_FIELD_SAMPLE } from '../../theme'
import { Card, DataTable } from '../ui'
import { RateCell, WonCell } from './RateCells'

/** A card of three columns: the row's word, "Won" and "Rate". */
function LabelledRatesCard({
  title,
  subtitle,
  first,
  rows,
}: {
  title: string
  subtitle: string
  first: string
  rows: LabelledRate[]
}) {
  const { t } = useTranslation()
  return (
    <Card title={title} subtitle={subtitle}>
      <DataTable
        columns={[first, t('coach.table.won'), t('coach.table.rate')]}
        rows={rows.map((row) => [
          <span key="label" className="wrap-anywhere">
            {row.label}
          </span>,
          <WonCell key="won" rate={row.rate} />,
          <RateCell key="rate" rate={row.rate} />,
        ])}
      />
    </Card>
  )
}

/** "By role" and "Mulligans", side by side from 40rem. */
export function RolesAndMulligans({
  byRole,
  mulligans,
}: {
  byRole: Record<string, RateModel>
  mulligans: Record<string, RateModel>
}) {
  const { t } = useTranslation()
  const roles = roleRates(byRole, t)
  const hands = mulliganRates(mulligans, t)
  if (roles.length === 0 && hands.length === 0) return null
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {roles.length > 0 && (
        <LabelledRatesCard
          title={t('coach.roles.title')}
          subtitle={t('coach.roles.subtitle')}
          first={t('coach.roles.first')}
          rows={roles}
        />
      )}
      {hands.length > 0 && (
        <LabelledRatesCard
          title={t('coach.mulligans.title')}
          subtitle={t('coach.mulligans.subtitle')}
          first={t('coach.mulligans.first')}
          rows={hands}
        />
      )}
    </div>
  )
}

/** An archetype's name, and under it in caption whatever else `lines`
 *  holds. `wrap-anywhere`, as the Guide's field has it: in a table only
 *  `overflow-wrap: anywhere` lets a long word shrink the column. */
function ArchetypeCell({ archetype, lines }: { archetype: string; lines: (string | null)[] }) {
  return (
    <div className="min-w-0 wrap-anywhere">
      <div className="text-body text-ink">{archetypeName(archetype)}</div>
      {lines.map((line, index) =>
        line ? (
          <div key={index} className="text-caption text-muted">
            {line}
          </div>
        ) : null,
      )}
    </div>
  )
}

/** "Decks you met": the archetypes met since the format last changed,
 *  most met first, in the server's order. */
export function DecksMetCard({
  matchups,
  windowStart,
  now,
}: {
  matchups: MatchupLineOut[]
  windowStart: string | null
  now: number
}) {
  const { t } = useTranslation()
  if (matchups.length === 0) return null
  const day = coachDay(windowStart, now)
  return (
    <Card
      title={t('coach.decksMet.title')}
      subtitle={day ? t('coach.decksMet.since', { day }) : t('coach.decksMet.sinceReset')}
    >
      <DataTable
        columns={[t('coach.table.archetype'), t('coach.table.won'), t('coach.table.rate')]}
        rows={matchups.map((m) => [
          <ArchetypeCell key="archetype" archetype={m.archetype} lines={[variantsWords(m.variants, t)]} />,
          <WonCell key="won" rate={m.rate} />,
          <RateCell key="rate" rate={m.rate} />,
        ])}
      />
    </Card>
  )
}

/** "The field": each archetype's share of the tournament lists and your
 *  own record against it. Four columns that fit 360 px, so no range. A
 *  share over fewer than `MIN_TRUSTED_FIELD_SAMPLE` lists is muted. */
export function FieldRatesCard({
  field,
  latestEvent,
  now,
}: {
  field: FieldLineOut[]
  latestEvent: string | null
  now: number
}) {
  const { t } = useTranslation()
  if (field.length === 0) return null
  const day = coachDay(latestEvent, now)
  return (
    <Card
      title={t('coach.field.title')}
      subtitle={day ? t('coach.field.to', { day }) : t('coach.field.plain')}
    >
      <DataTable
        columns={[t('coach.table.archetype'), t('coach.table.share'), t('coach.table.won'), t('coach.table.rate')]}
        rows={field.map((f) => [
          <ArchetypeCell
            key="archetype"
            archetype={f.archetype}
            lines={[listsWords(f.decks, t), variantsWords(f.variants, t)]}
          />,
          <span key="share" className={`whitespace-nowrap ${f.decks < MIN_TRUSTED_FIELD_SAMPLE ? 'text-muted' : ''}`}>
            {formatPercent(f.share)}%
          </span>,
          <WonCell key="won" rate={f.your_rate} />,
          <RateCell key="rate" rate={f.your_rate} withRange={false} />,
        ])}
      />
    </Card>
  )
}
