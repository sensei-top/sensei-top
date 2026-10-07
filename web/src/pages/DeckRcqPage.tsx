import { useOutletContext } from 'react-router'
import { RcqView } from '../views/RcqView'
import type { DeckOutletContext } from './DeckLayout'

/** `/decks/:id/guide/rcq`: the RCQ prep of the address's deck, read by
 *  the deck's key, whichever version the address chose, as the Guide is.
 *  Keyed by that key, so moving to another deck starts the page afresh,
 *  its inputs read again from that deck's own. */
export function DeckRcqPage() {
  const { deckKey } = useOutletContext<DeckOutletContext>()
  return <RcqView key={deckKey} deckKey={deckKey} />
}
