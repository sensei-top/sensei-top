import { useParams } from 'react-router'
import { MatchDetailView } from '../views/MatchDetailView'
import { MatchReplayView } from '../views/MatchReplayView'

/** `/matches/:id`: one match's report. Keyed by the id, so moving to
 *  another match starts its deck picker and its disclosures fresh. */
export function MatchPage() {
  const { id = '' } = useParams()
  return <MatchDetailView key={id} matchId={id} />
}

/** `/matches/:id/replay`: the match's games turn by turn. The view keeps
 *  the game and the turn in the address. Keyed by the id, as the report
 *  is. */
export function MatchReplayPage() {
  const { id = '' } = useParams()
  return <MatchReplayView key={id} matchId={id} />
}
