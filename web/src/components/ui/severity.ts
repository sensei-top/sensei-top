import type { ChipVariant } from './chipStyles'

/** The match report and the leak finder both render the same Severity
 *  vocabulary (decisive/flag/notice/note) as a chip; this maps that
 *  vocabulary onto Chip's own variants so both stay one implementation.
 *  Only `decisive` takes the accent. Text still carries the label: the
 *  colour is reinforcement only. */
export function severityChip(severity: string): { variant: ChipVariant; muted: boolean } {
  if (severity === 'decisive') return { variant: 'accent', muted: false }
  if (severity === 'flag') return { variant: 'warn', muted: false }
  if (severity === 'notice') return { variant: 'neutral', muted: false }
  return { variant: 'neutral', muted: true }
}
