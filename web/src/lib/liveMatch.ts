import { useCurrentMatch } from '../api'
import { minutesSince, useNow } from './time'

// Above this, a match still showing as "current" (v_current_match stays
// current until the next one starts — docs/current-match.md) is more likely
// abandoned than genuinely still being played, so nothing calls it in
// progress: not the Live page's strip, not the live status, not the rail's
// dot on Live. Measured from match.started_at, which for Arena is when the
// match room opened, so this tracks genuine staleness.
export const LIKELY_ABANDONED_MINUTES = 90

/** Whether a current match that started at `startedAt` is more likely
 *  abandoned than still being played. An unknown start is not stale. */
export function isLikelyAbandoned(startedAt: string | null | undefined, now: number): boolean {
  const minutes = minutesSince(startedAt, now)
  return minutes != null && minutes >= LIKELY_ABANDONED_MINUTES
}

/** A current match that is not likely abandoned. Rides the same heartbeat
 *  invalidation as every other query, so noticing a match costs no extra
 *  poll; the clock re-renders it once a second, so a match crossing the
 *  threshold stops being "in progress" without waiting for new data. */
export function useMatchInProgress(): boolean {
  const current = useCurrentMatch()
  const now = useNow()
  return current.data != null && !isLikelyAbandoned(current.data.started_at, now)
}
