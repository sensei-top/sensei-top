import { MtgoPicksView } from '../views/MtgoPicksView'

/** `/mtgo/picks`: every MTGO match still waiting for a deck, grouped so a
 *  whole group is confirmed at once. The address carries nothing to read. */
export function MtgoPicksPage() {
  return <MtgoPicksView />
}
