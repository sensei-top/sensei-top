import { useState } from 'react'
import { useLive, useMatches } from '../api'
import { MatchesSummary } from '../components/MatchesSummary'
import { MatchRow } from '../components/MatchRow'
import { Button, Card, EmptyState, ErrorNote, Loading } from '../components/ui'
import { formatCount } from '../lib/time'
import { placeById } from '../shell/places'

/** The route's maximum: the list asks for the newest this many. */
const MATCH_LIST_LIMIT = 500

/** Rows shown at first, and added by each press of the button. */
const STEP = 50

/** The words over the rows: how many are listed, of how many in hand. */
function listCaption(inHand: number, shown: number, full: boolean): string {
  if (full) {
    return shown < inHand
      ? `Showing ${formatCount(shown)} of the ${formatCount(inHand)} newest matches`
      : `The ${formatCount(inHand)} newest matches`
  }
  if (inHand === 1) return '1 match'
  return shown < inHand
    ? `Showing ${formatCount(shown)} of ${formatCount(inHand)} matches, newest first`
    : `${formatCount(inHand)} matches, newest first`
}

/** Matches' band and list, under the source and deck filters: the newest
 *  500 matches, 50 rows at a time, each row the way into its match. The
 *  band counts every match in hand, not only the rows shown. The shown
 *  count starts again at 50 when a filter changes (the page keys this
 *  view on them). */
export function MatchHistoryView({ deckId, source }: { deckId?: string; source?: string }) {
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
          title="No matches yet"
          message="Every match you play appears here when it ends, with its report and a turn-by-turn replay."
        />
      )
    }
    return (
      <EmptyState
        icon={placeById('matches').icon}
        title="No match fits these filters"
        message={
          recorded === 1
            ? '1 match is recorded under another source or deck.'
            : `${formatCount(recorded)} matches are recorded under another source or deck.`
        }
        action={<Button href="/matches?source=all">Show every match</Button>}
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
        <p className="mb-3 text-caption text-muted">{listCaption(inHand.length, rows.length, full)}</p>
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
              Show {formatCount(Math.min(STEP, left))} more
            </Button>
          </div>
        )}
        {full && left === 0 && (
          <p className="mt-4 text-caption text-muted">
            The list stops at the {formatCount(inHand.length)} newest matches.
          </p>
        )}
      </Card>
    </div>
  )
}
