import { useEffect, useRef, useState } from 'react'
import { QueryObserver, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { get, isNotFound, type ProgressOut } from '../api'
import type { TFunction } from '../i18n'

/** The build's stages in the order the server records them
 *  (`api/progress.py`); the page keys its own words for each. */
export const STAGE_ORDER = ['matches', 'field', 'together'] as const

/** How long a query is pending before the first poll, and the gap between
 *  polls after it. */
export const PROGRESS_DELAY_MS = 500
export const PROGRESS_POLL_MS = 500

export type StageKind = 'guide' | 'coach'
export const GUIDE_PAGE: StageKind = 'guide'
export const COACH_PAGE: StageKind = 'coach'
export type StageState = 'done' | 'current' | 'todo'
export type StageRow = { id: ProgressOut['stage']; label: string; state: StageState }

/** The key the latest fetch of each slow query passed as `?progress=`,
 *  under the query's own key stringified. A module map rather than state:
 *  every observer of the query, and every refetch and retry of it, shares
 *  one fetch, and that fetch's key is the one worth polling. */
const latestKeys = new Map<string, string>()

/** Run a slow query's fetch under a fresh UUID, remembered for the poll. Make
 *  the UUID here, in the `queryFn`, never when the hook renders: a retry, a
 *  refetch after a language change and a second page asking for the same
 *  query each get their own, so a stage the server still holds from an
 *  earlier build is never read as this one's. */
export function withProgress<T>(queryKey: readonly unknown[], run: (progress: string) => Promise<T>): Promise<T> {
  const progress = crypto.randomUUID()
  latestKeys.set(JSON.stringify(queryKey), progress)
  return run(progress)
}

/** One read of a fetch's stage by its UUID. A 404 is "not started yet" (the
 *  first stage is recorded a moment after the GET begins), so it reads as no
 *  progress, never as an error. */
async function readRecord(uuid: string): Promise<ProgressOut | null> {
  try {
    return await get<ProgressOut>(`/api/progress/${uuid}`)
  } catch (error) {
    if (isNotFound(error)) return null
    throw error
  }
}

/** What the poll's cache entry holds: the stage, with the UUID of the fetch
 *  it was read for, so a record left by an earlier fetch of the same query
 *  (a finished build, a cancelled one) can be told from the running one's. */
export type StageRecord = { uuid: string; progress: ProgressOut | null }

export async function readStage(queryKey: readonly unknown[]): Promise<StageRecord | null> {
  const uuid = latestKeys.get(JSON.stringify(queryKey))
  return uuid === undefined ? null : { uuid, progress: await readRecord(uuid) }
}

/** The stage to start from when a poll mounts: the cached record's, only
 *  when it was read for the fetch running now (`current`), else `null`. */
export function seedProgress(cached: StageRecord | null | undefined, current: string | undefined): ProgressOut | null {
  return cached != null && current !== undefined && cached.uuid === current ? cached.progress : null
}

/** The stages as a list: those before the server's current one done, the
 *  current one with its count only when both `done` and `total` are known,
 *  the rest still to come. `null` while nothing has been recorded. */
export function stageRows(progress: ProgressOut | null | undefined, kind: StageKind, t: TFunction): StageRow[] | null {
  if (progress == null) return null
  const prefix = kind === 'guide' ? 'decks.guide.stage' : 'coach.stage'
  const at = STAGE_ORDER.indexOf(progress.stage)
  return STAGE_ORDER.map((id, index) => {
    const state: StageState = index < at ? 'done' : index === at ? 'current' : 'todo'
    let label: string
    if (id === 'matches') {
      label =
        state === 'current' && progress.done != null && progress.total != null
          ? t(`${prefix}.matchesCount`, { done: progress.done, total: progress.total })
          : t(`${prefix}.matches`)
    } else if (id === 'field') {
      label = t(`${prefix}.field`)
    } else {
      label = t(`${prefix}.together`)
    }
    return { id, label, state }
  })
}

const progressKeyOf = (queryKey: readonly unknown[]) => ['progress', ...queryKey]

/** Poll the stage of `queryKey`'s running fetch: the first read after
 *  `PROGRESS_DELAY_MS`, or at once when the cache already holds a stage for
 *  this fetch (another instance of the page has been polling it), then every
 *  `PROGRESS_POLL_MS`, each handed to `onProgress`. Returns the function
 *  that stops it. */
export function pollProgress(
  client: QueryClient,
  queryKey: readonly unknown[],
  onProgress: (progress: ProgressOut | null) => void,
): () => void {
  let stop: (() => void) | undefined
  const current = () => latestKeys.get(JSON.stringify(queryKey))
  const known = seedProgress(client.getQueryData<StageRecord | null>(progressKeyOf(queryKey)), current()) != null
  const timer = setTimeout(
    () => {
      const observer = new QueryObserver(client, {
        queryKey: progressKeyOf(queryKey),
        queryFn: () => readStage(queryKey),
        refetchInterval: PROGRESS_POLL_MS,
        retry: false,
        gcTime: 0,
      })
      // The cache may still hold an earlier fetch's record: it is passed on
      // only when it belongs to the fetch running now.
      stop = observer.subscribe((result) => {
        // A fresh query (the last observer's entry was collected as it left)
        // has no data yet: that is not "no progress", and must not wipe the
        // stage the page started from.
        if (result.data === undefined) return
        onProgress(seedProgress(result.data, current()))
      })
    },
    known ? 0 : PROGRESS_DELAY_MS,
  )
  return () => {
    clearTimeout(timer)
    stop?.()
  }
}

/** The latest stage recorded for `queryKey`'s fetch while `pending`, else
 *  `null`. Stops when the query settles. A first mount keeps the stage the
 *  cache holds for this fetch, so a page taking over from another instance
 *  does not blink back to the words. */
export function useStageProgress(queryKey: readonly unknown[], pending: boolean): ProgressOut | null {
  const client = useQueryClient()
  const stringKey = JSON.stringify(queryKey)
  const [progress, setProgress] = useState<ProgressOut | null>(() =>
    seedProgress(client.getQueryData<StageRecord | null>(progressKeyOf(queryKey)), latestKeys.get(stringKey)),
  )
  const previousKey = useRef(stringKey)
  useEffect(() => {
    // Cleared on a real change of key, and when the query settles: a stage of
    // the last key, or of the last fetch, is not this one's.
    if (previousKey.current !== stringKey || !pending) setProgress(null)
    previousKey.current = stringKey
    if (!pending) return
    return pollProgress(client, JSON.parse(stringKey) as unknown[], setProgress)
  }, [client, stringKey, pending])
  return pending ? progress : null
}
