import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  formatParams,
  get,
  invalidateBriefWrite,
  invalidateGuideWrite,
  post,
  putPasted,
  query,
  type BriefPromptOut,
  type CoachNarrativeResponse,
  type CoachResponse,
  type CoverageOut,
  type CoveragePromptOut,
  type GuideMarkdownOut,
  type GuideNarrativeResponse,
  type MatchupBriefOut,
  type MatchupBriefResponse,
  type NarrativeResponse,
  type RcqGenerateIn,
  type RcqGuideOut,
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

/* The seven paste mutations. Each stores an answer pasted into its card
 * (`CopyPromptCard`'s box) and, on success, invalidates the card's own
 * queries, a stored answer changing no row count the heartbeat reads. Its
 * `onSuccess` returns the invalidations, so the mutation settles only once
 * those reads have refetched: the box says "Saving…" until the stored
 * answer is on the card, and does not empty early inviting a second save
 * (the coach, leak and RCQ tables keep every row). The response body is never
 * written into a query: a `PUT` answers with what it stored, and the next
 * `GET` is what the card should show (the coach's, for one, rebuilds the
 * prompt the `PUT` returned). A refusal rejects with `ApiError`, whose
 * message is the server's sentence. */

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

/** The live matchup brief for the match in progress — what to play around
 *  and the game-2 plan, from `brief/`. Every read here is free and local:
 *  this route has no generate mutation of its own (unlike the match report
 *  and the deck guide, `docs/llm.md`), so it always serves whatever was
 *  imported or filled by a guide plus the prompt to write one from, and
 *  riding the heartbeat like every other query is correct. */
export const useCurrentMatchBrief = () =>
  useQuery(query<MatchupBriefResponse>('current-match-brief', '/api/current-match/brief'))

/** The stored training-plan prose over the leak finder's own ranked output
 *  (every deck, unscoped — see `ai/review/leaks_store.py`), and always the
 *  prompt to (re)write it from. Free and local to fetch; an ordinary query
 *  on the heartbeat like the leak finder itself. */
export const useLeaksNarrative = () =>
  useQuery({
    queryKey: ['leaks-narrative'],
    queryFn: () => get<NarrativeResponse>('/api/review/leaks/narrative'),
  })

/** The evidence-only guide document, for copy or save. No narrative call —
 *  fetched fresh each time the export panel is opened rather than cached
 *  under the heartbeat, since it is only ever read right before a copy or
 *  a download. */
export const useGuideMarkdown = (key: string | undefined, enabled: boolean) =>
  useQuery({
    queryKey: ['guide-markdown', key],
    queryFn: () => get<GuideMarkdownOut>(`/api/guide/${encodeURIComponent(key ?? '')}/markdown`),
    enabled: enabled && Boolean(key),
  })

/** Every matchup brief stored for this deck, one per archetype
 *  (`brief/store.py`). Free and local, so an ordinary query on the
 *  heartbeat. It carries no stale flag: only coverage's `status` says
 *  `stale`. */
export const useGuideBriefs = (key: string | undefined) =>
  useQuery({
    queryKey: ['guide-briefs', key],
    queryFn: () => get<MatchupBriefOut[]>(`/api/guide/${encodeURIComponent(key ?? '')}/briefs`),
    enabled: Boolean(key),
  })

/** The single-brief prompt for one archetype, fetched only once its
 *  pairing's "Build the prompt" or "Write it again" is pressed, so a page
 *  never builds a prompt up front. */
export const useGuideBriefPrompt = (
  key: string | undefined,
  archetypeKey: string | undefined,
  enabled: boolean,
) =>
  useQuery({
    queryKey: ['guide-brief-prompt', key, archetypeKey],
    queryFn: () =>
      get<BriefPromptOut>(
        `/api/guide/${encodeURIComponent(key ?? '')}/briefs/${encodeURIComponent(archetypeKey ?? '')}/prompt`,
      ),
    enabled: enabled && Boolean(key) && Boolean(archetypeKey),
  })

/** Write a training plan over the leak finder's own ranked output with
 *  Claude, and store it. */
export const useGenerateLeaksNarrative = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => post<NarrativeResponse>('/api/review/leaks/narrative'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['leaks-narrative'] })
    },
  })
}

/** Write this deck's guide narrative with Claude, and store it — also fills
 *  every matchup plan it covers into `matchup_brief`, so it invalidates
 *  what `invalidateGuideWrite` names, not just this deck's own narrative. */
export const useGenerateGuideNarrative = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (key: string) =>
      post<GuideNarrativeResponse>(`/api/guide/${encodeURIComponent(key)}/narrative`),
    onSuccess: (_data, key) => invalidateGuideWrite(queryClient, key),
  })
}

