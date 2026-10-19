import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router'
import { useDeckMatches, useDeckVersions, useFieldRecords, useGuideCoverage } from '../api'
import { RateCell } from '../components/RateCell'
import { VersionSwitcher } from '../components/VersionSwitcher'
import { Button, Card, DataTable, EmptyState, ErrorNote, Loading, ManaPips, StatTile, TextLink } from '../components/ui'
import { mergeNewestFirst } from '../lib/deckOverview'
import {
  archetypeKeyOf,
  fieldLine,
  matchupName,
  matchupRows,
  matchupTiles,
} from '../lib/matchups'
import { formatRecord } from '../lib/format'
import { pairingAddress, withVersion } from '../lib/pairing'
import { formatCount, useNow } from '../lib/time'
import { placeById } from '../shell/places'

const MINUTE = 60_000

/** A deck's Matchups, over the versions the address chose (`versionIds`,
 *  every version when `version` is `null`), counted from the matches in
 *  hand, top to bottom: the version switcher when the deck has more than
 *  one; three tiles, the archetypes met and the best and worst of those met
 *  ten times or more; and every archetype met, one row each, whichever
 *  version met it, its name a link to the pairing's page carrying the
 *  version chosen, its record and rate, and its best-of-three games split
 *  into game 1 and games 2–3, each a `RateCell`. Finished matches only.
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
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const { deckIds, versions } = useDeckVersions(deckKey, versionIds)
  const matches = useDeckMatches(versionIds)
  const now = useNow()
  // The days move with the minute, not with every second's re-render.
  const minute = Math.floor(now / MINUTE) * MINUTE

  // The field's win rate, in the line under a name.
  // In the deck's own format: undefined while coverage loads, null when the
  // deck has none, and neither asks for a field.
  const fieldByKey = useFieldRecords(useGuideCoverage(deckKey).data?.fmt)

  const inHand = useMemo(() => (matches.data ? mergeNewestFirst(matches.data) : []), [matches.data])
  const rows = useMemo(() => matchupRows(inHand), [inHand])
  const tiles = useMemo(() => matchupTiles(rows, t), [rows, t])

  const switcher = deckIds.length > 1 && <VersionSwitcher versions={versions} value={version} now={minute} />
  const icon = placeById('decks').icon

  let body
  if (matches.error) body = <ErrorNote error={matches.error} />
  else if (matches.isPending) body = <Loading />
  else if (inHand.length === 0 && version != null) {
    body = (
      <EmptyState
        icon={icon}
        title={t('matchups.view.noVersionTitle')}
        message={t('matchups.view.noVersionMessage')}
        action={<Button href={pathname}>{t('matchups.view.everyVersion')}</Button>}
      />
    )
  } else if (rows.length === 0) {
    body = (
      <EmptyState
        icon={icon}
        title={t('matchups.view.noFinishedTitle')}
        message={t('matchups.view.noFinishedMessage')}
      />
    )
  } else {
    body = (
      <>
        <div className="grid gap-4 md:grid-cols-3">
          {tiles.map((tile) => (
            <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
          ))}
        </div>

        <Card title={t('matchups.view.archetypesMet')} subtitle={t('matchups.view.archetypesMetSubtitle')}>
          <DataTable
            columns={[
              t('matchups.view.columns.archetype'),
              t('matchups.view.columns.matches'),
              t('matchups.view.columns.record'),
              t('matchups.view.columns.rate'),
              t('matchups.view.columns.game1'),
              t('matchups.view.columns.postboard'),
            ]}
            rows={rows.map((row) => {
              const name = matchupName(row, t)
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
                    {fieldLine({ won: row.gamesWon, lost: row.gamesLost }, field, t)}
                  </div>
                </div>,
                formatCount(row.matches),
                formatRecord(row.won, row.lost),
                <RateCell key="rate" wins={row.won} losses={row.lost} />,
                <RateCell key="game1" wins={row.game1Won} losses={row.game1Lost} games />,
                <RateCell key="postboard" wins={row.postboardWon} losses={row.postboardLost} games />,
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
