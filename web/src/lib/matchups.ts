/**
 * What a deck's Matchups reads, as pure functions of the API's rows. The
 * page reads the matches of the versions the address chose (every version,
 * or one), one request per version, and these count them: one row per
 * format and `opponent_key` over the finished matches (`isFinished`: a win,
 * a loss or a draw), whichever version played them.
 */
import type { Match, MetaWinrate } from '../api'
import type { TFunction } from '../i18n'
import { mergeNewestFirst } from './deckOverview'
import { archetypeName, formatName } from './decks'
import { formatPercent, formatRecord } from './format'
import { isFinished, opponentNamed, startOf } from './home'
import { opponentLabelText } from './opponent'
import { MIN_TRUSTED_FIELD_SAMPLE, RATE_MIN_MATCHES, rateOrRecord } from './sample'
import { formatCount } from './time'

/** A no-break space: a count and the word after it never part. */
export const NBSP = '\u00a0'

/** How the opponent's deck is known, as `MatchRow` tells it: by a name (the
 *  classifier's or the viewer's own), by its colours and a card it showed,
 *  or not at all. */
export type MatchupKind = 'named' | 'unrecognized' | 'unknown'

export type MatchupRow = {
  /** The opponent's `opponent_key`, the empty one when the match has none. */
  key: string
  /** The format the row's matches were played in, `null` for matches with
   *  none (a group of their own). */
  format: string | null
  kind: MatchupKind
  label: string | null
  colors: string | null
  matches: number
  won: number
  /** Matches lost. A draw is neither this nor a win (`docs/design-system.md`, "Numbers"). */
  lost: number
  gamesWon: number
  gamesLost: number
  /** The finished best-of-three matches among `matches` (`best_of === 3`):
   *  the only ones whose games the two counts below read. */
  bo3Matches: number
  /** Game 1 won, and lost, over the best-of-three matches; a drawn game 1
   *  is neither. */
  game1Won: number
  game1Lost: number
  /** Games 2 and 3 won, and lost, over the best-of-three matches; a drawn
   *  game is neither. */
  postboardWon: number
  postboardLost: number
}

/** `opponent_key` is `'archetype:' + archetype_key` only when the classifier
 *  actually named the deck, the same vocabulary the metagame corpus uses.
 *  A manual label, a colours-only guess, or 'unknown' shares no archetype
 *  with the field data, so there is nothing honest to join against. */
export function archetypeKeyOf(opponentKey: string): string | null {
  const prefix = 'archetype:'
  return opponentKey.startsWith(prefix) ? opponentKey.slice(prefix.length) : null
}

function kindOf(match: Match): MatchupKind {
  if (opponentNamed(match) && match.opponent_label) return 'named'
  if (match.opponent_source === 'colors' && match.opponent_label) return 'unrecognized'
  return 'unknown'
}

/** What a key's matches say of the opponent's deck: how it is known, the
 *  label it goes by, and its colours. */
export type OpponentSeen = Pick<MatchupRow, 'kind' | 'label' | 'colors'>

/** The colour combination most of the matches showed; among equals, the
 *  one shown by the newest match. `counts` holds the combinations in the
 *  order first met, newest match first. */
function majorityColors(counts: Map<string, number>): string | null {
  let best: string | null = null
  let most = 0
  for (const [colors, count] of counts) {
    if (count > most) {
      best = colors
      most = count
    }
  }
  return best
}

/** Over one key's matches, given newest first: the kind and the label are
 *  the newest match's; the colours are the combination most of them showed
 *  (a combination compared as written), the newest match's among equals,
 *  `null` when none showed any. With no match, nothing was seen. Which
 *  matches to give, finished or every one, is the caller's. */
export function opponentSeen(newestFirst: Match[]): OpponentSeen {
  const newest = newestFirst[0]
  const counts = new Map<string, number>()
  for (const match of newestFirst) {
    const colors = match.opponent_colors
    if (colors) counts.set(colors, (counts.get(colors) ?? 0) + 1)
  }
  return {
    kind: newest ? kindOf(newest) : 'unknown',
    label: newest?.opponent_label ?? null,
    colors: majorityColors(counts),
  }
}

