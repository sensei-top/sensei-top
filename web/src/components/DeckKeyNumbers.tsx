import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { DECK_MATCH_LIMIT, useDeckMatches, useDeckPlayDraw } from '../api'
import { deckKeyNumbers, playDrawTotals } from '../lib/deckOverview'
import { NBSP } from '../lib/matchups'
import { formatCount } from '../lib/time'
import { ErrorNote, StatTile } from './ui'

/** The deck strip, under the deck's name on every tab: Matches, Games and
 *  Play vs draw (`deckKeyNumbers`), over the versions the tab reads, then
 *  the note on how the games on the play and the draw are counted. One row
 *  of three from 48rem, stacked under it.
 *
 *  The layout and the Overview ask for the same matches with the same
 *  query, so the strip costs no second request. While either read is
 *  pending the strip holds its own height, its labels and empty tiles, so
 *  the tabs under it do not jump; where a loaded detail wraps (some widths
 *  between 768 and about 1100 px, depending on the text and language), the
 *  tabs move once by that line. When either fails, the strip's place is
 *  the error: the Guide reads neither, so nothing else would show it. A
 *  version's list cut at `DECK_MATCH_LIMIT` says what was counted, here
 *  alone: the strip is the first thing on every tab drawn from that list. */
export function DeckKeyNumbers({ versionIds }: { versionIds: string[] }) {
  const { t } = useTranslation()
  const matches = useDeckMatches(versionIds)
  const playDraw = useDeckPlayDraw(versionIds)

  const inHand = useMemo(() => matches.data?.flat() ?? null, [matches.data])
  const tiles = useMemo(
    () => (inHand && playDraw.data ? deckKeyNumbers(inHand, playDrawTotals(playDraw.data.flat()), t) : null),
    [inHand, playDraw.data, t],
  )

  const error = matches.error ?? playDraw.error
  if (error) return <ErrorNote error={error} />

  const full = (matches.data ?? []).some((list) => list.length >= DECK_MATCH_LIMIT)
  const labels = [t('decks.strip.matches'), t('decks.strip.games'), t('decks.strip.playDraw')]

  return (
    <div className="space-y-2 pt-2">
      {tiles ? (
        <div className="grid gap-4 md:grid-cols-3">
          {tiles.map((tile) => (
            <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} muted={tile.thin} />
          ))}
        </div>
      ) : (
        <div className="grid animate-pulse gap-4 md:grid-cols-3" role="status" aria-label={t('common.loading')}>
          {labels.map((label) => (
            // A plain space collapses the value and detail lines, and the tabs would jump.
            <StatTile key={label} label={label} value={NBSP} detail={NBSP} />
          ))}
        </div>
      )}
      <p className="text-caption text-muted">
        {t('decks.overview.playDrawNote')}
        {tiles && full && ` ${t('matches.summary.counted', { n: formatCount(inHand?.length ?? 0) })}`}
      </p>
    </div>
  )
}
