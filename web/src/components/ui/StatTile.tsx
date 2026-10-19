/** A single number is a stat tile, never a one-bar bar chart. The label
 *  follows the label rule, the number is the display face at the `stat`
 *  step, and `detail` is the one line under it.
 *  `muted` draws the number muted, for a figure too thin to read as a rate. */
export function StatTile({
  label,
  value,
  detail,
  muted = false,
}: {
  label: string
  value: string
  detail?: string
  muted?: boolean
}) {
  return (
    <div className="rounded-card border border-edge bg-surface px-5 py-4 shadow-lift">
      <div className="text-chip font-semibold tracking-label text-muted">{label}</div>
      <div className={`mt-1 font-display text-stat ${muted ? 'text-muted' : 'text-ink'}`}>{value}</div>
      {detail && <div className="mt-1 text-caption text-muted">{detail}</div>}
    </div>
  )
}
