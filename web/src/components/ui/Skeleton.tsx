/** One shape-holding block. `Loading` composes a few of these into a
 *  placeholder for whatever card is about to render; used bare wherever a
 *  smaller inline placeholder is more honest than "Loading…" text. */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden className={`animate-pulse rounded-block bg-surface2 ${className}`} />
}
