import type { LibraryCardOut } from '../api'
import { probAtLeastOneIn } from './odds'

/** The horizon every chance on the library card is over. */
export const LIBRARY_DRAWS = 3

/** The group key of a nonland with no parseable mana value: last, never a
 *  made-up cost (rule 4). */
export const UNKNOWN_MANA_VALUE = 99

export type LibraryGroup = {
  /** The mana value, or `UNKNOWN_MANA_VALUE`. */
  manaValue: number
  cards: LibraryCardOut[]
}

export type LandsLine = {
  left: number
  /** The deck's lands, or null when the deck's count is not known. */
  total: number | null
  /** P(at least one land within `LIBRARY_DRAWS` draws). */
  chance: number
}

/** A row's chance of at least one copy within three draws. */
export function rowChance(libraryCount: number, left: number): number {
  return probAtLeastOneIn(libraryCount, left, LIBRARY_DRAWS)
}

/** The nonland cards grouped by mana value, ascending, an unknown value last;
 *  each group sorted by name, so a row's place never moves as the game goes. */
export function groupByManaValue(cards: LibraryCardOut[]): LibraryGroup[] {
  const groups = new Map<number, LibraryCardOut[]>()
  for (const c of cards) {
    if (c.is_land) continue
    const key = c.mana_value ?? UNKNOWN_MANA_VALUE
    const group = groups.get(key)
    if (group) group.push(c)
    else groups.set(key, [c])
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([manaValue, group]) => ({
      manaValue,
      cards: [...group].sort((a, b) => (a.name ?? '').localeCompare(b.name ?? '')),
    }))
}

/** Lands left, the deck's lands, and the chance of at least one land within
 *  three draws. `deckLands` comes from the deck (the keep guide's land
 *  count), never from the rows: the server leaves a card out once every copy
 *  is seen (`table/live.py`), so summing `quantity` over the land rows would
 *  shrink as lands run out and read 0/0 at the end. Unknown stays null
 *  (rule 4). */
export function landsLine(
  cards: LibraryCardOut[],
  libraryCount: number,
  deckLands: number | null | undefined,
): LandsLine {
  const left = cards.filter((c) => c.is_land).reduce((sum, c) => sum + c.left, 0)
  return { left, total: deckLands ?? null, chance: rowChance(libraryCount, left) }
}
