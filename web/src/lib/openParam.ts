import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'

/** The slugs a comma-separated address value names, in order, without
 *  blanks or repeats. */
export function parseOpen(value: string | null): string[] {
  if (!value) return []
  return [...new Set(value.split(',').map((s) => s.trim()).filter(Boolean))]
}

/** The address value for `slugs`, or `null` when none is open (the param is
 *  then deleted, so a page with nothing open keeps its bare address). */
export function serializeOpen(slugs: Iterable<string>): string | null {
  const list = [...new Set(slugs)]
  return list.length > 0 ? list.join(',') : null
}

/** `slugs` with `slug` added when absent, removed when present. */
export function toggleOpen(slugs: Iterable<string>, slug: string): string[] {
  const list = [...slugs]
  return list.includes(slug) ? list.filter((s) => s !== slug) : [...list, slug]
}

/** Which drawers are open, kept in `?<name>=a,b`. A change replaces the
 *  history entry and keeps the scroll, as the filters do. */
export function useOpenParam(name = 'open'): {
  open: Set<string>
  toggle: (slug: string) => void
  setAll: (slugs: string[]) => void
} {
  const [search, setSearch] = useSearchParams()
  const raw = search.get(name)
  const open = useMemo(() => new Set(parseOpen(raw)), [raw])
  const write = useCallback(
    (next: (current: string[]) => string[]) =>
      setSearch(
        (previous) => {
          const params = new URLSearchParams(previous)
          const value = serializeOpen(next(parseOpen(params.get(name))))
          if (value) params.set(name, value)
          else params.delete(name)
          return params
        },
        { replace: true, preventScrollReset: true },
      ),
    [name, setSearch],
  )
  const toggle = useCallback((slug: string) => write((cur) => toggleOpen(cur, slug)), [write])
  const setAll = useCallback((slugs: string[]) => write(() => slugs), [write])
  return { open, toggle, setAll }
}
