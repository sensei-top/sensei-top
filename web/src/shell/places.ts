import {
  Globe,
  GraduationCap,
  House,
  Layers,
  Radio,
  Settings,
  Swords,
  type LucideIcon,
} from 'lucide-react'
import type { TFunction } from '../i18n'

export type PlaceId = 'home' | 'live' | 'matches' | 'decks' | 'field' | 'coach' | 'settings'

export type Place = { id: PlaceId; path: string; icon: LucideIcon }

/** The seven places, in the rail's order, Settings last. One icon each and
 *  no two alike, so a place is told apart by its icon as well as its word
 *  (`placeLabel`). */
export const PLACES: readonly Place[] = [
  { id: 'home', path: '/', icon: House },
  { id: 'live', path: '/live', icon: Radio },
  { id: 'matches', path: '/matches', icon: Swords },
  { id: 'decks', path: '/decks', icon: Layers },
  { id: 'field', path: '/field', icon: Globe },
  { id: 'coach', path: '/coach', icon: GraduationCap },
  { id: 'settings', path: '/settings', icon: Settings },
]

/** A place's word, "Matches": its label in the rail and the bars, and the
 *  layout's `h1` while the page is there. */
export function placeLabel(place: Place, t: TFunction): string {
  const labels: Record<PlaceId, string> = {
    home: t('shell.places.home'),
    live: t('shell.places.live'),
    matches: t('shell.places.matches'),
    decks: t('shell.places.decks'),
    field: t('shell.places.field'),
    coach: t('shell.places.coach'),
    settings: t('shell.places.settings'),
  }
  return labels[place.id]
}

/** The bottom bar's four places; every other one is behind its More. */
export const BAR_PLACES: readonly PlaceId[] = ['home', 'live', 'matches', 'decks']

/** The product's name, the same in every language. */
export const PRODUCT_NAME = 'Sensei Top'

const PLACE_BY_ID = Object.fromEntries(PLACES.map((place) => [place.id, place])) as Record<PlaceId, Place>

/** A place by its id: where a page needs the place's own icon or word
 *  (an empty state's icon), rather than a second import of it. */
export function placeById(id: PlaceId): Place {
  return PLACE_BY_ID[id]
}

/** The place an address is at or under. Home only at `/` itself, since
 *  every address is under it. */
export function placeAt(pathname: string): Place | null {
  if (pathname === '/') return PLACES[0]
  return (
    PLACES.find(
      (place) => place.path !== '/' && (pathname === place.path || pathname.startsWith(`${place.path}/`)),
    ) ?? null
  )
}

/** "Matches · Sensei Top"; the product's name alone at Home and on an
 *  address that is no place. `title` names an address that is not a place
 *  but has a name of its own ("Welcome · Sensei Top"). */
export function documentTitle(place: Place | null, t: TFunction, title: string | null = null): string {
  const name = place ? (place.id !== 'home' ? placeLabel(place, t) : null) : title
  return name ? t('shell.documentTitle', { name, product: PRODUCT_NAME }) : PRODUCT_NAME
}

/** An address that is no place in the rail but has a name of its own. */
export type RouteTitle = 'mtgoPicks' | 'welcome'

/** The name of an address that is no place, "Welcome". */
export function routeTitle(title: RouteTitle, t: TFunction): string {
  const titles: Record<RouteTitle, string> = {
    mtgoPicks: t('shell.titles.mtgoPicks'),
    welcome: t('shell.titles.welcome'),
  }
  return titles[title]
}

/** What a route says of itself to the layout. */
export type RouteHandle = {
  /** The address is no page: the name is "No such page". */
  notFound?: boolean
  /** The name of an address that is no place in the rail (`routeTitle`). */
  title?: RouteTitle
  /** The page is only for a desktop shell; in a browser it is not found. */
  needsShell?: boolean
}

/** The name the layout shows as the `h1`, and `title`, the name of a
 *  non-place for the document's title (`null` when it has none or is not
 *  found). `handle` is the deepest matched route's. */
export function layoutName(
  place: Place | null,
  handle: RouteHandle | undefined,
  hasShell: boolean,
  t: TFunction,
): { name: string; title: string | null } {
  const notFound = { name: t('shell.notFound'), title: null }
  if (handle?.notFound) return notFound
  if (place) return { name: placeLabel(place, t), title: null }
  if (handle?.title && (hasShell || !handle.needsShell)) {
    const name = routeTitle(handle.title, t)
    return { name, title: name }
  }
  return notFound
}
