/**
 * Everything Home counts, as pure functions of the API's rows and a clock
 * (`now`, milliseconds since the epoch). No React here: the components in
 * `components/home/` only draw what these return.
 *
 * A finished match is one whose result is `win`, `loss` or `draw`. Every
 * timestamp is read through `lib/time.ts`'s `parseTimestamp`, which takes a
 * bare one as the log's local clock; weeks and days are the viewer's own.
 */
import type { ShellSettings } from '../bridge'
import type { TFunction } from '../i18n'
import type { DeckIdentityOut, LeakOut, Match, MetaPresence } from '../api'
import { parseTimestamp } from './time'

const HOUR = 3_600_000
const DAY = 24 * HOUR

/** A new session starts when a match starts more than this long after the
 *  one before it ended (its start, where it has no end). */
export const SESSION_GAP_MS = 3 * HOUR

/** How many matches Home asks for; a list this long may not reach back as
 *  far as a count needs. */
export const HOME_MATCH_LIMIT = 500

// Re-exported so importers need not change yet; the threshold lives in `lib/sample.ts` (plan 26, phase 10 removes this).
export { RATE_MIN_MATCHES } from './sample'

export type LiveState = 'down' | 'stopped' | 'match' | 'watching' | 'idle'

/** The status pill's state, the first that holds: the heartbeat failed, the
 *  watcher died on its own, a match is in progress, watching, not watching. */
export function liveState(input: {
  isError: boolean
  watcherStopped: boolean
  matchInProgress: boolean
  watching: boolean
}): LiveState {
  if (input.isError) return 'down'
  if (input.watcherStopped) return 'stopped'
  if (input.matchInProgress) return 'match'
  return input.watching ? 'watching' : 'idle'
}

export function isFinished(match: Match): boolean {
  return match.result === 'win' || match.result === 'loss' || match.result === 'draw'
}

/** A match's start, in ms; `null` for a row whose start cannot be read. */
export const startOf = (match: Match): number | null => parseTimestamp(match.started_at)

/** The matches finished and with a start, newest first. */
function finishedNewestFirst(matches: Match[]): Match[] {
  return matches
    .filter((match) => isFinished(match) && startOf(match) != null)
    .sort((a, b) => (startOf(b) ?? 0) - (startOf(a) ?? 0))
}

/** Every match with a start, newest first, finished or not. */
function newestFirst(matches: Match[]): Match[] {
  return matches.filter((match) => startOf(match) != null).sort((a, b) => (startOf(b) ?? 0) - (startOf(a) ?? 0))
}

export type Tally = { played: number; wins: number; losses: number; draws: number }

function tally(matches: Match[]): Tally {
  const out: Tally = { played: 0, wins: 0, losses: 0, draws: 0 }
  for (const match of matches) {
    if (!isFinished(match)) continue
    out.played += 1
    if (match.result === 'win') out.wins += 1
    else if (match.result === 'loss') out.losses += 1
    else out.draws += 1
  }
  return out
}

/* ------------------------------------------------------- detailed logs */

/** Whether Home asks the user to turn on Detailed Logs: they play Arena (a
 *  missing `plays` reads as both), the shell found or was given Arena's log,
 *  and doctor does not read the setting as on. */
export function detailedLogsNag(
  sources: Pick<ShellSettings['sources'], 'arenaLog'>,
  plays: ('arena' | 'mtgo')[] | undefined,
): boolean {
  const { path, detailedLogs } = sources.arenaLog
  return (plays ?? ['arena', 'mtgo']).includes('arena') && path !== null && detailedLogs !== 'enabled'
}

/* ------------------------------------------------------------ first run */

/** First run: no match from any source. */
export function isFirstRun(matches: Match[]): boolean {
  return matches.length === 0
}

export type StepState = 'done' | 'next' | 'later'

/** The three first-run steps, read from the heartbeat: watching, then one
 *  event or more, then a match (never done on that screen). The first step
 *  not done is the next one; any other not done is later. For a player of
 *  Magic Online alone (`mtgoOnly`) the second step is a folder being
 *  watched, since MTGO's events arrive only when a game ends. */
export function firstRunSteps(
  live: { watching: boolean; events: number; mtgo_watching?: boolean } | undefined,
  mtgoOnly = false,
): StepState[] {
  const second = mtgoOnly ? Boolean(live?.mtgo_watching) : (live?.events ?? 0) >= 1
  const done = [Boolean(live?.watching), second, false]
  const next = done.indexOf(false)
  return done.map((isDone, index) => (isDone ? 'done' : index === next ? 'next' : 'later'))
}

