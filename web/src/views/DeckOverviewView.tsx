import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router'
import { useDeckMatches, useDeckVersions, type Match } from '../api'
import { DeckMatchesCard } from '../components/DeckMatchesCard'
import { VersionSwitcher } from '../components/VersionSwitcher'
import { Button, Card, Chip, DataTable, EmptyState, ErrorNote, OutlineCard } from '../components/ui'
import { mergeNewestFirst, rankRows, versionDays, versionRecord } from '../lib/deckOverview'
import { formatCount, useNow } from '../lib/time'
import { placeById } from '../shell/places'

const MINUTE = 60_000

/** The "By rank" card's reserved block, for eight rank rows: the loaded
 *  card's title and line, its header, eight rows of padding, line and rule,
 *  less the frame's label (the label's line is 1.5 of its token). The row count
 *  is the deck's ranks and cannot be known here: a deck with fewer, or
 *  with fewer than two ranks (no card), moves the page. */
const RANK_HEIGHT =
  'h-[calc(var(--text-title)*1.25+var(--text-caption)*2.8+var(--text-body)*12-var(--text-chip)*1.5+var(--spacing)*41.5)]'

/** The block of an `OutlineCard` standing in for a `StatTile`: the tile's
 *  stat and detail lines, less what the frame's label and padding add. */
export const STAT_TILE_BLOCK = 'h-[calc(var(--text-stat)*1.1+var(--text-caption)*1.4-var(--spacing)*3)]'

/** The same block for a tile whose detail wraps to a second line under the
 *  `lg` breakpoint, where the tiles are three to a row, and not from it. */
export const STAT_TILE_BLOCK_WRAPS_UNDER_LG =
  'h-[calc(var(--text-stat)*1.1+var(--text-caption)*2.8-var(--spacing)*3)] lg:h-[calc(var(--text-stat)*1.1+var(--text-caption)*1.4-var(--spacing)*3)]'

/** The versions card's reserved height by how many versions it lists, from
 *  two: the loaded card's title and line, less the frame's label, plus per
 *  version the link's two lines, its padding and the row's (the first row
 *  carries the Newest chip, a little taller). Eight or more share the last. */
const VERSIONS_HEIGHT = [
  'h-[calc(var(--text-title)*1.25+var(--text-caption)*1.4*3+var(--text-body)*1.5*2-var(--text-chip)*1.5+var(--spacing)*12.75)]',
  'h-[calc(var(--text-title)*1.25+var(--text-caption)*1.4*4+var(--text-body)*1.5*3-var(--text-chip)*1.5+var(--spacing)*19.5)]',
  'h-[calc(var(--text-title)*1.25+var(--text-caption)*1.4*5+var(--text-body)*1.5*4-var(--text-chip)*1.5+var(--spacing)*26.25)]',
  'h-[calc(var(--text-title)*1.25+var(--text-caption)*1.4*6+var(--text-body)*1.5*5-var(--text-chip)*1.5+var(--spacing)*33)]',
  'h-[calc(var(--text-title)*1.25+var(--text-caption)*1.4*7+var(--text-body)*1.5*6-var(--text-chip)*1.5+var(--spacing)*39.75)]',
  'h-[calc(var(--text-title)*1.25+var(--text-caption)*1.4*8+var(--text-body)*1.5*7-var(--text-chip)*1.5+var(--spacing)*46.5)]',
  'h-[calc(var(--text-title)*1.25+var(--text-caption)*1.4*9+var(--text-body)*1.5*8-var(--text-chip)*1.5+var(--spacing)*53.25)]',
]

/** The Overview's frames while its matches load, in the place of its body:
 *  `versionCount` is the versions the versions card lists, 0 when it is
 *  not drawn. */
export function DeckOverviewFrames({ versionCount }: { versionCount: number }) {
  const { t } = useTranslation()
  return (
    <>
      <OutlineCard label={t('decks.overview.rank.title')} height={RANK_HEIGHT} />
      {versionCount > 1 && (
        <OutlineCard
          label={t('decks.overview.versions.title')}
          height={VERSIONS_HEIGHT[Math.min(versionCount, 8) - 2]}
        />
      )}
      <OutlineCard label={t('decks.matches.title')} words={t('decks.reading')} height="h-140" />
    </>
  )
}

