import type { TurningBucketOut } from '../../api'
import { turningSubtitle, turningTiles } from '../../lib/coach'
import { Card, StatTile } from '../ui'

/** "Where lost games turned": a tile a stage, one column under 48rem and
 *  three from it. Drawn only when a cell is above zero. */
export function TurningCard({ points }: { points: TurningBucketOut[] }) {
  const { lost, tiles } = turningTiles(points)
  if (points.every((p) => p.games === 0)) return null
  return (
    <Card title="Where lost games turned" subtitle={turningSubtitle(lost)}>
      <div className="grid gap-4 md:grid-cols-3">
        {tiles.map((tile) => (
          <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
        ))}
      </div>
    </Card>
  )
}
