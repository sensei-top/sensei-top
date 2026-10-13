import type { TFunction } from '../i18n'

/** Arena's event ids in words. The names known are written out; any other
 *  id is respelled, never looked up: a set code stays as it is stored. */
function knownEvents(t: TFunction): Record<string, string> {
  return {
    Ladder: t('matches.events.ranked'),
    Traditional_Ladder: t('matches.events.rankedBo3'),
    Play: t('matches.events.unranked'),
    Traditional_Play: t('matches.events.unrankedBo3'),
    Constructed_BestOf3: t('matches.events.unrankedBo3'),
    DirectGame: t('matches.events.direct'),
    DualColorPrecons: t('matches.events.starter'),
  }
}

/** A match's, game's or turn's result in words: the four the API sends, and
 *  `undefined` for anything else, which the caller words its own way. */
export function resultWord(result: string | null | undefined, t: TFunction): string | undefined {
  const words: Record<string, string> = {
    win: t('matches.result.win'),
    loss: t('matches.result.loss'),
    draw: t('matches.result.draw'),
    incomplete: t('matches.result.incomplete'),
  }
  return Object.hasOwn(words, result ?? '') ? words[result ?? ''] : undefined
}

/** The Traditional Constructed event carries its year or a date: every
 *  one reads the same. */
const CONS_EVENT = /^Traditional_Cons_Event_(\d{8}|\d{4})$/

/** A trailing date (`_20260831`) or year (`_2026`). */
const TRAILING_DATE = /_(\d{8}|\d{4})$/

/** The event's words, or `null` without an event. For an id not in the
 *  table: the trailing date goes, the first part gains a space before a
 *  capital that follows a lowercase letter or a digit (`QuickDraft` reads
 *  "Quick Draft", an all-capital part stays whole), and what is left
 *  follows a comma with its underscores as spaces: `QuickDraft_SOS_20260831`
 *  reads "Quick Draft, SOS". */
export function eventLabel(eventId: string | null | undefined, t: TFunction): string | null {
  if (!eventId) return null
  const known = knownEvents(t)
  if (Object.hasOwn(known, eventId)) return known[eventId]
  if (CONS_EVENT.test(eventId)) return t('matches.events.consEvent')
  const [first, ...rest] = eventId.replace(TRAILING_DATE, '').split('_')
  const head = first.replace(/([a-z0-9])([A-Z])/g, '$1 $2')
  const tail = rest.filter(Boolean).join(' ')
  if (!head) return tail || null
  return tail ? t('matches.events.respelled', { head, tail }) : head
}
