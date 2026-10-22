import { useTranslation } from 'react-i18next'
import { usePlayDraw, type Match } from '../api'
import { playDrawTile, playDrawTotals } from '../lib/deckOverview'
import { NBSP } from '../lib/matchups'
import { rateOrRecord } from '../lib/sample'
import { formatCount } from '../lib/time'
import { ErrorNote, StatTile } from './ui'

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

/** Matches, games and play vs draw, for the filter in force. Matches and
 *  games by the small-sample rule (`rateOrRecord`): from ten the rate with
 *  the record under it; five to nine the rate, muted, over the record and
 *  "rough"; under five the record, muted, and the line saying it is too few
 *  for a rate; with nothing finished an em dash and the line says so. Play
 *  vs draw is the deck strip's tile (`playDrawTile`), read from
 *  `/api/metrics/play-draw` under the same deck and source: while it loads
 *  it holds its label and an empty tile, when it fails it is the error, and
 *  the other two never wait for it. `full` is a list cut at the route's
 *  maximum: a caption says what was counted, and that play and draw count
 *  every game regardless. One row of three from 48rem up, stacked under
 *  it. */
export function MatchesSummary({
  matches,
  full,
  deckId,
  source,
}: {
  matches: Match[]
  full: boolean
  deckId?: string
  source?: string
}) {
  const { t } = useTranslation()
  const playDraw = usePlayDraw(deckId, source)
  const { won, lost, gamesWon, gamesLost } = count(matches)
  const matchesTile = rateOrRecord({ wins: won, losses: lost }, t)
  const gamesTile = rateOrRecord({ wins: gamesWon, losses: gamesLost }, t, 'games')
  const sides = playDraw.data ? playDrawTile(playDrawTotals(playDraw.data), t) : null
  return (
    <div className="space-y-2">
      <div className="grid gap-4 md:grid-cols-3">
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
        {playDraw.error ? (
          <ErrorNote error={playDraw.error} />
        ) : sides ? (
          <StatTile
            label={sides.label}
            value={sides.value}
            detail={sides.detail}
            muted={sides.thin}
          />
        ) : (
          <div className="animate-pulse" role="status" aria-label={t('common.loading')}>
            {/* A plain space collapses the value and detail lines, and the band would jump. */}
            <StatTile label={t('decks.strip.playDraw')} value={NBSP} detail={NBSP} />
          </div>
        )}
      </div>
      {full && (
        <p className="text-caption text-muted">
          {t('matches.summary.counted', { n: formatCount(matches.length) })} {t('matches.summary.playDrawAll')}
        </p>
      )}
    </div>
  )
}
