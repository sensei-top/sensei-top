import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'

/** Something worth having one click away rather than on the page: the
 *  native `<details>`, so it opens with the keyboard and in find-in-page
 *  with no script. The chevron points at the summary while closed and
 *  turns down once open. */
export function Disclosure({
  summary,
  defaultOpen = false,
  children,
}: {
  summary: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  return (
    <details className="group" open={defaultOpen}>
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-caption text-muted transition-chrome select-none hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronRight
          size={16}
          aria-hidden
          className="shrink-0 transition-transform group-open:rotate-90 motion-reduce:transition-none"
        />
        {summary}
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  )
}