type Group = { key: string; format: string | null; lastMet: number | null; matches: Match[] }

/** One group's row, its matches finished and given newest first. */
function countRow(group: Group): MatchupRow {
  const row: MatchupRow = {
    key: group.key,
    format: group.format,
    ...opponentSeen(group.matches),
    matches: group.matches.length,
    won: 0,
    lost: 0,
    gamesWon: 0,
    gamesLost: 0,
    bo3Matches: 0,
    game1Won: 0,
    game1Lost: 0,
    postboardWon: 0,
    postboardLost: 0,
  }
  for (const match of group.matches) {
    if (match.result === 'win') row.won += 1
    if (match.result === 'loss') row.lost += 1
    row.gamesWon += match.games_won ?? 0
    row.gamesLost += match.games_lost ?? 0
    if (match.best_of !== 3) continue
    row.bo3Matches += 1
    if (match.game1_result === 'win') row.game1Won += 1
    if (match.game1_result === 'loss') row.game1Lost += 1
    row.postboardWon += match.postboard_won ?? 0
    row.postboardLost += match.postboard_lost ?? 0
  }
  return row
}

/** One row per format and `opponent_key` over the finished matches (a
 *  missing format a group of its own, so a deck whose matches share one
 *  format has one row per key), its kind, label and colours by
 *  `opponentSeen` over them. A draw is a match and not a
 *  win; a match with no games recorded adds none. Game 1 and games 2–3
 *  are counted over the best-of-three matches alone (`best_of === 3`): a
 *  best-of-one game is a different queue's and in neither, and a drawn
 *  game is in neither count. Most matches first, then
 *  the archetype met last (a key whose every start is unreadable after the
 *  rest), then by label. */
export function matchupRows(matches: Match[]): MatchupRow[] {
  const groups = new Map<string, Group>()
  for (const match of mergeNewestFirst([matches])) {
    if (!isFinished(match)) continue
    const key = match.opponent_key ?? ''
    const format = match.format ?? null
    const groupKey = JSON.stringify([format, key])
    const group = groups.get(groupKey)
    if (group) group.matches.push(match)
    else groups.set(groupKey, { key, format, lastMet: startOf(match), matches: [match] })
  }
  return [...groups.values()]
    .map((group) => ({ row: countRow(group), lastMet: group.lastMet }))
    .sort((a, b) => {
      if (a.row.matches !== b.row.matches) return b.row.matches - a.row.matches
      if (a.lastMet !== b.lastMet) {
        if (a.lastMet == null) return 1
        if (b.lastMet == null) return -1
        return b.lastMet - a.lastMet
      }
      const x = a.row.label ?? ''
      const y = b.row.label ?? ''
      return x < y ? -1 : x > y ? 1 : 0
    })
    .map((group) => group.row)
}

/** The fewest rows the Matchups table shows before its fold. */
export const MATCHUPS_MIN_SHOWN = 5

/** The rows to show before "Show all": those met `RATE_MIN_MATCHES` times or
 *  more, and never fewer than the `MATCHUPS_MIN_SHOWN` most played. `rows`
 *  come most played first (`matchupRows`), so the shown are a prefix. */
export function foldMatchups<T extends Pick<MatchupRow, 'matches'>>(rows: T[]): T[] {
  const barred = rows.filter((row) => row.matches >= RATE_MIN_MATCHES).length
  return rows.slice(0, Math.max(barred, MATCHUPS_MIN_SHOWN))
}

/** One row over the finished of `matches`, whatever their formats, counted
 *  as `matchupRows` counts a row: for a pairing read over every format,
 *  whose matches share one key. The key is the newest finished match's;
 *  the format is theirs when they share one, `null` otherwise. `null` with
 *  none finished. */
