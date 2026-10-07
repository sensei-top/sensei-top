/**
 * The words the event page (`/field/events/<key>`) says, as pure functions
 * of the API's `MetaEventDetail` and its decks: the source and credit lines,
 * the read line, the ordinal and standing, the kind by tier, and the group
 * headings. The page in `views/FieldEventView.tsx` only draws what these
 * return. The lines are plan 14's catalog (§3), word for word.
 */
import type { MetaCard, MetaEventDeck, MetaEventDetail } from '../api'

/** One run of a line: plain text, or text linked to `href`. */
export type SourcePart = { text: string; href?: string }

const TOPDECK = 'https://topdeck.gg'

/** The source line or lines: the credit for the place the results came
 *  from, and for TopDeck the link to the event on it. */
export function sourceLines(event: Pick<MetaEventDetail, 'source' | 'uri'>): SourcePart[][] {
  const href = event.uri ?? undefined
  if (event.source === 'Topdeck') {
    const lines: SourcePart[][] = [
      [{ text: 'Data provided by ' }, { text: 'TopDeck.gg', href: TOPDECK }, { text: '.' }],
    ]
    if (href) lines.push([{ text: 'This event on TopDeck.gg', href }])
    return lines
  }
  if (event.source === 'MTGO') return [[{ text: 'Results from ' }, { text: 'mtgo.com', href }]]
  if (event.source === 'MTGmelee') return [[{ text: 'Results from ' }, { text: 'melee.gg', href }]]
  return []
}

/** The date part of a stored UTC stamp (`2026-10-05T17:10:00Z`). */
const dayOf = (stamp: string): string => stamp.slice(0, 10)

/** What the last read of the event did to its lists, or null when nothing
 *  needs saying: the event kept its lists and the last read found no change. */
export function readLine(
  event: Pick<MetaEventDetail, 'decks' | 'lists_read_at' | 'empty_read_at' | 'empty_read_kind'>,
): string | null {
  const hasLists = event.decks.some((deck) => deck.main.length > 0)
  const kind = event.empty_read_kind
  const emptyDay = event.empty_read_at ? dayOf(event.empty_read_at) : null
  if (!hasLists) {
    if (emptyDay) return `Standings only: no decklists were returned for this event when it was last read, on ${emptyDay}.`
    return 'Standings only: no decklists were returned for this event when it was last read.'
  }
  if (!kind || !emptyDay) return null
  if (event.lists_read_at) {
    const listsDay = dayOf(event.lists_read_at)
    return kind === 'empty'
      ? `Decklists as read on ${listsDay}; none were returned when this event was last read, on ${emptyDay}.`
      : `Decklists as read on ${listsDay}; the event's page was not found when it was last read, on ${emptyDay}.`
  }
  return kind === 'empty'
    ? `The decklists shown were read on a date that was not recorded; none were returned when this event was last read, on ${emptyDay}.`
    : `The decklists shown were read on a date that was not recorded; the event's page was not found when it was last read, on ${emptyDay}.`
}

/** 1 as `1st`, 2 as `2nd`, 11 as `11th`, 21 as `21st`. */
export function ordinal(n: number): string {
  const last2 = n % 100
  if (last2 >= 11 && last2 <= 13) return `${n}th`
  switch (n % 10) {
    case 1:
      return `${n}st`
    case 2:
      return `${n}nd`
    case 3:
      return `${n}rd`
    default:
      return `${n}th`
  }
}

/** A deck's standing, `1st · 6–1`: the placement and the record, each only
 *  when known, draws only when there are some. Null when neither is. */
export function standing(deck: Pick<MetaEventDeck, 'placement' | 'record'>): string | null {
  const parts: string[] = []
  if (deck.placement != null) parts.push(ordinal(deck.placement))
  const record = deck.record
  if (record) {
    parts.push(`${record.wins}–${record.losses}${record.draws > 0 ? `–${record.draws}` : ''}`)
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

/** What kind of event the tier says it is; null for a tier that says
 *  nothing. */
export function kindWords(tier: string | null | undefined): string | null {
  switch (tier) {
    case 'A':
      return 'paper tournament of 64+ players'
    case 'B':
      return 'MTGO challenge'
    case 'C':
      return 'MTGO league'
    case 'D':
      return 'paper tournament under 64 players'
    default:
      return null
  }
}

const PLURALS: Record<string, string> = {
  Creature: 'Creatures',
  Planeswalker: 'Planeswalkers',
  Battle: 'Battles',
  Instant: 'Instants',
  Sorcery: 'Sorceries',
  Artifact: 'Artifacts',
  Enchantment: 'Enchantments',
  Land: 'Lands',
}

/** A mainboard group's heading, `Creatures (12)`; `n` is its copies. The
 *  null group has no plural. A type the table does not know is named as the
 *  API sent it. */
export function groupHeading(type: string | null, n: number): string {
  if (type === null) return `Unknown type (${n})`
  return `${PLURALS[type] ?? type} (${n})`
}

/** The sideboard's heading, or null when it is empty. */
export function sideboardHeading(side: MetaCard[]): string | null {
  if (side.length === 0) return null
  return `Sideboard (${side.reduce((sum, card) => sum + card.count, 0)})`
}
