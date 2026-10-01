/**
 * What a deck's Overview reads, as pure functions of the API's rows and a
 * clock (`now`, milliseconds since the epoch). A version is a row of
 * `/api/decks`; a deck lists its versions in its identity's `deck_ids`. The
 * page reads the matches and the games on the play and on the draw one
 * version at a time, and these add them up.
 *
 * A finished match is a win, a loss or a draw (`isFinished`), as the band
 * above them counts it.
 */
import type { Deck, Match, PlayDrawWinrate } from '../api'
import { isFinished, RATE_MIN_MATCHES, startOf } from './home'
import { formatCount, formatPercent, formatShortDay, parseTimestamp } from './time'

/** A no-break space: a count and the word after it never part. */
const NBSP = '\u00a0'

/** For a sort, newest first: a time that cannot be read comes last. */
function newestFirst(a: number | null, b: number | null): number {
  if (a == null || b == null) return (a == null ? 1 : 0) - (b == null ? 1 : 0)
  return b - a
}

/** "1 match", "12 matches", joined by a no-break space. */
function matchesWord(count: number): string {
  return `${formatCount(count)}${NBSP}${count === 1 ? 'match' : 'matches'}`
}

/* ------------------------------------------------------------- versions */

/** The rows of `decks` that are the deck's versions (`deckIds`), newest
 *  first by `last_played`; a version never played comes last. A version
 *  `/api/decks` does not list has no row, and is left out. */
export function versionsInOrder(deckIds: string[], decks: Deck[]): Deck[] {
  const ids = new Set(deckIds)
  return decks
    .filter((deck) => ids.has(deck.deck_id))
    .sort((a, b) => newestFirst(parseTimestamp(a.last_played), parseTimestamp(b.last_played)))
}

/** The `?version=` a deck's pages read: `param` when it is one of the
 *  deck's versions and the deck has more than one, else `null`, which is
 *  every version. */
export function chosenVersion(param: string | null | undefined, deckIds: string[]): string | null {
  if (!param || deckIds.length < 2) return null
  return deckIds.includes(param) ? param : null
}

const sameDay = (a: Date, b: Date) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()

/** When a version was played, from its `first_seen` to its `last_played`,
 *  in the viewer's own days: "Sep 14" for one day, "Sep 3 to 14" within a
 *  month, "Aug 28 to Sep 3" across two. With one of the two missing, the
 *  other day alone; with neither, `null`. A year other than `now`'s is
 *  written as `formatShortDay` writes it. */
export function versionDays(deck: Pick<Deck, 'first_seen' | 'last_played'>, now: number): string | null {
  const first = parseTimestamp(deck.first_seen)
  const last = parseTimestamp(deck.last_played)
  if (first == null && last == null) return null
  if (first == null || last == null) return formatShortDay((first ?? last) as number, now)
  const from = Math.min(first, last)
  const to = Math.max(first, last)
  const a = new Date(from)
  const b = new Date(to)
  if (sameDay(a, b)) return formatShortDay(from, now)
  if (a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()) {
    // The month once, the year (when not `now`'s) at the end: "Sep 3 to
    // 14, 2025". `formatShortDay` against its own day never writes a year.
    const year = a.getFullYear() === new Date(now).getFullYear() ? '' : `, ${a.getFullYear()}`
    return `${formatShortDay(from, from)} to ${b.getDate()}${year}`
  }
  return `${formatShortDay(from, now)} to ${formatShortDay(to, now)}`
}

/** A version as the switcher names it: its days ("Undated" with none),
 *  then its `matches_played`. "Sep 3 to 14 · 37 matches". */
export function versionLabel(deck: Deck, now: number): string {
  return `${versionDays(deck, now) ?? 'Undated'} · ${matchesWord(deck.matches_played)}`
}

/** The second line of a version's row, over that version's matches: from
 *  ten finished a rate, "57% · won 21 of 37"; one to nine the count, "won 3
 *  of 7"; none, "no finished match yet". */
export function versionRecord(matches: Match[]): string {
  const finished = matches.filter(isFinished)
  const wins = finished.filter((match) => match.result === 'win').length
  const count = `won ${formatCount(wins)} of ${formatCount(finished.length)}`
  if (finished.length >= RATE_MIN_MATCHES) return `${formatPercent(wins / finished.length)}% · ${count}`
  if (finished.length > 0) return count
  return 'no finished match yet'
}

/* -------------------------------------------------- on the play and draw */

export type PlayDrawSide = { games: number; won: number }
export type PlayDrawTotals = { play: PlayDrawSide; draw: PlayDrawSide }

/** The games on the play and on the draw, over every row of every version. */
export function playDrawTotals(rows: PlayDrawWinrate[]): PlayDrawTotals {
  const totals: PlayDrawTotals = { play: { games: 0, won: 0 }, draw: { games: 0, won: 0 } }
  for (const row of rows) {
    const side = row.on_play ? totals.play : totals.draw
    side.games += row.games_completed
    side.won += row.games_won
  }
  return totals
}

