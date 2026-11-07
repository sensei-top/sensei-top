import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Before the imports run: TanStack Query reads `window` once at load to tell
// a browser from a server, and a server never refetches on an interval.
vi.hoisted(() => {
  Object.assign(globalThis, { window: { location: { origin: 'http://127.0.0.1:8000' } } })
})
import { translator } from '../i18n'
import { ApiError, type ProgressOut } from '../api'
import { QueryClient } from '@tanstack/react-query'
import {
  PROGRESS_DELAY_MS,
  PROGRESS_POLL_MS,
  pollProgress,
  readStage,
  seedProgress,
  stageRows,
  withProgress,
} from './stageProgress'

const t = translator('en')

const at = (stage: ProgressOut['stage'], done: number | null = null, total: number | null = null): ProgressOut => ({
  stage,
  done,
  total,
})

describe('readStage', () => {
  beforeEach(async () => {
    vi.stubGlobal('window', { location: { origin: 'http://127.0.0.1:8000' } })
    await withProgress(['guide', 'x'], async () => undefined)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('reads a 404 as not started yet, not as an error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 404, statusText: 'Not Found' })))
    const record = await readStage(['guide', 'x'])
    expect(record?.progress).toBeNull()
    expect(record?.uuid).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('reads nothing for a query that has not fetched yet', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    expect(await readStage(['guide', 'never-fetched'])).toBeNull()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('reads the recorded stage', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(at('matches', 3, 10)), { status: 200 })),
    )
    expect((await readStage(['guide', 'x']))?.progress).toEqual(at('matches', 3, 10))
  })

  it('still throws any other failure', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500, statusText: 'Server Error' })))
    await expect(readStage(['guide', 'x'])).rejects.toBeInstanceOf(ApiError)
  })
})

describe('stageRows', () => {
  it('draws no list until a stage is recorded', () => {
    expect(stageRows(null, 'guide', t)).toBeNull()
  })

  it('counts the current stage only when the total is known', () => {
    const counted = stageRows(at('matches', 140, 212), 'guide', t)
    expect(counted?.[0]).toEqual({ id: 'matches', label: 'Reading your matches · 140 of 212', state: 'current' })
    const uncounted = stageRows(at('matches'), 'guide', t)
    expect(uncounted?.[0].label).toBe('Reading your matches')
    const half = stageRows(at('matches', 140), 'guide', t)
    expect(half?.[0].label).toBe('Reading your matches')
  })

  it('ticks the stages before the current one and leaves the rest to come', () => {
    const rows = stageRows(at('field'), 'guide', t)
    expect(rows?.map((row) => row.state)).toEqual(['done', 'current', 'todo'])
    expect(rows?.[0].label).toBe('Reading your matches')
  })

  it('names the last stage for the page that asked', () => {
    expect(stageRows(at('together'), 'guide', t)?.[2].label).toBe('Putting the guide together')
    expect(stageRows(at('together'), 'coach', t)?.[2].label).toBe('Putting the report together')
  })
})

describe('pollProgress', () => {
  const origin = 'http://127.0.0.1:8000'
  const queryKey = ['guide', 'mono-red']

  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('window', { location: { origin } })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('waits for the delay, polls on the interval, and stops when stopped', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: URL) => {
        urls.push(url.toString())
        return new Response(JSON.stringify(at('matches', 1, 4)), { status: 200 })
      }),
    )
    const client = new QueryClient()
    const seen: (ProgressOut | null)[] = []
    // The fetch of the slow query names its key; the poll reads that one.
    await withProgress(queryKey, async () => undefined)
    const stop = pollProgress(client, queryKey, (progress) => seen.push(progress))

    await vi.advanceTimersByTimeAsync(PROGRESS_DELAY_MS - 1)
    expect(urls).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(1)
    expect(urls).toHaveLength(1)
    expect(seen.at(-1)).toEqual(at('matches', 1, 4))
    await vi.advanceTimersByTimeAsync(PROGRESS_POLL_MS)
    expect(urls).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(PROGRESS_POLL_MS)
    expect(urls).toHaveLength(3)

    stop()
    await vi.advanceTimersByTimeAsync(PROGRESS_POLL_MS * 4)
    expect(urls).toHaveLength(3)
  })

  it('polls the key of the latest fetch, and a refetch gets a new one', async () => {
    await withProgress(queryKey, async () => undefined)
    const first = [...(await keysOf(queryKey))]
    await withProgress(queryKey, async () => undefined)
    const second = await keysOf(queryKey)
    expect(second[0]).not.toBe(first[0])
  })

  it('polls at once for a fetch the cache already holds, and never reports null when its entry is collected', async () => {
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify(at('field')), { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)
    const key = ['guide', 'taken-over']
    await withProgress(key, async () => undefined)
    const uuid = (await readStage(key))?.uuid ?? ''
    const client = new QueryClient()
    client.setQueryData(['progress', ...key], { uuid, progress: at('matches', 2, 9) })
    fetchSpy.mockClear()
    const seen: (ProgressOut | null)[] = []
    const stop = pollProgress(client, key, (progress) => seen.push(progress))
    // What the last observer's leaving does before the timer fires.
    client.removeQueries({ queryKey: ['progress', ...key] })

    await vi.advanceTimersByTimeAsync(0)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(seen).not.toContain(null)
    expect(seen.at(-1)).toEqual(at('field'))
    stop()
  })

  it('never polls before the delay when stopped at once', async () => {
    const fetchSpy = vi.fn(async () => new Response('{}', { status: 404 }))
    vi.stubGlobal('fetch', fetchSpy)
    const stop = pollProgress(new QueryClient(), queryKey, () => undefined)
    stop()
    await vi.advanceTimersByTimeAsync(PROGRESS_DELAY_MS * 4)
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

async function keysOf(queryKey: readonly unknown[]): Promise<string[]> {
  const urls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: URL) => {
      urls.push(url.pathname.split('/').pop() ?? '')
      return new Response('{}', { status: 404 })
    }),
  )
  await readStage(queryKey)
  return urls
}

describe('seedProgress', () => {
  it('keeps the stage cached for the fetch running now', () => {
    expect(seedProgress({ uuid: 'now', progress: at('field') }, 'now')).toEqual(at('field'))
  })

  it('drops a record left by an earlier fetch of the same query', () => {
    expect(seedProgress({ uuid: 'earlier', progress: at('together') }, 'now')).toBeNull()
  })

  it('drops a record when no fetch has run yet, or nothing is cached', () => {
    expect(seedProgress({ uuid: 'now', progress: at('field') }, undefined)).toBeNull()
    expect(seedProgress(undefined, 'now')).toBeNull()
    expect(seedProgress({ uuid: 'now', progress: null }, 'now')).toBeNull()
  })
})
