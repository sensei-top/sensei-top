import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useGuideDecks, useMatchArt, useMatches, type MatchDetail } from '../api'
import { DeckTile, EmptyState, ErrorNote, Loading } from '../components/ui'
import { deckAddress, deckRecord, decksTiles } from '../lib/decks'
import { HOME_MATCH_LIMIT } from '../lib/home'
import { castCards, takeUnused } from '../lib/matchArt'
import { formatShortDay, useNow } from '../lib/time'
import { placeById } from '../shell/places'

const MINUTE = 60_000

/** `/decks`: one tile per deck (an identity of `/api/guide/decks`, however
 *  many versions its list has had), the last played first as the API
 *  answers them, each a way into the deck's own page by its key. A tile
 *  carries the deck's name, its record by Home's rule (`deckRecord`), the
 *  format in words with how many versions when there are several, and when
 *  it was last played. Home's grid: two to a row under 48rem, three from
 *  there, five from 64rem.
 *
 *  The art is a card the viewer cast in the deck's newest finished match of
 *  the list Home asks for (the same request serves both pages), no card on
 *  two tiles. A deck with no finished match in that list keeps the empty
 *  box: nothing more is asked for it. */
export function DecksPage() {
  const { t } = useTranslation()
  const identities = useGuideDecks()
  const matches = useMatches(undefined, 'all', HOME_MATCH_LIMIT)
  const now = useNow()
  // The days move with the minute, not with every second's re-render.
  const minute = Math.floor(now / MINUTE) * MINUTE

  const tiles = useMemo(
    () => (identities.data ? decksTiles(identities.data, matches.data ?? [], t) : []),
    [identities.data, matches.data, t],
  )
  const artIds = [...new Set(tiles.map((tile) => tile.artMatchId).filter((id): id is string => id != null))]
  const artQueries = useMatchArt(artIds)
  const details = new Map<string, MatchDetail | undefined>(artIds.map((id, index) => [id, artQueries[index]?.data]))

  if (identities.isPending) return <Loading />
  if (identities.error) return <ErrorNote error={identities.error} />
  if (tiles.length === 0) {
    return (
      <EmptyState
        icon={placeById('decks').icon}
        title={t('decks.list.empty.title')}
        message={t('decks.list.empty.message')}
      />
    )
  }

  // One card appears once on the page, taken in the tiles' order.
  const used = new Set<number>()
  return (
    <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4 lg:grid-cols-5">
      {tiles.map((tile) => {
        const { figure, line } = deckRecord(tile, t)
        const detail = tile.artMatchId ? details.get(tile.artMatchId) : undefined
        return (
          <li key={tile.key} className="min-w-0">
            <DeckTile
              name={tile.name}
              href={deckAddress(tile.key)}
              figure={figure}
              line={line}
              detail={tile.detail}
              lastPlayed={tile.lastPlayed != null ? t('decks.tile.lastPlayed', { day: formatShortDay(tile.lastPlayed, minute) }) : null}
              art={takeUnused(castCards(detail, 'self'), used)}
            />
          </li>
        )
      })}
    </ul>
  )
}
