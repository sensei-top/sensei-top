/**
 * What a pairing's page reads (`/decks/:id/matchups/:opponent`: one deck
 * against one opponent's deck, `?format=` one format's matches), as pure
 * functions of the API's rows and a clock. The opponent is a Matchups row's
 * `opponent_key`, the format its format when known, and the page counts the
 * matches in hand against it as Matchups does, so a pairing reached from a
 * row of a known format has that row's numbers.
 */
import type { CoverageOut, CoverageRowOut, Match, MatchupBriefOut } from '../api'
import type { TFunction } from '../i18n'
import { mergeNewestFirst } from './deckOverview'
import { addressSegment, archetypeName, deckAddress } from './decks'
import {
  archetypeKeyOf,
  type FieldRecord,
  matchupName,
  type MatchupRow,
  opponentSeen,
  type TileText,
} from './matchups'
import { formatPercent, formatRecord } from './format'
import { MIN_TRUSTED_FIELD_SAMPLE, rateOrRecord } from './sample'
import { ago, formatCount } from './time'

/** A pairing's page: the deck's address, `/matchups/`, and the opponent's
 *  key spelled in one segment (`addressSegment`: encoded, the colon bare,
 *  a `/` as `%2F`); with a format, `?format=` carrying it, and with none
 *  (`null`, or not given) every format's. */
export function pairingAddress(deckKey: string, opponentKey: string, format?: string | null): string {
  const address = `${deckAddress(deckKey)}/matchups/${addressSegment(opponentKey)}`
  return format ? `${address}?${new URLSearchParams({ format })}` : address
}

/** `address` carrying the version the address chose, `?version=` (after
 *  any parameter `address` already has), as the deck's tabs carry it;
 *  `address` unchanged for every version. */
export function withVersion(address: string, version: string | null): string {
  if (!version) return address
  return `${address}${address.includes('?') ? '&' : '?'}${new URLSearchParams({ version })}`
}

/** The matches against `opponentKey` over every version's list, finished
 *  or not, newest first (a match whose start cannot be read last). A key
 *  is compared as Matchups groups it, a missing key as the empty one. With
 *  a `format`, the address's `?format=`, only the matches played in it,
 *  compared exactly, so a format no match has keeps none; with `null`,
 *  every format's. */
