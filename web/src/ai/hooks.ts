import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  formatParams,
  get,
  post,
  putPasted,
  type CoachNarrativeResponse,
  type CoachResponse,
} from '../api'

/** The coach tab's free, local evidence bundle — population, by-deck/role/
 *  mulligan/opponent rollups, leaks, turning points and the field, plus
 *  every report ever written. Deck-independent (no `deckId` in the key):
 *  the coach reasons across every deck at once, unlike the guide. An
 *  ordinary query on the heartbeat like the match report and the deck
 *  guide, even though a real corpus measures ~7.5s to rebuild — `CoachView`
 *  gates its own cards on `isPending` rather than letting that read as an
 *  empty flash. */
export const useCoach = (format?: string, enabled = true) =>
  useQuery({
    queryKey: ['coach', format ?? null],
    queryFn: () => get<CoachResponse>('/api/coach', formatParams(format)),
    enabled,
  })

/** The report list and the models, which are the same for every format:
 *  the first `/api/coach` answer already cached, whichever format it was
 *  built for (read once, so the page does not move when another arrives);
 *  only when none is cached, one request, for the default format. */
export const useAnyCoach = () => {
  const queryClient = useQueryClient()
  const [cached] = useState(
    () => queryClient.getQueriesData<CoachResponse>({ queryKey: ['coach'] }).find(([, data]) => data != null)?.[1],
  )
  const fetched = useCoach(undefined, cached === undefined)
  return cached !== undefined
    ? { isPending: false as const, error: null, data: cached }
    : { isPending: fetched.isPending, error: fetched.error, data: fetched.data }
}

/** The latest coach report, the prompt to write the next one from, and
 *  whether the evidence has drifted since it was written. A separate query
 *  from `useCoach` (neither `enabled`-gates the other), so the two ~7.5s
 *  evidence rebuilds happen in parallel over the network instead of one
 *  waiting on the other. */
export const useCoachNarrative = (format?: string, enabled = true) =>
  useQuery({
    queryKey: ['coach-narrative', format ?? null],
    queryFn: () => get<CoachNarrativeResponse>('/api/coach/narrative', formatParams(format)),
    enabled,
  })

/** One past report exactly as it was written, for `/coach/:id`. Not
 *  fetched while `id` is null. */
export const useCoachReport = (id: number | null) =>
  useQuery({
    queryKey: ['coach-report', id],
    queryFn: () => get<CoachNarrativeResponse>(`/api/coach/narrative/${id}`),
    enabled: id != null,
  })

/** Write a fresh coach report with Claude — high reasoning effort, web
 *  search enabled, and measured in minutes rather than seconds. No
 *  client-side timeout and no optimistic update: `GenerateCard` already
 *  shows elapsed time while this is pending.
 *
 *  `model` is the Coach tab's dropdown choice: a `REPORT_MODELS` id posts
 *  `{ model }` to override the configured coach model for this one report;
 *  `null` means "leave it alone" and posts no body at all, so the server
 *  keeps using the configured model.
 *
 *  `format` is always sent: the one the page's GETs showed, never left to
 *  the server's default, which can move between the GET and the press. */
export const useGenerateCoachNarrative = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ model, format }: { model: string | null; format: string }) =>
      post<CoachNarrativeResponse>(
        `/api/coach/narrative?format=${encodeURIComponent(format)}`,
        model !== null ? { model } : undefined,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['coach'] })
      queryClient.invalidateQueries({ queryKey: ['coach-narrative'] })
    },
  })
}

/** A pasted coach report, for the format the page's reads showed. */
export const usePasteCoachNarrative = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ format, answer }: { format: string; answer: string }) =>
      putPasted<CoachNarrativeResponse>({ card: 'coach', format }, answer),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ['coach'] }),
        queryClient.invalidateQueries({ queryKey: ['coach-narrative'] }),
      ]),
  })
}
