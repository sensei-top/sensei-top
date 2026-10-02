import { useState } from 'react'
import type { MetaMatchup } from '../../api'
import type { Pairs } from '../../lib/field'
import { MATCHUPS_SHOWN, MATCHUP_THIN, PAIRS, PAIRS_OPTION, noPairsMessage, shownRows } from '../../lib/field'
import { NBSP } from '../../lib/matchups'
import { formatCount, formatPercent } from '../../lib/time'
import { Button, Card, DataTable, EmptyState, ErrorNote, Loading, Segmented } from '../ui'
import { CONTROL_ROW, SEGMENTED_OPTIONS } from './FieldControls'
import { ShowAll } from './ShowAll'

const PAIRS_OPTIONS = PAIRS.map((pairs) => ({ value: pairs, label: PAIRS_OPTION[pairs] }))

/** The empty card's button, by the step it takes: AB adds MTGO challenges,
 *  ABD smaller paper events. */
const nextAction = (next: Pairs) => (next === 'AB' ? 'Count MTGO challenges too' : 'Count smaller paper events too')

/** "3–1–0": won, lost and drawn, en dashes, as a score. */
const score = (row: MetaMatchup) =>
  `${formatCount(row.matches_won)}–${formatCount(row.matches_lost)}–${formatCount(row.matches_drawn)}`

/** The rate after the score, muted on fewer than five matches; nothing
 *  where the API sends none. */
function Rate({ row }: { row: MetaMatchup }) {
  if (row.winrate == null) return null
  return <span className={row.n < MATCHUP_THIN ? 'text-muted' : ''}>{`, ${formatPercent(row.winrate)}%`}</span>
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
  const [all, setAll] = useState(false)
  const shown = rows ? shownRows(rows, MATCHUPS_SHOWN, all) : []

  let body
  if (error) body = <ErrorNote error={error} />
  else if (isPending || !rows) body = <Loading />
  else if (rows.length === 0)
    body = (
      <EmptyState
        message={noPairsMessage(pairs, when)}
        action={
          next && (
            <Button className="min-h-[44px]" onClick={() => onPairs(next)}>
              {nextAction(next)}
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
            columns={['Archetype', 'Against', 'Matches', 'Record']}
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
              <p className="text-body font-medium text-ink">{`${row.label} against ${row.opponent_label}`}</p>
              <p className="text-caption text-ink2 tabular-nums">
                {row.n === 1 ? `1${NBSP}match, ` : `${formatCount(row.n)}${NBSP}matches, `}
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
      title="Archetype against archetype"
      action={<span className="text-caption text-muted">{action}</span>}
      subtitle="Rounds between two named decks. A rate on fewer than five matches is muted: too few to lean on."
    >
      {pairs && (
        <div className={`mb-4 ${CONTROL_ROW}`}>
          <span aria-hidden className="shrink-0 text-muted">
            Counted from
          </span>
          <Segmented
            label="Counted from"
            value={pairs}
            options={PAIRS_OPTIONS}
            onChange={onPairs}
            className={SEGMENTED_OPTIONS}
          />
        </div>
      )}
      {body}
    </Card>
  )
}
