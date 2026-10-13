import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLive, useMatches } from '../api'
import { MatchesSummary } from '../components/MatchesSummary'
import { MatchRow } from '../components/MatchRow'
import { Button, Card, EmptyState, ErrorNote, Loading } from '../components/ui'
import type { TFunction } from '../i18n'
import { formatCount } from '../lib/time'
import { placeById } from '../shell/places'

/** The route's maximum: the list asks for the newest this many. */
const MATCH_LIST_LIMIT = 500

/** Rows shown at first, and added by each press of the button. */
const STEP = 50

/** The words over the rows: how many are listed, of how many in hand. */
function listCaption(inHand: number, shown: number, full: boolean, t: TFunction): string {
  const values = { shown: formatCount(shown), inHand: formatCount(inHand) }
  if (full) {
    return shown < inHand ? t('matches.history.capFullShowing', values) : t('matches.history.capFull', values)
  }
  if (inHand === 1) return t('matches.history.capOne')
  return shown < inHand ? t('matches.history.capShowing', values) : t('matches.history.capAll', values)
}

/** Matches' band and list, under the source and deck filters: the newest
 *  500 matches, 50 rows at a time, each row the way into its match. The
 *  band counts every match in hand, not only the rows shown. The shown
 *  count starts again at 50 when a filter changes (the page keys this
 *  view on them). */
export function MatchHistoryView({ deckId, source }: { deckId?: string; source?: string }) {
  const { t } = useTranslation()
  const matches = useMatches(deckId, source, MATCH_LIST_LIMIT)
  const live = useLive()
  const [shown, setShown] = useState(STEP)

  if (matches.isPending) return <Loading />
  if (matches.error) return <ErrorNote error={matches.error} />
  if (!matches.data.length) {
    // Until the heartbeat answers, which empty state applies is unknown.
    if (live.isPending) return <Loading />
    // The heartbeat counts every match recorded, from every source: none
    // at all is the first case, some elsewhere the second.
    const recorded = live.data?.matches ?? 0
    if (recorded === 0) {
      return (
        <EmptyState
          icon={placeById('matches').icon}
          title={t('matches.history.emptyTitle')}
          message={t('matches.history.emptyMessage')}
        />
      )
    }
    return (
      <EmptyState
        icon={placeById('matches').icon}
        title={t('matches.history.noFitTitle')}
        message={t('matches.history.elsewhere', { count: recorded, n: formatCount(recorded) })}
        action={<Button href="/matches?source=all">{t('matches.history.showEvery')}</Button>}
      />
    )
  }

  const inHand = matches.data
  const full = inHand.length >= MATCH_LIST_LIMIT
  const rows = inHand.slice(0, shown)
  const left = inHand.length - rows.length

  return (
    <div className="space-y-8">
      <MatchesSummary matches={inHand} full={full} />
      <Card>
        <p className="mb-3 text-caption text-muted">{listCaption(inHand.length, rows.length, full, t)}</p>
        <ul className="divide-y divide-line">
          {rows.map((match) => (
            <li key={match.match_id} className="py-1 first:pt-0 last:pb-0">
              <MatchRow match={match} withEvent />
            </li>
          ))}
        </ul>
        {left > 0 && (
          <div className="mt-4">
            <Button onClick={() => setShown((count) => count + STEP)}>
              {t('matches.history.showMore', { n: formatCount(Math.min(STEP, left)) })}
            </Button>
          </div>
        )}
        {full && left === 0 && (
          <p className="mt-4 text-caption text-muted">
            {t('matches.history.stops', { n: formatCount(inHand.length) })}
          </p>
        )}
      </Card>
    </div>
  )
}
