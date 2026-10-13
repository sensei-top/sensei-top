/**
 * The words the event page (`/field/events/<key>`) says, as pure functions
 * of the API's `MetaEventDetail` and its decks: the source and credit lines,
 * the read line, the ordinal and standing, the kind by tier, and the group
 * headings. The page in `views/FieldEventView.tsx` only draws what these
 * return. The lines are keys under `field.event.*` in
 * `locales/en/field.json`, and their English is plan 14's catalog (§3), word
 * for word.
 */
import type { MetaCard, MetaEventDeck, MetaEventDetail } from '../api'
import type { TFunction } from '../i18n'

/** One line of the source credit: which sentence (`field.event.source*`), the
 *  site it names, and the address the site's name links to, when there is one.
 *  The view writes the sentence, with the site as its link. */
export type SourceLine = {
  sentence: 'topdeck' | 'topdeckEvent' | 'results'
  site: string
  href?: string
}

const TOPDECK = 'https://topdeck.gg'

/** The source line or lines: the credit for the place the results came
 *  from, and for TopDeck the link to the event on it. */
export function sourceLines(event: Pick<MetaEventDetail, 'source' | 'uri'>): SourceLine[] {
  const href = event.uri ?? undefined
  if (event.source === 'Topdeck') {
    const lines: SourceLine[] = [{ sentence: 'topdeck', site: 'TopDeck.gg', href: TOPDECK }]
    if (href) lines.push({ sentence: 'topdeckEvent', site: 'TopDeck.gg', href })
    return lines
  }
  if (event.source === 'MTGO') return [{ sentence: 'results', site: 'mtgo.com', href }]
  if (event.source === 'MTGmelee') return [{ sentence: 'results', site: 'melee.gg', href }]
  return []
}

/** The date part of a stored UTC stamp (`2026-10-05T17:10:00Z`). */
const dayOf = (stamp: string): string => stamp.slice(0, 10)

/** What the last read of the event did to its lists, or null when nothing
 *  needs saying: the event kept its lists and the last read found no change. */
export function readLine(
  event: Pick<MetaEventDetail, 'decks' | 'lists_read_at' | 'empty_read_at' | 'empty_read_kind'>,
  t: TFunction,
): string | null {
  const hasLists = event.decks.some((deck) => deck.main.length > 0)
  const kind = event.empty_read_kind
  const emptyDay = event.empty_read_at ? dayOf(event.empty_read_at) : null
  if (!hasLists) {
    if (emptyDay) return t('field.event.read.standingsOnlyOn', { emptyDay })
    return t('field.event.read.standingsOnly')
  }
  if (!kind || !emptyDay) return null
  if (event.lists_read_at) {
    const listsDay = dayOf(event.lists_read_at)
    return kind === 'empty'
      ? t('field.event.read.listsEmpty', { listsDay, emptyDay })
      : t('field.event.read.listsGone', { listsDay, emptyDay })
  }
  return kind === 'empty'
    ? t('field.event.read.unrecordedEmpty', { emptyDay })
    : t('field.event.read.unrecordedGone', { emptyDay })
}

/** 1 as `1st`, 2 as `2nd`, 11 as `11th`, 21 as `21st`: the language's own
 *  ordinal category picks the sentence (`field.event.ordinal.*`). */
export function ordinal(n: number, t: TFunction): string {
  // The language the given `t` answers in: where one of the sentences
  // resolved from, not the dashboard's own.
  const { usedLng } = t('field.event.ordinal.other', { n, returnDetails: true })
  switch (new Intl.PluralRules(usedLng, { type: 'ordinal' }).select(n)) {
    case 'one':
      return t('field.event.ordinal.one', { n })
    case 'two':
      return t('field.event.ordinal.two', { n })
    case 'few':
      return t('field.event.ordinal.few', { n })
    default:
      return t('field.event.ordinal.other', { n })
  }
}

/** A deck's standing, `1st · 6–1`: the placement and the record, each only
 *  when known, draws only when there are some. Null when neither is. */
export function standing(deck: Pick<MetaEventDeck, 'placement' | 'record'>, t: TFunction): string | null {
  const parts: string[] = []
  if (deck.placement != null) parts.push(ordinal(deck.placement, t))
  const record = deck.record
  if (record) {
    parts.push(`${record.wins}–${record.losses}${record.draws > 0 ? `–${record.draws}` : ''}`)
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

/** What kind of event the tier says it is; null for a tier that says
 *  nothing. */
export function kindWords(tier: string | null | undefined, t: TFunction): string | null {
  switch (tier) {
    case 'A':
      return t('field.event.kind.A')
    case 'B':
      return t('field.event.kind.B')
    case 'C':
      return t('field.event.kind.C')
    case 'D':
      return t('field.event.kind.D')
    default:
      return null
  }
}

/** A mainboard group's heading, `Creatures (12)`; `n` is its copies. The
 *  null group has no plural. A type the table does not know is named as the
 *  API sent it. */
export function groupHeading(type: string | null, n: number, t: TFunction): string {
  switch (type) {
    case null:
      return t('field.event.group.unknown', { n })
    case 'Creature':
      return t('field.event.group.creature', { n })
    case 'Planeswalker':
      return t('field.event.group.planeswalker', { n })
    case 'Battle':
      return t('field.event.group.battle', { n })
    case 'Instant':
      return t('field.event.group.instant', { n })
    case 'Sorcery':
      return t('field.event.group.sorcery', { n })
    case 'Artifact':
      return t('field.event.group.artifact', { n })
    case 'Enchantment':
      return t('field.event.group.enchantment', { n })
    case 'Land':
      return t('field.event.group.land', { n })
    default:
      return t('field.event.group.other', { type, n })
  }
}

/** The sideboard's heading, or null when it is empty. */
export function sideboardHeading(side: MetaCard[], t: TFunction): string | null {
  if (side.length === 0) return null
  return t('field.event.sideboard', { n: side.reduce((sum, card) => sum + card.count, 0) })
}
