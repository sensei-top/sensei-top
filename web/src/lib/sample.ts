import type { TFunction } from '../i18n'
import { formatPercent, formatRecord } from './format'

/** Personal records: from this many finished matches (or games, for a games
 *  figure) a figure is a rate; under it, a record. One threshold for all of
 *  the user's own play. */
export const RATE_MIN_MATCHES = 10

/** Personal records: from this many finished, under `RATE_MIN_MATCHES`, the
 *  rate is shown but drawn muted, a rough rate; under it, no rate at all.
 *  Only where a figure can be drawn muted (a tile, a table cell): the
 *  one-line form and a sentence keep `RATE_MIN_MATCHES` alone. */
export const ROUGH_RATE_MIN = 5

/** Field (corpus) evidence: below this many corpus entries (tournament
 *  decks, matches), a field-derived rate is real but too thin to trust as a
 *  measurement. It measures other people's lists, not the user's play, so it
 *  keeps its own threshold (docs/metagame.md, the evidence tiers). */
export const MIN_TRUSTED_FIELD_SAMPLE = 5

/** Field (corpus) evidence: the fewest matches an archetype's win rate needs
 *  in the corpus before it is shown at all (docs/metagame.md). */
export const WINRATE_MIN_MATCHES = 2

/** A tile's figure and the line under it. `thin` is a record drawn muted
 *  because there are too few for a rate. */
export type RateOrRecord = { figure: string | null; line: string; thin: boolean }

/** A personal record, by the small-sample rule. Ten or more finished
 *  (`RATE_MIN_MATCHES`): the rate as the figure, the record as the line.
 *  Five to nine (`ROUGH_RATE_MIN`): the rate as the figure, `thin`, the
 *  record and "rough" as the line. One to four: the record as the figure,
 *  the "too few" line, `thin`. None: no figure, and the "no finished ..."
 *  line. The caller passes losses with
 *  draws left out (`docs/design-system.md`, "Numbers"), so the threshold and
 *  the rate are over wins plus losses. `unit` picks the words, matches or
 *  games. */
export function rateOrRecord(
  { wins, losses }: { wins: number; losses: number },
  t: TFunction,
  unit: 'matches' | 'games' = 'matches',
): RateOrRecord {
  const finished = wins + losses
  const record = formatRecord(wins, losses)
  if (finished >= RATE_MIN_MATCHES) {
    return { figure: formatPercent(wins / finished), line: record, thin: false }
  }
  if (finished >= ROUGH_RATE_MIN) {
    const key = unit === 'games' ? 'common.sample.roughGames' : 'common.sample.roughMatches'
    return { figure: formatPercent(wins / finished), line: t(key, { record, min: RATE_MIN_MATCHES }), thin: true }
  }
  if (finished > 0) {
    const key = unit === 'games' ? 'common.sample.tooFewGames' : 'common.sample.tooFewMatches'
    return { figure: record, line: t(key, { min: ROUGH_RATE_MIN }), thin: true }
  }
  return { figure: null, line: t(unit === 'games' ? 'common.sample.noGame' : 'common.sample.noMatch'), thin: false }
}

/** A table's Rate cell, by the same rule: from ten the rate; five to nine
 *  the rate, `muted`; one to four the "too few" word, `muted`; `null` with
 *  none won or lost, which the caller draws as its em dash. */
export function rateCell(
  { wins, losses }: { wins: number; losses: number },
  t: TFunction,
  unit: 'matches' | 'games' = 'matches',
): { text: string; muted: boolean } | null {
  const finished = wins + losses
  if (finished <= 0) return null
  if (finished >= ROUGH_RATE_MIN) return { text: formatPercent(wins / finished), muted: finished < RATE_MIN_MATCHES }
  return { text: t(unit === 'games' ? 'common.sample.tooFewCellGames' : 'common.sample.tooFewCellMatches'), muted: true }
}

/** The one-line form, for a place with room for nothing else: ten or more
 *  "58% · 35–25"; one to nine the record alone, "6–3"; none, `null`. */
export function rateAndRecordLine({ wins, losses }: { wins: number; losses: number }): string | null {
  const finished = wins + losses
  if (finished <= 0) return null
  const record = formatRecord(wins, losses)
  return finished >= RATE_MIN_MATCHES ? `${formatPercent(wins / finished)} · ${record}` : record
}
