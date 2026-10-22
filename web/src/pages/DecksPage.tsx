import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'
import { useGuideDecks, useMatchArt, useMatches, type MatchDetail } from '../api'
import { DeckTile, EmptyState, ErrorNote, Loading, Select } from '../components/ui'
import {
  chosenSort,
  deckAddress,
  DECKS_SORTS,
  deckRecord,
  decksTiles,
  filterTiles,
  formatName,
  sortTiles,
  tileFormats,
} from '../lib/decks'
import { HOME_MATCH_LIMIT } from '../lib/home'
import { castCards, takeUnused } from '../lib/matchArt'
import { formatShortDay, useNow } from '../lib/time'
import { placeById } from '../shell/places'

const MINUTE = 60_000

/** `/decks`: one tile per deck (an identity of `/api/guide/decks`, however
 *  many versions its list has had), the last played first as the API
 *  answers them (the default order), each a way into the deck's own page by
 *  its key. A tile carries the deck's name, its record by Home's rule
 *  (`deckRecord`), the format in words with how many versions when there
 *  are several, and when it was last played. Home's grid: two to a row
 *  under 48rem, three from there, five from 64rem.
 *
 *  The art is a card the viewer cast in the deck's newest finished match of
 *  the list Home asks for (the same request serves both pages), no card on
 *  two tiles. A deck with no finished match in that list keeps the empty
 *  box: nothing more is asked for it.
 *
 *  The format filter and the sort: `docs/frontend-pages.md`, "Decks". */
export function DecksPage() {
  const { t } = useTranslation()
  const identities = useGuideDecks()
  const matches = useMatches(undefined, 'all', HOME_MATCH_LIMIT)
  const now = useNow()
  // The days move with the minute, not with every second's re-render.
  const minute = Math.floor(now / MINUTE) * MINUTE

  const tiles = useMemo(
    () => (identities.data ? decksTiles(identities.data, matches.data ?? [], t, minute) : []),
    [identities.data, matches.data, t, minute],
  )
  const [params, setParams] = useSearchParams()
  const format = params.get('format') || null
  const sort = chosenSort(params.get('sort'))
  const setParam = (key: string, value: string, fallback: string) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        if (value === fallback) next.delete(key)
        else next.set(key, value)
        return next
      },
      { replace: true, preventScrollReset: true },
    )
  const shown = useMemo(() => sortTiles(filterTiles(tiles, format), sort), [tiles, format, sort])
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

  // One card appears once on the page, taken in the API's order over every
  // tile, so a tile's art does not change with the sort or the filter.
  const used = new Set<number>()
  const art = new Map(tiles.map((tile) => {
    const detail = tile.artMatchId ? details.get(tile.artMatchId) : undefined
    return [tile.key, takeUnused(castCards(detail, 'self'), used)] as const
  }))
  const options = tileFormats(tiles)
  if (format && !options.includes(format)) options.unshift(format)
  const formatOptions = options.map((each) => ({ value: each, label: formatName(each, t) ?? each }))
  const sortOptions = DECKS_SORTS.map((each) => ({ value: each, label: t(`decks.list.sort.${each}`) }))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <Select
          label={t('decks.list.formatLabel')}
          size="caption"
          value={format ?? ''}
          onChange={(value) => setParam('format', value, '')}
          options={formatOptions}
        >
          <option value="">{t('decks.list.allFormats')}</option>
        </Select>
        <Select
          label={t('decks.list.sortLabel')}
          size="caption"
          value={sort}
          onChange={(value) => setParam('sort', value, 'lastPlayed')}
          options={sortOptions}
        />
      </div>
      {shown.length === 0 ? (
        <EmptyState icon={placeById('decks').icon} message={t('decks.list.noneInFormat')} />
      ) : (
        <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4 lg:grid-cols-5">
          {shown.map((tile) => {
            const { figure, line, thin } = deckRecord(tile, t)
            return (
              <li key={tile.key} className="min-w-0">
                <DeckTile
                  name={tile.name}
                  href={deckAddress(tile.key)}
                  figure={figure}
                  muted={thin}
                  line={line}
                  detail={tile.detail}
                  chip={tile.newest ? t('decks.overview.newest') : null}
                  lastPlayed={
                    tile.playedRange ??
                    (tile.lastPlayed != null ? t('decks.tile.lastPlayed', { day: formatShortDay(tile.lastPlayed, minute) }) : null)
                  }
                  art={art.get(tile.key) ?? null}
                />
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
