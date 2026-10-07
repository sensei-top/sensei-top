import { Ellipsis, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { Button } from '../components/ui'
import { useMatchInProgress } from '../lib/liveMatch'
import { PlaceIcon } from './Rail'
import { BAR_PLACES, PLACES, type Place } from './places'

const BAR = PLACES.filter((place) => BAR_PLACES.includes(place.id))
const MORE = PLACES.filter((place) => !BAR_PLACES.includes(place.id))

const ITEM_CLASS =
  'flex min-h-[44px] flex-col items-center justify-center gap-0.5 rounded-control px-1 py-1.5 text-chip font-medium transition-chrome'

function itemLook(current: boolean) {
  return `${ITEM_CLASS} ${current ? 'bg-surface3 text-ink' : 'text-muted hover:text-ink'}`
}

/** Under 48rem, in place of the rail: Home, Live, Matches and Decks, and
 *  More for the rest. More opens a native modal `<dialog>`, which holds
 *  focus while it is open and closes on Escape by itself; More reads as
 *  current when the page is one of the places behind it. Every target is
 *  at least 44 px high. */
export function BottomBar({ current }: { current: Place | null }) {
  const matchInProgress = useMatchInProgress()
  const isLive = (place: Place) => place.id === 'live' && matchInProgress
  const sheet = useRef<HTMLDialogElement>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const location = useLocation()
  const moreCurrent = current !== null && MORE.some((place) => place.id === current.id)

  // Any navigation closes the sheet, Back included.
  useEffect(() => {
    sheet.current?.close()
  }, [location.key])

  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface px-1.5 pt-1 pb-[max(0.25rem,env(safe-area-inset-bottom))] md:hidden"
    >
      <div className="grid grid-cols-5 gap-1">
        {BAR.map((place) => {
          const isCurrent = current?.id === place.id
          return (
            <Link
              key={place.id}
              to={place.path}
              aria-current={isCurrent ? 'page' : undefined}
              className={itemLook(isCurrent)}
            >
              <PlaceIcon place={place} live={isLive(place)} current={isCurrent} />
              <span>{place.label}</span>
            </Link>
          )
        })}
        <button
          type="button"
          aria-haspopup="dialog"
          aria-expanded={sheetOpen}
          onClick={() => {
            sheet.current?.showModal()
            setSheetOpen(true)
          }}
          className={itemLook(moreCurrent)}
        >
          <Ellipsis size={22} strokeWidth={1.75} aria-hidden className={moreCurrent ? 'text-accent' : undefined} />
          <span>More</span>
        </button>
      </div>

      <dialog
        ref={sheet}
        aria-label="More places"
        onClose={() => setSheetOpen(false)}
        // A click on the backdrop lands on the dialog itself, never on
        // anything inside it.
        onClick={(event) => {
          if (event.target === event.currentTarget) event.currentTarget.close()
        }}
        className="m-0 mt-auto w-full max-w-none rounded-t-card border-t border-line bg-surface p-0 text-ink shadow-lift backdrop:bg-plane/70"
      >
        <div className="flex flex-col gap-1 px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <div className="flex justify-end">
            <Button variant="quiet" onClick={() => sheet.current?.close()}>
              <X size={18} strokeWidth={1.75} aria-hidden />
              Close
            </Button>
          </div>
          {MORE.map((place) => {
            const isCurrent = current?.id === place.id
            return (
              <Link
                key={place.id}
                to={place.path}
                aria-current={isCurrent ? 'page' : undefined}
                onClick={() => sheet.current?.close()}
                className={`flex min-h-[44px] items-center gap-3 rounded-control px-3 text-body font-medium transition-chrome ${
                  isCurrent ? 'bg-surface3 text-ink' : 'text-muted hover:text-ink'
                }`}
              >
                <PlaceIcon place={place} live={isLive(place)} current={isCurrent} />
                <span>{place.label}</span>
              </Link>
            )
          })}
        </div>
      </dialog>
    </nav>
  )
}
