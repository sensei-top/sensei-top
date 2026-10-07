import { useMemo } from 'react'
import { Link, useLocation } from 'react-router'
import { DECK_MATCH_LIMIT, useDeckMatches, useDeckPlayDraw, useDeckVersions, type Match } from '../api'
import { DeckMatchesCard } from '../components/DeckMatchesCard'
import { MatchesSummary } from '../components/MatchesSummary'
import { VersionSwitcher } from '../components/VersionSwitcher'
import { Button, Card, Chip, DataTable, EmptyState, ErrorNote, Loading, StatTile } from '../components/ui'
import { mergeNewestFirst, playDrawTiles, playDrawTotals, rankRows, versionDays, versionRecord } from '../lib/deckOverview'
import { formatCount, useNow } from '../lib/time'
import { placeById } from '../shell/places'

const MINUTE = 60_000

/** A deck's Overview, over the versions the address chose (`versionIds`,
 *  every version when `version` is `null`), top to bottom: the version
 *  switcher when the deck has more than one; Matches' band over the matches
 *  in hand; the games on the play and on the draw as three tiles; the
 *  finished matches by the rank they were played at, when there are two
 *  ranks; under every version, each version as a way to read it alone; and
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
  const { pathname } = useLocation()
  const { deckIds, versions } = useDeckVersions(deckKey, versionIds)
  const matches = useDeckMatches(versionIds)
  const playDraw = useDeckPlayDraw(versionIds)
  const now = useNow()
  // The days move with the minute, not with every second's re-render.
  const minute = Math.floor(now / MINUTE) * MINUTE

  const inHand = useMemo(() => (matches.data ? mergeNewestFirst(matches.data) : []), [matches.data])
  const byVersion = useMemo(
    () => new Map<string, Match[]>(versionIds.map((id, index) => [id, matches.data?.[index] ?? []])),
    [versionIds, matches.data],
  )
  const ranks = useMemo(() => rankRows(inHand), [inHand])
  const tiles = useMemo(() => (playDraw.data ? playDrawTiles(playDrawTotals(playDraw.data.flat())) : null), [playDraw.data])

  const switcher = deckIds.length > 1 && <VersionSwitcher versions={versions} value={version} now={minute} />

  const error = matches.error ?? playDraw.error
  let body
  if (error) body = <ErrorNote error={error} />
  else if (matches.isPending || playDraw.isPending || !tiles) body = <Loading />
  else if (inHand.length === 0 && version != null) {
    body = (
      <EmptyState
        icon={placeById('decks').icon}
        title="No match with this version"
        message="Pick another version, or read every version together."
        action={<Button href={pathname}>Every version</Button>}
      />
    )
  } else {
    const full = (matches.data ?? []).some((list) => list.length >= DECK_MATCH_LIMIT)
    body = (
      <>
        <MatchesSummary matches={inHand} full={full} />

        <div className="space-y-2">
          <p className="text-caption text-muted">Counted per game, over the games whose first player is known.</p>
          <div className="grid gap-4 md:grid-cols-3">
            {tiles.map((tile) => (
              <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
            ))}
          </div>
        </div>

        {ranks.length >= 2 && (
          <Card title="By rank" subtitle="Your rank when each match was played. Finished matches only.">
            <DataTable
              columns={['Rank', 'Matches', 'Won', 'Rate']}
              rows={ranks.map((row) => [row.rank, formatCount(row.matches), formatCount(row.won), row.rate])}
            />
          </Card>
        )}

        {version == null && versions.length > 1 && (
          <Card
            title="Versions"
            subtitle="A change to the list starts a new version. Pick one to read it alone."
          >
            <ul className="divide-y divide-line">
              {versions.map((row, index) => (
                <li key={row.deck_id} className="py-1 first:pt-0 last:pb-0">
                  <Link
                    to={{ search: `?${new URLSearchParams({ version: row.deck_id })}` }}
                    className="-mx-2 flex min-h-[44px] flex-col justify-center gap-0.5 rounded-control px-2 py-2 transition-chrome hover:bg-surface3"
                  >
                    <span className="flex flex-wrap items-center gap-2 text-body text-ink">
                      {versionDays(row, minute) ?? 'Undated'}
                      {index === 0 && <Chip size="sm">Newest</Chip>}
                    </span>
                    <span className="text-caption text-muted">{versionRecord(byVersion.get(row.deck_id) ?? [])}</span>
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
    <div className="space-y-8">
      {switcher}
      {body}
    </div>
  )
}