/** What a `StatTile` says. */
export type TileText = { label: string; value: string; detail: string }

/** A whole percentage, 0..100, of a side with at least ten games; `null`
 *  under ten, where no rate is shown. */
function sidePercent(side: PlayDrawSide): number | null {
  return side.games >= RATE_MIN_MATCHES ? Math.round((side.won / side.games) * 100) : null
}

function sideTile(side: PlayDrawSide, where: 'play' | 'draw'): TileText {
  const label = where === 'play' ? 'On the play' : 'On the draw'
  const percent = sidePercent(side)
  if (percent != null) {
    return {
      label,
      value: `${percent}%`,
      detail: `won ${formatCount(side.won)} of ${formatCount(side.games)}${NBSP}games`,
    }
  }
  if (side.games > 0) return { label, value: `${formatCount(side.won)} of ${formatCount(side.games)}`, detail: 'games won' }
  return { label, value: '—', detail: `no game on the ${where} yet` }
}

/** The three tiles: on the play, on the draw, and the one against the
 *  other. A side under ten games (`RATE_MIN_MATCHES`) shows its count, not
 *  a rate, and the third tile compares only when both sides have ten: the
 *  two whole percentages subtracted, so the three agree. */
export function playDrawTiles(totals: PlayDrawTotals): [TileText, TileText, TileText] {
  const play = sidePercent(totals.play)
  const draw = sidePercent(totals.draw)
  const label = 'Play against draw'
  let difference: TileText
  if (play == null || draw == null) {
    difference = { label, value: '—', detail: 'too few games to compare' }
  } else {
    const points = play - draw
    const size = Math.abs(points)
    const word = `${size}${NBSP}${size === 1 ? 'point' : 'points'}`
    if (points > 0) difference = { label, value: `+${word}`, detail: 'better on the play' }
    else if (points < 0) difference = { label, value: `\u2212${word}`, detail: 'better on the draw' }
    else difference = { label, value: word, detail: 'no difference' }
  }
  return [sideTile(totals.play, 'play'), sideTile(totals.draw, 'draw'), difference]
}

/* ---------------------------------------------------------------- by rank */

/** The ladder's classes, best first. */
const LADDER = ['Mythic', 'Diamond', 'Platinum', 'Gold', 'Silver', 'Bronze']

export type RankRow = { rank: string; matches: number; won: number; rate: string }

type RankGroup = { rankClass: string | null; level: number | null; matches: number; won: number }

/** Where a class sits: its place on the ladder, a class not on it after
 *  every one that is, no rank last. */
function classPlace(rankClass: string | null): number {
  if (rankClass == null) return LADDER.length + 1
  const index = LADDER.indexOf(rankClass)
  return index >= 0 ? index : LADDER.length
}

/** The finished matches by the rank they were played at, in the ladder's
 *  order: Mythic, Diamond, Platinum, Gold, Silver, Bronze, level 1 before
 *  4 within a class and a class's row with no level after its levels; a
 *  class not on the ladder after them by name; matches with no rank last.
 *  The rate is an em dash under ten matches. */
export function rankRows(matches: Match[]): RankRow[] {
  const groups = new Map<string, RankGroup>()
  for (const match of matches) {
    if (!isFinished(match)) continue
    const rankClass = match.rank_class ?? null
    const level = rankClass != null ? (match.rank_level ?? null) : null
    const key = `${rankClass ?? ''}\u0000${level ?? ''}`
    const group = groups.get(key) ?? { rankClass, level, matches: 0, won: 0 }
    group.matches += 1
    if (match.result === 'win') group.won += 1
    groups.set(key, group)
  }
  return [...groups.values()]
    .sort((a, b) => {
      const byPlace = classPlace(a.rankClass) - classPlace(b.rankClass)
      if (byPlace !== 0) return byPlace
      if (a.rankClass !== b.rankClass) return (a.rankClass ?? '') < (b.rankClass ?? '') ? -1 : 1
      return (a.level ?? Infinity) - (b.level ?? Infinity)
    })
    .map((group) => ({
      rank:
        group.rankClass == null
          ? 'No rank recorded'
          : group.level != null
            ? `${group.rankClass} ${group.level}`
            : group.rankClass,
      matches: group.matches,
      won: group.won,
      rate: group.matches >= RATE_MIN_MATCHES ? `${formatPercent(group.won / group.matches)}%` : '—',
    }))
}

/* ------------------------------------------------------------ the matches */

/** Every version's matches in one list, newest first by start; a match
 *  whose start cannot be read comes last. */
export function mergeNewestFirst(lists: Match[][]): Match[] {
  return lists.flat().sort((a, b) => newestFirst(startOf(a), startOf(b)))
}

/** The words over the list: how many are listed, of how many in hand. */
export function matchesCaption(inHand: number, shown: number): string {
  if (inHand === 1) return matchesWord(1)
  return shown < inHand
    ? `Showing ${formatCount(shown)} of ${matchesWord(inHand)}, newest first`
    : `${matchesWord(inHand)}, newest first`
}
