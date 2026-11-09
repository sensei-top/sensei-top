import type { RouteObject } from 'react-router'
import { SETTINGS_GROUPS } from './lib/settings'
import { AccountWelcomePage } from './pages/AccountWelcomePage'
import { ContributePage } from './pages/ContributePage'
import { CoachPage } from './pages/CoachPage'
import { DecksPage } from './pages/DecksPage'
import { DeckLayout } from './pages/DeckLayout'
import { DeckRcqPage, RcqRedirect } from './pages/DeckRcqPage'
import { DeckGuidePage, DeckMatchupsPage, DeckOverviewPage, DeckPairingPage } from './pages/DeckPages'
import { ErrorPage } from './pages/ErrorPage'
import { DesignPage } from './pages/DesignPage'
import { DesignSurfacesPage } from './pages/DesignSurfacesPage'
import { FieldEventPage } from './pages/FieldEventPage'
import { FieldPage } from './pages/FieldPage'
import { HomePage } from './pages/HomePage'
import { MatchesPage } from './pages/MatchesPage'
import { MatchPage, MatchReplayPage } from './pages/MatchPage'
import { MtgoPicksPage } from './pages/MtgoPicksPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { SettingsLayout } from './pages/SettingsLayout'
import { SettingsPage } from './pages/SettingsPage'
import { WelcomePage } from './pages/WelcomePage'
import { Shell } from './shell/Shell'
import type { RouteHandle } from './shell/places'
import { CurrentMatchView } from './views/CurrentMatchView'

/** Every address the dashboard answers (the plan's S5 table). No loader and
 *  no action: TanStack Query stays the only data layer, and a route only
 *  says which page an address shows. The API answers any address that is
 *  not `/api/...` or a file with the dashboard itself, so each of these
 *  opens from a cold load. */
export const routes: RouteObject[] = [
  // The design reference and its second page, surfaces, stand in place of
  // the app, outside the shell.
  { path: '/design', Component: DesignPage, ErrorBoundary: ErrorPage },
  { path: '/design/surfaces', Component: DesignSurfacesPage, ErrorBoundary: ErrorPage },
  {
    path: '/',
    Component: Shell,
    // An error in the layout itself lands here, without the layout.
    ErrorBoundary: ErrorPage,
    children: [
      // A page's error lands in this pathless route instead, so the layout stays
      // around it and the screen fills the page area.
      {
        ErrorBoundary: ErrorPage,
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
              { path: 'rcq', Component: DeckRcqPage },
              { path: 'guide/rcq', Component: RcqRedirect },
            ],
          },
          { path: 'field', Component: FieldPage },
          { path: 'field/events/*', Component: FieldEventPage },
          { path: 'coach', Component: CoachPage },
          { path: 'coach/:id', Component: CoachPage },
          // Bare `/settings` is sent on to a group by the layout.
          {
            path: 'settings',
            Component: SettingsLayout,
            children: SETTINGS_GROUPS.map((group) => ({
              path: group.id,
              element: <SettingsPage group={group.id} />,
            })),
          },
          // Not a place in the rail: Home's "Needs a deck" card links to it. Its
          // name, and Welcome's, is a key the shell resolves (`routeTitle`).
          {
            path: 'mtgo/picks',
            Component: MtgoPicksPage,
            handle: { title: 'mtgoPicks' } satisfies RouteHandle,
          },
          // Not a place in the rail: the shell opens it until onboarding is done,
          // and Settings links back to it.
          {
            path: 'welcome',
            Component: WelcomePage,
            handle: { title: 'welcome', needsShell: true, bare: true } satisfies RouteHandle,
          },
          // Not a place in the rail: the shell layout sends a signed-in user here
          // until the account's consent questions are answered under the current
          // policy. Its title is the consent screen's own heading (`accountWelcome`).
          {
            path: 'account/welcome',
            Component: AccountWelcomePage,
            handle: { title: 'accountWelcome', needsShell: true, bare: true } satisfies RouteHandle,
          },
          // Not a place in the rail: the shell opens it once, for an install that
          // has not answered "Help build the stats". Its name is the question's.
          {
            path: 'contribute',
            Component: ContributePage,
            handle: { title: 'contribute', needsShell: true, bare: true } satisfies RouteHandle,
          },
          // The shell reads this handle: no place is current, and its name is
          // "No such page".
          { path: '*', Component: NotFoundPage, handle: { notFound: true } satisfies RouteHandle },
        ],
      },
    ],
  },
]
