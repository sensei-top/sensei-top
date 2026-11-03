import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { useShell, type Saved } from '../bridge'

const STORAGE_KEY = 'sensei-top:ai-features'
const CHANGED = 'sensei-top:ai-features-changed'

/** A provider giving a boolean overrides the shell and storage: how tests and
 *  the reference page draw the off state. */
export const AiFeaturesContext = createContext<boolean | undefined>(undefined)

// On by default; every read/write guarded, as in liveAdvice.ts.
function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'off'
  } catch {
    return true
  }
}

/** Whether AI features are on, its setter, and whether the choice is still
 *  undecided (a fresh desktop install). Order: the context override, the
 *  desktop shell's `aiFeatures` (`null` reads as off), then `localStorage`
 *  in a browser (on by default). A shell whose `initial` is null
 *  (`useShell()` null) falls back to storage. The setter answers the shell's
 *  `Saved`, so a caller can show a failed save; the storage branch always
 *  answers `{ ok: true }`. */
export function useAiFeatures(): [on: boolean, set: (on: boolean) => Promise<Saved>, undecided: boolean] {
  const override = useContext(AiFeaturesContext)
  const shell = useShell()
  const [stored, setStored] = useState<boolean>(readStored)
  useEffect(() => {
    const sync = () => setStored(readStored())
    window.addEventListener('storage', sync)
    window.addEventListener(CHANGED, sync)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener(CHANGED, sync)
    }
  }, [])
  const app = shell?.app
  const choose = useCallback(
    (next: boolean): Promise<Saved> => {
      if (app) return app.set({ aiFeatures: next })
      setStored(next)
      try {
        localStorage.setItem(STORAGE_KEY, next ? 'on' : 'off')
      } catch {
        // per-viewer convenience only
      }
      window.dispatchEvent(new Event(CHANGED))
      return Promise.resolve({ ok: true })
    },
    [app],
  )
  if (override !== undefined) return [override, choose, false]
  if (app) {
    const value = app.settings.aiFeatures
    return [value === true, choose, value === null]
  }
  return [stored, choose, false]
}
