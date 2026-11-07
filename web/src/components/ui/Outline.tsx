import type { ReactNode } from 'react'
import { SectionLabel } from './SectionLabel'
import { Skeleton } from './Skeleton'

/** One card's frame while its page loads: the card's own title in a
 *  `SectionLabel` (a key the loaded page already uses, never a label
 *  inside that card) over a block as tall as the card will be. `height` is
 *  a Tailwind height class, for example `h-64`; it is the reservation that
 *  keeps the page from jumping on arrival. `label` is omitted for a card
 *  that has none. `words`, given to the page's main frame only, is the
 *  page's one `role="status"` line, centred in the block; a frame without
 *  it has no status element. `children`, given beside `words`, take the words' place
 *  inside the same `role="status"` element, so the live region is not
 *  replaced when something richer than a line of words (the stage list)
 *  arrives. */
export function OutlineCard({
  label,
  words,
  height,
  children,
}: {
  label?: string
  words?: string
  height: string
  children?: ReactNode
}) {
  return (
    <div className="rounded-card border border-edge bg-surface p-5 shadow-lift">
      {label != null && (
        <SectionLabel as="p" className="mb-3">
          {label}
        </SectionLabel>
      )}
      <div className="relative">
        <Skeleton className={`w-full ${height}`} />
        {(words != null || children != null) && (
          <div
            role="status"
            className="absolute inset-0 flex items-center justify-center text-center text-caption text-muted"
          >
            {children ?? words}
          </div>
        )}
      </div>
    </div>
  )
}
