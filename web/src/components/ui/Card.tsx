import type { ReactNode } from 'react'
import { Skeleton } from './Skeleton'
import { useTranslation } from 'react-i18next'

/** The one raised surface. `elevation={2}` is a block nested inside another
 *  Card: the fill steps up, and it takes neither border nor shadow. Each
 *  surface names its own colour in `--art-surface`, which a `CardArt` fade
 *  inside it arrives at. */
export function Card({
  title,
  subtitle,
  action,
  art,
  elevation = 1,
  tone,
  children,
  className = '',
}: {
  title?: string
  subtitle?: string
  /** A small control (a `Segmented`, a `<select>`) that belongs beside the
   *  title rather than inside the body — e.g. Metagame's window picker. */
  action?: ReactNode
  /** Rendered above the header, edge to edge, clipped by the card's own
   *  radius: a `CardArt` with a fade at its bottom edge. */
  art?: ReactNode
  /** 2 is a block nested inside another Card (the deck guide's sections,
   *  the rail's disclosure cards): surface-2, no border, no shadow. */
  elevation?: 1 | 2
  /** 'accent' tints the border for an authored/metered artefact (a written
   *  narrative) — never a decoration on its own; the header still spells out
   *  who wrote it and when. Controlled here, not via `className`, so it
   *  always wins over the plain border-edge default. */
  tone?: 'accent'
  children: ReactNode
  className?: string
}) {
  const nested = elevation === 2
  const surface = nested
    ? 'rounded-block bg-surface2 p-4 [--art-surface:var(--surface-2)]'
    : `rounded-card border bg-surface p-5 shadow-lift [--art-surface:var(--surface-1)] ${
        tone === 'accent' ? 'border-accent/30' : 'border-edge'
      }`
  return (
    <section className={`${surface} ${art ? 'overflow-hidden' : ''} ${className}`}>
      {art && <div className={nested ? '-mx-4 -mt-4 mb-4' : '-mx-5 -mt-5 mb-4'}>{art}</div>}
      {(title || action) && (
        // The title's line holds the title and, at its right, the action. The
        // subtitle runs under it at the card's full width, so neither a long
        // subtitle nor a wide action squeezes the other into a column. An
        // action too wide for the title's line takes the line under the
        // title; one wider than the card wraps its own text. Nothing is
        // truncated.
        <header className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {title && <h2 className="min-w-0 font-display text-title text-ink">{title}</h2>}
          {action && <div className="ml-auto min-w-0 max-w-full">{action}</div>}
          {subtitle && <p className="basis-full text-caption text-muted">{subtitle}</p>}
        </header>
      )}
      {children}
    </section>
  )
}

/** Inline `**bold**` / `` `code` `` only — narrative prose (the deck guide,
 *  the live matchup brief) needs no more, and this avoids pulling in a
 *  Markdown renderer for a handful of spans. Shared rather than duplicated
 *  between the two narrative-rendering views that use it. */
export function Prose({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return (
    <p className="whitespace-pre-wrap text-body text-ink2">
      {parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return (
            <strong key={i} className="font-semibold text-ink">
              {part.slice(2, -2)}
            </strong>
          )
        }
        if (part.startsWith('`') && part.endsWith('`')) {
          return (
            <code key={i} className="rounded-control bg-plane px-1 py-0.5 text-caption text-ink">
              {part.slice(1, -1)}
            </code>
          )
        }
        return part
      })}
    </p>
  )
}

/** A shape-holding placeholder rather than bare "Loading…" text — the
 *  outline of what is about to render, so the layout does not jump into
 *  place once data arrives. */
export function Loading() {
  const { t } = useTranslation()
  return (
    <div className="space-y-3 px-1 py-6" role="status" aria-label={t('common.loading')}>
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  )
}

export function ErrorNote({ error }: { error: Error }) {
  const { t } = useTranslation()
  return (
    <div className="rounded-card border border-edge bg-surface px-5 py-6 text-body shadow-lift">
      <p className="font-medium text-ink">{t('common.loadError')}</p>
      <p className="mt-1 text-ink2">{error.message}</p>
    </div>
  )
}
