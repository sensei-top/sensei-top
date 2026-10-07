import type { Match } from '../../api'
import { formatCount } from '../../lib/time'
import { MatchRow } from '../MatchRow'
import { Card, TextLink } from '../ui'

/** The eight newest matches, finished or not, each row the way into its
 *  match. The score puts the viewer's own games first. */
export function RecentMatches({ matches, total }: { matches: Match[]; total: number | undefined }) {
  return (
    <Card
      title="Recent matches"
      className="h-full"
      action={
        <TextLink href="/matches?source=all" className="text-caption">
          {total != null ? `All ${formatCount(total)} matches` : 'All matches'}
        </TextLink>
      }
    >
      <ul className="divide-y divide-line">
        {matches.map((match) => (
          <li key={match.match_id} className="py-1 first:pt-0 last:pb-0">
            <MatchRow match={match} />
          </li>
        ))}
      </ul>
    </Card>
  )
}
