import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { MetaWinrate } from '../../api'
import { WINRATE_SHOWN, matchesOf, shownRows } from '../../lib/field'
import { formatCount, formatPercent } from '../../lib/time'
import { Card, DataTable, EmptyState, ManaPips } from '../ui'
import { ShowAll } from './ShowAll'

/** "How the field wins": each archetype's win rate over paper tournaments
 *  and MTGO challenges together, whatever tier the share is counted in (a
 *  league publishes no losses), with its matches beside it, never alone.
 *  `rows` are `winrateRows`'s, already cut to two matches or more and
 *  sorted; twelve, then the rest behind a button. The four columns fit a
 *  360 px screen as the Guide's field table does: the name takes what the
 *  numbers leave and breaks inside a word if it must. */
export function WinrateCard({ rows, when, action }: { rows: MetaWinrate[]; when: string; action: string }) {
  const { t } = useTranslation()
  const [all, setAll] = useState(false)
  const shown = shownRows(rows, WINRATE_SHOWN, all)
  return (
    <Card
      title={t('field.winrate.title')}
      action={<span className="text-caption text-muted">{action}</span>}
      subtitle={t('field.winrate.subtitle')}
    >
      {rows.length === 0 ? (
        <EmptyState message={t('field.winrate.empty', { when })} />
      ) : (
        <>
          <DataTable
            columns={[
              t('field.winrate.columns.archetype'),
              t('field.winrate.columns.winRate'),
              t('field.winrate.columns.matches'),
              t('field.winrate.columns.lists'),
            ]}
            rows={shown.map((row) => [
              // `wrap-anywhere`, not `break-words`: in a table only
              // `overflow-wrap: anywhere` lets a long word shrink the column.
              <div key="archetype" className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <ManaPips colors={row.colors} />
                <span className="min-w-0 wrap-anywhere">{row.label}</span>
              </div>,
              <span key="rate" className="whitespace-nowrap">
                {row.winrate != null ? `${formatPercent(row.winrate)}%` : null}
              </span>,
              formatCount(matchesOf(row)),
              formatCount(row.entries),
            ])}
          />
          {shown.length < rows.length && <ShowAll total={rows.length} onShow={() => setAll(true)} />}
        </>
      )}
    </Card>
  )
}