/** A deck's Overview, over the versions the address chose (`versionIds`,
 *  every version when `version` is `null`), top to bottom: the version
 *  switcher when the deck has more than one; the finished matches by the
 *  rank they were played at, when there are two ranks; under every version,
 *  each version as a way to read it alone; and
 *  the matches themselves, newest first, ten at first and fifty more a
 *  press. Each version is read on its own and the page adds them up, and it
 *  waits for every one; one failure is the page's error. A chosen version
 *  with no match says so under the switcher and draws nothing else. The
 *  page keys this view on the deck alone, so a change of version keeps the
 *  switcher's `<select>` the same element, and the focus on it; only the
 *  Matches card is keyed on the version, so its rows start again at ten. */
export function DeckOverviewView({
  deckKey,
  versionIds,
  version,
}: {
  deckKey: string
  versionIds: string[]
  version: string | null
}) {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const { deckIds, versions } = useDeckVersions(deckKey, versionIds)
  const matches = useDeckMatches(versionIds)
  const now = useNow()
  // The days move with the minute, not with every second's re-render.
  const minute = Math.floor(now / MINUTE) * MINUTE

  const inHand = useMemo(() => (matches.data ? mergeNewestFirst(matches.data) : []), [matches.data])
  const byVersion = useMemo(
    () => new Map<string, Match[]>(versionIds.map((id, index) => [id, matches.data?.[index] ?? []])),
    [versionIds, matches.data],
  )
  const ranks = useMemo(() => rankRows(inHand, t), [inHand, t])

  const switcher = deckIds.length > 1 && <VersionSwitcher versions={versions} value={version} now={minute} />

  let body
  if (matches.error) body = <ErrorNote error={matches.error} />
  else if (matches.isPending) body = <DeckOverviewFrames versionCount={version == null ? deckIds.length : 0} />
  else if (inHand.length === 0 && version != null) {
    body = (
      <EmptyState
        icon={placeById('decks').icon}
        title={t('decks.overview.noMatch.title')}
        message={t('decks.overview.noMatch.message')}
        action={<Button href={pathname}>{t('common.filters.everyVersion')}</Button>}
      />
    )
  } else {
    body = (
      <>
        {ranks.length >= 2 && (
          <Card title={t('decks.overview.rank.title')} subtitle={t('decks.overview.rank.subtitle')}>
            <DataTable
              columns={[
                t('decks.overview.rank.rank'),
                t('decks.overview.rank.matches'),
                t('decks.overview.rank.record'),
                t('decks.overview.rank.rate'),
              ]}
              rows={ranks.map((row) => [
                row.rank,
                formatCount(row.matches),
                row.record,
                row.thin ? (
                  <span key="rate" className="whitespace-nowrap text-muted">
                    {row.rate}
                  </span>
                ) : (
                  row.rate
                ),
              ])}
            />
          </Card>
        )}

        {version == null && versions.length > 1 && (
          <Card
            title={t('decks.overview.versions.title')}
            subtitle={t('decks.overview.versions.subtitle')}
          >
            <ul className="divide-y divide-line">
              {versions.map((row, index) => (
                <li key={row.deck_id} className="py-1 first:pt-0 last:pb-0">
                  <Link
                    to={{ search: `?${new URLSearchParams({ version: row.deck_id })}` }}
                    className="-mx-2 flex min-h-[44px] flex-col justify-center gap-0.5 rounded-control px-2 py-2 transition-chrome hover:bg-surface3"
                  >
                    <span className="flex flex-wrap items-center gap-2 text-body text-ink">
                      {versionDays(row, minute, t) ?? t('decks.overview.undated')}
                      {index === 0 && <Chip size="sm">{t('decks.overview.newest')}</Chip>}
                    </span>
                    <span className="text-caption text-muted">{versionRecord(byVersion.get(row.deck_id) ?? [], t)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}

        {inHand.length > 0 && <DeckMatchesCard key={version ?? ''} matches={inHand} />}
      </>
    )
  }

  return (
    <div className={`${matches.isPending ? '' : 'arrive '}space-y-8`}>
      {switcher}
      {body}
    </div>
  )
}