/** A pasted training plan over the leak finder's ranked output. */
export const usePasteLeaksNarrative = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ answer }: { answer: string }) => putPasted<NarrativeResponse>({ card: 'leaks' }, answer),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['leaks-narrative'] }),
  })
}

/** A pasted deck guide. Its matchup plans land in `matchup_brief` in the
 *  same write, so the deck's briefs, its coverage and the live brief are
 *  invalidated with the narrative. */
export const usePasteGuideNarrative = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ key, answer }: { key: string; answer: string }) =>
      putPasted<GuideNarrativeResponse>({ card: 'guide', key }, answer),
    onSuccess: (_data, { key }) => invalidateGuideWrite(queryClient, key),
  })
}

/** A pasted matchup brief for one archetype: the deck's briefs, its
 *  coverage and the live brief are invalidated. */
export const usePasteBrief = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ key, archetypeKey, answer }: { key: string; archetypeKey: string; answer: string }) =>
      putPasted<MatchupBriefOut>({ card: 'brief', key, archetypeKey }, answer),
    onSuccess: (_data, { key }) => invalidateBriefWrite(queryClient, key),
  })
}

/** The stored "Coach's summary" for one match, and always the prompt to
 *  (re)write it from. An ordinary query, enabled only while the panel is
 *  open — the route recomputes the report/snapshot/field context on every
 *  call, so this stays opt-in rather than riding the heartbeat. */
export const useReportNarrativePrompt = (matchId: string, enabled: boolean) =>
  useQuery({
    queryKey: ['match-report-narrative-prompt', matchId],
    queryFn: () => get<NarrativeResponse>(`/api/matches/${matchId}/report/narrative`),
    enabled,
  })

/** Write this match's "Coach's summary" with Claude, and store it.
 *
 *  The explicit invalidation is required, same reasoning as
 *  `useSetOpponentDeck`: nothing about a stored narrative changes the
 *  heartbeat's row-count revision, so without this the card would show a
 *  stale "nothing written yet" until an unrelated refetch happened to
 *  overwrite it. */
export const useGenerateMatchReportNarrative = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (matchId: string) =>
      post<NarrativeResponse>(`/api/matches/${matchId}/report/narrative`),
    onSuccess: (_data, matchId) => {
      queryClient.invalidateQueries({ queryKey: ['match-report-narrative-prompt', matchId] })
    },
  })
}

/** A pasted "Coach's summary" for one match. */
export const usePasteMatchReportNarrative = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ matchId, answer }: { matchId: string; answer: string }) =>
      putPasted<NarrativeResponse>({ card: 'match', matchId }, answer),
    onSuccess: (_data, { matchId }) =>
      queryClient.invalidateQueries({ queryKey: ['match-report-narrative-prompt', matchId] }),
  })
}

/** Write this deck's RCQ guide with Claude from the pasted 75 and the
 *  archetypes expected, and store it. A stored guide changes no row count
 *  the heartbeat reads, so the answer goes straight into the guide's query
 *  and that query is invalidated too. */
export const useGenerateRcq = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ key, body }: { key: string; body: RcqGenerateIn }) =>
      post<RcqGuideOut>(`/api/guide/${encodeURIComponent(key)}/rcq/narrative`, body),
    onSuccess: (data, { key }) => {
      queryClient.setQueryData(['rcq-guide', key], data)
      queryClient.invalidateQueries({ queryKey: ['rcq-guide', key] })
      queryClient.invalidateQueries({ queryKey: ['rcq-markdown', key] })
    },
  })
}

/** A pasted RCQ guide, sent with the 75 and the picks it was written
 *  from (`inputs`, the same fields the generate route takes). */
export const usePasteRcq = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ key, inputs, answer }: { key: string; inputs: RcqGenerateIn; answer: string }) =>
      putPasted<RcqGuideOut>({ card: 'rcq', key, inputs }, answer),
    onSuccess: (_data, { key }) =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ['rcq-guide', key] }),
        queryClient.invalidateQueries({ queryKey: ['rcq-markdown', key] }),
      ]),
  })
}

/** The multi-brief prompt for every missing/stale coverage row — fetched
 *  only when the "copy one prompt for all" action is clicked. */
export const useGuideCoveragePrompt = (key: string | undefined, enabled: boolean) =>
  useQuery({
    queryKey: ['guide-coverage-prompt', key],
    queryFn: () =>
      get<CoveragePromptOut>(`/api/guide/${encodeURIComponent(key ?? '')}/coverage/prompt`),
    enabled: enabled && Boolean(key),
  })

/** A pasted answer to the coverage prompt, up to eight briefs at once:
 *  invalidated as for one brief. */
export const usePasteCoverage = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ key, answer }: { key: string; answer: string }) =>
      putPasted<CoverageOut>({ card: 'coverage', key }, answer),
    onSuccess: (_data, { key }) => invalidateBriefWrite(queryClient, key),
  })
}
