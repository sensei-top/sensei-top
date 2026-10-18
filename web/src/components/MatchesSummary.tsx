import { useTranslation } from 'react-i18next'
import type { Match } from '../api'
import { rateOrRecord } from '../lib/sample'
import { formatCount } from '../lib/time'
import { StatTile } from './ui'

type Counts = { won: number; lost: number; gamesWon: number; gamesLost: number }

/** Counted over every match in hand, not only the rows shown, so the band
 *  and the list never disagree. Matches are the wins and the losses among
 *  the finished ones: a draw is neither (`docs/design-system.md`,
 *  "Numbers"). Games are each row's own games won and lost, finished match
 *  or not. */
function count(matches: Match[]): Counts {
  const counts: Counts = { won: 0, lost: 0, gamesWon: 0, gamesLost: 0 }
  for (const match of matches) {
    if (match.result === 'win') counts.won += 1
    else if (match.result === 'loss') counts.lost += 1
    counts.gamesWon += match.games_won ?? 0
    counts.gamesLost += match.games_lost ?? 0
  }
  return counts
}

/** Matches and games, for the filter in force, by the small-sample rule
 *  (`rateOrRecord`): from ten the rate with the record under it, under ten
 *  the record, muted, and the line saying it is too few for a rate; with
 *  nothing finished an em dash and the line says so. `full` is a list cut at
 *  the route's maximum: a caption says what was counted. One row of two from
 *  48rem up, stacked under it. */
export function MatchesSummary({ matches, full }: { matches: Match[]; full: boolean }) {
  const { t } = useTranslation()
  const { won, lost, gamesWon, gamesLost } = count(matches)
  const matchesTile = rateOrRecord({ wins: won, losses: lost }, t)
  const gamesTile = rateOrRecord({ wins: gamesWon, losses: gamesLost }, t, 'games')
  return (
    <div className="space-y-2">
      <div className="grid gap-4 md:grid-cols-2">
        <StatTile
          label={t('matches.summary.matchesWon')}
          value={matchesTile.figure ?? '—'}
          detail={matchesTile.line}
          muted={matchesTile.thin}
        />
        <StatTile
          label={t('matches.summary.gamesWon')}
          value={gamesTile.figure ?? '—'}
          detail={gamesTile.line}
          muted={gamesTile.thin}
        />
      </div>
      {full && (
        <p className="text-caption text-muted">{t('matches.summary.counted', { n: formatCount(matches.length) })}</p>
      )}
    </div>
  )
}
