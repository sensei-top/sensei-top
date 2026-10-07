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

export type PlaceId = 'home' | 'live' | 'matches' | 'decks' | 'field' | 'coach' | 'settings'

export type Place = { id: PlaceId; label: string; path: string; icon: LucideIcon }

/** The seven places, in the rail's order, Settings last. One icon each and
 *  no two alike, so a place is told apart by its icon as well as its word. */
export const PLACES: readonly Place[] = [
  { id: 'home', label: 'Home', path: '/', icon: House },
  { id: 'live', label: 'Live', path: '/live', icon: Radio },
  { id: 'matches', label: 'Matches', path: '/matches', icon: Swords },
  { id: 'decks', label: 'Decks', path: '/decks', icon: Layers },
  { id: 'field', label: 'Field', path: '/field', icon: Globe },
  { id: 'coach', label: 'Coach', path: '/coach', icon: GraduationCap },
  { id: 'settings', label: 'Settings', path: '/settings', icon: Settings },
]

/** The bottom bar's four places; every other one is behind its More. */
export const BAR_PLACES: readonly PlaceId[] = ['home', 'live', 'matches', 'decks']

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
 *  address that is no place. */
export function documentTitle(place: Place | null): string {
  return place && place.id !== 'home' ? `${place.label} · ${PRODUCT_NAME}` : PRODUCT_NAME
}
