import { memo, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Weeks } from '../../lib/home'
import { RATE_MIN_MATCHES } from '../../lib/home'
import { formatCount, formatPercent, formatShortDay } from '../../lib/time'
import { useTokens } from '../../theme'
import { ChartTooltip } from '../ChartTooltip'
import { axisProps, gridProps } from '../chartChrome'
import { Card, DataTable, Disclosure } from '../ui'

/** The chart's least height: tall enough to read a trend across twelve
 *  weeks. Beside the recent matches it takes whatever height their card
 *  leaves it, so the two cards end on one line. */
const CHART_MIN_HEIGHT = 'min-h-[200px]'

type Point = { label: string; rate: number | null; played: number; won: number }

/** Finished matches by week, as a line on 0 to 100%: a dashed line at 50%
 *  (a threshold, "even"), the last point labelled with its rate, a hollow
 *  dot for a week under ten matches, no line across a week with none. The
 *  numbers under a disclosure. One week alone is a sentence.
 *
 *  Rendered only when the weeks or the year change (`memo`, and
 *  `yearStart` in place of the clock: a short date reads the time for its
 *  year alone). Any render moves the chart: its axes' props are new
 *  objects each time, recharts stores them again, the line's points come
 *  out a new array, and a new array starts the line's motion over; the
 *  last point's label is drawn only once that motion ends. */
export const WeeklyWinrate = memo(function WeeklyWinrate({
  weeks,
  yearStart,
}: {
  weeks: Weeks
  /** 00:00 on 1 January of the current year, in ms. */
  yearStart: number
}) {
  const { t } = useTranslation()
  const tokens = useTokens()
  // The chart's data keeps its identity while the weeks do not change.
  const points: Point[] = useMemo(
    () =>
      weeks.weeks.map((week) => ({
        label: formatShortDay(week.start, yearStart),
        rate: week.rate == null ? null : Math.round(week.rate * 100),
        played: week.played,
        won: week.won,
      })),
    [weeks, yearStart],
  )
  // The chart is drawn anew when its box changes height (the numbers
  // opening or closing), so the line draws in at its new size rather than
  // gliding across the axis from where it was.
  const [chartHeight, setChartHeight] = useState(0)

  const played = weeks.weeks.filter((week) => week.played > 0)
  if (played.length === 0) return null

  const lastIndex = points.findLastIndex((point) => point.rate != null)
  const thin = played.some((week) => week.played < RATE_MIN_MATCHES)

  if (played.length === 1) {
    const [week] = played
    return (
      <Card title={t('home.weekly.title')} className="h-full">
        <p className="text-body text-ink2">
          {t('home.weekly.single', {
            won: formatCount(week.won),
            played: formatCount(week.played),
            week: formatShortDay(week.start, yearStart),
          })}
        </p>
      </Card>
    )
  }

  return (
    <Card title={t('home.weekly.title')} className="flex h-full flex-col">
      {/* The chart fills what the card has left; it is laid over its box
          rather than sizing it, so the chart's own size never feeds back
          into the card's. */}
      <div className={`relative flex-1 ${CHART_MIN_HEIGHT}`}>
        <div className="absolute inset-0">
          <ResponsiveContainer
            width="100%"
            height="100%"
            onResize={(_, height) => setChartHeight(Math.round(height))}
          >
            <LineChart key={chartHeight} data={points} margin={{ top: 20, left: 0, right: 16 }}>
              <CartesianGrid {...gridProps(tokens)} />
              <XAxis dataKey="label" {...axisProps(tokens)} interval="preserveStartEnd" minTickGap={16} />
              <YAxis width={40} domain={[0, 100]} ticks={[0, 50, 100]} unit="%" {...axisProps(tokens)} />
              <ReferenceLine
                y={50}
                stroke={tokens.muted}
                strokeDasharray="4 4"
                label={{ value: t('home.weekly.even'), position: 'insideBottomLeft', fill: tokens.muted, fontSize: 12 }}
              />
              <Tooltip
                content={({ active, payload, label }) => (
                  <ChartTooltip
                    active={active}
                    payload={payload}
                    label={label}
                    labelFormat={(week) => t('home.weekly.weekOfLabel', { week })}
                    format={(value) => `${value}%`}
                  />
                )}
              />
              <Line
                dataKey="rate"
                name={t('home.weekly.winRate')}
                stroke={tokens.self}
                strokeWidth={2}
                connectNulls={false}
                dot={(props: { cx?: number; cy?: number; index?: number; payload?: Point }) => {
                  const { cx, cy, index, payload } = props
                  if (cx == null || cy == null || payload?.rate == null) return <g key={`dot-${index}`} />
                  const hollow = payload.played < RATE_MIN_MATCHES
                  return (
                    <circle
                      key={`dot-${index}`}
                      cx={cx}
                      cy={cy}
                      r={hollow ? 3.5 : 3}
                      strokeWidth={2}
                      stroke={hollow ? tokens.self : tokens.surface}
                      fill={hollow ? tokens.surface : tokens.self}
                    />
                  )
                }}
                activeDot={{ r: 4, strokeWidth: 2, stroke: tokens.surface }}
              >
                <LabelList
                  dataKey="rate"
                  content={(props: { x?: number | string; y?: number | string; index?: number; value?: unknown }) => {
                    if (props.index !== lastIndex || typeof props.value !== 'number') return null
                    return (
                      <text
                        x={Number(props.x)}
                        y={Number(props.y) - 10}
                        textAnchor="middle"
                        fill={tokens.ink}
                        fontSize={12}
                        fontWeight={600}
                      >
                        {props.value}%
                      </text>
                    )
                  }}
                />
              </Line>
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="mt-3 space-y-1 text-caption text-muted">
        {thin && <p>{t('home.weekly.hollow')}</p>}
        {weeks.truncated && <p>{t('home.weekly.truncated')}</p>}
      </div>
      <div className="mt-3">
        <Disclosure summary={t('home.weekly.showNumbers')}>
          <DataTable
            columns={[t('home.weekly.weekOf'), t('home.weekly.matches'), t('home.weekly.won'), t('home.weekly.winRate')]}
            rows={weeks.weeks
              .filter((week) => week.played > 0)
              .map((week) => [
                formatShortDay(week.start, yearStart),
                formatCount(week.played),
                formatCount(week.won),
                `${formatPercent(week.won / week.played)}%`,
              ])}
          />
        </Disclosure>
      </div>
    </Card>
  )
})
