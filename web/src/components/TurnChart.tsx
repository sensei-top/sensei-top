import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { CurrentTurn } from '../api'
import { ChartTooltip } from './ChartTooltip'
import { axisProps, gridProps } from './chartChrome'
import { Card } from './ui'
import { useTokens } from '../theme'

export type SeriesSpec = { key: keyof CurrentTurn; name: string; color: string }

/**
 * One game's actual numbers, not an average — so unlike the aggregate metric
 * charts the y-axis is left to fit the data: life can climb past 20 in a
 * single game, and clamping it would silently flatten exactly the game worth
 * looking at.
 */
export function TurnChart({
  title,
  subtitle,
  data,
  series,
  height = 220,
  showLegend = true,
  syncId,
}: {
  title: string
  subtitle: string
  data: CurrentTurn[]
  series: SeriesSpec[]
  height?: number
  /** Off when a shared legend above several `TurnChart`s already says the
   *  same thing once — the match-detail trio's own legend, e.g. */
  showLegend?: boolean
  /** Recharts' own hover-sync id: charts sharing one id crosshair together,
   *  which is the point of the match-detail trio sharing this prop. */
  syncId?: string
}) {
  const t = useTokens()
  return (
    <Card title={title} subtitle={subtitle}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, left: 0, right: 12 }} syncId={syncId}>
          <CartesianGrid {...gridProps(t)} />
          <XAxis dataKey="turn_number" {...axisProps(t)} />
          <YAxis width={40} domain={[0, 'auto']} allowDecimals={false} {...axisProps(t)} />
          <Tooltip
            content={({ active, payload, label }) => (
              <ChartTooltip
                active={active}
                payload={payload}
                label={label}
                t={t}
                labelPrefix="Turn "
              />
            )}
          />
          {showLegend && (
            <Legend
              iconType="plainline"
              wrapperStyle={{ fontSize: 13, color: t.muted, paddingTop: 4 }}
            />
          )}
          {series.map((s) => (
            <Line
              key={String(s.key)}
              type="monotone"
              dataKey={s.key as string}
              name={s.name}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: t.surface }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </Card>
  )
}
