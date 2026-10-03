/**
 * What a pairing's page reads (`/decks/:id/matchups/:opponent`: one deck
 * against one opponent's deck), as pure functions of the API's rows and a
 * clock. The opponent is a Matchups row's `opponent_key`, and the page
 * counts the matches in hand against it as Matchups does, so a pairing's
 * numbers equal its row there.
 */
import type { CoverageOut, CoverageRowOut, Match, MatchupBriefOut } from '../api'
import { MIN_TRUSTED_FIELD_SAMPLE } from '../theme'
import { mergeNewestFirst } from './deckOverview'
import { addressSegment, archetypeName, deckAddress } from './decks'
import { RATE_MIN_MATCHES } from './home'
import {
  archetypeKeyOf,
  type FieldRecord,
  matchupName,
  type MatchupRow,
  NBSP,
  opponentSeen,
  type TileText,
} from './matchups'
import { ago, formatCount, formatPercent } from './time'

/** A pairing's page: the deck's address, `/matchups/`, and the opponent's
 *  key spelled in one segment (`addressSegment`: encoded, the colon bare,
 *  a `/` as `%2F`). */
export function pairingAddress(deckKey: string, opponentKey: string): string {
  return `${deckAddress(deckKey)}/matchups/${addressSegment(opponentKey)}`
}

/** `address` carrying the version the address chose, `?version=`, as the
 *  deck's tabs carry it; `address` unchanged for every version. */
export function withVersion(address: string, version: string | null): string {
  return version ? `${address}?${new URLSearchParams({ version })}` : address
}

/** The matches against `opponentKey` over every version's list, finished
 *  or not, newest first (a match whose start cannot be read last). A key
 *  is compared as Matchups groups it, a missing key as the empty one. */
export function pairingMatches(opponentKey: string, lists: Match[][]): Match[] {
  return mergeNewestFirst(lists).filter((match) => (match.opponent_key ?? '') === opponentKey)
}

/** The pairing's heading: `name` in the `h3`, muted for an unknown deck;
 *  `showed` under it for a deck known by its colours and a card; the
 *  colours' pips beside the name, `null` for none. */
export type PairingHeading = { name: string; showed: string | null; muted: boolean; colors: string | null }

/** The heading over `matches`, every match against `opponentKey` finished
 *  or not (`pairingMatches`): the kind and label of the newest and the
 *  colours most of them showed (`opponentSeen`), drawn as a Matchups row
 *  draws them (`matchupName`). With no match, from the key alone and with
 *  no colours: `archetype:X` named by `label`, coverage's label for X,
 *  when given, and `archetypeName(X)` otherwise; `manual:X` named X as
 *  typed, `colors:…` an unrecognized deck with no `showed` line, and
 *  anything else an unknown deck. */
export function pairingHeading(opponentKey: string, matches: Match[], label?: string | null): PairingHeading {
  if (matches.length > 0) {
    const seen = opponentSeen(mergeNewestFirst([matches]))
    const { name, showed } = matchupName(seen)
    return { name, showed, muted: seen.kind === 'unknown', colors: seen.colors }
  }
  const archetype = archetypeKeyOf(opponentKey)
  if (archetype != null) return { name: label || archetypeName(archetype), showed: null, muted: false, colors: null }
  if (opponentKey.startsWith('manual:')) {
    return { name: opponentKey.slice('manual:'.length), showed: null, muted: false, colors: null }
  }
  if (opponentKey.startsWith('colors:')) return { name: 'Unrecognized deck', showed: null, muted: false, colors: null }
  return { name: 'Unknown deck', showed: null, muted: true, colors: null }
}

/** Coverage's row for `opponentKey`'s archetype (`archetypeKeyOf`),
 *  compared exactly; `null` for a key that is not `archetype:X` or an X
 *  coverage has no row for. */
export function coverageRowOf(opponentKey: string, coverage: CoverageOut): CoverageRowOut | null {
  const archetype = archetypeKeyOf(opponentKey)
  if (archetype == null) return null
  return coverage.rows.find((row) => row.archetype_key === archetype) ?? null
}

