/** Which panels the Live page draws while a game is on, by phase. A table
 *  rather than nested conditionals in the view, so the event rule
 *  (`table/queues.py`) can be read and tested in one place.
 *
 *  `advice` is the server's own `CurrentMatchRead.advice`, never derived
 *  here, and-ed in the view with the user's switch in Settings
 *  (`shell/liveAdvice.ts`): false during an event's game, or when the user
 *  turned advice off. Without it the keep verdict, the keep guide and the
 *  opponent-hand estimate leave the page, and what stays is what every
 *  tracker shows: the remaining library with its odds, the
 *  opponent's revealed cards and the archetype read. The break between
 *  games is drawn elsewhere and is not in this table. */

export type LivePanel =
  | 'opening-hand'
  | 'keep-guide'
  | 'library'
  | 'opponent-hand'
  | 'opponent-hand-facts'
  | 'opponent-read'
  | 'opponent-read-dense'

export interface LivePanels {
  primary: LivePanel
  rail: LivePanel[]
}

export function livePanels({
  decisionPending,
  mulliganPhase,
  advice,
}: {
  /** An opening hand is waiting on keep or mulligan. */
  decisionPending: boolean
  /** No turn has started yet. */
  mulliganPhase: boolean
  advice: boolean
}): LivePanels {
  if (!advice) {
    return decisionPending || mulliganPhase
      ? { primary: 'library', rail: ['opponent-read'] }
      : { primary: 'library', rail: ['opponent-hand-facts', 'opponent-read-dense'] }
  }
  if (decisionPending) return { primary: 'opening-hand', rail: ['keep-guide'] }
  if (mulliganPhase) return { primary: 'keep-guide', rail: ['opponent-read'] }
  // Once a turn has started the keep guide has said what it had to: the
  // rail is the opponent's alone.
  return { primary: 'library', rail: ['opponent-hand', 'opponent-read-dense'] }
}

/** The alternatives the break's rail lists. A closest plan is itself
 *  `alternatives[0]` (`table/intermission.py`), and the plan card already
 *  shows it, so it is dropped here: by the plan's archetype key, or the
 *  first entry when that key is null. */
export function railAlternatives<A extends { archetype_key: string }>(intermission: {
  alternatives?: A[] | null
  plan_basis?: string | null
  plan?: { archetype_key?: string | null } | null
}): A[] {
  const alternatives = intermission.alternatives ?? []
  if (intermission.plan_basis !== 'closest') return alternatives
  const key = intermission.plan?.archetype_key
  return key == null ? alternatives.slice(1) : alternatives.filter((a) => a.archetype_key !== key)
}
