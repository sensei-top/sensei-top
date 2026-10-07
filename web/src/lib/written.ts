import { formatShortDay, parseTimestamp } from './time'

/** Who wrote it and on which day: "Written by claude-opus-5 on
 *  Sep 18.", the year added in a year other than `now`'s. Either part
 *  alone reads on its own; a day that cannot be read counts as none;
 *  `null` with neither. The author is shown as stored. */
export function writtenLine(
  author: string | null | undefined,
  authoredAt: string | null | undefined,
  now: number,
): string | null {
  const ms = parseTimestamp(authoredAt)
  const day = ms == null ? null : formatShortDay(ms, now)
  if (author && day) return `Written by ${author} on ${day}.`
  if (author) return `Written by ${author}.`
  if (day) return `Written on ${day}.`
  return null
}

/** With no stale sentence of the caller's own, a written artefact that
 *  has gone stale says this: the match's summary, the training plan and
 *  the coach's report all read it this way. */
const DEFAULT_STALE_NOTE = 'The evidence has changed since.'

/** Up to three sentences a written artefact carries, joined by one
 *  space: who wrote it and when (`writtenLine`), what it cost, and, when
 *  stale, the sentence that says so: the caller's own when given, the
 *  default otherwise. `null` when none of the three has anything to
 *  say. */
export function writtenNote({
  author,
  authoredAt,
  costUsd,
  stale,
  staleNote,
  now,
}: {
  author: string | null | undefined
  authoredAt: string | null | undefined
  costUsd: number | null | undefined
  stale: boolean | null | undefined
  staleNote?: string
  now: number
}): string | null {
  const parts = [
    writtenLine(author, authoredAt, now),
    costUsd != null ? `It cost $${costUsd.toFixed(3)}.` : null,
    stale ? staleNote ?? DEFAULT_STALE_NOTE : null,
  ].filter((part) => part != null)
  return parts.length > 0 ? parts.join(' ') : null
}