/** Whether the user plays Magic Online alone; a missing `plays` reads as
 *  both. */
export function mtgoOnly(plays: ('arena' | 'mtgo')[] | undefined): boolean {
  return plays !== undefined && plays.length === 1 && plays[0] === 'mtgo'
}

/* -------------------------------------------------------------- session */

export type Session = {
  /** The session's matches, newest first. */
  matches: Match[]
  /** When its first match started, in ms. */
  start: number
  tally: Tally
  /** The session's decks by name, the most played first (ties: the one
   *  played last first). A match with no deck adds none. */
  decks: { name: string | null; count: number }[]
}

/** The newest run of finished matches in which no match starts more than
 *  three hours after the one before it ended (its start, where it has no
 *  end). `null` with no finished match. */
export function lastSession(matches: Match[]): Session | null {
  const finished = finishedNewestFirst(matches)
  if (finished.length === 0) return null
  const run = [finished[0]]
  for (let i = 1; i < finished.length; i += 1) {
    const older = finished[i]
    const newerStart = startOf(run[run.length - 1]) ?? 0
    const olderEnd = parseTimestamp(older.ended_at) ?? startOf(older) ?? 0
    if (newerStart - olderEnd > SESSION_GAP_MS) break
    run.push(older)
  }

  const byName = new Map<string, { name: string | null; count: number; newest: number }>()
  run.forEach((match, index) => {
    if (match.deck_id == null) return
    const key = match.deck_name ?? ''
    const entry = byName.get(key) ?? { name: match.deck_name ?? null, count: 0, newest: index }
    entry.count += 1
    byName.set(key, entry)
  })
  const decks = [...byName.values()]
    .sort((a, b) => b.count - a.count || a.newest - b.newest)
    .map(({ name, count }) => ({ name, count }))

  return { matches: run, start: startOf(run[run.length - 1]) ?? 0, tally: tally(run), decks }
}

/** The headline's words: "15 wins, 10 losses", "1 win, 1 loss", "No wins,
 *  3 losses", "15 wins, no losses", ending ", 1 draw" or ", 2 draws" when
 *  there was one. */
export function sessionHeadline({ wins, losses, draws }: Tally, t: TFunction): string {
  const w = wins === 0 ? t('home.headline.noWins') : t('home.headline.wins', { count: wins })
  const l = losses === 0 ? t('home.headline.noLosses') : t('home.headline.losses', { count: losses })
  if (draws === 0) return t('home.headline.record', { wins: w, losses: l })
  return t('home.headline.recordWithDraws', { wins: w, losses: l, draws: t('home.headline.draws', { count: draws }) })
}

export type ThirtyDays = { played: number; won: number; losses: number; outsideSession: boolean }

/** The finished matches that started in the 30 days before `now`, and
 *  whether any of them is not part of the session. */
export function lastThirtyDays(matches: Match[], session: Session | null, now: number): ThirtyDays {
  const since = now - 30 * DAY
  const inSession = new Set(session?.matches.map((match) => match.match_id) ?? [])
  const recent = finishedNewestFirst(matches).filter((match) => (startOf(match) ?? 0) >= since)
  return {
    played: recent.length,
    won: recent.filter((match) => match.result === 'win').length,
    losses: recent.filter((match) => match.result === 'loss').length,
    outsideSession: recent.some((match) => !inSession.has(match.match_id)),
  }
}

/* ----------------------------------------------------------- opponents */

/** Whether the opponent's deck was named: by the classifier, the corpus or
 *  the viewer's own pick. `colors` is a deck known only by its colours and
 *  a card it showed; `unknown` is nothing seen. */
export function opponentNamed(match: Pick<Match, 'opponent_source'>): boolean {
  const source = match.opponent_source
  return source != null && source !== 'colors' && source !== 'unknown'
}

/** The newest finished match. */
export function lastFinished(matches: Match[]): Match | null {
  return finishedNewestFirst(matches)[0] ?? null
}

/** The eight newest matches, finished or not. */
export function recentMatches(matches: Match[], count = 8): Match[] {
  return newestFirst(matches).slice(0, count)
}

/** A score with the viewer's own games first: "1–2". `null` without one. */
export function ownScore(match: Pick<Match, 'games_won' | 'games_lost'>): string | null {
  if (match.games_won == null || match.games_lost == null) return null
  if (match.games_won === 0 && match.games_lost === 0) return null
  return `${match.games_won}–${match.games_lost}`
}

/** A score with the winner's games first, for a sentence: a loss 1–2 is
 *  "2–1". `null` without one. */
