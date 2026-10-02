import { ManaPips } from './ManaPips'
import { Meter } from './Meter'

/** The series a bar is drawn in: `s1` for your own cards, `s3` for your
 *  lands (docs/design-system.md's palette). */
type BarColor = 's1' | 's3'

/** One colour's count: `color` is a WUBRG letter. */
export type ColorCount = { color: string; count: number }

const BAR_FILL: Record<BarColor, string> = {
  s1: 'bg-s1',
  s3: 'bg-s3',
}

/** One row per colour, in the order given: the colour's pip, a bar as long
 *  as its count against the largest, and the count in figures. Every bar is
 *  one hue, `color`; a colour named in `highlight` has a ring around its
 *  pip, never a hue of its own on the bar (docs/design-system.md: a pip
 *  labels the row, it never colours a chart mark). */
export function ColorBars({
  colors,
  highlight = new Set(),
  color = 's1',
}: {
  colors: ColorCount[]
  highlight?: Set<string>
  color?: BarColor
}) {
  if (colors.length === 0) return null
  const max = Math.max(...colors.map((c) => c.count))
  return (
    <div className="space-y-1.5">
      {colors.map((c) => {
        const ringed = highlight.has(c.color)
        return (
          <div key={c.color} className="flex items-center gap-2">
            <span className={ringed ? 'rounded-pill ring-2 ring-ink' : undefined}>
              <ManaPips colors={c.color} />
            </span>
            <Meter fraction={max > 0 ? c.count / max : 0} color={color} height="h-2" className="flex-1" />
            <span className="w-6 text-right text-caption tabular-nums text-ink2">{c.count}</span>
          </div>
        )
      })}
    </div>
  )
}

/** The mana curve as seven bars, mana value 1 to 7+, each as tall as its
 *  count against the largest, in `color`. Under every bar its mana value
 *  and its count, a 0 included and muted, so the seven stand on one line.
 *  `curve` is `[mana_value, count]` pairs; a bucket it leaves out is 0. */
export function CurveBars({ curve, color = 's1' }: { curve: [number, number][]; color?: BarColor }) {
  if (curve.length === 0) return null
  const max = Math.max(...curve.map(([, n]) => n))
  const byBucket = new Map(curve)
  return (
    <div className="flex items-end gap-1.5">
      {Array.from({ length: 7 }, (_, i) => i + 1).map((mv) => {
        const n = byBucket.get(mv) ?? 0
        return (
          <div key={mv} className="flex flex-1 flex-col items-center gap-1">
            <div className="flex h-16 w-full items-end overflow-hidden rounded-control bg-surface3">
              <div
                className={`w-full ${BAR_FILL[color]}`}
                style={{ height: n > 0 ? `${Math.max((n / max) * 100, 8)}%` : 0 }}
              />
            </div>
            <span className="text-caption tabular-nums text-muted">{mv === 7 ? '7+' : mv}</span>
            <span className={`text-caption tabular-nums ${n > 0 ? 'text-ink2' : 'text-muted'}`}>{n}</span>
          </div>
        )
      })}
    </div>
  )
}
