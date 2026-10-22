import { useTranslation } from 'react-i18next'
import type { MetaPresence } from '../../api'
import type { FieldRecord } from '../../lib/home'
import { formatPercent } from '../../lib/format'
import { topTwoTile } from '../../lib/field'
import { formatCount } from '../../lib/time'
import { StatTile } from '../ui'

/** Two tiles, a row from 48rem, stacked under it: the most played deck,
 *  leading over two of the three columns, its share and the lists of the
 *  tier in the window it is counted from; and the viewer's record against
 *  the top two (or the one) over every deck of theirs. The caller draws
 *  them only when the tier has a row. */
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
  const { t } = useTranslation()
  const top = rows[0]
  const against = topTwoTile(topTwo, when, t)
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {/* A grid of one, so the tile stretches to the row's height. */}
      <div className="grid md:col-span-2">
        <StatTile
          label={t('field.tiles.mostPlayed')}
          value={top.label}
          detail={t('field.tiles.mostPlayedOf', {
            count: lists,
            n: formatCount(lists),
            pct: formatPercent(top.share),
            kind,
            when,
          })}
        />
      </div>
      <StatTile
        label={rows.length === 1 ? t('field.tiles.againstOne') : t('field.tiles.againstTwo')}
        value={against.value}
        muted={against.muted}
        detail={against.detail}
      />
    </div>
  )
}
