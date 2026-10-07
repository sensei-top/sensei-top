import { useMemo } from 'react'
import { useLocation } from 'react-router'
import { DECK_MATCH_LIMIT, useDeckMatches, useDeckVersions, useFieldRecords, useGuideCoverage } from '../api'
import { DeckMatchesCard } from '../components/DeckMatchesCard'
import { PairingBrief } from '../components/PairingBrief'
import { VersionSwitcher } from '../components/VersionSwitcher'
import { BackLink, Button, EmptyState, ErrorNote, Loading, ManaPips, StatTile } from '../components/ui'
import { deckAddress } from '../lib/decks'
import { archetypeKeyOf, matchupRows } from '../lib/matchups'
import {
  coverageRowOf,
  lastMetLine,
  pairingHeading,
  pairingMatches,
  pairingTiles,
  withVersion,
} from '../lib/pairing'
import { formatCount, useNow } from '../lib/time'
import { placeById } from '../shell/places'

const MINUTE = 60_000

/** One deck against one opponent's deck (`opponentKey`, a Matchups row's
 *  `opponent_key`), over the versions the address chose (`versionIds`,
 *  every version when `version` is `null`), counted from the matches in
 *  hand against it, top to bottom: the way back to the deck's Matchups;
 *  the opponent's deck, its pips and name as a Matchups row draws them,
 *  and when it was last met; the version switcher when the deck has more
 *  than one; three tiles over the finished matches, the record, the games
 *  and the field's record in tournaments, and under them, when a version's
 *  list is cut at the route's maximum, how many matches were counted; the
 *  brief against it (`PairingBrief`), whatever the state of the matches;
 *  and every match against it, finished or not, newest first. Each version
 *  is read on its own and the page waits for every one; one failure is the
 *  page's error. The field's numbers never hold the page: until they come,
 *  or when they fail, the third tile says there are none. With no match
 *  against it, or none finished, the tiles' place says so; with no match
 *  against an `archetype:` key, the heading waits for the deck's coverage,
 *  whose label names it. The page keys this view on the deck and the
 *  opponent, so a change of version keeps the switcher's `<select>`, and
 *  the focus on it; only the Matches card is keyed on the version, so its
 *  rows start again at ten. The brief is the deck's, not a version's, and
 *  is not keyed on it. */
export function PairingView({
  deckKey,
  versionIds,
  version,
  opponentKey,
}: {
  deckKey: string
  versionIds: string[]
  version: string | null
  opponentKey: string
}) {
  const { pathname } = useLocation()
  const { deckIds, versions } = useDeckVersions(deckKey, versionIds)
  const matches = useDeckMatches(versionIds)
  const now = useNow()
  // The days move with the minute, not with every second's re-render.
  const minute = Math.floor(now / MINUTE) * MINUTE

  // Shared with `PairingBrief`: one query. Here it names an archetype no
  // match has met by coverage's label.
  const coverage = useGuideCoverage(deckKey)
  // The field in the deck's own format: nothing is asked until coverage
  // answers, or when the deck has none.
  const fieldByKey = useFieldRecords(coverage.data?.fmt)

  const against = useMemo(
    () => (matches.data ? pairingMatches(opponentKey, matches.data) : []),
    [opponentKey, matches.data],
  )
  const label = coverage.data ? coverageRowOf(opponentKey, coverage.data)?.label : null
  const heading = useMemo(() => pairingHeading(opponentKey, against, label), [opponentKey, against, label])
  // An archetype no match has met waits for coverage (answered or failed),
  // so its key never shows before its name.
  const headingReady =
    matches.data != null && (against.length > 0 || archetypeKeyOf(opponentKey) == null || !coverage.isPending)
  const row = useMemo(() => matchupRows(against)[0] ?? null, [against])
  const lastMet = lastMetLine(against, now)

  const switcher = deckIds.length > 1 && <VersionSwitcher versions={versions} value={version} now={minute} />
  const icon = placeById('decks').icon

  // `body` is the tiles or what stands in their place, and `matchesCard`
  // the matches, when there are any: the brief goes between the two.
  let body
  let matchesCard = null
  if (matches.error) body = <ErrorNote error={matches.error} />
  else if (matches.isPending) body = <Loading />
  else if (against.length === 0 && version != null) {
    body = (
      <EmptyState
        icon={icon}
        title="No match against it with this version"
        message="Pick another version, or read every version together."
        action={<Button href={pathname}>Every version</Button>}
      />
    )
  } else if (against.length === 0) {
    body = <EmptyState icon={icon} title="No match against it yet" message="Once you play one, it is counted here." />
  } else {
    const inHand = (matches.data ?? []).reduce((count, list) => count + list.length, 0)
    const full = (matches.data ?? []).some((list) => list.length >= DECK_MATCH_LIMIT)
    body = row ? (
      <div className="space-y-2">
        <div className="grid gap-4 md:grid-cols-3">
          {pairingTiles(row, fieldByKey).map((tile) => (
            <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
          ))}
        </div>
        {full && <p className="text-caption text-muted">Counted over the {formatCount(inHand)} newest matches.</p>}
      </div>
    ) : (
      <EmptyState icon={icon} title="No finished match yet" message="Matchups are counted once a match has ended." />
    )
    matchesCard = <DeckMatchesCard key={version ?? ''} matches={against} />
  }

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <p className="text-caption">
          <BackLink href={withVersion(`${deckAddress(deckKey)}/matchups`, version)}>All matchups</BackLink>
        </p>
        {headingReady && (
          <div>
            <h3 className="flex flex-wrap items-center gap-x-2 gap-y-1 font-display text-title">
              <ManaPips colors={heading.colors} />
              <span className={`min-w-0 break-words ${heading.muted ? 'text-muted' : 'text-ink'}`}>{heading.name}</span>
            </h3>
            {heading.showed && <p className="text-body break-words text-ink2">{heading.showed}</p>}
            {lastMet && <p className="text-caption text-muted">{lastMet}</p>}
          </div>
        )}
      </div>
      {switcher}
      {body}
      <PairingBrief deckKey={deckKey} opponentKey={opponentKey} />
      {matchesCard}
    </div>
  )
}
