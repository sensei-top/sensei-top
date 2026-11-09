import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { DECK_MATCH_LIMIT, useDeckMatches, useDeckPlayDraw } from '../api'
import { deckKeyNumbers, playDrawTotals } from '../lib/deckOverview'
import { formatCount } from '../lib/time'
import { ErrorNote, OutlineCard, STAT_TILE_BLOCK, StatTile } from './ui'

/** The strip's place while it waits: its three tiles' frames and the note.
 *  It carries no `role="status"` and no pulse: the page's body has the one
 *  line of words. The layout draws it before the deck is known, and
 *  `DeckKeyNumbers` while its reads load, so the two are one tree. */
export function StripFrames() {
  const { t } = useTranslation()
  return (
    <div className="space-y-2 pt-2">
      <div className="grid gap-4 md:grid-cols-3">
        <OutlineCard label={t('decks.strip.matches')} height={STAT_TILE_BLOCK} />
        <OutlineCard label={t('decks.strip.games')} height={STAT_TILE_BLOCK} />
        <OutlineCard label={t('decks.strip.playDraw')} height={STAT_TILE_BLOCK} />
      </div>
      <p className="text-caption text-muted">{t('decks.overview.playDrawNote')}</p>
    </div>
  )
}

/** The deck strip, under the deck's name on every tab: Matches, Games and
 *  Play vs draw (`deckKeyNumbers`), over the versions the tab reads, then
 *  the note on how the games on the play and the draw are counted. One row
 *  of three from 48rem, stacked under it.
 *
 *  The layout and the Overview ask for the same matches with the same
 *  query, so the strip costs no second request. While either read is
 *  pending the strip holds its own height, as `StripFrames`, so
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
  if (!tiles) return <StripFrames />

  return (
    <div className="space-y-2 pt-2">
      <div className="grid gap-4 md:grid-cols-3">
        {tiles.map((tile) => (
          <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} muted={tile.thin} />
        ))}
      </div>
      <p className="text-caption text-muted">
        {t('decks.overview.playDrawNote')}
        {full && ` ${t('matches.summary.counted', { n: formatCount(inHand?.length ?? 0) })}`}
      </p>
    </div>
  )
}