export function winnerScore(match: Pick<Match, 'games_won' | 'games_lost' | 'result'>): string | null {
  if (ownScore(match) == null) return null
  const won = match.games_won ?? 0
  const lost = match.games_lost ?? 0
  return match.result === 'loss' ? `${lost}–${won}` : `${won}–${lost}`
}

/* --------------------------------------------------------- three things */

export type ThingKind = 'match' | 'pattern' | 'field'

/** Which of Home's candidates fill its three cards, in order: the last
 *  match, the pattern, the field. Those that exist; fewer when fewer do,
 *  never a filler. */
export function threeThings(has: { match: boolean; pattern: boolean; field: boolean }): ThingKind[] {
  const order: ThingKind[] = []
  if (has.match) order.push('match')
  if (has.pattern) order.push('pattern')
  if (has.field) order.push('field')
  return order
}

/* -------------------------------------------------------------- pattern */

export type Pattern = { leak: LeakOut; wonWith: number; wonWithout: number }

/** The first pattern in the API's order that costs the viewer: its rate
 *  with it below its rate without. The counts of wins are the rates times
 *  the matches (`review/leaks.py`'s `with_wins / n_with`), rounded. */
export function firstPattern(leaks: LeakOut[]): Pattern | null {
  const leak = leaks.find((candidate) => candidate.win_rate_with < candidate.win_rate_without)
  if (!leak) return null
  return {
    leak,
    wonWith: Math.round(leak.n_with * leak.win_rate_with),
    wonWithout: Math.round(leak.n_without * leak.win_rate_without),
  }
}

/* ---------------------------------------------------------------- weeks */

export type Week = {
  /** The week's Monday at 00:00, the viewer's zone, in ms. */
  start: number
  played: number
  won: number
  /** Finished losses alone: a draw is in `played` and in neither `won` nor
   *  `losses`. */
  losses: number
  /** 0..1, over wins plus losses (a draw is in neither); `null` for a week
   *  with neither a win nor a loss. */
  rate: number | null
}

/** The Monday at 00:00 of the week `ms` falls in, the viewer's zone. */
export function weekStart(ms: number): number {
  const date = new Date(ms)
  // Back to Monday first, then its midnight: a day whose clock changes at
  // midnight has no 00:00, and setting the hours on it first would leave
  // the key at another hour of Monday than every other match's.
  date.setDate(date.getDate() - ((date.getDay() + 6) % 7))
  date.setHours(0, 0, 0, 0)
  return date.getTime()
}

/** The Monday `weeks` weeks from `weekMs`, at its own first hour, so one
 *  Monday with no midnight never shifts every week after it. */
function addWeeks(weekMs: number, weeks: number): number {
  const date = new Date(weekMs)
  date.setDate(date.getDate() + 7 * weeks)
  date.setHours(0, 0, 0, 0)
  return date.getTime()
}

export type Weeks = {
  /** From the first week with a finished match to the newest match's week,
   *  twelve at most; a week with none has a `null` rate. */
  weeks: Week[]
  /** Whether a week was left out because the list, full, cut it short. */
  truncated: boolean
}

/** Finished matches by the week they started in, the twelve weeks that end
 *  with the newest match's. When the list is full (`HOME_MATCH_LIMIT`),
 *  its oldest week holds only part of its matches, so that week and any
 *  before it are left out. Weeks before the first with a match are not
 *  drawn. */
export function weeklyWinrate(matches: Match[], listFull: boolean): Weeks {
  const finished = finishedNewestFirst(matches)
  if (finished.length === 0) return { weeks: [], truncated: false }

  const newest = weekStart(startOf(finished[0]) ?? 0)
  let first = addWeeks(newest, -11)
  let truncated = false
  if (listFull) {
    const oldestListed = newestFirst(matches).at(-1)
    const cut = weekStart(startOf(oldestListed ?? finished[finished.length - 1]) ?? 0)
    if (cut >= first) {
      first = addWeeks(cut, 1)
      truncated = true
    }
  }

  const weeks: Week[] = []
  for (let start = first; start <= newest; start = addWeeks(start, 1)) {
    weeks.push({ start, played: 0, won: 0, losses: 0, rate: null })
  }
  const index = new Map(weeks.map((week, i) => [week.start, i]))
  for (const match of finished) {
    const i = index.get(weekStart(startOf(match) ?? 0))
    if (i == null) continue
    weeks[i].played += 1
    if (match.result === 'win') weeks[i].won += 1
    else if (match.result === 'loss') weeks[i].losses += 1
  }
  for (const week of weeks) {
    const decided = week.won + week.losses
    week.rate = decided > 0 ? week.won / decided : null
  }

  const firstWithMatch = weeks.findIndex((week) => week.played > 0)
  return { weeks: firstWithMatch < 0 ? [] : weeks.slice(firstWithMatch), truncated }
}

