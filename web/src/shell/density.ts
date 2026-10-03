import { useCallback, useState } from 'react'

export type Density = 'comfortable' | 'compact'

const DENSITY_STORAGE_KEY = 'sensei-top:density'

// Comfortable by default; every read/write guarded, since a private window
// or blocked storage must never break the density switch itself.
function readStoredDensity(): Density {
  try {
    return localStorage.getItem(DENSITY_STORAGE_KEY) === 'compact' ? 'compact' : 'comfortable'
  } catch {
    return 'comfortable'
  }
}

function apply(density: Density) {
  document.documentElement.dataset.density = density
}

/** Puts the stored density on the document before the first render, so a
 *  compact page never paints comfortable first. `main.tsx` calls it. */
export function applyStoredDensity(): void {
  apply(readStoredDensity())
}

/** The density and its setter, for the control on `/settings`. */
export function useDensity(): [Density, (density: Density) => void] {
  const [density, setDensity] = useState<Density>(readStoredDensity)
  const choose = useCallback((next: Density) => {
    setDensity(next)
    apply(next)
    try {
      localStorage.setItem(DENSITY_STORAGE_KEY, next)
    } catch {
      // per-viewer convenience only — nothing here is worth surfacing an error for
    }
  }, [])
  return [density, choose]
}
