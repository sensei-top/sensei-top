import type { CoverageOut, CoveragePromptOut, CoverageRowOut, CurrentMatch } from '../api'
import { archetypeName } from './decks'
import { NBSP, type TileText } from './matchups'
import { formatCount, formatPercent } from './time'

/** A row a prompt can close: its brief `missing` or `stale`. A row
 *  `no_consensus` is not one: too few tournament lists to write from. */
export function isCoverageGap(row: CoverageRowOut): boolean {
  return row.status === 'missing' || row.status === 'stale'
}

/** A coverage row's archetype by name: its label, `archetypeName` of its
 *  key when it has none. */
export function coverageName(row: CoverageRowOut): string {
  return row.label || archetypeName(row.archetype_key)
}

const STATUS_WORDS: Record<string, string> = {
  ok: 'Written',
  stale: 'Out of date',
  missing: 'Not written',
  no_consensus: 'Too few lists',
}

/** A coverage row's status as the word on its chip; a status not known
 *  here as sent. */
export function coverageStatusWord(status: string): string {
  return STATUS_WORDS[status] ?? status
}

/** The three tiles over a deck's coverage. Matches covered: the share of
 *  the matches against a named archetype whose archetype has an
 *  up-to-date brief, or none when there is no such match
 *  (`matches_covered` null). Field covered: the field's share with an
 *  up-to-date brief, or none when no row knows its share of the field.
 *  To write: the rows a prompt can close (`isCoverageGap`) of every row,
 *  and how many more have too few lists. A word after a count is singular
 *  when that count is one: "1 of 1 match" (the denominator's count), "of 1
 *  archetype", "1 more has". */
export function coverageTiles(coverage: CoverageOut): [TileText, TileText, TileText] {
  const matches: TileText =
    coverage.matches_covered == null
      ? { label: 'Matches covered', value: '—', detail: 'no match against a named archetype yet' }
      : {
          label: 'Matches covered',
          value: `${formatPercent(coverage.matches_covered)}%`,
          detail:
            `${formatCount(coverage.matches_covered_numerator)} of ` +
            `${formatCount(coverage.matches_covered_denominator)}${NBSP}` +
            `${coverage.matches_covered_denominator === 1 ? 'match' : 'matches'} against a named archetype`,
        }
  const field: TileText = coverage.rows.every((row) => row.field_share == null)
    ? { label: 'Field covered', value: '—', detail: 'no tournament results yet' }
    : {
        label: 'Field covered',
        value: `${formatPercent(coverage.field_covered)}%`,
        detail: 'of tournament decks have an up-to-date brief',
      }
  const gaps = coverage.rows.filter(isCoverageGap).length
  const unwritable = coverage.rows.filter((row) => row.status === 'no_consensus').length
  const of = `of ${formatCount(coverage.rows.length)}${NBSP}${coverage.rows.length === 1 ? 'archetype' : 'archetypes'}`
  const more = `${formatCount(unwritable)}${NBSP}more ${unwritable === 1 ? 'has' : 'have'} too few lists`
  const toWrite: TileText = {
    label: 'To write',
    value: formatCount(gaps),
    detail: unwritable > 0 ? `${of}; ${more}` : of,
  }
  return [matches, field, toWrite]
}

/** The notes under the prompt for every gap: the archetypes it left out
 *  for too few lists, then those left for the next prompt, each key named
 *  by its coverage row (`coverageName`) and by `archetypeName(key)` when
 *  it has no row; names joined by ", ". A list with no key has no note. */
export function coveragePromptNotes(
  prompt: Pick<CoveragePromptOut, 'no_consensus' | 'deferred'>,
  rows: CoverageRowOut[],
): string[] {
  const byKey = new Map(rows.map((row) => [row.archetype_key, row]))
  const names = (keys: string[]) =>
    keys
      .map((key) => {
        const row = byKey.get(key)
        return row ? coverageName(row) : archetypeName(key)
      })
      .join(', ')
  const notes: string[] = []
  if (prompt.no_consensus.length > 0) notes.push(`Too few lists to write: ${names(prompt.no_consensus)}.`)
  if (prompt.deferred.length > 0) {
    notes.push(`Left for the next prompt: ${names(prompt.deferred)}. Save this answer, then build it again.`)
  }
  return notes
}

/** How old a timestamp is, in the same coarse day/hour granularity the rest
 *  of the dashboard uses for "when was this last generated" (see
 *  the Guide's export panel). Briefs are written once per (deck, archetype)
 *  and reused across matches, so this is often the only clue a reader has
 *  that the card in front of them predates today's opponent by weeks.
 *  Exported: SideboardPlanCard's own provenance footer (the break card)
 *  reuses this for the exact same reason. */
export function ageText(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const hours = ms / 3_600_000
  if (hours < 1) return 'just now'
  if (hours < 24) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}

/** Opponent card names actually revealed this match — the same set
 *  BriefBody strikes a play-around card through once it has shown up, the
 *  trick OpponentHandCard uses for its own revealed-card chips. Exported so
 *  SideboardPlanCard's break-phase play-around list uses the identical
 *  rule rather than a second copy of it. */
export function seenOpponentCards(match: CurrentMatch | null | undefined): Set<string> {
  return new Set(
    (match?.cards ?? [])
      .filter((c) => !c.is_self && c.card_name)
      .map((c) => c.card_name as string)
  )
}
