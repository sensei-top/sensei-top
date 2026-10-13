import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import { Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { PositionPoint, SummaryBeat, SummaryGameLine } from '../../api'
import { resultWord } from '../../lib/events'
import { formatNumber } from '../../lib/format'
import { useTokens } from '../../theme'
import { ChartTooltip } from '../ChartTooltip'
import { axisProps } from '../chartChrome'
import {
  Card,
  Chip,
  type ChipVariant,
  type FindingWeight,
  SectionLabel,
  TextLink,
  TwoSidedMeter,
  severityChip,
} from '../ui'

type ResultChip = { variant: ChipVariant; muted?: boolean }

const RESULT: Record<string, ResultChip> = {
  win: { variant: 'win' },
  loss: { variant: 'loss' },
  draw: { variant: 'neutral' },
  incomplete: { variant: 'neutral', muted: true },
}

/** A game with no result, or one not in `RESULT`: muted, as `Incomplete` is. */
const NO_RESULT: ResultChip = { variant: 'neutral', muted: true }

/** A beat whose severity is already one of the four weights: the caller
 *  maps it (`MatchReportPanel`'s `weightOf`), so no code reaches the page. */
export type GameBeat = Omit<SummaryBeat, 'severity'> & { severity: FindingWeight }

/** A game of the report's summary, its beats weighed. */
export type WeighedGame = Omit<SummaryGameLine, 'beats'> & { beats: GameBeat[] }

/** A position, to two decimals, as `toFixed(2)` wrote it. */
const TWO_DIGITS = { minimumFractionDigits: 2, maximumFractionDigits: 2 }

/** The line's height, in pixels. */
const LINE_HEIGHT = 120

/** The smallest half-range of the line's axis: a game that never moved far
 *  from zero still reads as close, rather than filling the box. */
const MIN_REACH = 0.25

/** The axis reaches the largest distance from zero in the game, rounded up
 *  to a quarter, and never past 1, the index's own bound. */
function reachOf(points: PositionPoint[]): number {
  const largest = Math.max(0, ...points.map((point) => Math.abs(point.index)))
  return Math.min(1, Math.max(MIN_REACH, Math.ceil(largest / MIN_REACH) * MIN_REACH))
}

function tick(value: number): string {
  return value === 0 ? '0' : formatNumber(value || 0, TWO_DIGITS)
}

/** One game's position, turn by turn: the line, the zero line drawn heavier
 *  than the axis (above it you are ahead), and a dot on the turning point
 *  when the report found one. Rendered again only when its points change. */
const GameLine = memo(function GameLine({
  points,
  turningPointTurn,
  label,
}: {
  points: PositionPoint[]
  turningPointTurn: number | null
  label: string
}) {
  const { t } = useTranslation()
  const tokens = useTokens()
  const reach = reachOf(points)
  const turningPoint =
    turningPointTurn != null ? points.find((point) => point.turn_number === turningPointTurn) : undefined
  return (
    <div role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height={LINE_HEIGHT}>
        <LineChart data={points} margin={{ top: 8, left: 0, right: 8, bottom: 0 }}>
          <XAxis dataKey="turn_number" {...axisProps(tokens)} interval="preserveStartEnd" minTickGap={16} />
          <YAxis width={40} domain={[-reach, reach]} ticks={[-reach, 0, reach]} tickFormatter={tick} {...axisProps(tokens)} />
          <ReferenceLine y={0} stroke={tokens.ink2} strokeWidth={1.5} />
          <Tooltip
            content={({ active, payload, label: turn }) => (
              <ChartTooltip
                active={active}
                payload={payload}
                label={turn}
                labelFormat={(value) => t('matches.chart.turn', { turn: value })}
                format={(value) => formatNumber(value || 0, TWO_DIGITS)}
              />
            )}
          />
          <Line
            type="monotone"
            dataKey="index"
            name={t('matches.charts.position')}
            stroke={tokens.self}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: tokens.surface }}
            connectNulls
          />
          {turningPoint && (
            <ReferenceDot
              x={turningPoint.turn_number}
              y={turningPoint.index}
              r={4.5}
              fill={tokens.ink}
              stroke={tokens.surface}
              strokeWidth={2}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
})

function Beat({ beat }: { beat: GameBeat }) {
  const { t } = useTranslation()
  const weight = beat.severity
  const weightWords: Record<FindingWeight, string> = {
    decisive: t('common.finding.decisive'),
    flag: t('common.finding.flag'),
    notice: t('common.finding.notice'),
    note: t('common.finding.note'),
  }
  return (
    <li className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <SectionLabel as="span">{beat.label}</SectionLabel>
        {weight !== 'note' && (
          <Chip size="sm" {...severityChip(weight)}>
            {weightWords[weight]}
          </Chip>
        )}
      </div>
      {beat.meter && (
        <div className="max-w-40">
          <TwoSidedMeter self={beat.meter[0]} opp={beat.meter[1]} />
        </div>
      )}
      <p className="text-body text-ink">{beat.text}</p>
    </li>
  )
}

function Fact({ term, children }: { term: string; children: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-caption text-muted">{term}</dt>
      <dd className="text-right text-body text-ink">{children}</dd>
    </div>
  )
}

/** One game of the match: its result, its position line when the report
 *  has one, what is known of how it went (seat, mulligans, length, how it
 *  ended; a fact not known is not drawn), the report's beats for it, and
 *  the way to its replay. A game with no line draws no chart and no box
 *  for one. */
export function GameCard({
  game,
  points,
  turningPointTurn,
  replayHref,
}: {
  game: WeighedGame
  /** This game's points of the report's position line, in turn order. */
  points: PositionPoint[]
  turningPointTurn: number | null
  replayHref: string
}) {
  const { t } = useTranslation()
  const result = (game.result ? RESULT[game.result] : undefined) ?? NO_RESULT
  const resultText = (game.result ? resultWord(game.result, t) : undefined) ?? t('matches.result.unknown')
  const beats = game.beats
  const reason = game.result_reason_text
  const mulligans = game.self_mulligans
  return (
    <Card
      title={t('matches.game.title', { n: game.game_number })}
      action={
        <Chip size="sm" variant={result.variant} muted={result.muted}>
          {resultText}
        </Chip>
      }
      className="flex h-full flex-col"
    >
      {points.length > 0 && (
        <div className="mb-4">
          <GameLine
            points={points}
            turningPointTurn={turningPointTurn}
            label={t('matches.game.positionLabel', { n: game.game_number })}
          />
        </div>
      )}
      <dl className="space-y-1.5">
        {game.on_play != null && (
          <Fact term={t('matches.game.seat')}>{game.on_play ? t('matches.game.onPlay') : t('matches.game.onDraw')}</Fact>
        )}
        {mulligans != null && (
          <Fact term={t('matches.game.mulligans')}>{mulligans === 0 ? t('matches.game.noMulligans') : String(mulligans)}</Fact>
        )}
        {game.turn_count != null && (
          <Fact term={t('matches.game.length')}>{t('matches.game.turns', { count: game.turn_count, n: game.turn_count })}</Fact>
        )}
        {reason && <Fact term={t('matches.game.ended')}>{`${reason.charAt(0).toUpperCase()}${reason.slice(1)}`}</Fact>}
      </dl>
      {beats.length > 0 && (
        <ul className="mt-4 space-y-3 border-t border-line pt-4">
          {beats.map((beat, index) => (
            <Beat key={`${beat.code}-${index}`} beat={beat} />
          ))}
        </ul>
      )}
      <p className="mt-auto pt-4 text-caption">
        <TextLink href={replayHref}>{t('matches.game.replay', { n: game.game_number })}</TextLink>
      </p>
    </Card>
  )
}
