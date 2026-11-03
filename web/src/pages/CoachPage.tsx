import { useParams } from 'react-router'
import { useAi } from '../ai/registry'

/** `/coach`, the latest report, and `/coach/:id`, one report. Keyed by
 *  the parameter, as `MatchPage` is, so moving between reports starts the
 *  model picker fresh. */
export function CoachPage() {
  const { id } = useParams()
  const ai = useAi()
  if (ai === null) return null
  return <ai.CoachView key={id ?? ''} id={id} />
}
