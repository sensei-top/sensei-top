import { useMemo } from 'react'
import { useLocation } from 'react-router'
import { DECK_MATCH_LIMIT, useDeckMatches, useDeckVersions, useFieldRecords } from '../api'
import { VersionSwitcher } from '../components/VersionSwitcher'
import { Button, Card, DataTable, EmptyState, ErrorNote, Loading, ManaPips, StatTile, TextLink } from '../components/ui'
import { mergeNewestFirst } from '../lib/deckOverview'
import { archetypeKeyOf, fieldLine, matchupName, matchupRows, matchupTiles } from '../lib/matchups'
import { RATE_MIN_MATCHES } from '../lib/home'
import { pairingAddress, withVersion } from '../lib/pairing'
import { formatCount, formatPercent, useNow } from '../lib/time'
import { placeById } from '../shell/places'

const MINUTE = 60_000

/** A deck's Matchups, over the versions the address chose (`versionIds`,
 *  every version when `version` is `null`), counted from the matches in
 *  hand, top to bottom: the version switcher when the deck has more than
 *  one; three tiles, the archetypes met and the best and worst of those met
 *  five times or more, and under them, when a version's list is cut at the
 *  route's maximum, how many matches were counted; and every archetype
 *  met, one row each, whichever version met it, its name a link to the
 *  pairing's page carrying the version chosen. Finished matches only.
 *  Each version is read on its own and the page waits for every one; one
 *  failure is the page's error. The field's numbers never hold the page:
 *  until they come, or when they fail, the line under a name is the games
 *  alone. A chosen version with no match says so under the switcher. The
 *  page keys this view on the deck alone, so a change of version keeps the
 *  switcher's `<select>`, and the focus on it; nothing here must start over
 *  on a change of version. */
export function MatchupsView({
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
  const now = useNow()
  // The days move with the minute, not with every second's re-render.
  const minute = Math.floor(now / MINUTE) * MINUTE

  // The field's win rate, in the line under a name.
  const fieldByKey = useFieldRecords()

  const inHand = useMemo(() => (matches.data ? mergeNewestFirst(matches.data) : []), [matches.data])
  const rows = useMemo(() => matchupRows(inHand), [inHand])
  const tiles = useMemo(() => matchupTiles(rows), [rows])

  const switcher = deckIds.length > 1 && <VersionSwitcher versions={versions} value={version} now={minute} />
  const icon = placeById('decks').icon

  let body
  if (matches.error) body = <ErrorNote error={matches.error} />
  else if (matches.isPending) body = <Loading />
  else if (inHand.length === 0 && version != null) {
    body = (
      <EmptyState
        icon={icon}
        title="No match with this version"
        message="Pick another version, or read every version together."
        action={<Button href={pathname}>Every version</Button>}
      />
    )
  } else if (rows.length === 0) {
    body = <EmptyState icon={icon} title="No finished match yet" message="Matchups are counted once a match has ended." />
  } else {
    const full = (matches.data ?? []).some((list) => list.length >= DECK_MATCH_LIMIT)
    body = (
      <>
        <div className="space-y-2">
          <div className="grid gap-4 md:grid-cols-3">
            {tiles.map((tile) => (
              <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
            ))}
          </div>
          {full && <p className="text-caption text-muted">Counted over the {formatCount(inHand.length)} newest matches.</p>}
        </div>

        <Card title="Archetypes met" subtitle="Finished matches only, most met first. A rate needs ten matches.">
          <DataTable
            columns={['Archetype', 'Matches', 'Won', 'Rate']}
            rows={rows.map((row) => {
              const name = matchupName(row)
              const archetype = archetypeKeyOf(row.key)
              const field = archetype != null ? fieldByKey.get(archetype) : undefined
              return [
                <div key="archetype" className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <ManaPips colors={row.colors} />
                    <TextLink
                      href={withVersion(pairingAddress(deckKey, row.key), version)}
                      className="min-w-0 break-words text-body"
                    >
                      {/* The muted colour sits on a child: a child's own colour beats the
                          link's, whatever order the built CSS puts the two classes in. */}
                      <span className={row.kind === 'unknown' ? 'text-muted' : undefined}>{name.name}</span>
                    </TextLink>
                  </div>
                  {name.showed && <div className="text-caption break-words text-muted">{name.showed}</div>}
                  <div className="text-caption break-words text-muted">
                    {fieldLine({ won: row.gamesWon, lost: row.gamesLost }, field)}
                  </div>
                </div>,
                formatCount(row.matches),
                formatCount(row.won),
                row.matches >= RATE_MIN_MATCHES ? `${formatPercent(row.won / row.matches)}%` : '—',
              ]
            })}
          />
        </Card>
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
