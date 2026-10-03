import type { MtgoFormat } from '../api'

/** The seven formats an MTGO pick may confirm (plan 12, D9): no "other". */
export const MTGO_FORMATS: readonly MtgoFormat[] = [
  'Standard',
  'Pioneer',
  'Modern',
  'Pauper',
  'Legacy',
  'Vintage',
  'Premodern',
]

/** The choice that means "no list": confirm the format alone. A deck's id is
 *  never empty, so the empty string cannot be mistaken for one; `null` is
 *  "nothing chosen yet". */
export const NO_LIST = ''

/** The format after choosing `deckId`. A deck sets it to its own
 *  `format_prefill` (D16: the store's, else D10's last confirmed for the same
 *  deck), or clears it when the deck has none; the user confirms it either
 *  way. "No list" has no deck to pre-fill from, so the format already chosen
 *  stays. */
export function formatAfterChoosing(
  deckId: string,
  prefill: MtgoFormat | null | undefined,
  current: MtgoFormat | null,
): MtgoFormat | null {
  if (deckId === NO_LIST) return current
  return prefill ?? null
}

/** Whether the choice can be sent. The route answers 400 for a body with
 *  neither field, so a choice of nothing is not ready; "No list" sends no
 *  deck and so needs a format; a deck alone is a deck-only pick. The route's
 *  `MtgoPickIn` allows either field null, but not both; this is stricter on
 *  one point: a format alone is not an answer until "No list" is chosen (D1,
 *  the user always answers the deck question). */
export function canConfirm(deckId: string | null, format: MtgoFormat | null): boolean {
  if (deckId == null) return false
  return deckId !== NO_LIST || format != null
}

/** The PUT body's `deck_id`: null for "No list". */
export function bodyDeckId(deckId: string): string | null {
  return deckId === NO_LIST ? null : deckId
}
