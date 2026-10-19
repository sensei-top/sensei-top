import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from '../../i18n'
import type { MetaMatchup } from '../../api'
import type { Pairs } from '../../lib/field'
import { MATCHUPS_SHOWN, PAIRS, noPairsMessage, pairsOption, shownRows } from '../../lib/field'
import { formatPercent } from '../../lib/format'
import { MIN_TRUSTED_FIELD_SAMPLE } from '../../lib/sample'
import { formatCount } from '../../lib/time'
import { Button, Card, DataTable, EmptyState, ErrorNote, Loading, Segmented } from '../ui'
import { CONTROL_ROW, SEGMENTED_OPTIONS } from './FieldControls'
import { ShowAll } from './ShowAll'

/** The empty card's button, by the step it takes: AB adds MTGO challenges,
 *  ABD smaller paper events. */
const nextAction = (next: Pairs, t: TFunction) =>
  next === 'AB' ? t('field.matchups.nextAB') : t('field.matchups.nextABD')

/** "3–1–0": won, lost and drawn, en dashes, as a score. */
const score = (row: MetaMatchup) =>
  `${formatCount(row.matches_won)}–${formatCount(row.matches_lost)}–${formatCount(row.matches_drawn)}`

/** The rate after the score, muted on fewer than five matches; nothing
 *  where the API sends none. */
function Rate({ row }: { row: MetaMatchup }) {
  if (row.winrate == null) return null
  return <span className={row.n < MIN_TRUSTED_FIELD_SAMPLE ? 'text-muted' : ''}>{`, ${formatPercent(row.winrate)}`}</span>
}

/** "Archetype against archetype": which tiers the rounds are counted over,
 *  then every pair, the most matches first (`matchupRows`' order), twenty
 *  and then the rest. From 48rem a table of four columns; under it each
 *  pair is two lines, as the Guide's key-card timing does. `n` is always
 *  shown. Empty, it says so, naming the tiers counted, and offers the next
 *  step (`next`, `nextPairs`) when that step's tier has lists in the
 *  window. `pairs` is `null` until the lists say which is the default, and
 *  the rows wait for it. */
export function MatchupsCard({
  pairs,
  rows,
  isPending,
  error,
  next,
  when,
  action,
  onPairs,
}: {
  pairs: Pairs | null
  rows: MetaMatchup[] | undefined
  isPending: boolean
  error: Error | null
  next: Pairs | null
  when: string
  action: string
  onPairs: (pairs: Pairs) => void
}) {
  const { t } = useTranslation()
  const pairsOptions = PAIRS.map((each) => ({ value: each, label: pairsOption(each, t) }))
  const [all, setAll] = useState(false)
  const shown = rows ? shownRows(rows, MATCHUPS_SHOWN, all) : []

  let body
  if (error) body = <ErrorNote error={error} />
  else if (isPending || !rows) body = <Loading />
  else if (rows.length === 0)
    body = (
      <EmptyState
        message={noPairsMessage(pairs, when, t)}
        action={
          next && (
            <Button className="min-h-[44px]" onClick={() => onPairs(next)}>
              {nextAction(next, t)}
            </Button>
          )
        }
      />
    )
  else
    body = (
      <>
        <div className="hidden md:block">
          <DataTable
            columns={[
              t('field.matchups.columns.archetype'),
              t('field.matchups.columns.against'),
              t('field.matchups.columns.matches'),
              t('field.matchups.columns.record'),
            ]}
            rows={shown.map((row) => [
              row.label,
              <span key="against" className="wrap-anywhere">
                {row.opponent_label}
              </span>,
              formatCount(row.n),
              <span key="record" className="whitespace-nowrap">
                {score(row)}
                <Rate row={row} />
              </span>,
            ])}
          />
        </div>
        <ul className="space-y-3 md:hidden">
          {shown.map((row) => (
            <li key={`${row.archetype_key}:${row.opponent_key}`}>
              <p className="text-body font-medium text-ink">{t('field.matchups.pair', { label: row.label, opponent: row.opponent_label })}</p>
              <p className="text-caption text-ink2 tabular-nums">
                {t('field.matchups.matches', { count: row.n, n: formatCount(row.n) })}{' '}
                {score(row)}
                <Rate row={row} />
              </p>
            </li>
          ))}
        </ul>
        {shown.length < rows.length && <ShowAll total={rows.length} onShow={() => setAll(true)} />}
      </>
    )

  return (
    <Card
      title={t('field.matchups.title')}
      action={<span className="text-caption text-muted">{action}</span>}
      subtitle={t('field.matchups.subtitle')}
    >
      {pairs && (
        <div className={`mb-4 ${CONTROL_ROW}`}>
          <span aria-hidden className="shrink-0 text-muted">
            {t('field.matchups.countedFrom')}
          </span>
          <Segmented
            label={t('field.matchups.countedFrom')}
            value={pairs}
            options={pairsOptions}
            onChange={onPairs}
            className={SEGMENTED_OPTIONS}
          />
        </div>
      )}
      {body}
    </Card>
  )
}
