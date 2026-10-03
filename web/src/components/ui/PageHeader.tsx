import type { ReactNode } from 'react'

/** The top of a page: a label above, the title as the page's one `h1`, the
 *  sentence under it, and the page's own actions on the right (under the
 *  title at a narrow width). */
export function PageHeader({
  kicker,
  title,
  lead,
  actions,
}: {
  /** A label above the title, by the label rule. */
  kicker?: string
  title: string
  /** One sentence under the title. */
  lead?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 max-w-3xl">
        {kicker && <p className="text-chip font-semibold tracking-label text-muted">{kicker}</p>}
        <h1 className={`font-display text-heading text-ink ${kicker ? 'mt-1' : ''}`}>{title}</h1>
        {lead && <p className="mt-2 text-lead text-ink2">{lead}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}
