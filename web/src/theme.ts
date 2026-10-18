import { formatFixed } from './lib/format'

/**
 * Chart colors, kept in TypeScript because recharts writes SVG presentation
 * attributes and those do not resolve `var()`. Values mirror index.css and
 * scripts/validate_palette.py — see the comment in index.css.
 * tests/test_palette.py fails when the three disagree. Slots are assigned
 * by *entity*, never by rank, so a filter that drops a series never repaints
 * the survivors.
 *
 * Dark only (docs/design-system.md): there is one palette now, not a
 * selected dark set alongside a light one.
 */
export type Tokens = {
  self: string
  opponent: string
  /** The field's own colour (series 3). Also the second series of your
   *  own in the one chart that has one, your lands. Not the brand
   *  accent: that one is CSS only and never marks data. */
  field: string
  grid: string
  axis: string
  muted: string
  surface: string
  ink: string
  /** PositionTrack's own zero line — the one chart whose zero means
   *  ahead/behind, drawn heavier than an ordinary axis line. */
  ink2: string
}

const DARK: Tokens = {
  self: '#4a95f0',
  opponent: '#f0762f',
  field: '#9ee0a8',
  grid: '#252a40',
  axis: '#343a57',
  muted: '#989db5',
  surface: '#131522',
  ink: '#f2f3f8',
  ink2: '#b9bdd0',
}

/** Dark only — kept as a function (rather than inlining DARK at call sites)
 *  so no call site changes if the palette ever needs a per-viewer switch
 *  again. */
export function useTokens(): Tokens {
  return DARK
}

export const decimal = (value: number | null | undefined): string =>
  value == null ? '—' : formatFixed(value, 1)
