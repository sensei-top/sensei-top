import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, Outlet, ScrollRestoration, useLocation, useMatches } from 'react-router'
import { useLive } from '../api'
import { BrandGlyph, Callout, TextLink } from '../components/ui'
import { wizardsNotice } from '../credits'
import { BottomBar } from './BottomBar'
import { LiveStatus } from './LiveStatus'
import { documentTitle, placeAt, PRODUCT_NAME } from './places'
import { Rail } from './Rail'

// The main column's width, and its gutters: the bar, the page and the
// footer line up on the same edges.
const COLUMN = 'mx-auto w-full max-w-[1196px] px-3.5 md:px-9'

/** The first thing a keyboard reaches: past the rail, straight to the page.
 *  Out of sight until it holds focus, which it tracks itself rather than
 *  through a class of its own: the page's one `:focus-visible` ring is
 *  still the one that marks it. */
function SkipLink() {
  const [shown, setShown] = useState(false)
  return (
    <a
      href="#page"
      onFocus={() => setShown(true)}
      onBlur={() => setShown(false)}
      onClick={(event) => {
        // The router owns the address; moving focus is all this link does.
        event.preventDefault()
        document.getElementById('page')?.focus()
      }}
      className={
        shown
          ? 'fixed top-4 left-4 z-50 rounded-control bg-surface3 px-4 py-2.5 text-caption font-medium text-ink shadow-lift'
          : 'sr-only'
      }
    >
      Skip to the page
    </a>
  )
}

/** The layout every place renders in: the skip link, the rail (48rem up) or
 *  the strip and the bottom bar (under it), the bar with the place's name as
 *  the page's one `h1` and the live status, the page, the footer. The window
 *  scrolls, not an element inside it, so `ScrollRestoration` puts a list
 *  back where it was left when Back returns to it.
 *
 *  Live is in focus mode from 48rem up: the bar and the footer go and the
 *  page is capped at the window's height, so a live read never scrolls on
 *  a second monitor. The rail stays as it is, and the name stays as the
 *  `h1` for a screen reader. Under 48rem it scrolls like any other page. */
export function Shell() {
  const live = useLive()
  const { pathname } = useLocation()
  const notFound = useMatches().some((match) => (match.handle as { notFound?: boolean } | undefined)?.notFound)
  const place = notFound ? null : placeAt(pathname)
  const name = place?.label ?? 'No such page'
  const focus = place?.id === 'live'

  // The heartbeat is the only thing on a timer (current-match/read, ridden by
  // CurrentMatchView, is the one scoped exception — see its own hook). When
  // it reports a new projection_revision, every other query is marked stale
  // and the visible ones refetch — so an idle dashboard costs one small
  // request every few seconds, and a live one updates within a beat of the
  // projector committing.
  //
  // projection_revision, not revision: revision moves on every 1 Hz ingest
  // tick (raw_events growing), which is not something any query here reads
  // — matches/games/turns/etc. only change when a rebuild actually commits.
  // Keying invalidation on revision was invalidating every mounted query on
  // every heartbeat for the whole session, not just when there was new
  // projected data to show (docs/frontend.md has the numbers).
  // projection_revision is what actually moves on that beat instead.
  const queryClient = useQueryClient()
  const projectionRevision = live.data?.projection_revision
  useEffect(() => {
    if (!projectionRevision) return
    queryClient.invalidateQueries({
      predicate: (q) => q.queryKey[0] !== 'live',
    })
  }, [projectionRevision, queryClient])

  useEffect(() => {
    document.title = documentTitle(place)
  }, [place])

  return (
    <div className="min-h-screen bg-plane md:flex">
      <SkipLink />
      <Rail current={place} />

      {/* Under 48rem the bottom bar is fixed over the window's foot, so the
          column leaves its height free under the footer. */}
      <div
        className={`flex min-h-screen min-w-0 flex-1 flex-col pb-[calc(4rem+env(safe-area-inset-bottom))] md:pb-0 ${
          focus ? 'md:h-screen md:overflow-hidden' : ''
        }`}
      >
        {/* The strip under 48rem, sticky, on surface-1; the bar from 48rem
            up, on the plane. In focus mode the bar leaves the screen and its
            name stays for a screen reader. */}
        <header
          className={`sticky top-0 z-20 shrink-0 border-b border-line bg-surface md:static md:border-0 md:bg-transparent ${
            focus ? 'md:sr-only' : ''
          }`}
        >
          <div className={`${COLUMN} flex items-center gap-3 py-2.5 md:pt-7 md:pb-0`}>
            <Link
              to="/"
              aria-label={`${PRODUCT_NAME}, home`}
              className="flex size-9 shrink-0 items-center justify-center rounded-control text-accent md:hidden"
            >
              <BrandGlyph size={24} />
            </Link>
            <h1 className="min-w-0 flex-1 truncate font-display text-title text-ink md:text-heading">{name}</h1>
            <LiveStatus className={focus ? 'md:hidden' : ''} />
          </div>
        </header>

        <main
          id="page"
          tabIndex={-1}
          className={`${COLUMN} flex-1 py-5 md:py-7 ${
            focus ? 'md:flex md:min-h-0 md:flex-col md:overflow-hidden md:py-3' : ''
          }`}
        >
          {live.isError && (
            <div className="mb-4 shrink-0">
              <Callout tone="warn">
                The tracker is not running, so nothing new can load. What is on screen is what was last loaded.
                This notice goes away once the tracker answers again.
              </Callout>
            </div>
          )}
          {/* In focus mode the page fills what the callout leaves, and a live
              view's own h-full column measures against this box. */}
          <div className={focus ? 'md:flex md:min-h-0 md:flex-1 md:flex-col' : undefined}>
            <Outlet />
          </div>
        </main>

        <footer className={`shrink-0 border-t border-line ${focus ? 'md:hidden' : ''}`}>
          {/* Wizards' notice comes from credits.ts, like every sentence the
              credits show. */}
          <div className={`${COLUMN} flex flex-wrap items-baseline gap-x-3 gap-y-1 py-4 text-caption text-muted`}>
            <p className="min-w-0 flex-1">
              Reads a local SQLite database. No account, no upload. {wizardsNotice}
            </p>
            <TextLink href="/settings#credits" className="shrink-0">
              Credits
            </TextLink>
          </div>
        </footer>
      </div>

      <BottomBar current={place} />
      <ScrollRestoration />
    </div>
  )
}
