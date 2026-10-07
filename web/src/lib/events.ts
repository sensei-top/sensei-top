/** Arena's event ids in words. The names known are written out; any other
 *  id is respelled, never looked up: a set code stays as it is stored. */
const KNOWN: Record<string, string> = {
  Ladder: 'Ranked',
  Traditional_Ladder: 'Ranked, best of three',
  Play: 'Unranked',
  Traditional_Play: 'Unranked, best of three',
  Constructed_BestOf3: 'Unranked, best of three',
  DirectGame: 'Direct challenge',
  DualColorPrecons: 'Starter decks',
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
export function eventLabel(eventId: string | null | undefined): string | null {
  if (!eventId) return null
  const known = KNOWN[eventId]
  if (known) return known
  if (CONS_EVENT.test(eventId)) return 'Traditional Constructed event'
  const [first, ...rest] = eventId.replace(TRAILING_DATE, '').split('_')
  const head = first.replace(/([a-z0-9])([A-Z])/g, '$1 $2')
  const tail = rest.filter(Boolean).join(' ')
  if (!head) return tail || null
  return tail ? `${head}, ${tail}` : head
}
