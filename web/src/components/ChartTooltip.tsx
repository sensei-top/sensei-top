import type { Tokens } from '../theme'

/** Mirrors recharts' TooltipPayloadEntry, whose name/value are deliberately
 *  wide (`NameType` is string | number, values may be arrays). */
type TooltipRow = {
  name?: string | number
  value?: string | number | readonly (string | number)[]
  color?: string
}

/** Recharts' default tooltip paints its text in the series color; text wears
 *  text tokens instead, with a colored swatch carrying identity. It is HTML,
 *  so it takes the tokens as classes rather than inline colours. */
export function ChartTooltip({
  active,
  payload,
  label,
  labelPrefix = '',
  labelFormat,
  format = (value: number) => String(value),
}: {
  active?: boolean
  payload?: readonly TooltipRow[]
  label?: string | number
  /** Unread since the tooltip took its colours from classes; kept so the
   *  charts that still pass it need no change. */
  t?: Tokens
  labelPrefix?: string
  /** The label as the tooltip writes it, whole: for a label whose words
   *  come from a catalogue, which a prefix could only join to it. Wins
   *  over `labelPrefix`. */
  labelFormat?: (label: string | number) => string
  format?: (value: number) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-control border border-edge-strong bg-surface3 px-3 py-2 text-caption text-ink shadow-lift">
      {label !== undefined && (
        <div className="mb-1 font-medium">
          {labelFormat ? (
            labelFormat(label)
          ) : (
            <>
              {labelPrefix}
              {label}
            </>
          )}
        </div>
      )}
      {payload.map((row) => (
        <div key={row.name} className="flex items-center gap-2 py-0.5">
          <span
            aria-hidden
            className="inline-block size-2 rounded-pill"
            style={{ background: row.color }}
          />
          <span className="text-muted">{row.name}</span>
          <span className="ml-auto tabular-nums font-medium text-ink">
            {typeof row.value === 'number' ? format(row.value) : String(row.value ?? '—')}
          </span>
        </div>
      ))}
    </div>
  )
}
