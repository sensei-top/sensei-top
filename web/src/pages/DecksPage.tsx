import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'
import { useGuideDecks, useMatchArt, useMatches, type MatchDetail } from '../api'
import { DeckTile, Disclosure, EmptyState, ErrorNote, OutlineCard, Select } from '../components/ui'
import {
  chosenQuery,
  chosenSort,
  FOLD_MIN_MATCHES,
  deckAddress,
  DECKS_SORTS,
  deckRecord,
  decksTiles,
  filterTiles,
  formatName,
  sortTiles,
  splitFold,
  tileFormats,
  tileArt,
} from '../lib/decks'
import { HOME_MATCH_LIMIT } from '../lib/home'
import { castCards } from '../lib/matchArt'
import { formatShortDay, useNow } from '../lib/time'
import { placeById } from '../shell/places'

const MINUTE = 60_000

/** The pending page: the filter row's place reserved, then a row of tiles
 *  in the grid the loaded page uses. */
function DecksOutline() {
  const { t } = useTranslation()
  return (
    <div className="space-y-4">
      <div className="h-[44px]" />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4 lg:grid-cols-5">
        {[0, 1, 2, 3, 4].map((each) => (
          <OutlineCard key={each} words={each === 0 ? t('decks.reading') : undefined} height="h-57 lg:h-61.5" />
        ))}
      </div>
    </div>
  )
}

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
 *  two tiles. A deck with no finished match in that list, or whose cards
 *  are all taken, wears its identity's `art_grp_id`; with that null too,
 *  the empty box: nothing more is asked for it.
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
  const query = chosenQuery(params.get('q'))
  // The box holds its own text, so a space typed inside the query survives
  // while the address keeps it trimmed. `written` is the last value the box
  // put in the address: the box resets only when the address holds another.
  const [typed, setTyped] = useState(query)
  const written = useRef(query)
  useEffect(() => {
    if (query === written.current) return
    written.current = query
    setTyped(query)
  }, [query])
  const shown = useMemo(() => sortTiles(filterTiles(tiles, format), sort), [tiles, format, sort])
  const { main, folded } = useMemo(() => splitFold(shown, query), [shown, query])
  const artIds = [...new Set(tiles.map((tile) => tile.artMatchId).filter((id): id is string => id != null))]
  const artQueries = useMatchArt(artIds)
  const details = new Map<string, MatchDetail | undefined>(artIds.map((id, index) => [id, artQueries[index]?.data]))

  if (identities.isPending) return <DecksOutline />
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
    const index = tile.artMatchId ? artIds.indexOf(tile.artMatchId) : -1
    const settled = !matches.isPending && (index < 0 || !artQueries[index]?.isPending)
    return [tile.key, tileArt(castCards(detail, 'self'), used, tile.artGrpId, settled)] as const
  }))
  const options = tileFormats(tiles)
  if (format && !options.includes(format)) options.unshift(format)
  const formatOptions = options.map((each) => ({ value: each, label: formatName(each, t) ?? each }))
  const sortOptions = DECKS_SORTS.map((each) => ({ value: each, label: t(`decks.list.sort.${each}`) }))
  const grid = (list: typeof shown) => (
    <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4 lg:grid-cols-5">
      {list.map((tile) => {
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
  )
  return (
    <div className="arrive space-y-4">
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
        <label className="flex max-w-full min-w-0 items-center gap-2">
          <span className="shrink-0 text-caption text-muted">{t('decks.list.searchLabel')}</span>
          <input
            type="search"
            value={typed}
            onChange={(event) => {
              setTyped(event.target.value)
              written.current = chosenQuery(event.target.value)
              setParam('q', written.current, '')
            }}
            placeholder={t('decks.list.searchPlaceholder')}
            autoComplete="off"
            spellCheck={false}
            className="min-h-[44px] min-w-0 rounded-control border border-edge bg-surface px-2 py-1.5 text-caption text-ink placeholder:text-muted"
          />
        </label>
      </div>
      {shown.length === 0 ? (
        <EmptyState icon={placeById('decks').icon} message={t('decks.list.noneInFormat')} />
      ) : (
        main.length + folded.length === 0 && (
          <EmptyState icon={placeById('decks').icon} message={t('decks.list.noMatch', { q: query })} />
        )
      )}
      {main.length > 0 && grid(main)}
      <div hidden={folded.length === 0}>
        <Disclosure summary={t('decks.list.fewer', { min: FOLD_MIN_MATCHES, count: folded.length })}>
          {grid(folded)}
        </Disclosure>
      </div>
    </div>
  )
}
