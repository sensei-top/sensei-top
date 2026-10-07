import { memo } from 'react'
import type { CurrentTurn, PositionPoint } from '../../api'
import { useTokens } from '../../theme'
import { PositionTrack } from '../PositionTrack'
import { TurnChart } from '../TurnChart'

const POSITION_SUBTITLE =
  'Life, board, hand and mana weighed into one number, turn by turn. Above zero you are ahead.'

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
  const t = useTokens()
  const track = (positionTrack ?? []).filter((point) => point.game_number === gameNumber)
  if (track.length === 0 && turns.length === 0) return null

  const hasDot = turningPointTurn != null && track.some((point) => point.turn_number === turningPointTurn)
  const syncId = `match-charts-${gameNumber}`

  return (
    <div className="space-y-6">
      {track.length > 0 && (
        <PositionTrack
          title="Position"
          subtitle={hasDot ? `${POSITION_SUBTITLE} The dot is the game's largest swing.` : POSITION_SUBTITLE}
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
              You
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-0.5 w-4 rounded-pill bg-s2" />
              Opponent
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-0.5 w-4 rounded-pill bg-s3" />
              Your lands, on Board only
            </span>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <TurnChart
              title="Life"
              subtitle="Both players, turn by turn."
              data={turns}
              height={180}
              showLegend={false}
              syncId={syncId}
              series={[
                { key: 'self_life', name: 'You', color: t.self },
                { key: 'opp_life', name: 'Opponent', color: t.opponent },
              ]}
            />
            <TurnChart
              title="Cards in hand"
              subtitle="The opponent's cards are hidden, and still counted."
              data={turns}
              height={180}
              showLegend={false}
              syncId={syncId}
              series={[
                { key: 'self_hand', name: 'You', color: t.self },
                { key: 'opp_hand', name: 'Opponent', color: t.opponent },
              ]}
            />
            <TurnChart
              title="Board"
              subtitle="The permanents on each side, and your lands among yours."
              data={turns}
              height={180}
              showLegend={false}
              syncId={syncId}
              series={[
                { key: 'self_permanents', name: 'Your permanents', color: t.self },
                { key: 'opp_permanents', name: 'Their permanents', color: t.opponent },
                { key: 'self_lands', name: 'Your lands', color: t.field },
              ]}
            />
          </div>
        </div>
      )}
    </div>
  )
})
