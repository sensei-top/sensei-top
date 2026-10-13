import { useEffect, useRef } from 'react'
import type { MouseEvent, ReactNode, RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router'
import { rowScrollTarget } from '../../lib/guide'
import type { GuideSection } from '../../lib/guide'
import { TextLink } from '../ui'

/** `smooth` unless the viewer asks for reduced motion. */
function scrollBehavior(): ScrollBehavior {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
}

/** The one way to a section, for the nav's links and every link to a
 *  section in the page: the window moves down or up to the section's top
 *  less its own `scroll-margin-top`, and never sideways. Not
 *  `scrollIntoView`, which moves every scrolling ancestor on both axes.
 *  Focus then moves to the section (its block takes `tabIndex={-1}`)
 *  without a second scroll, so the next Tab starts inside it rather than
 *  back at the link. */
function goToSection(id: string) {
  const element = document.getElementById(id)
  if (!element) return
  const margin = Number.parseFloat(getComputedStyle(element).scrollMarginTop) || 0
  const top = element.getBoundingClientRect().top + window.scrollY - margin
  window.scrollTo({ top, behavior: scrollBehavior() })
  element.focus({ preventScroll: true })
}

/** The shell's header: the element just before `#page`, which Shell.tsx
 *  draws as a sticky strip under 48rem. `null` if that ever changes. */
function shellHeader(): HTMLElement | null {
  const header = document.getElementById('page')?.previousElementSibling
  return header instanceof HTMLElement && header.tagName === 'HEADER' ? header : null
}

/** Writes on the strip's parent, the view's root, the two heights the
 *  strip's `top` and the sections' `scroll-margin-top` are made of, as
 *  read from the DOM: `--guide-header`, the shell's header, and
 *  `--guide-strip`, the strip itself. Read once on mount and again
 *  whenever either box changes size (the width, the density setting). */
function useStickyHeights(strip: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const element = strip.current
    const root = element?.parentElement
    if (!element || !root) return
    const header = shellHeader()
    const write = () => {
      root.style.setProperty('--guide-header', `${header?.getBoundingClientRect().height ?? 0}px`)
      root.style.setProperty('--guide-strip', `${element.getBoundingClientRect().height}px`)
    }
    write()
    const observer = new ResizeObserver(write)
    observer.observe(element)
    if (header) observer.observe(header)
    return () => observer.disconnect()
  }, [strip])
}

/** The address of a section of this page: the page's own, its hash the
 *  section's id. */
function useSectionHref(id: string): string {
  const { pathname, search } = useLocation()
  return `${pathname}${search}#${id}`
}

/** A link in text to a section of the Guide ("Write the guide"). A
 *  `TextLink` to this page's own address with the section as its hash, so
 *  a new tab opens the same page; a plain click goes to the section. */
export function SectionLink({ id, children }: { id: string; children: ReactNode }) {
  const href = useSectionHref(id)
  return (
    <TextLink
      href={href}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        // `TextLink` renders the router's `Link`, which leaves a click
        // whose default is prevented to the handler.
        event.preventDefault()
        goToSection(id)
      }}
    >
      {children}
    </TextLink>
  )
}

function NavLink({
  section,
  current,
  className,
}: {
  section: GuideSection
  current: boolean
  className: string
}) {
  return (
    <a
      href={`#${section.id}`}
      onClick={(event) => {
        event.preventDefault()
        goToSection(section.id)
      }}
      aria-current={current ? 'true' : undefined}
      className={`rounded-control px-2.5 py-1.5 text-caption transition-chrome ${
        current ? 'bg-surface3 font-medium text-ink' : 'text-muted hover:text-ink'
      } ${className}`}
    >
      {section.label}
    </a>
  )
}

/** The way between the Guide's sections, two navs of which one is shown:
 *  from 64rem a column at the page's right, sticky at the top; under
 *  64rem a strip above the sections. Both mark the current section, which
 *  `activeId` names.
 *
 *  The strip's links sit in one row that scrolls sideways inside itself,
 *  never the page's. It is sticky under the shell's header below 48rem
 *  and at the window's top from 48rem, on the plane and over the content,
 *  under the header, and its negative margins take it across the page's
 *  gutters so it covers what scrolls under it across the column. The
 *  current link is brought into view by moving the row's own scroll. Its
 *  parent in `GuideView` has to be the block that holds every section
 *  (sticky holds only inside its parent) with no clipping ancestor; that
 *  parent also takes the two heights (`useStickyHeights`), which the
 *  sections read for their `scroll-margin-top`. */
