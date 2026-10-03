/**
 * A pattern's own words: the title and sentence-clause Home
 * (`components/home/ThreeThings.tsx`), the Guide (`components/guide/
 * LeakCard.tsx`) and the Coach's profile (`components/coach/`) draw from
 * one `Leak` (`review/leaks.py`), and the sentence the Guide and the Coach
 * both write. Shared here so the pages never say a pattern's story two
 * different ways.
 */
import type { LeakOut } from '../api'
import { NBSP } from './matchups'
import { formatCount } from './time'

/** Each pattern's title and the clause its sentence takes, by code
 *  (`review/leaks.py`). A code not here takes the API's own title and
 *  "where this happened". */
export const PATTERN_WORDS: Record<string, { title: string; clause: string }> = {
  long_game: {
    title: 'Long games are where you lose',
    clause: "where a game ran past your deck's usual length",
  },
  short_game: {
    title: 'Short games go against you',
    clause: "where a game ended sooner than your deck's usual length",
  },
  race_behind: {
    title: 'Falling behind on damage costs you',
    clause: 'where you fell behind in the damage race',
  },
  race_ahead: {
    title: 'Ahead on damage, and still losing',
    clause: 'where you led the damage race',
  },
  mana_screwed: {
    title: 'Short on lands by turn four',
    clause: 'where you were short on lands by your fourth turn',
  },
  mana_flooded: {
    title: 'More lands than your deck plans for',
    clause: "where you drew more lands than your deck's own share",
  },
  over_committed_into_sweeper: {
    title: 'Full boards, with a sweeper still possible',
    clause: "where you filled the board while the opponent's deck could still hold a sweeper",
  },
  control_never_ahead_on_cards: {
    title: 'As the control deck, never ahead on cards',
    clause: 'where you were the control deck and never led on cards',
  },
  beatdown_held_back: {
    title: 'Holding back with the stronger board',
    clause: 'where you had the stronger board and did not attack',
  },
}

/** `PATTERN_WORDS[leak.code]`, or the API's own `sample_title` with a
 *  generic clause for a code this table does not know. Takes the two
 *  fields it reads, so the coach's pattern row, which names its title
 *  `pattern`, can pass it as `sample_title`. */
export function patternWords(leak: Pick<LeakOut, 'code' | 'sample_title'>): { title: string; clause: string } {
  return PATTERN_WORDS[leak.code] ?? { title: leak.sample_title, clause: 'where this happened' }
}

/** Matches won out of matches played, on one side of a pattern. */
export type PatternSide = { wins: number; n: number }

/** The sentence under a pattern's title: "You won 133 of the 234 matches
 *  where you led the damage race, and 41 of the other 151." `clause` is
 *  `patternWords`' clause; `withIt` counts the matches with the pattern,
 *  `without` the rest. A no-break space holds the count of matches with it
 *  to the word "matches". */
export function patternSentence(clause: string, withIt: PatternSide, without: PatternSide): string {
  return (
    `You won ${formatCount(withIt.wins)} of the ${formatCount(withIt.n)}${NBSP}matches ${clause}, ` +
    `and ${formatCount(without.wins)} of the other ${formatCount(without.n)}.`
  )
}
