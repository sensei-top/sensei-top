import type { MatchDetail } from '../api'

/** One card whose art a page can show. */
export type ArtCard = { grpId: number; name: string | null }

/** Whose cards: the viewer's, or the opponent's. */
export type ArtSide = 'self' | 'opponent'

/** The cards one side cast in a match (Arena's `CastSpell`: a land's art
 *  repeats across sets, and a card only drawn says little), distinct by
 *  id, the card first cast latest in the match first: the cards the match
 *  turned to, rather than its opening plays. Games in order, events in
 *  their order within a game. An event whose side is unknown counts for
 *  neither.
 *
 *  Art is never the carrier of anything (docs/design-system.md): with no
 *  detail, or no cast card, this is empty and the box shows nothing. */
export function castCards(detail: MatchDetail | undefined, side: ArtSide): ArtCard[] {
  if (!detail) return []
  const wantSelf = side === 'self'
  const games = [...detail.games].sort((a, b) => a.game_number - b.game_number)
  const first = new Map<number, { at: number; name: string | null }>()
  let at = 0
  for (const game of games) {
    const events = [...game.cards].sort((a, b) => a.seq - b.seq)
    for (const event of events) {
      at += 1
      if (event.category !== 'CastSpell' || event.grp_id == null) continue
      if (event.is_self == null || event.is_self !== wantSelf) continue
      if (!first.has(event.grp_id)) first.set(event.grp_id, { at, name: event.card_name ?? null })
    }
  }
  return [...first.entries()]
    .sort((a, b) => b[1].at - a[1].at)
    .map(([grpId, { name }]) => ({ grpId, name }))
}

/** The first of `cards` whose id is not in `used`, which it then joins, so
 *  that the pictures on one page are different cards. `null` when every
 *  card is taken or there is none. */
export function takeUnused(cards: ArtCard[], used: Set<number>): ArtCard | null {
  const card = cards.find((candidate) => !used.has(candidate.grpId)) ?? null
  if (card) used.add(card.grpId)
  return card
}
