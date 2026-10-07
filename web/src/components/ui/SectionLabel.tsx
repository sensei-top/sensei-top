import type { ElementType, ReactNode } from 'react'

/** Replaces the old all-caps heading pattern hand-rolled at ~a dozen sites
 *  (revealed-card groups, the mulligan record, the library's mana-value
 *  groups, the pack's rated sections, …): the label rule — sentence case, in
 *  the interface face, letterspaced, muted. */
export function SectionLabel({
  children,
  as: Component = 'h3',
  className = '',
}: {
  children: ReactNode
  as?: ElementType
  className?: string
}) {
  return (
    <Component className={`text-chip font-semibold tracking-label text-muted ${className}`}>
      {children}
    </Component>
  )
}
