import { useEffect, useState } from 'react'
import { scrollEdge, spyCurrent } from './guide'
import type { ScrollEdge } from './guide'

/** Which of `ids` is current, by watching each with one shared
 *  `IntersectionObserver` rather than a scroll listener — a section counts
 *  as "current" once it crosses into the top ~30% of the scrolling
 *  viewport (the window is what scrolls), the ordinary scrollspy convention.
 *
 *  The page's two ends have a rule of their own (`spyCurrent`): at the top
 *  (`scrollY` 0) the first id is current, and at the end (within 2 px) the
 *  last. The observer's band cannot answer there. A last section shorter
 *  than the band's distance from the window's foot never reaches the band,
 *  however far the page goes, so the section before it stayed marked after
 *  a link had taken the page to the last one. And going back to the top
 *  moves no section into the band when the first is already inside it, so
 *  the mark stayed on whatever was current before. The window's scroll
 *  position is read on every scroll and resize for these two rules only;
 *  everything between them is still the observer's. Since the edge is read
 *  on scroll and resize only, a change of the page's height with no scroll
 *  (the Markdown opening at the page's end) waits for the next scroll.
 *
 *  `ready` has to be a real, separate dependency, not just `ids` (a stable
 *  array): the guide's own data can take a long time to load
 *  (a real corpus's `/api/guide/{key}` measured ~45s), so `GuideView` shows
 *  `<Loading />` — no `#guide-...` elements in the DOM at all — for a while
 *  after this hook first mounts. Keying the effect only on `ids` meant it
 *  ran exactly once, found nothing, and never looked again once the real
 *  sections finally rendered — the nav stayed stuck on the first entry
 *  forever. Re-running when `ready` flips true is what makes it find the
 *  sections that just appeared. */
export function useScrollSpy(ids: readonly string[], ready: boolean): string {
  const [observed, setObserved] = useState<string>(ids[0] ?? '')
  const [edge, setEdge] = useState<ScrollEdge>(null)

  useEffect(() => {
    if (!ready) return
    const elements = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el != null)
    if (elements.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting)
        if (visible.length === 0) return
        const topmost = visible.reduce((a, b) =>
          a.boundingClientRect.top <= b.boundingClientRect.top ? a : b,
        )
        setObserved(topmost.target.id)
      },
      { rootMargin: '-10% 0px -70% 0px', threshold: [0, 1] },
    )
    for (const el of elements) observer.observe(el)
    return () => observer.disconnect()
  }, [ids, ready])

  useEffect(() => {
    if (!ready) return
    const read = () =>
      setEdge(scrollEdge(window.scrollY, window.innerHeight, document.documentElement.scrollHeight))
    read()
    window.addEventListener('scroll', read, { passive: true })
    window.addEventListener('resize', read)
    return () => {
      window.removeEventListener('scroll', read)
      window.removeEventListener('resize', read)
    }
  }, [ready])

  return spyCurrent(ids, observed, edge)
}
