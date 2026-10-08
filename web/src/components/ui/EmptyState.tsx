import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

/** What a page or a card shows when there is nothing to show yet: an
 *  optional icon and title, one sentence saying what will appear and what
 *  causes it, and an optional action. It sits on whatever surface holds
 *  it, so it draws a dashed edge rather than a fill of its own. A place's
 *  own empty state carries that place's icon (`shell/places.ts`); the icon
 *  repeats what the title says, so it is hidden from a screen reader. */
export function EmptyState({
  icon: Icon,
  title,
  message,
  action,
}: {
  icon?: LucideIcon
  title?: string
  /** The one sentence. */
  message: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-edge-strong px-5 py-10 text-center">
      {Icon && (
        <span className="mb-1 flex size-11 items-center justify-center rounded-pill bg-surface2 text-muted">
          <Icon size={22} strokeWidth={1.75} aria-hidden />
        </span>
      )}
      {title && <h3 className="font-display text-title text-ink">{title}</h3>}
      <p className="max-w-prose text-body text-muted">{message}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
