import type { CoverageOut, CoveragePromptOut, CoverageRowOut, CurrentMatch } from '../api'
import type { TFunction } from '../i18n'
import { archetypeName } from './decks'
import type { TileText } from './matchups'
import { formatList, formatPercent } from './format'
import { formatCount, parseTimestamp } from './time'

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

/** A coverage row's status as the word on its chip; a status not known
 *  here as sent. */
export function coverageStatusWord(status: string, t: TFunction): string {
  switch (status) {
    case 'ok':
      return t('matchups.coverage.status.ok')
    case 'stale':
      return t('matchups.coverage.status.stale')
    case 'missing':
      return t('matchups.coverage.status.missing')
    case 'no_consensus':
      return t('matchups.coverage.status.noConsensus')
    default:
      return status
  }
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
export function coverageTiles(coverage: CoverageOut, t: TFunction): [TileText, TileText, TileText] {
  const matches: TileText =
    coverage.matches_covered == null
      ? {
          label: t('matchups.coverage.tiles.matchesCovered'),
          value: '—',
          detail: t('matchups.coverage.tiles.noNamedMatch'),
        }
      : {
          label: t('matchups.coverage.tiles.matchesCovered'),
          value: formatPercent(coverage.matches_covered),
          detail: t('matchups.coverage.tiles.matchesDetail', {
            count: coverage.matches_covered_denominator,
            covered: formatCount(coverage.matches_covered_numerator),
            n: formatCount(coverage.matches_covered_denominator),
          }),
        }
  const field: TileText = coverage.rows.every((row) => row.field_share == null)
    ? {
        label: t('matchups.coverage.tiles.fieldCovered'),
        value: '—',
        detail: t('matchups.coverage.tiles.noResults'),
      }
    : {
        label: t('matchups.coverage.tiles.fieldCovered'),
        value: formatPercent(coverage.field_covered),
        detail: t('matchups.coverage.tiles.fieldDetail'),
      }
  const gaps = coverage.rows.filter(isCoverageGap).length
  const unwritable = coverage.rows.filter((row) => row.status === 'no_consensus').length
  const of = t('matchups.coverage.tiles.ofArchetypes', {
    count: coverage.rows.length,
    n: formatCount(coverage.rows.length),
  })
  const more = t('matchups.coverage.tiles.moreTooFew', { count: unwritable, n: formatCount(unwritable) })
  const toWrite: TileText = {
    label: t('matchups.coverage.tiles.toWrite'),
    value: formatCount(gaps),
    detail: unwritable > 0 ? t('matchups.coverage.tiles.ofWithMore', { of, more }) : of,
  }
  return [matches, field, toWrite]
}

/** The notes under the prompt for every gap: the archetypes it left out
 *  for too few lists, then those left for the next prompt, each key named
 *  by its coverage row (`coverageName`) and by `archetypeName(key)` when
 *  it has no row; names joined as a list in the language read. A list with no key has no note. */
export function coveragePromptNotes(
  prompt: Pick<CoveragePromptOut, 'no_consensus' | 'deferred'>,
  rows: CoverageRowOut[],
  t: TFunction,
): string[] {
  const byKey = new Map(rows.map((row) => [row.archetype_key, row]))
  const names = (keys: string[]) =>
    formatList(
      keys.map((key) => {
        const row = byKey.get(key)
        return row ? coverageName(row) : archetypeName(key)
      }),
    )
  const notes: string[] = []
  if (prompt.no_consensus.length > 0) {
    notes.push(t('matchups.coverage.notes.tooFew', { names: names(prompt.no_consensus) }))
  }
  if (prompt.deferred.length > 0) {
    notes.push(t('matchups.coverage.notes.deferred', { names: names(prompt.deferred) }))
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
export function ageText(iso: string, t: TFunction): string {
  const ms = Date.now() - (parseTimestamp(iso) ?? Number.NaN)
  const hours = ms / 3_600_000
  if (hours < 1) return t('matchups.age.now')
  if (hours < 24) return t('matchups.age.hours', { count: Math.round(hours) })
  return t('matchups.age.days', { count: Math.round(hours / 24) })
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
