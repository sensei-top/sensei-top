import { useState } from 'react'
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
  const [all, setAll] = useState(false)
  const actionNode = <span className="text-caption text-muted">{action}</span>
  if (rows.length === 0) {
    return (
      <Card title="What is being played" action={actionNode}>
        <EmptyState message={`No lists from ${kind} ${when}.`} />
      </Card>
    )
  }
  const shown = shownRows(rows, SHARE_SHOWN, all)
  return (
    <Card title="What is being played" action={actionNode}>
      <ul className="space-y-3">
        {shown.map((row, index) => (
          <FieldRow
            key={`${row.archetype_key}:${row.label}`}
            presence={row}
            record={records[index]}
            notPlayed={`not played ${when}`}
            lists={row.decks}
          />
        ))}
      </ul>
      {shown.length < rows.length && <ShowAll total={rows.length} onShow={() => setAll(true)} />}
      <div className="mt-4 space-y-1 text-caption text-muted">
        <p>
          {`Each bar is a deck's share of ${formatCount(lists)} lists from ${kind} ${when}. The line under each is your own record against it in the same period, with any of your decks.`}
        </p>
        {short && <p>{`Your record is counted over your last ${formatCount(HOME_MATCH_LIMIT)} matches.`}</p>}
        {league && (
          <p>A league publishes only its undefeated lists, so this is what wins leagues, not all that is played.</p>
        )}
      </div>
    </Card>
  )
}