export function matchupRowOver(matches: Match[]): MatchupRow | null {
  const finished = mergeNewestFirst([matches]).filter(isFinished)
  const newest = finished[0]
  if (!newest) return null
  const formats = new Set(finished.map((match) => match.format ?? null))
  const format = formats.size === 1 ? (newest.format ?? null) : null
  return countRow({ key: newest.opponent_key ?? '', format, lastMet: startOf(newest), matches: finished })
}

/** Whether the rows are of more than one format (a missing one among
 *  them), when each row names its own (`rowFormatName`); rows of one
 *  format name none. */
export function rowsSpanFormats(rows: MatchupRow[]): boolean {
  return new Set(rows.map((row) => row.format)).size > 1
}

/** A row's format as a row names it (`formatName`), "Format unknown" for
 *  none. */
export function rowFormatName(row: Pick<MatchupRow, 'format'>, t: TFunction): string {
  return formatName(row.format, t) ?? t('matchups.view.formatUnknown')
}

/** An archetype as drawn: `name` on its own line, `showed` under it for a
 *  deck known by its colours and a card, and `inSentence` for a tile's
 *  line. A named archetype is its label, the colours stripped and the
 *  words spaced (`archetypeName`). */
export type MatchupName = { name: string; showed: string | null; inSentence: string }

export function matchupName(row: OpponentSeen, t: TFunction): MatchupName {
  const text = opponentLabelText(row.label ?? '', row.colors)
  if (row.kind === 'named') {
    const name = archetypeName(text)
    return { name, showed: null, inSentence: name }
  }
  if (row.kind === 'unrecognized') {
    return {
      name: t('matchups.name.unrecognized'),
      showed: t('matchups.name.showed', { card: text }),
      inSentence: t('matchups.name.unrecognizedInSentence'),
    }
  }
  return { name: t('common.unknownDeck'), showed: null, inSentence: t('matchups.name.unknownInSentence') }
}

/** What a `StatTile` says. */
export type TileText = { label: string; value: string; detail: string }

/** A row's rate for ranking: wins over wins plus losses, a draw in neither. */
const rateOf = (row: MatchupRow) => row.won / (row.won + row.lost)

/** The number and line of a best or worst tile: the rate, "73%", and the
 *  record against the archetype, "8–3 against …". Only a row of ten
 *  finished matches or more reaches it (`RATE_MIN_MATCHES`). */
function rankedTile(label: string, row: MatchupRow, t: TFunction): TileText {
  const { figure, line } = rateOrRecord({ wins: row.won, losses: row.lost }, t)
  return {
    label,
    value: figure ?? '—',
    detail: t('matchups.tiles.rankedRate', { record: line, against: matchupName(row, t).inSentence }),
  }
}

/** The first of `rows` (in their own order) that `better` puts ahead of the
 *  rest; `undefined` for none. */
function pick(rows: MatchupRow[], better: (a: MatchupRow, b: MatchupRow) => boolean): MatchupRow | undefined {
  let chosen: MatchupRow | undefined
  for (const row of rows) if (!chosen || better(row, chosen)) chosen = row
  return chosen
}

/** The three tiles over the rows `matchupRows` gave: how many archetypes
 *  were met and how many of them named, each key once however many
 *  formats it was met in; the best and the worst among the rows met ten
 *  times or more (`RATE_MIN_MATCHES`, wins plus losses), by wins over wins
 *  plus losses. Among equal rates each takes the row of more matches, and
 *  among rows equal in both the first in the rows' order; the worst is
 *  never the row the best took. With one such row it is the best, and the
 *  worst says so. */
