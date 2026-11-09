import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

/** What the main column says above the page: the restart screen while the
 *  desktop shell restarts the server on purpose (`AppSettings.restarting`)
 *  and until the heartbeat has been asked again after it, the tracker-down
 *  notice when the heartbeat fails at any other time, nothing otherwise. A
 *  crash restart never sets `restarting`, so it keeps the notice. */
export function mainNotice(shown: boolean, liveError: boolean): 'restarting' | 'trackerDown' | null {
  if (shown) return 'restarting'
  return liveError ? 'trackerDown' : null
}

/** Whether the restart screen shows: while the shell says it is restarting,
 *  then until one more heartbeat has answered either way, so the notice the
 *  failed beats left behind never flashes between the screen and the page. */
export function useRestartScreen(restarting: boolean): boolean {
  const queryClient = useQueryClient()
  const [was, setWas] = useState(restarting)
  const [settling, setSettling] = useState(false)
  if (restarting !== was) {
    setWas(restarting)
    setSettling(!restarting)
  }
  useEffect(() => {
    if (!settling) return
    let current = true
    void queryClient.refetchQueries({ queryKey: ['live'] }).finally(() => {
      if (current) setSettling(false)
    })
    return () => {
      current = false
    }
  }, [settling, queryClient])
  return restarting || settling
}
