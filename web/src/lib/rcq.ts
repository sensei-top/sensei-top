/**
 * The RCQ prep page's pure helpers (its routes' shapes are the generated
 * `Rcq*` types in `api.ts`): the 75 a deck's current list prefills, the
 * freshness sentence for each corpus source, the key a debounced preview
 * is asked by, the archetypes offered as expected, and the inputs kept in
 * `localStorage` per deck.
 */
import { useEffect, useState } from 'react'
import type { ListDiffOut, MetaPresence, RcqFreshnessOut } from '../api'
import { archetypeName } from './decks'
import { ago, formatIsoDateShort, formatShortDay, parseTimestamp } from './time'

// --- Inputs ----------------------------------------------------------------

/** What the player gave: the 75 as pasted, the archetype keys expected at
 *  the store, and the archetype the 75 is, when they had to choose it. */
export type RcqInputs = {
  decklist: string
  expected: string[]
  own: string | null
}

/** How long the inputs stand still before the preview is asked again. */
export const PREVIEW_DEBOUNCE_MS = 600

/** The 75 a deck's current list reads as in Arena's export: `Deck`, then a
 *  count and a name a line, then a blank line, `Sideboard` and the same.
 *  From the list diff's rows that the deck runs (`yours` above 0), in the
 *  server's order; a row the field runs and the deck does not is not the
 *  deck's. The empty string with no list diff, or nothing in it. */
export function prefillText(diff: ListDiffOut | null | undefined): string {
  if (!diff) return ''
  const lines = (rows: ListDiffOut['maindeck']) =>
    rows.filter((row) => row.yours > 0).map((row) => `${row.yours} ${row.card}`)
  const main = lines(diff.maindeck)
  const side = lines(diff.sideboard)
  if (main.length === 0 && side.length === 0) return ''
  const parts = ['Deck', ...main]
  if (side.length > 0) parts.push('', 'Sideboard', ...side)
  return parts.join('\n')
}

/** The key a preview is asked by: the 75 with its outer whitespace
 *  dropped, the expected keys in sorted order without repeats, and the
 *  chosen archetype. Two inputs that ask the same question share a key, so
 *  re-picking the same chips in another order asks nothing new. */
export function previewKey(inputs: RcqInputs): string {
  const expected = [...new Set(inputs.expected)].sort()
  return JSON.stringify([inputs.decklist.trim(), expected, inputs.own ?? null])
}

/** `value`, once it has stood still for `ms`. */
export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), ms)
    return () => window.clearTimeout(timer)
  }, [value, ms])
  return settled
}

/** A day the API sends, bare (`YYYY-MM-DD`) or as a timestamp, as "Oct 3";
 *  `null` when it reads as neither. */
function dayOf(value: string, now: number): string | null {
  const bare = formatIsoDateShort(value, now)
  if (bare != null) return bare
  const ms = parseTimestamp(value)
  return ms == null ? null : formatShortDay(ms, now)
}

/** One source's freshness as its line reads: "mtgo.com: newest event Oct
 *  3, fetched 2h ago". Either half says so when there is none ("no event
 *  yet", "never fetched"); a day that cannot be read is shown as sent. */
export function freshnessSentence(entry: RcqFreshnessOut, now: number): string {
  const day = entry.newest_event == null ? null : (dayOf(entry.newest_event, now) ?? entry.newest_event)
  const event = day == null ? 'no event yet' : `newest event ${day}`
  const fetched = ago(entry.fetched_at, now)
  return `${entry.source}: ${event}, ${fetched == null ? 'never fetched' : `fetched ${fetched}`}`
}

/** An archetype the player may expect at the store, as a chip offers it:
 *  its key, its name, and its share at the tier the options are read at
 *  (`null` when that tier has none of it). */
export type ExpectedOption = { key: string; label: string; share: number | null }

/** The archetypes to offer as expected, most played first. The field's
 *  presence comes one row per archetype and tier, and tiers are never
 *  blended (`docs/metagame.md`), so every share is read at one tier: the
 *  one with the most decks in the window. An archetype that tier never
 *  saw comes after, with no share, by its decks at the other tiers. Ties
 *  go by name. */
export function expectedOptions(presence: MetaPresence[]): {
  tier: string | null
  options: ExpectedOption[]
} {
  const tierDecks = new Map<string, number>()
  for (const row of presence) tierDecks.set(row.tier, (tierDecks.get(row.tier) ?? 0) + row.decks)
  let tier: string | null = null
  for (const [name, decks] of tierDecks) {
    if (tier == null || decks > (tierDecks.get(tier) ?? 0)) tier = name
  }

  const byKey = new Map<string, { label: string; share: number | null; decks: number }>()
  for (const row of presence) {
    const entry = byKey.get(row.archetype_key) ?? { label: row.label, share: null, decks: 0 }
    entry.decks += row.decks
    if (row.tier === tier) {
      entry.share = row.share
      entry.label = row.label
    }
    byKey.set(row.archetype_key, entry)
  }

  const options = Array.from(byKey, ([key, entry]) => ({ key, ...entry }))
  options.sort((a, b) => {
    if (a.share != null && b.share != null && a.share !== b.share) return b.share - a.share
    if ((a.share == null) !== (b.share == null)) return a.share == null ? 1 : -1
    if (a.decks !== b.decks) return b.decks - a.decks
    return a.label.localeCompare(b.label)
  })
  return {
    tier,
    options: options.map(({ key, label, share }) => ({ key, label: archetypeName(label), share })),
  }
}

/** The part of `Storage` the inputs need, so a test can hand in its own. */
export type InputStorage = Pick<Storage, 'getItem' | 'setItem'>

/** Where one deck's inputs are kept. */
export function storageKey(deckKey: string): string {
  return `sensei-top:rcq:${deckKey}`
}

/** The inputs kept for `deckKey`, or `null` when there are none, they do
 *  not read as inputs, or storage refuses (a private window). */
export function readInputs(storage: InputStorage | null | undefined, deckKey: string): RcqInputs | null {
  try {
    const raw = storage?.getItem(storageKey(deckKey))
    if (!raw) return null
    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value == null) return null
    const { decklist, expected, own } = value as Record<string, unknown>
    if (typeof decklist !== 'string') return null
    return {
      decklist,
      expected: Array.isArray(expected) ? expected.filter((key): key is string => typeof key === 'string') : [],
      own: typeof own === 'string' ? own : null,
    }
  } catch {
    return null
  }
}

/** Keep `inputs` for `deckKey`; a storage that refuses is let be. */
export function writeInputs(storage: InputStorage | null | undefined, deckKey: string, inputs: RcqInputs): void {
  try {
    storage?.setItem(storageKey(deckKey), JSON.stringify(inputs))
  } catch {
    // Blocked or full storage: the page works without it.
  }
}

/** The browser's `localStorage`, or `null` where reading it throws. */
export function browserStorage(): InputStorage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

/** The file name a downloaded guide is saved as: `rcq-guide-<day>.md`,
 *  the day it was written (`YYYY-MM-DD`, from its timestamp's own digits),
 *  else plain `rcq-guide.md`. */
export function markdownFileName(generatedAt: string | null | undefined): string {
  const day = generatedAt ? /^(\d{4}-\d{2}-\d{2})/.exec(generatedAt)?.[1] : undefined
  return day ? `rcq-guide-${day}.md` : 'rcq-guide.md'
}
