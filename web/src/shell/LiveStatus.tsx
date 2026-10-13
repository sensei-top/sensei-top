import { useEffect, useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router'
import { useLive } from '../api'
import { TextLink } from '../components/ui'
import type { TFunction } from '../i18n'
import { liveState, type LiveState as State } from '../lib/home'
import { useMatchInProgress } from '../lib/liveMatch'
import { ago, useNow } from '../lib/time'

/** The pill's words for a state. */
function words(state: State, t: TFunction): string {
  const all: Record<State, string> = {
    down: t('shell.liveStatus.down'),
    stopped: t('shell.liveStatus.stopped'),
    match: t('shell.liveStatus.match'),
    watching: t('shell.liveStatus.watching'),
    idle: t('shell.liveStatus.idle'),
  }
  return all[state]
}

// Never colour alone: the dot is decoration, the words are the fact.
const DOT: Record<State, string> = {
  down: 'bg-warn',
  stopped: 'bg-warn',
  match: 'animate-pulse bg-s3',
  watching: 'animate-pulse bg-s3',
  idle: 'bg-muted',
}

/** The tracker's state, one at a time, the first that holds: not running
 *  (the heartbeat's last request failed), the watcher
 *  started and died, a match in progress, watching
 *  Arena, not watching. The words also sit in a polite
 *  live region of their own, out of sight beside the pill and never around
 *  it, so a change is announced, the control is not read again with it,
 *  and nothing takes focus; under 48rem the pill is its dot alone and the
 *  words are its name. The pill opens a panel
 *  with the rest: a link to the match, what is watched, when
 *  data last changed. The link is in the panel, not the pill, because a
 *  button that is also a link has two jobs and a keyboard can ask for only
 *  one. */
export function LiveStatus({ className = '' }: { className?: string }) {
  const { t } = useTranslation()
  const live = useLive()
  const matchInProgress = useMatchInProgress()
  const now = useNow()
  const { pathname } = useLocation()
  // Open for one address: following the panel's link, or any other
  // navigation, closes it without an effect to reset it.
  const [openAt, setOpenAt] = useState<string | null>(null)
  const open = openAt === pathname
  const root = useRef<HTMLDivElement>(null)
  const pill = useRef<HTMLButtonElement>(null)
  const panelId = useId()

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpenAt(null)
      pill.current?.focus()
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpenAt(null)
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open])

  // Nothing to say until the first beat answers either way.
  if (live.isPending) return null

  const state: State = liveState({
    isError: live.isError,
    watcherStopped: Boolean(live.data?.watcher_stopped),
    matchInProgress,
    watching: Boolean(live.data?.watching),
  })
  const watching = Boolean(live.data?.watching)

  // last_ingest_at is when data last *changed*, not when the reader last
  // looked — so this reads "5m ago" during a lull instead of resetting every
  // poll and implying activity that is not happening.
  const changed = live.data ? ago(live.data.last_ingest_at, now) : null

  return (
    <div ref={root} className={`relative ${className}`}>
      <button
        ref={pill}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpenAt(open ? null : pathname)}
        className="inline-flex min-h-8 min-w-8 items-center justify-center gap-2 rounded-pill text-caption text-ink2 transition-chrome hover:text-ink md:border md:border-edge md:bg-surface md:px-3 md:py-1"
      >
        <span aria-hidden className={`inline-block size-2 shrink-0 rounded-full ${DOT[state]}`} />
        <span className="sr-only md:not-sr-only">{words(state, t)}</span>
      </button>
      <span role="status" className="sr-only">
        {words(state, t)}
      </span>
      {open && (
        <div
          id={panelId}
          className="absolute top-full right-0 z-30 mt-2 flex w-72 max-w-[calc(100vw-2rem)] flex-col gap-2 rounded-block bg-surface3 p-4 text-caption text-ink2 shadow-lift"
        >
          {state === 'down' ? (
            // Nothing else: what the heartbeat last said is old.
            <p>{t('shell.liveStatus.unreachable')}</p>
          ) : (
            <>
              {state === 'match' && (
                <p>
                  <TextLink href="/live">{t('shell.liveStatus.goToMatch')}</TextLink>
                </p>
              )}
              {/* A match in progress says what watching or not
                  watching says: the log is followed only when it is. */}
              {state === 'stopped' ? (
                <p>{t('shell.liveStatus.watcherStopped')}</p>
              ) : watching ? (
                <p>{t('shell.liveStatus.following')}</p>
              ) : (
                <p>{t('shell.liveStatus.notWatching')}</p>
              )}
              <p>{changed ? t('shell.liveStatus.changed', { ago: changed }) : t('shell.liveStatus.noData')}</p>
              {watching && live.data?.mtgo_watching && <p>{t('shell.liveStatus.mtgoWatched')}</p>}
            </>
          )}
        </div>
      )}
    </div>
  )
}
