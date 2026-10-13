import { useParams } from 'react-router'
import { reportParam } from '../lib/coach'
import { CoachView } from '../views/CoachView'

/** `/coach`, the latest report, and `/coach/:id`, one report. Keyed by
 *  the parameter, as `MatchPage` is, so moving between reports starts the
 *  model picker fresh. */
export function CoachPage() {
  const { id } = useParams()
  return <CoachView key={id ?? ''} report={reportParam(id)} />
}