/* ---------------------------------------------------------------- decks */

export type HomeDeck = {
  key: string
  name: string | null
  /** Finished matches, draws aside: `match_wins + match_losses`. */
  finished: number
  wins: number
  lastPlayed: number | null
  /** The identity's newest finished match in the list, for its art: a
   *  match's detail is read once, so never one still in progress. */
  artMatchId: string | null
}

/** One tile for a deck, not a version: five identities at most, those
 *  with the most matches in the 30 days before `now` first, then by last
 *  played; an identity with no match is left out. A tile links to the
 *  deck by its key (`lib/decks.ts`'s `deckAddress`). */
export function homeDecks(identities: DeckIdentityOut[], matches: Match[], now: number, count = 5): HomeDeck[] {
  const since = now - 30 * DAY
  const listed = newestFirst(matches)
  const finished = finishedNewestFirst(matches)
  const rows = identities
    .filter((identity) => identity.matches > 0)
    .map((identity) => {
      const ids = new Set(identity.deck_ids)
      const mine = listed.filter((match) => match.deck_id != null && ids.has(match.deck_id))
      const recent = mine.filter((match) => (startOf(match) ?? 0) >= since).length
      const deck: HomeDeck = {
        key: identity.key,
        name: identity.name ?? null,
        finished: identity.match_wins + identity.match_losses,
        wins: identity.match_wins,
        lastPlayed: parseTimestamp(identity.last_played),
        artMatchId: finished.find((match) => match.deck_id != null && ids.has(match.deck_id))?.match_id ?? null,
      }
      return { deck, recent }
    })
  return rows
    .sort((a, b) => b.recent - a.recent || (b.deck.lastPlayed ?? 0) - (a.deck.lastPlayed ?? 0))
    .slice(0, count)
    .map(({ deck }) => deck)
}

/* ---------------------------------------------------------------- field */

/** The corpus's four tiers, in rank order: paper tournaments of 64 or
 *  more players, MTGO challenges, MTGO leagues, smaller paper tournaments
 *  (`docs/metagame.md`, "The evidence tiers"). */
export type Tier = 'A' | 'B' | 'C' | 'D'

export const TIERS: readonly Tier[] = ['A', 'B', 'C', 'D']

/** Whether the tier has a list in the rows' window. */
export function hasLists(presence: MetaPresence[], tier: Tier): boolean {
  return presence.some((row) => row.tier === tier && row.decks > 0)
}

/** The first tier in rank order with lists in the window, A, then B, then
 *  C, then D; `null` when none has any. Home and the Field page's default
 *  share both read the field from it. A league (C) still comes before a
 *  smaller paper event (D), though its lists are only its undefeated
 *  decks: the rank says which tier is shown first, not what it may say. */
export function firstTierWithLists(presence: MetaPresence[]): Tier | null {
  return TIERS.find((tier) => hasLists(presence, tier)) ?? null
}

/** `losses` is the finished losses alone: a draw is in `played` and in
 *  neither `won` nor `losses`. */
export type FieldRecord = { played: number; won: number; losses: number }

export type FieldRow = { presence: MetaPresence; record: FieldRecord }

export type Field = {
  tier: Tier
  /** Six at most, the most played first. */
  rows: FieldRow[]
  /** Every list of the tier in the window, not only the rows'. */
  lists: number
  /** The window's start, in ms. */
  windowStart: number
  /** The format's reset the window starts at, a bare date; `null` when the
   *  window is the last 90 days. */
  reset: string | null
  /** The format the field and the records are of. */
  format: string
  /** The deck of the newest match in that format that has one, which the
   *  records are for; `null` when no match in the format has a deck, and
   *  the records are then every deck's in the format. */
  deck: { name: string | null; deckIds: Set<string> } | null
  /** The two decks together: every finished match in the window and the
   *  format against either, for the same deck. */
  topTwo: FieldRecord
  /** The list is full and does not reach back to the window's start. */
  listShort: boolean
  /** The viewer's newest finished match in the format against the first
   *  row's deck, for its art (never one in progress: its detail is read once). */
  artMatchId: string | null
}

/** The window's start: the format's reset (a bare date, taken at the
 *  viewer's local midnight, since match starts are the log's local clock),
 *  else 90 days before `now`. */