export function pairingMatches(opponentKey: string, lists: Match[][], format: string | null = null): Match[] {
  return mergeNewestFirst(lists).filter(
    (match) => (match.opponent_key ?? '') === opponentKey && (format == null || match.format === format),
  )
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
export function pairingHeading(
  opponentKey: string,
  matches: Match[],
  label: string | null | undefined,
  t: TFunction,
): PairingHeading {
  if (matches.length > 0) {
    const seen = opponentSeen(mergeNewestFirst([matches]))
    const { name, showed } = matchupName(seen, t)
    return { name, showed, muted: seen.kind === 'unknown', colors: seen.colors }
  }
  const archetype = archetypeKeyOf(opponentKey)
  if (archetype != null) return { name: label || archetypeName(archetype), showed: null, muted: false, colors: null }
  if (opponentKey.startsWith('manual:')) {
    return { name: opponentKey.slice('manual:'.length), showed: null, muted: false, colors: null }
  }
  if (opponentKey.startsWith('colors:')) {
    return { name: t('matchups.name.unrecognized'), showed: null, muted: false, colors: null }
  }
  return { name: t('common.unknownDeck'), showed: null, muted: true, colors: null }
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
  | { kind: 'format_unknown'; archetype: string }
  | { kind: 'cannot_write'; archetype: string }
  | { kind: 'not_written'; archetype: string }

/** Which state the brief against `opponentKey` is in, from the deck's
 *  coverage and its stored briefs, both joined on X of `archetype:X`
 *  compared exactly. A key that is not `archetype:X` is not named. A brief
 *  stored for X is written, and stale only when coverage's row for X says
 *  `stale` (the briefs carry no flag of their own), and wins over an
 *  unknown format because it is the user's authored artifact; with no
 *  brief, a deck whose format is unknown (coverage's `fmt` null) has no
 *  field to write from, said before any row is read; a row `no_consensus`
 *  cannot be written, and a row `missing`, or no row, is not written yet. */
export function briefState(opponentKey: string, coverage: CoverageOut, briefs: MatchupBriefOut[]): BriefState {
  const archetype = archetypeKeyOf(opponentKey)
  if (archetype == null) return { kind: 'not_named' }
  const row = coverageRowOf(opponentKey, coverage)
  const brief = briefs.find((b) => b.archetype_key === archetype)
  if (brief) return { kind: 'written', archetype, brief, stale: row?.status === 'stale' }
  if (coverage.fmt === null) return { kind: 'format_unknown', archetype }
  if (row?.status === 'no_consensus') return { kind: 'cannot_write', archetype }
  return { kind: 'not_written', archetype }
}

/** "Last met 3d ago", from the newest of `matches` whose start can be
 *  read; `null` when none can. */
export function lastMetLine(matches: Match[], now: number, t: TFunction): string | null {
  const since = ago(mergeNewestFirst([matches])[0]?.started_at, now)
  return since ? t('matchups.pairing.lastMet', { since }) : null
}

/** The last tile: how the opponent's archetype wins in the field's
 *  tournaments, joined on its archetype key (`archetypeKeyOf`). A key that
 *  is not a named archetype has nothing to join; a named one the field has
 *  no rate for says so; under five entries (`MIN_TRUSTED_FIELD_SAMPLE`) the
 *  rate is said to be too few to trust. */
function fieldTile(opponentKey: string, fieldByKey: Map<string, FieldRecord>, t: TFunction): TileText {
  const label = t('matchups.pairing.inTournaments')
  const archetype = archetypeKeyOf(opponentKey)
  if (archetype == null) return { label, value: '—', detail: t('matchups.pairing.onlyNamed') }
  const field = fieldByKey.get(archetype)
  if (field == null || field.winrate == null) return { label, value: '—', detail: t('matchups.pairing.noResults') }
  const values = { count: field.entries, n: formatCount(field.entries) }
  return {
    label,
    value: formatPercent(field.winrate),
    detail:
      field.entries < MIN_TRUSTED_FIELD_SAMPLE
        ? t('matchups.pairing.wonInTournamentsThin', values)
        : t('matchups.pairing.wonInTournaments', values),
  }
}

/** What a pairing's tile says: `muted` is a record drawn muted, too few
 *  for a rate. */
export type PairingTileText = TileText & { muted?: boolean }

/** The tile of one split of the best-of-three games, Game 1 or Post-board,
 *  drawn as Record is (`rateOrRecord`, over games), a drawn game in
 *  neither number. */
function splitTile(label: string, wins: number, losses: number, t: TFunction): PairingTileText {
  const { figure, line, thin } = rateOrRecord({ wins, losses }, t, 'games')
  const tile: PairingTileText = { label, value: figure ?? '—', detail: line }
  if (thin) tile.muted = true
  return tile
}

/** The tiles over the pairing's row (`matchupRowOver`, over its finished
 *  matches: wins, losses and draws, a draw neither won nor lost): three,
 *  or five when the row has a best-of-three match (`bo3Matches`). Record,
 *  as Matchups rates the same row (`rateOrRecord` over `won` and `lost`):
 *  from ten won or lost the rate (a draw is not one of the ten), "73%",
 *  over the record "8–3"; five to nine the rate, "71%", muted, over the
 *  record and "rough"; under five the record, "3–1", muted, over the
 *  "too few" line. Games: own first, "17–4". Then, with a best-of-three
 *  match, Game 1 and Post-board (`splitTile`), the split the Matchups row's
 *  two columns show. Last, In tournaments: `fieldTile` over `fieldByKey`,
 *  the field's records by archetype key, empty while they load or when
 *  they fail. */
export function pairingTiles(
  row: MatchupRow,
  fieldByKey: Map<string, FieldRecord>,
  t: TFunction,
): PairingTileText[] {
  const { figure, line, thin } = rateOrRecord({ wins: row.won, losses: row.lost }, t)
  const record: PairingTileText = { label: t('matchups.pairing.record'), value: figure ?? '—', detail: line }
  if (thin) record.muted = true
  const games: PairingTileText = {
    label: t('matchups.pairing.games'),
    value: formatRecord(row.gamesWon, row.gamesLost),
    detail: t('matchups.pairing.yoursFirst'),
  }
  const split =
    row.bo3Matches > 0
      ? [
          splitTile(t('matchups.pairing.game1'), row.game1Won, row.game1Lost, t),
          splitTile(t('matchups.pairing.postboard'), row.postboardWon, row.postboardLost, t),
        ]
      : []
  return [record, games, ...split, fieldTile(row.key, fieldByKey, t)]
}
