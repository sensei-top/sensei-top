import { Navigate, useLocation, useOutletContext } from 'react-router'
import { RcqView } from '../views/RcqView'
import type { DeckOutletContext } from './DeckLayout'

/** `/decks/:id/rcq`: the RCQ prep of the address's deck, read by
 *  the deck's key, whichever version the address chose, as the Guide is.
 *  Keyed by that key, so moving to another deck starts the page afresh,
 *  its inputs read again from that deck's own. */
export function DeckRcqPage() {
  const { deckKey } = useOutletContext<DeckOutletContext>()
  return <RcqView key={deckKey} deckKey={deckKey} />
}

/** `/decks/:id/guide/rcq` was the RCQ page's address in 1.0.x; it is the
 *  RCQ tab now. A bookmark keeps its search and hash. */
export function RcqRedirect() {
  const { search, hash } = useLocation()
  return <Navigate to={{ pathname: '../rcq', search, hash }} replace />
}
