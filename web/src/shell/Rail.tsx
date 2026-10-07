import { Link } from 'react-router'
import { BrandGlyph } from '../components/ui'
import { useMatchInProgress } from '../lib/liveMatch'
import { PLACES, PRODUCT_NAME, type Place } from './places'

/** A place's icon, with the live dot when something is happening there
 *  right now (only ever Live). Never colour alone: the dot is
 *  decoration, the words before the label are the fact. */
export function PlaceIcon({ place, live, current }: { place: Place; live: boolean; current: boolean }) {
  const Icon = place.icon
  return (
    <span className="relative shrink-0 leading-none">
      <Icon size={22} strokeWidth={1.75} aria-hidden className={current ? 'text-accent' : undefined} />
      {live && (
        <>
          <span
            aria-hidden
            className="absolute -top-1 -right-1 inline-block size-2 animate-pulse rounded-full bg-s3"
          />
          <span className="sr-only">match in progress,</span>
        </>
      )}
    </span>
  )
}

/** The rail, from 48rem up: the glyph (a link Home), then every place as an
 *  icon over its label, Settings pushed to the bottom. It stays as it is in
 *  focus mode, so every place is one click away while a live read fills the
 *  rest of the window. Focus is the page's one `:focus-visible` ring. */
export function Rail({ current }: { current: Place | null }) {
  const matchInProgress = useMatchInProgress()
  const isLive = (place: Place) => place.id === 'live' && matchInProgress
  return (
    <nav
      aria-label="Main"
      className="sticky top-0 hidden h-screen w-[84px] shrink-0 flex-col items-center gap-1 self-start overflow-y-auto border-r border-line bg-surface px-1.5 py-4 md:flex"
    >
      <Link
        to="/"
        aria-label={`${PRODUCT_NAME}, home`}
        className="mb-3 flex size-11 items-center justify-center rounded-control text-accent"
      >
        <BrandGlyph size={28} />
      </Link>
      {PLACES.map((place) => {
        const isCurrent = current?.id === place.id
        return (
          <Link
            key={place.id}
            to={place.path}
            aria-current={isCurrent ? 'page' : undefined}
            className={`flex w-full flex-col items-center gap-1 rounded-control px-1 py-2 text-chip font-medium transition-chrome ${
              place.id === 'settings' ? 'mt-auto' : ''
            } ${isCurrent ? 'bg-surface3 text-ink' : 'text-muted hover:text-ink'}`}
          >
            <PlaceIcon place={place} live={isLive(place)} current={isCurrent} />
            <span>{place.label}</span>
          </Link>
        )
      })}
    </nav>
  )
}
