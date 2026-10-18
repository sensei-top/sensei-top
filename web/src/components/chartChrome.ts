import type { Tokens } from '../theme'
import { formatPercent } from '../lib/format'

/** Shared chart chrome: ticks at 12 px in the muted text colour, the grid a
 *  solid hairline in `grid`, the axis line in `axis` — never dashed, which
 *  reads as "threshold" when it is just a grid. */
export const axisProps = (t: Tokens) => ({
  stroke: t.axis,
  tick: { fill: t.muted, fontSize: 12 },
  tickLine: false,
  axisLine: { stroke: t.axis },
})

export const gridProps = (t: Tokens) => ({
  stroke: t.grid,
  strokeDasharray: '0',
  vertical: false,
})

/** recharts hands label formatters a `RenderableText`, so this accepts the
 *  widened type and narrows it itself. */
export const percentLabel = (value: unknown): string =>
  typeof value === 'number' ? formatPercent(value / 100) : ''