export function matchupTiles(rows: MatchupRow[], t: TFunction): [TileText, TileText, TileText] {
  // Each row takes its kind from its own newest match, so a key's rows can
  // disagree; the key counts as named when any of them is.
  const namedByKey = new Map<string, boolean>()
  for (const row of rows) namedByKey.set(row.key, namedByKey.get(row.key) === true || row.kind === 'named')
  const named = [...namedByKey.values()].filter(Boolean).length
  const notNamed = namedByKey.size - named
  const metDetail =
    named === 0
      ? t('matchups.tiles.noneNamed')
      : notNamed === 0
        ? t('matchups.tiles.allNamed')
        : t('matchups.tiles.namedAndNot', { named: formatCount(named), notNamed: formatCount(notNamed) })
  const met: TileText = { label: t('matchups.tiles.archetypesMet'), value: formatCount(namedByKey.size), detail: metDetail }

  const eligible = rows.filter((row) => row.won + row.lost >= RATE_MIN_MATCHES)
  const noneYet = t('matchups.tiles.noneYet', { min: RATE_MIN_MATCHES })
  const best = pick(eligible, (a, b) => rateOf(a) > rateOf(b) || (rateOf(a) === rateOf(b) && a.matches > b.matches))
  const worst = pick(
    eligible.filter((row) => row !== best),
    (a, b) => rateOf(a) < rateOf(b) || (rateOf(a) === rateOf(b) && a.matches > b.matches),
  )

  const bestLabel = t('matchups.tiles.best')
  const worstLabel = t('matchups.tiles.worst')
  const bestTile: TileText = best
    ? rankedTile(bestLabel, best, t)
    : { label: bestLabel, value: '—', detail: noneYet }
  const worstTile: TileText = worst
    ? rankedTile(worstLabel, worst, t)
    : {
        label: worstLabel,
        value: '—',
        detail: best ? t('matchups.tiles.oneSoFar', { min: RATE_MIN_MATCHES }) : noneYet,
      }
  return [met, bestTile, worstTile]
}

/** How an archetype fares in the field's tournaments: its win rate (0..1,
 *  `null` when the field has none) over `entries` decks. */
export type FieldRecord = { winrate: number | null; entries: number }

/** The field's record of each key, pooled over every label the key carries
 *  (`/api/metagame/winrate` answers one row per `(archetype_key, label)`;
 *  `Control` alone spans Jeskai, Sultai, Azorius Control and more). Sums
 *  `matches_won`, `matches_lost`, `matches_drawn` and `entries` over a
 *  key's rows; `winrate` is the pooled wins over the pooled total, `null`
 *  when that total is 0. */
export function fieldRecordsByKey(rows: MetaWinrate[]): Map<string, FieldRecord> {
  const totals = new Map<string, { won: number; lost: number; drawn: number; entries: number }>()
  for (const row of rows) {
    const total = totals.get(row.archetype_key) ?? { won: 0, lost: 0, drawn: 0, entries: 0 }
    total.won += row.matches_won
    total.lost += row.matches_lost
    total.drawn += row.matches_drawn
    total.entries += row.entries
    totals.set(row.archetype_key, total)
  }
  return new Map(
    [...totals].map(([key, total]) => {
      const played = total.won + total.lost + total.drawn
      return [key, { winrate: played > 0 ? total.won / played : null, entries: total.entries }]
    }),
  )
}

/** The line under an archetype's name: its games, own first, "Games 17–4";
 *  and when the field knows the archetype, how it wins in tournaments and
 *  over how many entries, under five (`MIN_TRUSTED_FIELD_SAMPLE`) saying
 *  it is too few to trust. With no field record, or one with no rate, the
 *  games alone. */
export function fieldLine(
  games: { won: number; lost: number },
  field: FieldRecord | null | undefined,
  t: TFunction,
): string {
  const record = formatRecord(games.won, games.lost)
  if (field == null || field.winrate == null) return t('matchups.fieldLine.games', { record })
  const values = { record, rate: formatPercent(field.winrate), count: field.entries, n: formatCount(field.entries) }
  return field.entries < MIN_TRUSTED_FIELD_SAMPLE
    ? t('matchups.fieldLine.recordThin', values)
    : t('matchups.fieldLine.record', values)
}
