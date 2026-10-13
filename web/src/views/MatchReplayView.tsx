import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'
import { useMatchDetail, useMatchReport, useSideboarding } from '../api'
import { GameCharts } from '../components/match/GameCharts'
import { SideboardingCard } from '../components/match/SideboardingCard'
import { TurnByTurn } from '../components/TurnByTurn'
import { BackLink, EmptyState, ErrorNote, Loading, Segmented } from '../components/ui'
import { resultWord } from '../lib/events'

/** The way back to the match's report: a link, so Back in the browser does
 *  the same. */
function BackToReport({ matchId }: { matchId: string }) {
  const { t } = useTranslation()
  return (
    <p className="text-caption">
      <BackLink href={`/matches/${encodeURIComponent(matchId)}`}>{t('matches.replay.back')}</BackLink>
    </p>
  )
}

/** A whole number from the address, or null when it holds none. */
function wholeNumber(raw: string | null): number | null {
  if (raw == null || raw.trim() === '') return null
  const value = Number(raw)
  return Number.isInteger(value) ? value : null
}

/** `/matches/:id/replay`: one game of the match at a time, and one turn of
 *  it, both in the address (`?game=2&turn=5`). No game, or one the match
 *  does not have, is the first game; no turn, or one the game does not
 *  have, is its last; `turn=0` is the opening hand, when the game has
 *  one. Choosing a game or a turn replaces the address rather than adding
 *  to the history, so Back leads to the report; choosing a game drops the
 *  turn.
 *
 *  Top to bottom: the games, the game's sideboarding, its turns, then its
 *  numbers. */
export function MatchReplayView({ matchId }: { matchId: string }) {
  const { t } = useTranslation()
  const detail = useMatchDetail(matchId)
  const report = useMatchReport(matchId)
  const sideboarding = useSideboarding(matchId)
  const [params, setParams] = useSearchParams()
  const gameNumber = wholeNumber(params.get('game'))
  const turn = wholeNumber(params.get('turn'))

  const chooseGame = (value: number) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        next.set('game', String(value))
        next.delete('turn')
        return next
      },
      { replace: true },
    )

  const chooseTurn = (value: number) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        next.set('turn', String(value))
        return next
      },
      { replace: true },
    )

  if (detail.isPending) return <Loading />
  if (detail.error) {
    return (
      <div className="space-y-4">
        <BackToReport matchId={matchId} />
        <ErrorNote error={detail.error} />
      </div>
    )
  }

  const match = detail.data
  const games = match.games
  const game = games.find((g) => g.game_number === gameNumber) ?? games[0]
  const turningPointTurn =
    game == null
      ? null
      : (report.data?.findings.find((f) => f.code === 'turning_point' && f.game_number === game.game_number)
          ?.turn_number ?? null)

  return (
    <div className="space-y-6">
      <BackToReport matchId={matchId} />

      {games.length === 0 ? (
        <EmptyState message={t('matches.replay.noGames')} />
      ) : (
        <>
          {games.length > 1 && (
            <Segmented
              label={t('matches.report.game')}
              value={game.game_number}
              options={games.map((g) => {
                const result = resultWord(g.result, t)
                return {
                  value: g.game_number,
                  label: result
                    ? t('matches.replay.gameResult', { n: g.game_number, result })
                    : t('matches.game.title', { n: g.game_number }),
                }
              })}
              onChange={chooseGame}
            />
          )}

          <SideboardingCard
            boarded={sideboarding.data?.games.find((sg) => sg.game_number === game.game_number)}
          />

          <TurnByTurn
            key={game.game_number}
            game={game}
            selfSeat={match.self_seat}
            turn={turn}
            onTurn={chooseTurn}
          />

          <GameCharts
            gameNumber={game.game_number}
            turns={game.turns}
            positionTrack={report.data?.position_track}
            turningPointTurn={turningPointTurn}
          />
        </>
      )}
    </div>
  )
}
