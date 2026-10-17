import type { TFunction } from '../i18n'
import { formatDollars } from './format'
import { formatShortDay, parseTimestamp } from './time'

/** The author or model the API stores for an answer pasted into a card
 *  (`answers.py`'s `PASTED_AUTHOR`): a sentinel, never shown as written. */
export const PASTED_AUTHOR = 'pasted'

/** Whether the stored author or model says the answer was pasted in. */
export function isPasted(author: string | null | undefined): boolean {
  return author === PASTED_AUTHOR
}

/** Who wrote it and on which day: "Written by claude-opus-5 on
 *  Sep 18.", the year added in a year other than `now`'s. Either part
 *  alone reads on its own; a day that cannot be read counts as none;
 *  `null` with neither. The author is shown as stored, except the
 *  sentinel for a pasted answer, which reads "Pasted in on Sep 18." or,
 *  with no day, "Pasted in." */
export function writtenLine(
  author: string | null | undefined,
  authoredAt: string | null | undefined,
  now: number,
  t: TFunction,
): string | null {
  const ms = parseTimestamp(authoredAt)
  const day = ms == null ? null : formatShortDay(ms, now)
  if (isPasted(author)) return day ? t('decks.written.pastedOn', { day }) : t('decks.written.pasted')
  if (author && day) return t('decks.written.byOn', { author, day })
  if (author) return t('decks.written.by', { author })
  if (day) return t('decks.written.on', { day })
  return null
}

/** Up to three sentences a written artefact carries, joined by one
 *  space: who wrote it and when (`writtenLine`), what it cost, and, when
 *  stale, the sentence that says so: the caller's own when given, the
 *  default otherwise. `null` when none of the three has anything to
 *  say. */
export function writtenNote(
  {
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
  },
  t: TFunction,
): string | null {
  const parts = [
    writtenLine(author, authoredAt, now, t),
    costUsd != null ? t('decks.written.cost', { cost: formatDollars(costUsd) }) : null,
    // With no stale sentence of the caller's own, a written artefact that
    // has gone stale says the default: the match's summary, the training
    // plan and the coach's report all read it this way.
    stale ? staleNote ?? t('decks.written.staleDefault') : null,
  ].filter((part) => part != null)
  return parts.length > 0 ? parts.join(' ') : null
}
