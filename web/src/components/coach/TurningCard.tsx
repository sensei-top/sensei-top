import { useTranslation } from 'react-i18next'
import type { TurningBucketOut } from '../../api'
import { turningSubtitle, turningTiles } from '../../lib/coach'
import { Card, StatTile } from '../ui'

/** "Where lost games turned": a tile a stage, one column under 48rem and
 *  three from it. Drawn only when a cell is above zero. */
export function TurningCard({ points }: { points: TurningBucketOut[] }) {
  const { t } = useTranslation()
  const { lost, tiles } = turningTiles(points, t)
  if (points.every((p) => p.games === 0)) return null
  return (
    <Card title={t('coach.turning.title')} subtitle={turningSubtitle(lost, t)}>
      <div className="grid gap-4 md:grid-cols-3">
        {tiles.map((tile) => (
          <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
        ))}
      </div>
    </Card>
  )
}
