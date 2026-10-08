import { useSearchParams } from 'react-router'

export type Source = 'arena' | 'mtgo' | 'all'

const SOURCES: readonly string[] = ['arena', 'mtgo', 'all']

/** The source and deck filters, read from the address (`?source=`,
 *  `?deck=`) so a filtered page can be linked to and reloaded as it is.
 *  Each setter replaces the history entry rather than adding one, so Back
 *  leaves the page instead of walking through filter states, and keeps the
 *  scroll where it is. */
export function useFilters(): {
  source: Source
  deck: string | undefined
  setSource: (source: Source) => void
  setDeck: (deckId: string | undefined) => void
} {
  const [params, setParams] = useSearchParams()

  // Absent, or anything but the three values, is 'arena', matching the
  // API's own default (api/deps.py's SourceFilter): every number on this
  // dashboard predates MTGO, and 'arena' is what reproduces every one of
  // them exactly. 'all' is spelled out rather than left empty, since the
  // API itself tells "no source" (arena) from an explicit 'all'.
  const raw = params.get('source')
  const source: Source = raw !== null && SOURCES.includes(raw) ? (raw as Source) : 'arena'
  const deck = params.get('deck') || undefined

  const update = (key: string, value: string | undefined) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true, preventScrollReset: true },
    )

  return {
    source,
    deck,
    // The default leaves the address, so an unfiltered page has one address.
    setSource: (value) => update('source', value === 'arena' ? undefined : value),
    setDeck: (deckId) => update('deck', deckId),
  }
}
