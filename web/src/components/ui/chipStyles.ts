export type ChipVariant = 'neutral' | 'win' | 'loss' | 'warn' | 'accent' | 'seen'

/** Fill and text colour only: reinforcement, never the only signal. The
 *  label is always text; a variant never stands in for a word. Split from
 *  `Chip.tsx` itself so that file exports only the component
 *  (react-refresh wants one file, one component). */
export const CHIP_VARIANT_CLASS: Record<ChipVariant, string> = {
  neutral: 'bg-surface3 text-ink',
  // A status colour at 12% under its own word: the tint the palette check
  // validates on the plane, surface-1 and surface-2 (index.css).
  win: 'bg-win/12 text-win',
  loss: 'bg-loss/12 text-loss',
  warn: 'bg-warn/12 text-warn',
  accent: 'bg-accent text-on-accent',
  seen: 'bg-surface3 text-muted line-through',
}

/** `neutral` with its word lowered to `text-muted`: the fill stays, the
 *  word steps back. Spelled whole rather than appended to `neutral`, since
 *  two text colours on one element leave the winner to stylesheet order. */
export const CHIP_MUTED_CLASS = 'bg-surface3 text-muted'
