import { useEffect, useRef, useState } from 'react'
import type { Saved } from '../../bridge'
import type { TFunction } from '../../i18n'
import { failureOf, settle } from '../../lib/settings'

/** Whether "Saved" is showing: `flash()` shows it for two seconds, `clear()`
 *  hides it at once. Nothing is set after the control has left the page. */
export function useSavedFlash(): { shown: boolean; flash: () => void; clear: () => void } {
  const [shown, setShown] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(
    () => () => clearTimeout(timer.current),
    [],
  )
  const clear = () => {
    clearTimeout(timer.current)
    setShown(false)
  }
  const flash = () => {
    clearTimeout(timer.current)
    setShown(true)
    timer.current = setTimeout(() => setShown(false), 2000)
  }
  return { shown, flash, clear }
}

/** What a control that saves on change does with one save: `start` before
 *  it is called, `settled` with the failure's sentence or `null` once it has
 *  answered (a refused promise is a failure), and `flash` only after one
 *  that worked. */
export async function runSave(
  save: () => Promise<Saved>,
  t: TFunction,
  on: { start: () => void; settled: (error: string | null) => void; flash: () => void },
): Promise<void> {
  on.start()
  const sentence = failureOf(await settle(save(), t), t)
  on.settled(sentence)
  if (sentence === null) on.flash()
}
