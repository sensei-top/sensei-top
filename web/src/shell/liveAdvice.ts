import { useCallback, useEffect, useState } from 'react'

const LIVE_ADVICE_STORAGE_KEY = 'sensei-top:live-advice'
const CHANGED = 'sensei-top:live-advice-changed'

// On by default; every read/write guarded, since a private window or blocked
// storage must never break the Live page or the switch itself. The switch
// can only hide advice: the server's own `advice` (table/queues.py) still
// decides where it may show at all.
function readStoredLiveAdvice(): boolean {
  try {
    return localStorage.getItem(LIVE_ADVICE_STORAGE_KEY) !== 'off'
  } catch {
    return true
  }
}

/** Whether the Live page shows advice during a game, and its setter, for
 *  the switch on `/settings` and for the Live page, which follows a change
 *  made in another tab or window too. */
export function useLiveAdvice(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState<boolean>(readStoredLiveAdvice)
  useEffect(() => {
    const sync = () => setOn(readStoredLiveAdvice())
    window.addEventListener('storage', sync)
    window.addEventListener(CHANGED, sync)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener(CHANGED, sync)
    }
  }, [])
  const choose = useCallback((next: boolean) => {
    setOn(next)
    try {
      localStorage.setItem(LIVE_ADVICE_STORAGE_KEY, next ? 'on' : 'off')
    } catch {
      // per-viewer convenience only — nothing here is worth surfacing an error for
    }
    window.dispatchEvent(new Event(CHANGED))
  }, [])
  return [on, choose]
}
