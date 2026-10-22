/**
 * What a deck's Overview and the strip over every deck tab read, as pure
 * functions of the API's rows and a clock (`now`, milliseconds since the
 * epoch). A version is a row of `/api/decks`; a deck lists its versions in
 * its identity's `deck_ids`. The pages read the matches and the games on the
 * play and on the draw one version at a time, and these add them up.
 * Matches' band draws the strip's play/draw tile too (`playDrawTile`).
 *
 * A finished match is a win, a loss or a draw (`isFinished`). A record and
 * a rate are over wins and losses alone: a draw is never a loss.
 */
import type { Deck, Match, PlayDrawWinrate } from '../api'
import type { TFunction } from '../i18n'
import { formatDate, formatPercent, formatRecord } from './format'
import { isFinished, startOf } from './home'
import { RATE_MIN_MATCHES, rateAndRecordLine, rateCell, rateOrRecord } from './sample'
import { formatCount, formatShortDay, parseTimestamp } from './time'

/** For a sort, newest first: a time that cannot be read comes last. */
function newestFirst(a: number | null, b: number | null): number {
  if (a == null || b == null) return (a == null ? 1 : 0) - (b == null ? 1 : 0)
  return b - a
}

/** "1 match", "12 matches", joined by a no-break space (the catalogue's). */
function matchesWord(count: number, t: TFunction): string {
  return t('decks.count.matches', { count, n: formatCount(count) })
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

/** When a version was played, from its `first_played` (its `first_seen`
 *  when it has none) to its `last_played`, in the viewer's own days: "Sep 14" for one day, "Sep 3 to 14" within a
 *  month, "Aug 28 to Sep 3" across two. With one of the two missing, the
 *  other day alone; with neither, `null`. A year other than `now`'s is
 *  written as `formatShortDay` writes it. */
export function versionDays(
  deck: Pick<Deck, 'first_played' | 'first_seen' | 'last_played'>,
  now: number,
  t: TFunction,
): string | null {
  const first = parseTimestamp(deck.first_played ?? deck.first_seen)
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
    const day = formatDate(to, { day: 'numeric' })
    const toDays =
      a.getFullYear() === new Date(now).getFullYear()
        ? day
        : t('decks.overview.dayWithYear', { day, year: formatDate(to, { year: 'numeric' }) })
    return t('decks.overview.daysWithinMonth', { from: formatShortDay(from, from), to: toDays })
  }
  return t('decks.overview.daysAcross', { from: formatShortDay(from, now), to: formatShortDay(to, now) })
}

/** A version as the switcher names it: its days ("Undated" with none),
 *  then its `matches_played`. "Sep 3 to 14 · 37 matches". */
export function versionLabel(
  deck: Deck,
  now: number,
  t: TFunction,
): string {
  return `${versionDays(deck, now, t) ?? t('decks.overview.undated')} · ${matchesWord(deck.matches_played, t)}`
}

/** A match's wins and losses, draws and matches in progress aside
 *  (`docs/design-system.md`, "Numbers": a draw is never a loss). */
function matchRecord(matches: Match[]): { wins: number; losses: number } {
  let wins = 0
  let losses = 0
  for (const match of matches) {
    if (match.result === 'win') wins += 1
    else if (match.result === 'loss') losses += 1
  }
  return { wins, losses }
}

/** The second line of a version's row, over that version's matches, in the
 *  one-line form: from ten finished a rate and the record, "57% · 21–16";
 *  one to nine the record alone, "3–3"; none, "no finished match yet". A
 *  draw counts toward neither. */
export function versionRecord(matches: Match[], t: TFunction): string {
  return rateAndRecordLine(matchRecord(matches)) ?? t('common.sample.noMatch')
}

/* -------------------------------------------------- on the play and draw */

/** `games` are the games won and lost: a draw counts toward neither. */
export type PlayDrawSide = { games: number; won: number }
export type PlayDrawTotals = { play: PlayDrawSide; draw: PlayDrawSide }

/** The games on the play and on the draw, over every row of every version. */
export function playDrawTotals(rows: PlayDrawWinrate[]): PlayDrawTotals {
  const totals: PlayDrawTotals = { play: { games: 0, won: 0 }, draw: { games: 0, won: 0 } }
  for (const row of rows) {
    const side = row.on_play ? totals.play : totals.draw
    side.games += row.games_won + row.games_lost
    side.won += row.games_won
  }
  return totals
}

/** What a `StatTile` says. `thin` is a figure drawn muted: a record, or
 *  "too few", where there are too few for a rate. */
export type KeyTile = { label: string; value: string; detail: string; thin: boolean }

/** A side's whole percentage, 0..100, from ten games; `null` under ten. */
function sidePercent(side: PlayDrawSide): number | null {
  return side.games >= RATE_MIN_MATCHES ? Math.round((side.won / side.games) * 100) : null
}

/** A side as the play/draw line names it: its rate from ten games, its
 *  record under ten, "no games" with none. */
function sideValue(side: PlayDrawSide, t: TFunction): string {
  if (side.games >= RATE_MIN_MATCHES) return formatPercent(side.won / side.games)
  if (side.games > 0) return formatRecord(side.won, side.games - side.won)
  return t('decks.strip.sideNone')
}

