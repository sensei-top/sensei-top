import { Navigate, useParams } from 'react-router'
import { useAi } from '../ai/registry'
import { useAiFeatures } from '../shell/aiFeatures'

/** `/coach`, the latest report, and `/coach/:id`, one report. Keyed by
 *  the parameter, as `MatchPage` is, so moving between reports starts the
 *  model picker fresh. With AI features off both addresses go Home. */
export function CoachPage() {
  const { id } = useParams()
  const [aiOn] = useAiFeatures()
  const ai = useAi()
  if (!aiOn) return <Navigate to="/" replace />
  if (ai === null) return null
  return <ai.CoachView key={id ?? ''} id={id} />
}