export function SectionNav({ sections, activeId }: { sections: GuideSection[]; activeId: string }) {
  const { t } = useTranslation()
  const stripRef = useRef<HTMLElement>(null)
  const rowRef = useRef<HTMLDivElement>(null)
  // Where the row's own smooth scroll is going while one is in flight;
  // `null` once it has arrived.
  const pendingLeftRef = useRef<number | null>(null)
  useStickyHeights(stripRef)

  // A scroll in flight is over when the row says so (`scrollend`), or,
  // where that event is missing, when the row is found at its target.
  // The gap: where a browser does not fire `scrollend`, a row dragged by
  // hand during a smooth scroll leaves the pending target out of date
  // until the current section next changes, and the row may then skip a
  // scroll it needed or make one it did not.
  useEffect(() => {
    const row = rowRef.current
    if (!row) return
    const arrived = () => {
      pendingLeftRef.current = null
    }
    row.addEventListener('scrollend', arrived)
    return () => row.removeEventListener('scrollend', arrived)
  }, [])

  // The current link into view, by the row's own scroll alone. The test is
  // against where the row is going, not where it is: the current id can
  // change twice in quick succession, and a link found in view a moment
  // after a smooth scroll began may be carried out of it by that scroll.
  // A new `scrollTo` replaces the one in flight. With no scroll in flight
  // and the link whole in view, the row does not move.
  useEffect(() => {
    const row = rowRef.current
    // Not drawn from 64rem, where the column holds the links.
    if (!row || row.offsetParent === null) return
    const link = row.querySelector<HTMLElement>('[aria-current]')
    if (!link) return
    const pending = pendingLeftRef.current
    if (pending != null && Math.abs(row.scrollLeft - pending) < 1) pendingLeftRef.current = null
    const rowBox = row.getBoundingClientRect()
    const linkBox = link.getBoundingClientRect()
    const target = rowScrollTarget({
      rowWidth: row.clientWidth,
      scrollWidth: row.scrollWidth,
      pendingLeft: pendingLeftRef.current ?? row.scrollLeft,
      // Both boxes are read at the same instant, so the link's place in
      // the row's content holds whatever the scroll.
      linkLeft: linkBox.left - rowBox.left + row.scrollLeft,
      linkWidth: linkBox.width,
    })
    if (target == null) return
    const behavior = scrollBehavior()
    // An instant scroll has arrived by the next line; only a smooth one is
    // in flight.
    pendingLeftRef.current = behavior === 'smooth' && Math.abs(row.scrollLeft - target) >= 1 ? target : null
    row.scrollTo({ left: target, behavior })
  }, [activeId, sections])

  return (
    <>
      {/* Under 48rem the strip's top is the height of Shell.tsx's strip,
          its sticky header, which `useStickyHeights` reads from the DOM
          into `--guide-header` (it moves with the density setting, so no
          number written here would hold). From 48rem that header is static
          and nothing is above this strip. z-10 keeps it over the content
          and under the header's z-20. */}
      <nav
        ref={stripRef}
        aria-label={t('decks.guide.sectionsNav')}
        className="sticky top-[var(--guide-header,0px)] z-10 -mx-3.5 border-b border-line bg-plane md:top-0 md:-mx-9 lg:hidden"
      >
        <div ref={rowRef} className="flex gap-1 overflow-x-auto px-3.5 py-1.5 md:px-9">
          {sections.map((section) => (
            <NavLink
              key={section.id}
              section={section}
              current={activeId === section.id}
              className="inline-flex min-h-[44px] shrink-0 items-center whitespace-nowrap"
            />
          ))}
        </div>
      </nav>
      <nav
        aria-label={t('decks.guide.sectionsNav')}
        className="sticky top-4 hidden w-44 shrink-0 flex-col gap-0.5 self-start lg:col-start-2 lg:row-start-1 lg:flex"
      >
        {sections.map((section) => (
          <NavLink key={section.id} section={section} current={activeId === section.id} className="" />
        ))}
      </nav>
    </>
  )
}
