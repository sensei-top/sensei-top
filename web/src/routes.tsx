import type { RouteObject } from 'react-router'
import { CoachPage } from './pages/CoachPage'
import { DecksPage } from './pages/DecksPage'
import { DeckLayout } from './pages/DeckLayout'
import { DeckGuidePage, DeckMatchupsPage, DeckOverviewPage, DeckPairingPage } from './pages/DeckPages'
import { DesignPage } from './pages/DesignPage'
import { DesignSurfacesPage } from './pages/DesignSurfacesPage'
import { FieldPage } from './pages/FieldPage'
import { HomePage } from './pages/HomePage'
import { MatchesPage } from './pages/MatchesPage'
import { MatchPage, MatchReplayPage } from './pages/MatchPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { SettingsPage } from './pages/SettingsPage'
import { Shell } from './shell/Shell'
import { CurrentMatchView } from './views/CurrentMatchView'

/** Every address the dashboard answers (the plan's S5 table). No loader and
 *  no action: TanStack Query stays the only data layer, and a route only
 *  says which page an address shows. The API answers any address that is
 *  not `/api/...` or a file with the dashboard itself, so each of these
 *  opens from a cold load. */
export const routes: RouteObject[] = [
  // The design reference and its second page, surfaces, stand in place of
  // the app, outside the shell.
  { path: '/design', Component: DesignPage },
  { path: '/design/surfaces', Component: DesignSurfacesPage },
  {
    path: '/',
    Component: Shell,
    children: [
      { index: true, Component: HomePage },
      { path: 'live', Component: CurrentMatchView },
      { path: 'matches', Component: MatchesPage },
      { path: 'matches/:id', Component: MatchPage },
      { path: 'matches/:id/replay', Component: MatchReplayPage },
      { path: 'decks', Component: DecksPage },
      {
        path: 'decks/:id',
        Component: DeckLayout,
        children: [
          { index: true, Component: DeckOverviewPage },
          { path: 'matchups', Component: DeckMatchupsPage },
          { path: 'matchups/:opponent', Component: DeckPairingPage },
          { path: 'guide', Component: DeckGuidePage },
        ],
      },
      { path: 'field', Component: FieldPage },
      { path: 'coach', Component: CoachPage },
      { path: 'coach/:id', Component: CoachPage },
      { path: 'settings', Component: SettingsPage },
      // The shell reads this handle: no place is current, and its name is
      // "No such page".
      { path: '*', Component: NotFoundPage, handle: { notFound: true } },
    ],
  },
]
