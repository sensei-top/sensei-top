import type { FormatsOut, MtgoFormat, PrefillSource } from '../api'
import type { TFunction } from '../i18n'

/** The seven formats an MTGO pick may confirm: no "other". */
export const MTGO_FORMATS: readonly MtgoFormat[] = [
  'Standard',
  'Pioneer',
  'Modern',
  'Pauper',
  'Legacy',
  'Vintage',
  'Premodern',
]

/** The formats the select offers, in `/api/formats`' order; the seven of D9
 *  while that has not answered. */
export function mtgoFormatsOf(formats: FormatsOut | undefined): readonly MtgoFormat[] {
  return formats ? formats.formats.map((entry) => entry.format) : MTGO_FORMATS
}

/** Where the pre-filled format came from, in words. */
export function prefillWords(source: PrefillSource, t: TFunction): string {
  const words: Record<PrefillSource, string> = {
    deck_store: t('mtgo.prefill.deckStore'),
    last_pick: t('mtgo.prefill.lastPick'),
    inferred: t('mtgo.prefill.inferred'),
  }
  return words[source]
}

/** Where the pre-filled format came from, only while the chosen format is
 *  still the pre-fill; `null` once the user picks another, or with no
 *  source. */
export function prefillCaptionIn(
  prefill: MtgoFormat | null | undefined,
  source: PrefillSource | null | undefined,
  chosen: MtgoFormat | null,
  t: TFunction,
): string | null {
  if (!prefill || !source || chosen !== prefill) return null
  return prefillWords(source, t)
}

/** The choice that means "no list": confirm the format alone. A deck's id is
 *  never empty, so the empty string cannot be mistaken for one; `null` is
 *  "nothing chosen yet". */
export const NO_LIST = ''

/** The format after choosing `deckId`. A deck sets it to its own
 *  `format_prefill` (D16: the store's, else D10's last confirmed for the same
 *  deck, else the one inferred from the cards revealed in this match), or clears it when the deck has none; the user confirms it either
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
