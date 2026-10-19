import { useTranslation } from 'react-i18next'
import type { FieldLineOut, MatchupLineOut, RateModel } from '../../api'
import {
  coachDay,
  listsWords,
  mulliganRates,
  rateWords,
  roleRates,
  variantsWords,
  type LabelledRate,
} from '../../lib/coach'
import { archetypeName } from '../../lib/decks'
import { formatPercent } from '../../lib/format'
import { MIN_TRUSTED_FIELD_SAMPLE } from '../../lib/sample'
import { Card, DataTable } from '../ui'

/** A table's Record cell (D6): wins then losses, "174–211"; a dash with no
 *  match. */
function RecordCell({ rate }: { rate: RateModel }) {
  const { record } = rateWords(rate)
  return <span className="whitespace-nowrap">{record ?? '—'}</span>
}

/** A table's Rate cell (D7): the percent over its range in caption, or the
 *  percent alone when `withRange` is false; under ten the "too few" word,
 *  muted, the record being the column beside it; a dash only with no match
 *  at all. */
function RateCell({
  rate,
  withRange = true,
  games = false,
}: {
  rate: RateModel
  withRange?: boolean
  games?: boolean
}) {
  const { t } = useTranslation()
  const words = rateWords(rate)
  if (words.record == null) return <span>—</span>
  if (words.percent == null) {
    const key = games ? 'common.sample.tooFewCellGames' : 'common.sample.tooFewCellMatches'
    return <span className="whitespace-nowrap text-muted">{t(key)}</span>
  }
  return (
    <span className="inline-flex flex-col items-end">
      <span className="whitespace-nowrap">{words.percent}</span>
      {withRange && <span className="whitespace-nowrap text-caption text-muted">{words.range}</span>}
    </span>
  )
}

/** A card of three columns: the row's word, "Record" and "Rate". */
function LabelledRatesCard({
  games = false,
  title,
  subtitle,
  first,
  rows,
}: {
  games?: boolean
  title: string
  subtitle: string
  first: string
  rows: LabelledRate[]
}) {
  const { t } = useTranslation()
  return (
    <Card title={title} subtitle={subtitle}>
      <DataTable
        columns={[first, t('coach.table.record'), t('coach.table.rate')]}
        rows={rows.map((row) => [
          <span key="label" className="wrap-anywhere">
            {row.label}
          </span>,
          <RecordCell key="record" rate={row.rate} />,
          <RateCell key="rate" rate={row.rate} games={games} />,
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
          games
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
        columns={[t('coach.table.archetype'), t('coach.table.record'), t('coach.table.rate')]}
        rows={matchups.map((m) => [
          <ArchetypeCell key="archetype" archetype={m.archetype} lines={[variantsWords(m.variants, t)]} />,
          <RecordCell key="record" rate={m.rate} />,
          <RateCell key="rate" rate={m.rate} />,
        ])}
      />
    </Card>
  )
}

/** "The field": your own record against each archetype, then its share of
 *  the tournament lists (D8). Four columns that fit 360 px, so no range. A
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
        columns={[t('coach.table.archetype'), t('coach.table.record'), t('coach.table.rate'), t('coach.table.share')]}
        rows={field.map((f) => [
          <ArchetypeCell
            key="archetype"
            archetype={f.archetype}
            lines={[listsWords(f.decks, t), variantsWords(f.variants, t)]}
          />,
          <RecordCell key="record" rate={f.your_rate} />,
          <RateCell key="rate" rate={f.your_rate} withRange={false} />,
          <span key="share" className={`whitespace-nowrap ${f.decks < MIN_TRUSTED_FIELD_SAMPLE ? 'text-muted' : ''}`}>
            {formatPercent(f.share)}
          </span>,
        ])}
      />
    </Card>
  )
}
