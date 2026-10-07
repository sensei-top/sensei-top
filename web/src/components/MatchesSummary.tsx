import type { Match } from '../api'
import { formatCount, formatPercent } from '../lib/time'
import { StatTile } from './ui'

type Counts = { finished: number; won: number; games: number; gamesWon: number }

/** Counted over every match in hand, not only the rows shown, so the band
 *  and the list never disagree. A finished match is a win, a loss or a
 *  draw; games are each row's own games won and lost, finished match or
 *  not. */
function count(matches: Match[]): Counts {
  const counts: Counts = { finished: 0, won: 0, games: 0, gamesWon: 0 }
  for (const match of matches) {
    if (match.result === 'win' || match.result === 'loss' || match.result === 'draw') {
      counts.finished += 1
      if (match.result === 'win') counts.won += 1
    }
    counts.games += (match.games_won ?? 0) + (match.games_lost ?? 0)
    counts.gamesWon += match.games_won ?? 0
  }
  return counts
}

/** Matches won and games won, for the filter in force. With nothing to
 *  divide by the number is an em dash and the line says so. `full` is a
 *  list cut at the route's maximum: a caption says what was counted. One
 *  row of two from 48rem up, stacked under it. */
export function MatchesSummary({ matches, full }: { matches: Match[]; full: boolean }) {
  const { finished, won, games, gamesWon } = count(matches)
  return (
    <div className="space-y-2">
      <div className="grid gap-4 md:grid-cols-2">
        <StatTile
          label="Matches won"
          value={finished ? `${formatPercent(won / finished)}%` : '—'}
          detail={
            finished
              ? `${formatCount(won)} of ${formatCount(finished)} finished ${finished === 1 ? 'match' : 'matches'}`
              : 'No finished matches'
          }
        />
        <StatTile
          label="Games won"
          value={games ? `${formatPercent(gamesWon / games)}%` : '—'}
          detail={
            games
              ? `${formatCount(gamesWon)} of ${formatCount(games)} finished ${games === 1 ? 'game' : 'games'}`
              : 'No finished games'
          }
        />
      </div>
      {full && <p className="text-caption text-muted">Counted over the {formatCount(matches.length)} newest matches.</p>}
    </div>
  )
}
