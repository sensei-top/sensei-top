import type { ReactNode } from 'react'

/** A nested block that says one thing apart from the rest of its card: a
 *  verdict, or what the numbers cannot say. `warn` adds a warn-tinted edge
 *  and nothing else; the words carry the warning. */
export function Callout({
  tone = 'neutral',
  title,
  children,
}: {
  tone?: 'neutral' | 'warn'
  title?: string
  children: ReactNode
}) {
  return (
    <aside
      className={`rounded-block bg-surface2 px-4.5 py-4 [--art-surface:var(--surface-2)] ${
        tone === 'warn' ? 'border border-warn/40' : ''
      }`}
    >
      {title && <h3 className="mb-1.5 font-display text-title text-ink">{title}</h3>}
      <div className="text-body text-ink2">{children}</div>
    </aside>
  )
}