/** The play/draw tile: the deck strip's third, and the third on Matches'
 *  band, so the two never disagree over the same games. With ten games on
 *  each side the gap in points, the two whole percentages subtracted so
 *  the figure and the line agree; with fewer on either side "too few",
 *  muted; with no game on either, an em dash. Its line names both sides,
 *  the play first. */
export function playDrawTile(totals: PlayDrawTotals, t: TFunction): KeyTile {
  const play = sidePercent(totals.play)
  const draw = sidePercent(totals.draw)
  let value: string
  let thin = false
  if (play != null && draw != null) {
    const points = play - draw
    const size = Math.abs(points)
    const sign = points > 0 ? '+' : points < 0 ? '\u2212' : ''
    value = t('decks.strip.points', { count: size, n: formatCount(size), sign })
  } else if (totals.play.games > 0 || totals.draw.games > 0) {
    value = t('common.sample.tooFewCellGames')
    thin = true
  } else {
    value = '—'
  }
  const detail = [
    t('decks.strip.onPlay', { value: sideValue(totals.play, t) }),
    t('decks.strip.onDraw', { value: sideValue(totals.draw, t) }),
  ].join(' · ')
  return { label: t('decks.strip.playDraw'), value, detail, thin }
}

/** The deck strip's three tiles, over the versions a tab reads.
 *
 *  Matches: the small-sample rule over the finished matches' wins and
 *  losses, a draw counting toward neither. Games: the same over every
 *  match's games won and lost, finished match or not. Play vs draw:
 *  `playDrawTile`. */
export function deckKeyNumbers(
  matches: Match[],
  totals: PlayDrawTotals,
  t: TFunction,
): [KeyTile, KeyTile, KeyTile] {
  let gamesWon = 0
  let gamesLost = 0
  for (const match of matches) {
    gamesWon += match.games_won ?? 0
    gamesLost += match.games_lost ?? 0
  }
  const tile = (label: string, record: { wins: number; losses: number }, unit: 'matches' | 'games'): KeyTile => {
    const { figure, line, thin } = rateOrRecord(record, t, unit)
    return { label, value: figure ?? '—', detail: line, thin }
  }

  return [
    tile(t('decks.strip.matches'), matchRecord(matches), 'matches'),
    tile(t('decks.strip.games'), { wins: gamesWon, losses: gamesLost }, 'games'),
    playDrawTile(totals, t),
  ]
}

/* ---------------------------------------------------------------- by rank */

/** The ladder's classes, best first. */
const LADDER = ['Mythic', 'Diamond', 'Platinum', 'Gold', 'Silver', 'Bronze']

/** `record` is wins–losses; `thin` is a `rate` drawn muted, a rough rate
 *  or "too few" (`rateCell`). */
export type RankRow = { rank: string; matches: number; record: string; rate: string; thin: boolean }

type RankGroup = { rankClass: string | null; level: number | null; matches: number; wins: number; losses: number }

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
 *  Matches counts every finished match, a draw too; the record and the
 *  rate are over wins and losses, a draw counting toward neither. The rate
 *  is `rateCell`'s: muted from five to nine of them, "too few", muted,
 *  from one to four, and an em dash with none (a row of draws alone). */
export function rankRows(matches: Match[], t: TFunction): RankRow[] {
  const groups = new Map<string, RankGroup>()
  for (const match of matches) {
    if (!isFinished(match)) continue
    const rankClass = match.rank_class ?? null
    const level = rankClass != null ? (match.rank_level ?? null) : null
    const key = `${rankClass ?? ''}\u0000${level ?? ''}`
    const group = groups.get(key) ?? { rankClass, level, matches: 0, wins: 0, losses: 0 }
    group.matches += 1
    if (match.result === 'win') group.wins += 1
    else if (match.result === 'loss') group.losses += 1
    groups.set(key, group)
  }
  return [...groups.values()]
    .sort((a, b) => {
      const byPlace = classPlace(a.rankClass) - classPlace(b.rankClass)
      if (byPlace !== 0) return byPlace
      if (a.rankClass !== b.rankClass) return (a.rankClass ?? '') < (b.rankClass ?? '') ? -1 : 1
      return (a.level ?? Infinity) - (b.level ?? Infinity)
    })
    .map((group) => {
      const cell = rateCell({ wins: group.wins, losses: group.losses }, t)
      const thin = cell?.muted ?? false
      const rate = cell?.text ?? '—'
      return {
        rank:
          group.rankClass == null
            ? t('decks.overview.noRank')
            : group.level != null
              ? `${group.rankClass} ${group.level}`
              : group.rankClass,
        matches: group.matches,
        record: formatRecord(group.wins, group.losses),
        rate,
        thin,
      }
    })
}

/* ------------------------------------------------------------ the matches */

/** Every version's matches in one list, newest first by start; a match
 *  whose start cannot be read comes last. */
export function mergeNewestFirst(lists: Match[][]): Match[] {
  return lists.flat().sort((a, b) => newestFirst(startOf(a), startOf(b)))
}

/** The words over the list: how many are listed, of how many in hand. */
export function matchesCaption(inHand: number, shown: number, t: TFunction): string {
  if (inHand === 1) return matchesWord(1, t)
  const counts = { count: inHand, n: formatCount(inHand) }
  return shown < inHand
    ? t('decks.overview.captionShowing', { ...counts, shown: formatCount(shown) })
    : t('decks.overview.captionAll', counts)
}
