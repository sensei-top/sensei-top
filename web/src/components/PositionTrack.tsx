import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { PositionPoint } from '../api'
import { ChartTooltip } from './ChartTooltip'
import { axisProps, gridProps } from './chartChrome'
import { Card, DataTable, Disclosure } from './ui'
import { useTokens } from '../theme'

/**
 * review/position.py's index, turn by turn — a transparent, fixed-weight
 * approximation over life/board/hand/mana, never fitted to outcomes (see
 * that module's own docstring for the measured separation this produced
 * against real games). Positive means ahead, negative means behind; the
 * zero line is the only reference this chart needs. The turning point, when
 * one exists, gets its own marker rather than a second series — it is a
 * single point, not a trend. The numbers under the line are one click
 * away, behind a disclosure.
 */
export function PositionTrack({
  title,
  subtitle,
  data,
  turningPointTurn,
}: {
  title: string
  subtitle: string
  data: PositionPoint[]
  turningPointTurn?: number | null
}) {
  const t = useTokens()
  if (data.length === 0) return null
  const turningPoint =
    turningPointTurn != null ? data.find((d) => d.turn_number === turningPointTurn) : undefined

  return (
    <Card title={title} subtitle={subtitle}>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data} margin={{ top: 8, left: 0, right: 12 }}>
          <CartesianGrid {...gridProps(t)} />
          <XAxis dataKey="turn_number" {...axisProps(t)} />
          <YAxis width={44} domain={[-1, 1]} allowDecimals {...axisProps(t)} />
          {/* The one chart whose zero line carries meaning (ahead/behind),
              not just an axis origin — drawn heavier than an ordinary
              gridline for that reason. */}
          <ReferenceLine y={0} stroke={t.ink2} strokeWidth={2} />
          <Tooltip
            content={({ active, payload, label }) => (
              <ChartTooltip
                active={active}
                payload={payload}
                label={label}
                t={t}
                labelPrefix="Turn "
                format={(value) => value.toFixed(2)}
              />
            )}
          />
          <Line
            type="monotone"
            dataKey="index"
            name="Position"
            stroke={t.self}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: t.surface }}
            connectNulls
          />
          {turningPoint && (
            <ReferenceDot
              x={turningPoint.turn_number}
              y={turningPoint.index}
              r={5}
              fill={t.opponent}
              stroke={t.surface}
              strokeWidth={2}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
      <div className="mt-3">
        <Disclosure summary="Show the numbers">
          <DataTable
            columns={['Turn', 'Position']}
            rows={data.map((d) => [String(d.turn_number), d.index.toFixed(2)])}
          />
        </Disclosure>
      </div>
    </Card>
  )
}
