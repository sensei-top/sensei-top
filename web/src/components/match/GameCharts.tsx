import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import type { CurrentTurn, PositionPoint } from '../../api'
import { useTokens } from '../../theme'
import { PositionTrack } from '../PositionTrack'
import { TurnChart } from '../TurnChart'

/** One game's numbers: its position, then life, cards in hand and board,
 *  with one legend over the three. Memoized, and given nothing that
 *  changes with the replay's chosen turn, so choosing a turn never starts
 *  a chart's motion again (docs/design-system.md, "Motion"). Draws nothing
 *  for a game with neither turns nor a position line. */
export const GameCharts = memo(function GameCharts({
  gameNumber,
  turns,
  positionTrack,
  turningPointTurn,
}: {
  gameNumber: number
  /** The game's turns, as the query returned them. */
  turns: CurrentTurn[]
  /** The whole match's position line, as the query returned it; this
   *  game's points are taken from it here. */
  positionTrack: PositionPoint[] | undefined
  turningPointTurn: number | null
}) {
  const { t } = useTranslation()
  const tokens = useTokens()
  const track = (positionTrack ?? []).filter((point) => point.game_number === gameNumber)
  if (track.length === 0 && turns.length === 0) return null

  const hasDot = turningPointTurn != null && track.some((point) => point.turn_number === turningPointTurn)
  const syncId = `match-charts-${gameNumber}`

  return (
    <div className="space-y-6">
      {track.length > 0 && (
        <PositionTrack
          title={t('matches.charts.position')}
          subtitle={hasDot ? t('matches.charts.positionSubtitleDot') : t('matches.charts.positionSubtitle')}
          data={track}
          turningPointTurn={turningPointTurn}
        />
      )}

      {turns.length > 0 && (
        <div className="space-y-2">
          {/* One legend for the three, since "You" and "Opponent" are the
              same colours in each; hovering one crosshairs all three through
              recharts' own syncId. */}
          <div className="flex flex-wrap items-center gap-4 text-caption text-muted">
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-0.5 w-4 rounded-pill bg-s1" />
              {t('matches.you')}
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-0.5 w-4 rounded-pill bg-s2" />
              {t('matches.opponent')}
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-0.5 w-4 rounded-pill bg-s3" />
              {t('matches.charts.landsLegend')}
            </span>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <TurnChart
              title={t('matches.charts.life')}
              subtitle={t('matches.charts.lifeSubtitle')}
              data={turns}
              height={180}
              showLegend={false}
              syncId={syncId}
              series={[
                { key: 'self_life', name: t('matches.you'), color: tokens.self },
                { key: 'opp_life', name: t('matches.opponent'), color: tokens.opponent },
              ]}
            />
            <TurnChart
              title={t('matches.charts.hand')}
              subtitle={t('matches.charts.handSubtitle')}
              data={turns}
              height={180}
              showLegend={false}
              syncId={syncId}
              series={[
                { key: 'self_hand', name: t('matches.you'), color: tokens.self },
                { key: 'opp_hand', name: t('matches.opponent'), color: tokens.opponent },
              ]}
            />
            <TurnChart
              title={t('matches.charts.board')}
              subtitle={t('matches.charts.boardSubtitle')}
              data={turns}
              height={180}
              showLegend={false}
              syncId={syncId}
              series={[
                { key: 'self_permanents', name: t('matches.charts.yourPermanents'), color: tokens.self },
                { key: 'opp_permanents', name: t('matches.charts.theirPermanents'), color: tokens.opponent },
                { key: 'self_lands', name: t('matches.charts.yourLands'), color: tokens.field },
              ]}
            />
          </div>
        </div>
      )}
    </div>
  )
})
