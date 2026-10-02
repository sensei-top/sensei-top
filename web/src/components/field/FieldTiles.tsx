import type { MetaPresence } from '../../api'
import type { FieldRecord } from '../../lib/home'
import { formatCount, formatPercent } from '../../lib/time'
import { StatTile } from '../ui'

/** Three tiles, a row from 48rem, stacked under it: every list of the tier
 *  in the window, the most played deck with its share, and the viewer's
 *  record against the top two (or the one) over every deck of theirs. The
 *  caller draws them only when the tier has a row. */
export function FieldTiles({
  rows,
  lists,
  kind,
  when,
  topTwo,
}: {
  rows: MetaPresence[]
  lists: number
  kind: string
  when: string
  topTwo: FieldRecord
}) {
  const top = rows[0]
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <StatTile label="Lists read" value={formatCount(lists)} detail={`${kind} ${when}`} />
      <StatTile label="Most played" value={top.label} detail={`${formatPercent(top.share)}% of those lists`} />
      <StatTile
        label={rows.length === 1 ? 'You against the most played' : 'You against the top two'}
        value={topTwo.played > 0 ? `${formatCount(topTwo.won)} of ${formatCount(topTwo.played)}` : '0'}
        detail={topTwo.played > 0 ? 'matches won, with any of your decks' : `not met ${when}`}
      />
    </div>
  )
}
