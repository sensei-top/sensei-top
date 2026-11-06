import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Outlet, ScrollRestoration, useLocation, useMatches, useNavigate } from 'react-router'
import { useLive } from '../api'
import { useShell } from '../bridge'
import { ReportProblemDialog } from '../components/ReportProblemDialog'
import { BrandGlyph, Callout, TextLink } from '../components/ui'
import { ACCOUNT_WELCOME_PATH, consentState, needsConsent } from '../lib/accountWelcome'
import { CONTRIBUTE_KEEPS, CONTRIBUTE_PATH, contribPageDue } from '../lib/contribute'
import { POLICY_VERSION } from '../lib/policy'
import { ReportProblemContext, signedInOf, type ReportOpener } from '../lib/reportProblem'
import { BottomBar } from './BottomBar'
import { LiveStatus } from './LiveStatus'
import { documentTitle, layoutName, placeAt, PRODUCT_NAME, type RouteHandle } from './places'
import { Rail } from './Rail'

// The main column's width, and its gutters: the bar, the page and the
// footer line up on the same edges.
const COLUMN = 'mx-auto w-full max-w-[1196px] px-3.5 md:px-9'

/** The first thing a keyboard reaches: past the rail, straight to the page.
 *  Out of sight until it holds focus, which it tracks itself rather than
 *  through a class of its own: the page's one `:focus-visible` ring is
 *  still the one that marks it. */
function SkipLink() {
  const { t } = useTranslation()
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
      {t('shell.skipLink')}
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
  const { t } = useTranslation()
  const live = useLive()
  const { pathname, search } = useLocation()
  const matches = useMatches()
  const handle = matches[matches.length - 1]?.handle as RouteHandle | undefined
  const shell = useShell()
  const hasShell = shell !== null
  const navigate = useNavigate()
  // A signed-in user with no profile, or answers given under an older
  // policy, is asked first; the consent screen itself is never redirected.
  // From setup it carries the step, to come back to it.
  const consentDue = needsConsent(shell?.app?.settings, POLICY_VERSION)
  useEffect(() => {
    if (consentDue && pathname !== ACCOUNT_WELCOME_PATH)
      void navigate(ACCOUNT_WELCOME_PATH, { replace: true, state: consentState(pathname, search) })
  }, [consentDue, pathname, search, navigate])
  // The one-time "Help build the stats" page: at most once per page load, so
  // a failed write of `contribAsked` followed by Decide later cannot bring
  // the person back to it.
  const contribDue = contribPageDue(shell?.app?.settings, consentDue)
  const contribSent = useRef(false)
  useEffect(() => {
    if (!contribDue || contribSent.current) return
    if ((CONTRIBUTE_KEEPS as readonly string[]).includes(pathname)) return
    contribSent.current = true
    void navigate(CONTRIBUTE_PATH, { replace: true })
  }, [contribDue, pathname, navigate])
  // The report dialog: one for the shell, remounted (`key`) per opening so
  // each starts with an empty draft. Only a shell that sends reports has it.
  const reportProblem = shell?.reportProblem
  const onReportProblem = shell?.onReportProblem
  const signedIn = signedInOf(shell?.app?.settings.account)
  const [report, setReport] = useState({ opening: 0, open: false, message: null as string | null, signedIn: false })
  const opener = useMemo<ReportOpener | null>(
    () =>
      reportProblem
        ? {
            open: (message) =>
              setReport((now) => (now.open ? now : { opening: now.opening + 1, open: true, message, signedIn })),
          }
        : null,
    [reportProblem, signedIn],
  )
  useEffect(() => onReportProblem?.(() => opener?.open(null)), [onReportProblem, opener])
  const notFound = matches.some((match) => (match.handle as RouteHandle | undefined)?.notFound)
  const place = notFound ? null : placeAt(pathname)
  const { name, title } = layoutName(place, handle, hasShell, t)
  const focus = place?.id === 'live'
  // The welcome's pages (`bare`) are the steps alone: the person finishes
  // or leaves them by their own buttons, not by the rail.
  const bare = handle?.bare === true && !notFound

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
    document.title = documentTitle(place, t, title)
  }, [place, t, title])

  return (
    <ReportProblemContext.Provider value={opener}>
      <div className="min-h-screen bg-plane md:flex">
        <SkipLink />
        {!bare && <Rail current={place} />}

        {/* Under 48rem the bottom bar is fixed over the window's foot, so the
            column leaves its height free under the footer. */}
        <div
          className={`flex min-h-screen min-w-0 flex-1 flex-col ${bare ? '' : 'pb-[calc(4rem+env(safe-area-inset-bottom))] md:pb-0'} ${
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
            {/* A bare page's name stands over its centred card (`max-w-3xl`,
                as the welcome pages draw it), on the card's own left edge. */}
            <div className={`${COLUMN} py-2.5 md:pt-7 md:pb-0`}>
              <div className={`flex items-center gap-3 ${bare ? 'mx-auto max-w-3xl' : ''}`}>
                <Link
                  to="/"
                  aria-label={t('shell.homeLink', { product: PRODUCT_NAME })}
                  className="flex size-9 shrink-0 items-center justify-center rounded-control text-accent md:hidden"
                >
                  <BrandGlyph size={24} />
                </Link>
                <h1 className="min-w-0 flex-1 truncate font-display text-title text-ink md:text-heading">{name}</h1>
                {!bare && <LiveStatus className={focus ? 'md:hidden' : ''} />}
              </div>
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
                <Callout tone="warn">{t('shell.trackerDown')}</Callout>
              </div>
            )}
            {/* In focus mode the page fills what the callout leaves, and a live
                view's own h-full column measures against this box. */}
            <div className={focus ? 'md:flex md:min-h-0 md:flex-1 md:flex-col' : undefined}>
              <Outlet />
            </div>
          </main>

          {!bare && (
            <footer className={`shrink-0 border-t border-line ${focus ? 'md:hidden' : ''}`}>
              {/* Wizards' notice is the welcome catalogue's, one sentence in one
                  place. */}
              <div
                className={`${COLUMN} flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 py-4 text-caption text-muted`}
              >
                <p className="min-w-0 max-w-prose flex-1">
                  {t('shell.footer.local')} {t('welcome.intro.wizardsNotice')}
                </p>
                <TextLink href="/settings#credits" className="shrink-0">
                  {t('shell.footer.credits')}
                </TextLink>
              </div>
            </footer>
          )}
        </div>

        {!bare && <BottomBar current={place} />}
        <ScrollRestoration />
        {reportProblem && report.opening > 0 && (
          <ReportProblemDialog
            key={report.opening}
            open={report.open}
            onOpenChange={(open) => setReport((now) => ({ ...now, open }))}
            send={reportProblem}
            signedIn={report.signedIn}
            message={report.message}
          />
        )}
      </div>
    </ReportProblemContext.Provider>
  )
}
