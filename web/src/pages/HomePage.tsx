import { HomeView } from '../views/HomeView'

/** `/`: Home, over every source and with no filter, so a player with no
 *  Arena match still opens a page with their own on it. One deck's own
 *  record, over any of its versions, is on its Overview
 *  (`DeckOverviewView`). */
export function HomePage() {
  return <HomeView />
}
