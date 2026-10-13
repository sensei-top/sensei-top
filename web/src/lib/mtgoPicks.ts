import type { MtgoFormat, MtgoGroupList, MtgoPickGroup, MtgoPickItem } from '../api'
import type { TFunction } from '../i18n'
import { ownScore } from './home'
import { formatCount } from './time'

/** "1 match", "12 matches". */
export function matchesWord(n: number, t: TFunction): string {
  return t('mtgo.matches', { count: n, n: formatCount(n) })
}

/** A match's result in a word. */
function resultWord(result: string, t: TFunction): string | undefined {
  if (result === 'win') return t('mtgo.result.win')
  if (result === 'loss') return t('mtgo.result.loss')
  if (result === 'draw') return t('mtgo.result.draw')
  return undefined
}

/** "Win 2–1": the result and the score, whichever are known. */
export function resultWords(
  match: { result?: string | null; games_won?: number | null; games_lost?: number | null },
  t: TFunction,
): string {
  const result = match.result ? resultWord(match.result, t) : undefined
  return [result, ownScore(match)].filter(Boolean).join(' ')
}

/** What the user has done to one group card so far. */
export interface GroupState {
  /** The chosen list's deck_id: the group's `proposed`, or null on a tie. */
  deckId: string | null
  /** The chosen format: the chosen list's pre-fill, or null. */
  format: MtgoFormat | null
  /** Matches taken out of this confirm. */
  removed: ReadonlySet<string>
}

function listOf(group: MtgoPickGroup, deckId: string | null): MtgoGroupList | undefined {
  return deckId == null ? undefined : group.lists.find((l) => l.deck_id === deckId)
}

export function initialGroupState(group: MtgoPickGroup): GroupState {
  return {
    deckId: group.proposed ?? null,
    format: listOf(group, group.proposed ?? null)?.format_prefill ?? null,
    removed: new Set(),
  }
}

/** Choose a list: the format becomes that list's pre-fill, or clears. */
export function chooseList(group: MtgoPickGroup, state: GroupState, deckId: string): GroupState {
  return { ...state, deckId, format: listOf(group, deckId)?.format_prefill ?? null }
}

export function chooseFormat(state: GroupState, format: MtgoFormat | null): GroupState {
  return { ...state, format }
}

export function toggleRemoved(state: GroupState, matchId: string): GroupState {
  const removed = new Set(state.removed)
  if (!removed.delete(matchId)) removed.add(matchId)
  return { ...state, removed }
}

/** The PUT items: one per match not removed, with the chosen list and format.
 *  Empty until a list is chosen. */
export function itemsToSend(group: MtgoPickGroup, state: GroupState): MtgoPickItem[] {
  if (state.deckId == null) return []
  return group.matches
    .filter((m) => !state.removed.has(m.match_id))
    .map((m) => ({ match_id: m.match_id, deck_id: state.deckId, format: state.format }))
}
