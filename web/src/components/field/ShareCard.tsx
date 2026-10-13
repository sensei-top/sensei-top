import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { MetaPresence } from '../../api'
import { SHARE_SHOWN, shownRows } from '../../lib/field'
import type { FieldRecord } from '../../lib/home'
import { HOME_MATCH_LIMIT } from '../../lib/home'
import { formatCount } from '../../lib/time'
import { Card, EmptyState } from '../ui'
import { FieldRow } from './FieldRow'
import { ShowAll } from './ShowAll'

/** "What is being played": the tier's decks in the window, the most played
 *  first, each with its share, its lists and the viewer's record against
 *  it; twelve, then the rest behind a button. Under the list, what the bars
 *  and the lines are, and when they need it, that the record is cut short
 *  and that a league's lists are only its undefeated ones. */
export function ShareCard({
  rows,
  lists,
  records,
  kind,
  when,
  action,
  short,
  league,
}: {
  rows: MetaPresence[]
  lists: number
  /** The viewer's record against each row, in the rows' order. */
  records: FieldRecord[]
  kind: string
  when: string
  action: string
  /** The match list is full and does not reach back to the window. */
  short: boolean
  league: boolean
}) {
  const { t } = useTranslation()
  const [all, setAll] = useState(false)
  const actionNode = <span className="text-caption text-muted">{action}</span>
  if (rows.length === 0) {
    return (
      <Card title={t('field.share.title')} action={actionNode}>
        <EmptyState message={t('field.share.empty', { kind, when })} />
      </Card>
    )
  }
  const shown = shownRows(rows, SHARE_SHOWN, all)
  return (
    <Card title={t('field.share.title')} action={actionNode}>
      <ul className="space-y-3">
        {shown.map((row, index) => (
          <FieldRow
            key={`${row.archetype_key}:${row.label}`}
            presence={row}
            record={records[index]}
            notPlayed={t('field.share.notPlayed', { when })}
            lists={row.decks}
          />
        ))}
      </ul>
      {shown.length < rows.length && <ShowAll total={rows.length} onShow={() => setAll(true)} />}
      <div className="mt-4 space-y-1 text-caption text-muted">
        <p>
          {t('field.share.bars', { lists: formatCount(lists), kind, when })}
        </p>
        {short && <p>{t('field.share.short', { n: formatCount(HOME_MATCH_LIMIT) })}</p>}
        {league && <p>{t('field.share.league')}</p>}
      </div>
    </Card>
  )
}