/** What a pairing's brief card draws. `archetype` is X of `archetype:X`,
 *  as the API spells it. */
export type BriefState =
  | { kind: 'not_named' }
  | { kind: 'written'; archetype: string; brief: MatchupBriefOut; stale: boolean }
  | { kind: 'cannot_write'; archetype: string }
  | { kind: 'not_written'; archetype: string }

/** Which state the brief against `opponentKey` is in, from the deck's
 *  coverage and its stored briefs, both joined on X of `archetype:X`
 *  compared exactly. A key that is not `archetype:X` is not named. A brief
 *  stored for X is written, and stale only when coverage's row for X says
 *  `stale` (the briefs carry no flag of their own); with no brief, a row
 *  `no_consensus` cannot be written, and a row `missing`, or no row, is
 *  not written yet. */
export function briefState(opponentKey: string, coverage: CoverageOut, briefs: MatchupBriefOut[]): BriefState {
  const archetype = archetypeKeyOf(opponentKey)
  if (archetype == null) return { kind: 'not_named' }
  const row = coverageRowOf(opponentKey, coverage)
  const brief = briefs.find((b) => b.archetype_key === archetype)
  if (brief) return { kind: 'written', archetype, brief, stale: row?.status === 'stale' }
  if (row?.status === 'no_consensus') return { kind: 'cannot_write', archetype }
  return { kind: 'not_written', archetype }
}

/** "Last met 3d ago", from the newest of `matches` whose start can be
 *  read; `null` when none can. */
export function lastMetLine(matches: Match[], now: number): string | null {
  const since = ago(mergeNewestFirst([matches])[0]?.started_at, now)
  return since ? `Last met ${since}` : null
}

/** The third tile: how the opponent's archetype wins in the field's
 *  tournaments, joined on its archetype key (`archetypeKeyOf`). A key that
 *  is not a named archetype has nothing to join; a named one the field has
 *  no rate for says so; under five entries (`MIN_TRUSTED_FIELD_SAMPLE`) the
 *  rate is said to be too few to trust. */
function fieldTile(opponentKey: string, fieldByKey: Map<string, FieldRecord>): TileText {
  const label = 'In tournaments'
  const archetype = archetypeKeyOf(opponentKey)
  if (archetype == null) return { label, value: '—', detail: 'only a named archetype has results' }
  const field = fieldByKey.get(archetype)
  if (field == null || field.winrate == null) return { label, value: '—', detail: 'no tournament results for it' }
  const entries = `${formatCount(field.entries)}${NBSP}${field.entries === 1 ? 'entry' : 'entries'}`
  const thin = field.entries < MIN_TRUSTED_FIELD_SAMPLE ? ', too few to trust' : ''
  return { label, value: `${formatPercent(field.winrate)}%`, detail: `won in tournaments, ${entries}${thin}` }
}

/** The three tiles over the pairing's row of `matchupRows` (its finished
 *  matches: wins, losses and draws, a draw a match and not a win). Record:
 *  from ten matches (`RATE_MIN_MATCHES`) the rate, "73%" and "won 8 of 11";
 *  under it the count, "7 of 9" and "matches won". Games: own first,
 *  "17–4". In tournaments: `fieldTile` over `fieldByKey`, the field's
 *  records by archetype key, empty while they load or when they fail. */
export function pairingTiles(row: MatchupRow, fieldByKey: Map<string, FieldRecord>): [TileText, TileText, TileText] {
  const record: TileText =
    row.matches >= RATE_MIN_MATCHES
      ? {
          label: 'Record',
          value: `${formatPercent(row.won / row.matches)}%`,
          detail: `won ${formatCount(row.won)} of ${formatCount(row.matches)}`,
        }
      : { label: 'Record', value: `${formatCount(row.won)} of ${formatCount(row.matches)}`, detail: 'matches won' }
  const games: TileText = {
    label: 'Games',
    value: `${formatCount(row.gamesWon)}–${formatCount(row.gamesLost)}`,
    detail: 'yours first',
  }
  return [record, games, fieldTile(row.key, fieldByKey)]
}
