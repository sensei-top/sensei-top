import type { LibraryCardOut } from '../api'
import { probAtLeastOneIn } from './odds'

/** The horizons the lands strip gives a chance over: the next draw, within
 *  two, within three. */
export const LANDS_HORIZONS = [1, 2, 3] as const

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
  /** The deck's lands: every land row's quantity, since the server keeps a
   *  row whose copies are all seen (`table/live.py`). */
  total: number
  /** P(at least one land) within each of `LANDS_HORIZONS`, in its order. */
  chances: number[]
}

/** A row's chance of drawing a copy next. */
export function nextDrawChance(libraryCount: number, left: number): number {
  return probAtLeastOneIn(libraryCount, left, 1)
}

/** The nonland cards grouped by mana value, ascending, an unknown value last;
 *  each group by copies left, most first, so its likeliest draw leads, then
 *  by name. A row whose copies are all seen stays, last in its group. */
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
      cards: [...group].sort((a, b) => b.left - a.left || (a.name ?? '').localeCompare(b.name ?? '')),
    }))
}

/** Lands left, the deck's lands, and the chance of at least one land within
 *  each horizon. */
export function landsLine(cards: LibraryCardOut[], libraryCount: number): LandsLine {
  const lands = cards.filter((c) => c.is_land)
  const left = lands.reduce((sum, c) => sum + c.left, 0)
  return {
    left,
    total: lands.reduce((sum, c) => sum + c.quantity, 0),
    chances: LANDS_HORIZONS.map((draws) => probAtLeastOneIn(libraryCount, left, draws)),
  }
}
