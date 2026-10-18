import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router'
import { useDeckMatches, useDeckVersions, type Match } from '../api'
import { DeckMatchesCard } from '../components/DeckMatchesCard'
import { VersionSwitcher } from '../components/VersionSwitcher'
import { Button, Card, Chip, DataTable, EmptyState, ErrorNote, Loading } from '../components/ui'
import { mergeNewestFirst, rankRows, versionDays, versionRecord } from '../lib/deckOverview'
import { formatCount, useNow } from '../lib/time'
import { placeById } from '../shell/places'

const MINUTE = 60_000

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
  else if (matches.isPending) body = <Loading />
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
    <div className="space-y-8">
      {switcher}
      {body}
    </div>
  )
}
