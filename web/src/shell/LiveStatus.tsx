import { useEffect, useId, useRef, useState } from 'react'
import { useLocation } from 'react-router'
import { useLive } from '../api'
import { TextLink } from '../components/ui'
import { useMatchInProgress } from '../lib/liveMatch'
import { ago, useNow } from '../lib/time'

type State = 'down' | 'match' | 'watching' | 'idle'

const WORDS: Record<State, string> = {
  down: 'Tracker not running',
  match: 'Match in progress',
  watching: 'Watching Arena',
  idle: 'Not watching',
}

// Never colour alone: the dot is decoration, the words are the fact.
const DOT: Record<State, string> = {
  down: 'bg-warn',
  match: 'animate-pulse bg-s3',
  watching: 'animate-pulse bg-s3',
  idle: 'bg-muted',
}

/** The tracker's state, one at a time, the first that holds: not running
 *  (the heartbeat's last request failed), a match in progress, watching
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

  const state: State = live.isError
    ? 'down'
    : matchInProgress
      ? 'match'
      : live.data.watching
        ? 'watching'
        : 'idle'
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
        <span className="sr-only md:not-sr-only">{WORDS[state]}</span>
      </button>
      <span role="status" className="sr-only">
        {WORDS[state]}
      </span>
      {open && (
        <div
          id={panelId}
          className="absolute top-full right-0 z-30 mt-2 flex w-72 max-w-[calc(100vw-2rem)] flex-col gap-2 rounded-block bg-surface3 p-4 text-caption text-ink2 shadow-lift"
        >
          {state === 'down' ? (
            // Nothing else: what the heartbeat last said is old.
            <p>This page cannot reach the tracker. What is on screen is what was last loaded.</p>
          ) : (
            <>
              {state === 'match' && (
                <p>
                  <TextLink href="/live">Go to the match</TextLink>
                </p>
              )}
              {/* A match in progress says what watching or not
                  watching says: the log is followed only when it is. */}
              {watching ? (
                <p>The tracker is following Arena's log as you play.</p>
              ) : (
                <p>
                  The tracker is running without watching Arena's log, so a match played now is not recorded
                  by it. Restart the tracker with watching turned on.
                </p>
              )}
              <p>{changed ? `Data last changed ${changed}.` : 'No data yet.'}</p>
              {watching && live.data?.mtgo_read_at_startup && (
                <p>
                  MTGO matches were read when the tracker started. One played since then appears after the
                  tracker is restarted.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