export function fieldWindowStart(resetStart: string | null, now: number): number {
  const parts = resetStart ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(resetStart) : null
  if (parts) return new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3])).getTime()
  return now - 90 * DAY
}

const archetypeKey = (presence: MetaPresence) => `archetype:${presence.archetype_key}`

/** One deck of the field as a match names its opponent: the classifier's
 *  key (`archetype:<key>` in a match's `opponent_key`) and its label
 *  (`opponent_label`). A key alone is not a deck: one key holds several
 *  labels ("Control" holds Jeskai Control and Sultai Control). */
export type FieldPair = Pick<MetaPresence, 'archetype_key' | 'label'>

const pairOf = (key: string, label: string) => `${key}\n${label}`

/** The viewer's record against the decks `pairs` names, each by its key and
 *  its label together: every finished match that started at `windowStart`
 *  or later, and, when `deckIds` is given, was played with one of them.
 *  Home and Field count a record this one way. */
export function recordAgainst(
  matches: Match[],
  pairs: readonly FieldPair[],
  windowStart: number,
  deckIds: Set<string> | null = null,
): FieldRecord {
  const wanted = new Set(pairs.map((pair) => pairOf(`archetype:${pair.archetype_key}`, pair.label)))
  const against = matches.filter(
    (match) =>
      isFinished(match) &&
      (startOf(match) ?? -Infinity) >= windowStart &&
      (deckIds == null || (match.deck_id != null && deckIds.has(match.deck_id))) &&
      match.opponent_key != null &&
      match.opponent_label != null &&
      wanted.has(pairOf(match.opponent_key, match.opponent_label)),
  )
  return {
    played: against.length,
    won: against.filter((match) => match.result === 'win').length,
    losses: against.filter((match) => match.result === 'loss').length,
  }
}

/** The matches played in `format`; a match with no format counts toward
 *  none (D14). */
export function matchesInFormat(matches: Match[], format: string): Match[] {
  return matches.filter((match) => match.format === format)
}

/** The field from the first tier in rank order with lists in the window
 *  (`firstTierWithLists`: A, then B, then C, then D, the Field page's
 *  default share too), and the viewer's record against each deck in the
 *  same window and format, with the deck of the newest match in the format
 *  that has one. `null` with no lists in any tier. */
export function homeField(
  presence: MetaPresence[],
  matches: Match[],
  identities: DeckIdentityOut[],
  resetStart: string | null,
  listFull: boolean,
  now: number,
  format: string,
  count = 6,
): Field | null {
  const tier = firstTierWithLists(presence)
  if (tier == null) return null
  const ofTier = presence.filter((row) => row.tier === tier && row.decks > 0).sort((a, b) => b.decks - a.decks)
  const windowStart = fieldWindowStart(resetStart, now)

  // Only the field's own format: `listShort` below reads the whole list,
  // since the fetch cap applies to it.
  const inFormat = matchesInFormat(matches, format)
  const listed = newestFirst(matches)
  const withDeck = newestFirst(inFormat).find((match) => match.deck_id != null)
  let deck: Field['deck'] = null
  if (withDeck?.deck_id) {
    const identity = identities.find((candidate) => candidate.deck_ids.includes(withDeck.deck_id ?? ''))
    deck = {
      name: identity ? (identity.name ?? null) : (withDeck.deck_name ?? null),
      deckIds: new Set(identity ? identity.deck_ids : [withDeck.deck_id]),
    }
  }

  const record = (pairs: FieldPair[]): FieldRecord =>
    recordAgainst(inFormat, pairs, windowStart, deck ? deck.deckIds : null)

  const rows = ofTier.slice(0, count).map((row) => ({ presence: row, record: record([row]) }))
  const oldest = listed.at(-1)
  const firstKey = rows[0] ? archetypeKey(rows[0].presence) : null
  return {
    tier,
    rows,
    lists: ofTier.reduce((sum, row) => sum + row.decks, 0),
    windowStart,
    reset: resetStart && /^\d{4}-\d{2}-\d{2}$/.test(resetStart) ? resetStart : null,
    format,
    deck,
    topTwo: record(rows.slice(0, 2).map((row) => row.presence)),
    listShort: listFull && oldest != null && (startOf(oldest) ?? 0) > windowStart,
    artMatchId: firstKey
      ? (finishedNewestFirst(inFormat).find(
          (match) => match.opponent_key === firstKey && match.opponent_label === rows[0].presence.label,
        )?.match_id ?? null)
      : null,
  }
}
