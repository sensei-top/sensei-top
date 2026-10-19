/**
 * A pattern's own words: the title and sentence-clause Home
 * (`components/home/ThreeThings.tsx`), the Guide (`components/guide/
 * LeakCard.tsx`) and the Coach's profile (`components/coach/`) draw from
 * one `Leak` (`review/leaks.py`), and the sentence the Guide and the Coach
 * both write. Shared here so the pages never say a pattern's story two
 * different ways.
 */
import type { LeakOut } from '../api'
import type { TFunction } from '../i18n'
import { formatRecord } from './format'

/** A pattern's title and the clause its sentence takes, by code
 *  (`review/leaks.py`). A code not here takes the API's own title and
 *  "where this happened". */
export function patternWords(
  leak: Pick<LeakOut, 'code' | 'sample_title'>,
  t: TFunction,
): { title: string; clause: string } {
  switch (leak.code) {
    case 'long_game':
      return { title: t('matchups.patterns.longGame.title'), clause: t('matchups.patterns.longGame.clause') }
    case 'short_game':
      return { title: t('matchups.patterns.shortGame.title'), clause: t('matchups.patterns.shortGame.clause') }
    case 'race_behind':
      return { title: t('matchups.patterns.raceBehind.title'), clause: t('matchups.patterns.raceBehind.clause') }
    case 'race_ahead':
      return { title: t('matchups.patterns.raceAhead.title'), clause: t('matchups.patterns.raceAhead.clause') }
    case 'mana_screwed':
      return { title: t('matchups.patterns.manaScrewed.title'), clause: t('matchups.patterns.manaScrewed.clause') }
    case 'mana_flooded':
      return { title: t('matchups.patterns.manaFlooded.title'), clause: t('matchups.patterns.manaFlooded.clause') }
    case 'over_committed_into_sweeper':
      return {
        title: t('matchups.patterns.overCommitted.title'),
        clause: t('matchups.patterns.overCommitted.clause'),
      }
    case 'control_never_ahead_on_cards':
      return { title: t('matchups.patterns.controlBehind.title'), clause: t('matchups.patterns.controlBehind.clause') }
    case 'beatdown_held_back':
      return { title: t('matchups.patterns.heldBack.title'), clause: t('matchups.patterns.heldBack.clause') }
    default:
      return { title: leak.sample_title, clause: t('matchups.patterns.genericClause') }
  }
}

/** Matches won out of matches played, on one side of a pattern. A leak's
 *  counts are over wins and losses only (`review/leaks.py` reads
 *  `result IN ('win', 'loss')`), so the losses are `n - wins`. */
export type PatternSide = { wins: number; n: number }

/** The sentence under a pattern's title: "You are 133–101 in the matches
 *  where you led the damage race, and 41–110 in the rest." `clause` is
 *  `patternWords`' clause; `withIt` counts the matches with the pattern,
 *  `without` the rest. */
export function patternSentence(
  clause: string,
  withIt: PatternSide,
  without: PatternSide,
  t: TFunction,
): string {
  return t('matchups.patterns.sentence', {
    clause,
    recordWith: formatRecord(withIt.wins, withIt.n - withIt.wins),
    recordWithout: formatRecord(without.wins, without.n - without.wins),
  })
}
