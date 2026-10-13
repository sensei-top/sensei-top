const METER_FILL = {
  s1: 'bg-s1',
  s2: 'bg-s2',
  s3: 'bg-s3',
  muted: 'bg-edge',
  /** A meter that measures no data: the accent, never a
   *  series colour. */
  accent: 'bg-accent',
} as const

/** One bar primitive — track `surface-3`, 8 px high, its ends rounded to
 *  half its height (4 px at the default) — absorbing the ad-hoc
 *  `h-1.5 rounded-full` tracks that used to be hand-rolled in `OpponentRead`
 *  (the fit bar), `KeepGuideCard` (land-odds bars), `LibraryCard` (odds
 *  tiles), `OpponentDeckLabel` (the picker's fit bar) and `PoolReadCard`
 *  (colour bars). `TwoSidedMeter` and `IntervalBar` below are a different
 *  shape (two fills, or a band-plus-tick) but share this same track
 *  language rather than inventing their own. */
export function Meter({
  fraction,
  color = 's1',
  height = 'h-2',
  className = '',
  label,
  indeterminate = false,
}: {
  /** 0..1; clamped, never overflows the track. */
  fraction: number
  color?: keyof typeof METER_FILL
  height?: string
  className?: string
  /** Makes the bar a labelled progressbar; without it the bar is decoration. */
  label?: string
  /** Progress with no known end: a full bar that pulses. `animate-pulse` is
   *  switched off under `prefers-reduced-motion` (index.css), leaving it static. */
  indeterminate?: boolean
}) {
  const pct = indeterminate ? 100 : Math.min(100, Math.max(0, fraction * 100))
  const semantics = label
    ? {
        role: 'progressbar',
        'aria-label': label,
        ...(indeterminate ? {} : { 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': Math.round(pct) }),
      }
    : { role: 'presentation' }
  return (
    <div
      className={`${height} w-full overflow-hidden rounded-pill bg-surface3 ${className}`}
      {...semantics}
    >
      <div
        className={`h-full rounded-pill ${METER_FILL[color]}${indeterminate ? ' animate-pulse' : ''}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

/** A two-sided proportional bar for one raw self-vs-opponent pair (the
 *  damage race beat) — `self`/`opp` colors follow the entity, matching every
 *  other chart in this app (docs/frontend.md), never a fresh color scheme
 *  for a single component. Text carries the exact numbers beside it; this is
 *  the "who was ahead, at a glance" read, not the only view of the data. */
export function TwoSidedMeter({ self, opp }: { self: number; opp: number }) {
  const total = self + opp
  const selfPct = total > 0 ? (self / total) * 100 : 50
  return (
    <div
      className="flex h-2 w-full overflow-hidden rounded-pill bg-surface3"
      role="presentation"
    >
      <div className="h-full bg-s1" style={{ width: `${selfPct}%` }} />
      <div className="h-full bg-s2" style={{ width: `${100 - selfPct}%` }} />
    </div>
  )
}

/** One row of the leak finder's win-rate comparison: a filled bar to the
 *  point estimate, with the Wilson interval drawn as a translucent band
 *  behind it — so whether two rows' intervals overlap is something the eye
 *  can see, not just arithmetic left to the reader. The exact numbers still
 *  ship in the sibling `DataTable`, per this file's own rule below. */
export function IntervalBar({
  rate,
  ci,
  colorClass,
}: {
  rate: number
  ci: [number, number]
  colorClass: 's1' | 's2'
}) {
  const bg = colorClass === 's1' ? 'bg-s1' : 'bg-s2'
  return (
    <div className="relative h-3 w-full rounded-pill bg-surface3" role="presentation">
      <div
        className={`absolute inset-y-0 rounded-pill opacity-25 ${bg}`}
        style={{ left: `${ci[0] * 100}%`, width: `${Math.max(0, (ci[1] - ci[0]) * 100)}%` }}
      />
      <div
        className={`absolute inset-y-0 w-0.5 rounded-pill ${bg}`}
        style={{ left: `calc(${rate * 100}% - 1px)` }}
      />
    </div>
  )
}
