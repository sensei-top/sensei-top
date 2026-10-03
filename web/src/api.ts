import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { useMemo } from 'react'
import { versionsInOrder } from './lib/deckOverview'
import { fieldRecordsByKey, type FieldRecord } from './lib/matchups'
import type { RcqGenerateIn, RcqGuideOut, RcqInputs, RcqMarkdownOut, RcqPreviewOut } from './lib/rcq'
import type { components } from './types/api'

/** Types are generated from the API's OpenAPI schema (`pnpm gen:types`), so a
 *  field renamed in FastAPI breaks the build here rather than at runtime. */
export type Deck = components['schemas']['Deck']
export type PlayDrawWinrate = components['schemas']['PlayDrawWinrate']
export type Health = components['schemas']['Health']
export type Match = components['schemas']['Match']
export type MatchDetail = components['schemas']['MatchDetail']
export type MatchGame = components['schemas']['MatchGame']
export type SideboardingOut = components['schemas']['SideboardingOut']
export type SideboardGameOut = components['schemas']['SideboardGameOut']
export type SideboardCardOut = components['schemas']['SideboardCardOut']
export type LiveStatus = components['schemas']['LiveStatus']
export type CurrentMatch = components['schemas']['CurrentMatch']
export type CurrentTurn = components['schemas']['CurrentTurn']
export type CurrentCardEvent = components['schemas']['CurrentCardEvent']
export type TurnZoneCard = components['schemas']['TurnZoneCard']
export type OpponentDeck = components['schemas']['OpponentDeck']
export type OpponentDeckCandidate = components['schemas']['OpponentDeckCandidate']
export type SignatureCard = components['schemas']['SignatureCard']
export type MtgoPick = components['schemas']['MtgoPick']
export type MtgoPickCandidates = components['schemas']['MtgoPickCandidates']
export type MtgoDeckCandidate = components['schemas']['MtgoDeckCandidate']
export type MtgoNeedsPick = components['schemas']['MtgoNeedsPick']
export type MtgoFormat = NonNullable<components['schemas']['MtgoPickIn']['format']>
export type MatchReportOut = components['schemas']['MatchReportOut']
export type ReportFinding = components['schemas']['ReportFinding']
export type ReportEvidence = components['schemas']['ReportEvidence']
export type ReportGap = components['schemas']['ReportGap']
export type MatchSummaryOut = components['schemas']['MatchSummaryOut']
export type SummaryBeat = components['schemas']['SummaryBeat']
export type SummaryGameLine = components['schemas']['SummaryGameLine']
export type SummaryGapGroup = components['schemas']['SummaryGapGroup']
export type NarrativeResponse = components['schemas']['NarrativeResponse']
export type PositionPoint = components['schemas']['PositionPoint']
export type LeaksOut = components['schemas']['LeaksOut']
export type LeakOut = components['schemas']['LeakOut']
export type MetagameStatus = components['schemas']['MetagameStatus']
export type MetaPresence = components['schemas']['MetaPresence']
export type MetaWinrate = components['schemas']['MetaWinrate']
export type MetaMatchup = components['schemas']['MetaMatchup']
export type DeckIdentityOut = components['schemas']['DeckIdentityOut']
export type DeckGuideOut = components['schemas']['DeckGuideOut']
export type CardVerdictOut = components['schemas']['CardVerdictOut']
export type ListDiffOut = components['schemas']['ListDiffOut']
export type ArchetypeShareOut = components['schemas']['ArchetypeShareOut']
export type ArchetypeChangeOut = components['schemas']['ArchetypeChangeOut']
export type PersonalRateOut = components['schemas']['PersonalRateOut']
export type FormatResetOut = components['schemas']['FormatResetOut']
export type GuideNarrativeResponse = components['schemas']['GuideNarrativeResponse']
export type GuideNarrativeOut = components['schemas']['GuideNarrativeOut']
export type MatchupPlanOut = components['schemas']['MatchupPlanOut']
export type CardNoteOut = components['schemas']['CardNoteOut']
export type PlanProblemOut = components['schemas']['PlanProblemOut']
export type GuideMarkdownOut = components['schemas']['GuideMarkdownOut']
export type CoverageOut = components['schemas']['CoverageOut']
export type CoverageRowOut = components['schemas']['CoverageRowOut']
export type BriefPromptOut = components['schemas']['BriefPromptOut']
export type CoveragePromptOut = components['schemas']['CoveragePromptOut']
export type MatchupBriefOut = components['schemas']['MatchupBriefOut']
export type MatchupBriefResponse = components['schemas']['MatchupBriefResponse']
export type PlayAroundOut = components['schemas']['PlayAroundOut']
export type BoardCardOut = components['schemas']['BoardCardOut']
export type StapleOut = components['schemas']['StapleOut']
export type IntermissionOut = components['schemas']['IntermissionOut']
export type IntermissionOpponentOut = components['schemas']['IntermissionOpponentOut']
export type AlternativePlanOut = components['schemas']['AlternativePlanOut']
export type PastBoardingOut = components['schemas']['PastBoardingOut']
export type PastBoardingGameOut = components['schemas']['PastBoardingGameOut']
export type PastBoardingCardOut = components['schemas']['PastBoardingCardOut']
export type LLMStatus = components['schemas']['LLMStatus']
export type CurrentMatchRead = components['schemas']['CurrentMatchRead']
export type KeepGuideOut = components['schemas']['KeepGuideOut']
export type KeyPlayOut = components['schemas']['KeyPlayOut']
export type MulliganCostOut = components['schemas']['MulliganCostOut']
export type HandSlotOut = components['schemas']['HandSlotOut']
export type MulliganRecordOut = components['schemas']['MulliganRecordOut']
export type HandReadOut = components['schemas']['HandReadOut']
export type HandCardOut = components['schemas']['HandCardOut']
export type RevealedCardOut = components['schemas']['RevealedCardOut']
export type LibraryCardOut = components['schemas']['LibraryCardOut']
export type OpeningHandOut = components['schemas']['OpeningHandOut']
export type OpeningHandCardOut = components['schemas']['OpeningHandCardOut']
export type RateModel = components['schemas']['RateModel']
export type DeckLineOut = components['schemas']['DeckLineOut']
export type MatchupLineOut = components['schemas']['MatchupLineOut']
export type LeakLineOut = components['schemas']['LeakLineOut']
export type DeckLeaksOut = components['schemas']['DeckLeaksOut']
export type TurningBucketOut = components['schemas']['TurningBucketOut']
export type FieldLineOut = components['schemas']['FieldLineOut']
export type CoachEvidenceModel = components['schemas']['CoachEvidenceModel']
export type CoachReportSummary = components['schemas']['CoachReportSummary']
export type CoachModelOption = components['schemas']['CoachModelOption']
export type CoachResponse = components['schemas']['CoachResponse']
export type CoachSource = components['schemas']['CoachSource']
export type CoachNarrativeResponse = components['schemas']['CoachNarrativeResponse']

/** How often the dashboard asks whether anything changed. Cheap (a few COUNTs)
 *  compared with refetching every metric on a timer. */
export const HEARTBEAT_MS = 3000

/** A request the API answered with an error status. `status` is what tells
 *  a thing that is not there (404) from a failure. */
export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Whether `error` is the API's 404: the thing asked for is not there. */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

async function get<T>(path: string, params?: Record<string, string | string[]>): Promise<T> {
  const url = new URL(path, window.location.origin)
  for (const [key, value] of Object.entries(params ?? {})) {
    if (Array.isArray(value)) {
      for (const v of value) url.searchParams.append(key, v)
    } else {
      url.searchParams.set(key, value)
    }
  }
  const response = await fetch(url)
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new ApiError(detail?.detail ?? `${response.status} ${response.statusText}`, response.status)
  }
  return response.json() as Promise<T>
}

/** One hook per endpoint. `deckId`/`source` are part of the key, so switching
 *  either refetches instead of showing another deck's or source's numbers.
 *  `source` omitted (rather than defaulted here) mirrors the API's own
 *  default: no `source` param at all means the same 'arena'-only answer the
 *  dashboard has always shown, not a request that happens to spell it out. */
const query = <T,>(key: string, path: string, deckId?: string, source?: string) => ({
  queryKey: [key, deckId ?? 'all', source ?? 'arena'],
  queryFn: () =>
    get<T>(path, {
      ...(deckId ? { deck_id: deckId } : {}),
      ...(source ? { source } : {}),
    }),
})

export const useHealth = () => useQuery(query<Health>('health', '/api/health'))
export const useDecks = () => useQuery(query<Deck[]>('decks', '/api/decks'))

/** Whether a Claude credential is configured right now — never the key
 *  itself. Every `GenerateCard` reads this once to decide between a
 *  generate button and the `CopyPromptCard` fallback (`docs/llm.md`). */
export const useLLMStatus = () =>
  useQuery({ queryKey: ['llm-status'], queryFn: () => get<LLMStatus>('/api/llm/status') })

/** The heartbeat. Polls on its own timer; everything else refetches only when
 *  this reports a new `revision`, so an idle dashboard does no real work. */
export const useLive = () =>
  useQuery({
    ...query<LiveStatus>('live', '/api/live'),
    refetchInterval: HEARTBEAT_MS,
    staleTime: 0,
  })

const matchesQuery = (deckId?: string, source?: string, limit?: number) => ({
  queryKey: ['matches', deckId ?? 'all', source ?? 'arena', limit ?? 'default'],
  queryFn: () =>
    get<Match[]>('/api/matches', {
      ...(deckId ? { deck_id: deckId } : {}),
      ...(source ? { source } : {}),
      ...(limit ? { limit: String(limit) } : {}),
    }),
})

/** `limit` omitted is the route's own default (50); it is part of the key,
 *  so a page asking for 500 never reads a list of 50 or the reverse. */
export const useMatches = (deckId?: string, source?: string, limit?: number) =>
  useQuery(matchesQuery(deckId, source, limit))

/** The route's maximum, which a deck's pages ask for per version. */
export const DECK_MATCH_LIMIT = 500

/** Several queries read as one: `data` holds each query's answer in the
 *  order asked, once every one has answered; `error` is the first failure. */
export type AllQueries<T> = { data: T[] | undefined; isPending: boolean; error: Error | null }

function all<T>(results: UseQueryResult<T>[]): AllQueries<T> {
  const error = results.find((result) => result.error)?.error ?? null
  const isPending = results.some((result) => result.isPending)
  return {
    data: error || isPending ? undefined : results.map((result) => result.data as T),
    isPending,
    error,
  }
}

/** A deck's matches over the versions given, one request per version (the
 *  metric routes take one `deck_id`), each keyed and limited as
 *  `useMatches(id, 'all', DECK_MATCH_LIMIT)` is, so a list already in hand is
 *  not asked for twice. */
export const useDeckMatches = (deckIds: string[]) =>
  useQueries({
    queries: deckIds.map((deckId) => matchesQuery(deckId, 'all', DECK_MATCH_LIMIT)),
    combine: all<Match[]>,
  })

/** A deck's games on the play and on the draw over the versions given, one
 *  request per version: each answers up to two rows, `on_play` true and
 *  false. */
export const useDeckPlayDraw = (deckIds: string[]) =>
  useQueries({
    queries: deckIds.map((deckId) =>
      query<PlayDrawWinrate[]>('play-draw', '/api/metrics/play-draw', deckId, 'all'),
    ),
    combine: all<PlayDrawWinrate[]>,
  })

/** One match's detail, read for its card art alone (Home). Keyed apart
 *  from `useMatchDetail`, with `staleTime: 'static'`: a finished match's
 *  cards do not change, so the heartbeat's invalidation never asks again. */
export const useMatchArt = (matchIds: string[]) =>
  useQueries({
    queries: matchIds.map((matchId) => ({
      queryKey: ['match-art', matchId],
      queryFn: () => get<MatchDetail>(`/api/matches/${matchId}`),
      staleTime: 'static' as const,
    })),
  })

/** One past match with every game's turns and cards. Keyed by match id, not
 *  deck: the history drill-down outlives the deck filter. */
export const useMatchDetail = (matchId: string) =>
  useQuery({
    queryKey: ['match-detail', matchId],
    queryFn: () => get<MatchDetail>(`/api/matches/${matchId}`),
  })

/** What was actually boarded, per game — empty for a match that never
 *  resubmitted a deck (Bo1, or a Bo3 that ended before any boarding). */
export const useSideboarding = (matchId: string) =>
  useQuery({
    queryKey: ['sideboarding', matchId],
    queryFn: () => get<SideboardingOut>(`/api/matches/${matchId}/sideboarding`),
  })

/** The match being played right now, or null between games. Deliberately not
 *  on its own timer: the heartbeat counts card events, so a play mid-turn
 *  moves the revision and invalidates this like every other query. */
export const useCurrentMatch = () =>
  useQuery(query<CurrentMatch | null>('current-match', '/api/current-match'))

/** The live matchup brief for the match in progress — what to play around
 *  and the game-2 plan, from `brief/`. Every read here is free and local:
 *  this route has no generate mutation of its own (unlike the match report
 *  and the deck guide, `docs/llm.md`), so it always serves whatever was
 *  imported or filled by a guide plus the prompt to write one from, and
 *  riding the heartbeat like every other query is correct. */
export const useCurrentMatchBrief = () =>
  useQuery(query<MatchupBriefResponse>('current-match-brief', '/api/current-match/brief'))

/** The opening-hand read, keep guide, opponent-hand read and our own
 *  remaining library for the match in progress — free and local, and now a
 *  fast, request-time replay of the current match rather than a stale
 *  projected `turns` row (`table/live.py`).
 *
 *  One scoped exception to "only /api/live is on a timer"
 *  (docs/frontend.md): this route rides its own unconditional 1s timer
 *  rather than gating on a projected match existing. It used to gate on
 *  `Boolean(current.data)` — but that data comes from `project()`, whose
 *  full-rebuild floor measured at 7.55s on a real database
 *  (`projector/live_state.py`), so the fast poll was off for several
 *  seconds at exactly the two moments it exists to cover: the opening
 *  mulligan offer (a measured 5-second median decision window) and the
 *  first turns of a new match. Unconditional is affordable now that the
 *  route it drives replays only the current match (0.04-0.2s) instead of
 *  reading data a full rebuild produced — this hook is only ever mounted
 *  while `CurrentMatchView` is, so an idle dashboard on another tab does
 *  none of this work regardless.
 */
export const useCurrentMatchRead = () =>
  useQuery({
    ...query<CurrentMatchRead>('current-match-read', '/api/current-match/read'),
    refetchInterval: 1000,
  })

/** Ranked deck candidates for the list that corrects an opponent's deck.
 *  Only fetched while the list is open: `enabled` keeps it off a match
 *  page's own requests, since most matches never need it. */
export const useOpponentDeckCandidates = (matchId: string, enabled: boolean) =>
  useQuery({
    queryKey: ['opponent-deck-candidates', matchId],
    queryFn: () => get<OpponentDeckCandidate[]>(`/api/matches/${matchId}/opponent-deck/candidates`),
    enabled,
  })

/** The MTGO decks to offer for one match, best match first, with the
 *  match's existing pick. Only fetched while the picker is on screen. */
export const useMtgoPickCandidates = (matchId: string, enabled: boolean) =>
  useQuery({
    queryKey: ['mtgo-pick-candidates', matchId],
    queryFn: () => get<MtgoPickCandidates>(`/api/matches/${matchId}/mtgo-pick/candidates`),
    enabled,
  })

/** The MTGO matches still waiting for the user to confirm a deck or a
 *  format: Home's "Needs a deck" queue. */
export const useMtgoNeedsPick = () =>
  useQuery({ queryKey: ['mtgo-needs-pick'], queryFn: () => get<MtgoNeedsPick[]>('/api/mtgo/needs-pick') })

/** The post-game report: local, deterministic findings computed fresh from
 *  already-projected data. Free and local, so an ordinary query — it rides
 *  the heartbeat invalidation like every other read, which keeps it honest
 *  as `cards` gets downloaded or an opponent-deck pick changes what the
 *  analyzers can see (see review/__init__.py for why it is never stored). */
export const useMatchReport = (matchId: string) =>
  useQuery({
    queryKey: ['match-report', matchId],
    queryFn: () => get<MatchReportOut>(`/api/matches/${matchId}/report`),
  })

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

/** The leak finder's recurring patterns over every source, ordered by the
 *  size of the gap (`review/leaks.py`). Free and local: an ordinary query
 *  on the heartbeat. */
export const useLeaks = () =>
  useQuery({
    queryKey: ['leaks', 'all'],
    queryFn: () => get<LeaksOut>('/api/review/leaks', { source: 'all' }),
  })

/** The stored training-plan prose over the leak finder's own ranked output
 *  (every deck, unscoped — see `review/leaks_store.py`), and always the
 *  prompt to (re)write it from. Free and local to fetch; an ordinary query
 *  on the heartbeat like the leak finder itself. */
export const useLeaksNarrative = () =>
  useQuery({
    queryKey: ['leaks-narrative'],
    queryFn: () => get<NarrativeResponse>('/api/review/leaks/narrative'),
  })

/** The coach tab's free, local evidence bundle — population, by-deck/role/
 *  mulligan/opponent rollups, leaks, turning points and the field, plus
 *  every report ever written. Deck-independent (no `deckId` in the key):
 *  the coach reasons across every deck at once, unlike the guide. An
 *  ordinary query on the heartbeat like the match report and the deck
 *  guide, even though a real corpus measures ~7.5s to rebuild — `CoachView`
 *  gates its own cards on `isPending` rather than letting that read as an
 *  empty flash. */
export const useCoach = () =>
  useQuery({ queryKey: ['coach'], queryFn: () => get<CoachResponse>('/api/coach') })

/** The latest coach report, the prompt to write the next one from, and
 *  whether the evidence has drifted since it was written. A separate query
 *  from `useCoach` (neither `enabled`-gates the other), so the two ~7.5s
 *  evidence rebuilds happen in parallel over the network instead of one
 *  waiting on the other. */
export const useCoachNarrative = () =>
  useQuery({
    queryKey: ['coach-narrative'],
    queryFn: () => get<CoachNarrativeResponse>('/api/coach/narrative'),
  })

/** One past report exactly as it was written, for `/coach/:id`. Not
 *  fetched while `id` is null. */
export const useCoachReport = (id: number | null) =>
  useQuery({
    queryKey: ['coach-report', id],
    queryFn: () => get<CoachNarrativeResponse>(`/api/coach/narrative/${id}`),
    enabled: id != null,
  })

/** Every deck with recorded matches, one row per deck however many
 *  versions it has (guide/deck.py): the Decks page's tiles and the
 *  layout's way from an address to a deck. */
export const useGuideDecks = () =>
  useQuery({ queryKey: ['guide-decks'], queryFn: () => get<DeckIdentityOut[]>('/api/guide/decks') })

/** A deck's versions, as a deck's pages find them from its key:
 *  `deckIds`, the identity's `deck_ids` (`fallback` until the identity is
 *  in hand; the layout has read both lists before drawing a page), and
 *  `versions`, their rows of `/api/decks` newest first (`versionsInOrder`). */
export function useDeckVersions(deckKey: string, fallback: string[]): { deckIds: string[]; versions: Deck[] } {
  const identities = useGuideDecks()
  const decks = useDecks()
  const deckIds = identities.data?.find((identity) => identity.key === deckKey)?.deck_ids ?? fallback
  const versions = useMemo(() => versionsInOrder(deckIds, decks.data ?? []), [deckIds, decks.data])
  return { deckIds, versions }
}

/** One deck's whole evidence bundle. Free and local, so an ordinary query on
 *  the heartbeat like the match report and the leak finder. */
export const useGuide = (key: string | undefined) =>
  useQuery({
    queryKey: ['guide', key],
    queryFn: () => get<DeckGuideOut>(`/api/guide/${encodeURIComponent(key ?? '')}`),
    enabled: Boolean(key),
  })

/** This deck's stored narrative, and always the prompt to (re)write it
 *  from. Free and local to read — the write is `useGenerateGuideNarrative`
 *  below, or `sensei-top guide --deck KEY --import FILE` with no
 *  credential configured. Riding the heartbeat as an ordinary query is what
 *  makes either path show up in the tab within a beat, generate button or
 *  terminal alike. */
export const useGuideNarrative = (key: string | undefined) =>
  useQuery({
    queryKey: ['guide-narrative', key],
    queryFn: () =>
      get<GuideNarrativeResponse>(`/api/guide/${encodeURIComponent(key ?? '')}/narrative`),
    enabled: Boolean(key),
  })

/** The evidence-only guide document, for copy or save. No narrative call —
 *  fetched fresh each time the export panel is opened rather than cached
 *  under the heartbeat, since it is only ever read right before a copy. */
export const useGuideMarkdown = (key: string | undefined, enabled: boolean) =>
  useQuery({
    queryKey: ['guide-markdown', key],
    queryFn: () => get<GuideMarkdownOut>(`/api/guide/${encodeURIComponent(key ?? '')}/markdown`),
    enabled: enabled && Boolean(key),
  })

/** The RCQ preview: the pasted 75 read back against this deck's evidence,
 *  the field it meets and the prompt. Free and local, so an ordinary query
 *  on the heartbeat, keyed by `previewKey` so the same question is asked
 *  once; the page hands it inputs already debounced. The answer before
 *  stays on the page while the next is asked, so typing does not blank
 *  it. Off while the 75 is empty. */
export const useRcqPreview = (key: string, inputs: RcqInputs, inputsKey: string) =>
  useQuery({
    queryKey: ['rcq-preview', key, inputsKey],
    queryFn: () =>
      get<RcqPreviewOut>(`/api/guide/${encodeURIComponent(key)}/rcq/preview`, {
        decklist: inputs.decklist,
        expected: inputs.expected,
        ...(inputs.own ? { own: inputs.own } : {}),
      }),
    enabled: Boolean(key) && inputs.decklist.trim() !== '',
    placeholderData: keepPreviousData,
  })

/** This deck's latest stored RCQ guide, or `status: 'none'`. Free and
 *  local, an ordinary query on the heartbeat. */
export const useRcqGuide = (key: string) =>
  useQuery({
    queryKey: ['rcq-guide', key],
    queryFn: () => get<RcqGuideOut>(`/api/guide/${encodeURIComponent(key)}/rcq`),
    enabled: Boolean(key),
  })

/** The latest RCQ guide as Markdown, for copy or download. Keyed by the
 *  guide's id, so a guide written since is fetched afresh; off until one
 *  is stored. */
export const useRcqMarkdown = (key: string, guideId: number | null) =>
  useQuery({
    queryKey: ['rcq-markdown', key, guideId],
    queryFn: () => get<RcqMarkdownOut>(`/api/guide/${encodeURIComponent(key)}/rcq/markdown`),
    enabled: Boolean(key) && guideId != null,
  })

/** How well this deck's cached matchup briefs cover the archetypes it
 *  actually faces and the field's own top archetypes (brief/coverage.py).
 *  Free and local, so an ordinary query on the heartbeat. */
export const useGuideCoverage = (key: string | undefined) =>
  useQuery({
    queryKey: ['guide-coverage', key],
    queryFn: () => get<CoverageOut>(`/api/guide/${encodeURIComponent(key ?? '')}/coverage`),
    enabled: Boolean(key),
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

/** The multi-brief prompt for every missing/stale coverage row — fetched
 *  only when the "copy one prompt for all" action is clicked. */
export const useGuideCoveragePrompt = (key: string | undefined, enabled: boolean) =>
  useQuery({
    queryKey: ['guide-coverage-prompt', key],
    queryFn: () =>
      get<CoveragePromptOut>(`/api/guide/${encodeURIComponent(key ?? '')}/coverage/prompt`),
    enabled: enabled && Boolean(key),
  })

/** How stale the archetype cache and the tournament corpus are, and how
 *  often the classifier actually names an opponent's own deck. Read once
 *  when Field mounts, not on the heartbeat — this is a diagnostic,
 *  not a metric that moves as the user plays. Also the source of
 *  `format_reset_start`, which `FieldView`/`useFieldRecords` use to decide
 *  whether a "Since the last reset" window is even offered. */
export const useMetagameStatus = () =>
  useQuery({ queryKey: ['metagame-status'], queryFn: () => get<MetagameStatus>('/api/metagame/status') })

/** The window a metagame query is scoped to: an explicit reset-start date
 *  ("since last reset") or a day count back from today — never both. Mirrors
 *  the API's own since-overrides-days rule (`api/routes/metagame.py::_since_cutoff`). */
export type MetaWindow = { since: string } | { days: number }

const windowParams = (metaWindow: MetaWindow): Record<string, string> =>
  'since' in metaWindow ? { since: metaWindow.since } : { days: String(metaWindow.days) }

/** Archetype share of the field. Every tier comes back, never blended: a
 *  Tier C league's decklists are only ever the undefeated ones, so mixing
 *  its count into Tier A's share would silently favour whatever archetype
 *  happens to win leagues (see the API route's own docstring). `metaWindow`
 *  is `undefined` until the caller knows whether a format reset exists
 *  (`useMetagameStatus`'s `format_reset_start`) — the query stays disabled
 *  until then, so no request ever fires with the wrong default window. */
export const useMetaPresence = (metaWindow: MetaWindow | undefined) =>
  useQuery({
    queryKey: ['meta-presence', metaWindow],
    queryFn: () => get<MetaPresence[]>('/api/metagame/presence', windowParams(metaWindow as MetaWindow)),
    enabled: metaWindow !== undefined,
  })

/** Win rate by archetype, Tiers A, B and D blended — Tier C is excluded by
 *  the view itself, a league has no losses in it to compute a rate from. Same
 *  `metaWindow`-gated-`enabled` rule as `useMetaPresence`. */
export const useMetaWinrate = (metaWindow: MetaWindow | undefined) =>
  useQuery({
    queryKey: ['meta-winrate', metaWindow],
    queryFn: () => get<MetaWinrate[]>('/api/metagame/winrate', windowParams(metaWindow as MetaWindow)),
    enabled: metaWindow !== undefined,
  })

/** The field's record of each archetype, by its archetype key, pooled over
 *  every label the key carries (`lib/matchups.ts`'s `fieldRecordsByKey`),
 *  as a deck's Matchups and a pairing's page join it (`archetypeKeyOf`).
 *  Empty until the numbers come, and when they fail: the field never holds
 *  a page. */
export function useFieldRecords(): Map<string, FieldRecord> {
  // The field's win rate uses the same post-reset window as Field
  // whenever a reset is detected: pooling a pre-ban field rate into a
  // post-ban matchup would repeat the mistake docs/metagame.md's
  // "format-reset boundary" section exists to prevent. With no reset
  // detected, a year is generous enough to have field data behind most
  // matchups without needing its own control here; Field owns the
  // window picker for anything more specific.
  const status = useMetagameStatus()
  const resetStart = status.data?.format_reset_start
  const fieldWindow = status.data ? (resetStart ? { since: resetStart } : { days: 365 }) : undefined
  const fieldWinrate = useMetaWinrate(fieldWindow)
  return useMemo(() => fieldRecordsByKey(fieldWinrate.data ?? []), [fieldWinrate.data])
}

/** Archetype-vs-archetype, from real completed matches. `tiers` defaults to
 *  Tier A alone (paper tournaments of 64+ players); pass `['A','B']` to add
 *  MTGO challenges' bracket rounds, and `['A','B','D']` to add smaller paper
 *  events' rounds too (`lib/field.ts`'s `PAIRS_TIERS`). It sends each tier as its own
 *  `tier` parameter and the caller's window as `since` or `days`, never
 *  neither: the route counts the whole corpus when given no window, so the
 *  hook stays disabled while `metaWindow` is `undefined`, the same rule as
 *  `useMetaPresence`, and the table never shows the whole corpus for one
 *  frame before the window arrives. */
export const useMetaMatchups = (metaWindow: MetaWindow | undefined, tiers: string[] = ['A']) =>
  useQuery({
    queryKey: ['meta-matchups', tiers, metaWindow],
    queryFn: () =>
      get<MetaMatchup[]>('/api/metagame/matchups', {
        tier: tiers,
        ...windowParams(metaWindow as MetaWindow),
      }),
    enabled: metaWindow !== undefined,
  })

/** Sent on every write: `api/guard.py` refuses a non-GET request without it.
 *  A cross-site page can't add a custom header without a CORS preflight, and
 *  nothing here ever answers one, so it can't spend a Claude credential or
 *  write a row. Only its presence is checked. */
const CLIENT_HEADERS = { 'X-Tracker-Client': 'dashboard' } as const

async function put<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(new URL(path, window.location.origin), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...CLIENT_HEADERS },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? `${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

/** Pick the opponent's deck from the ranked candidates, or clear the pick with
 *  an empty label. The one write that touches this match's own row directly
 *  — see the generate mutations below for the other writes this app makes
 *  (an authored narrative, never a derived one).
 *
 *  The explicit invalidation is not an optimisation, it is required: the
 *  heartbeat's revision is built from row counts, and an override changes none
 *  of them, so nothing would ever refetch on its own. `live` is left alone —
 *  invalidating it would only cost a request without changing its answer.
 *  `opponent-deck-candidates` is in the list too: a pick flips that match's
 *  `picked` flag in the candidate list itself (rank_candidates recomputes it
 *  from `opponent_deck_override`), which both the picker popover and the
 *  current-match tab's "play around" card read — without this, picking a
 *  deck mid-match would update the label but leave the play-around hint
 *  pointed at the classifier's old guess until the next heartbeat happened
 *  to refetch it for an unrelated reason. */
export const useSetOpponentDeck = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      matchId,
      label,
      archetypeKey,
    }: {
      matchId: string
      label: string
      archetypeKey?: string | null
    }) =>
      put<OpponentDeck>(`/api/matches/${matchId}/opponent-deck`, {
        label,
        archetype_key: archetypeKey ?? null,
      }),
    onSettled: () => {
      for (const key of ['matches', 'current-match', 'matchups', 'opponent-deck-candidates']) {
        queryClient.invalidateQueries({ queryKey: [key] })
      }
    },
  })
}

/** Confirm an MTGO match's deck and format, replacing any earlier answer
 *  whole: `deckId` null with a `format` is a format-only pick ("No list").
 *  A pick changes no row count, so nothing refetches unless this says so.
 *  The response goes straight into the picker's own query, so the summary
 *  shows the new pick at once. Then everything but the heartbeat is
 *  invalidated, as the shell does when the projection moves: a pick changes
 *  which deck and format a match belongs to, which most reads see, so it
 *  refetches what the heartbeat does. */
export const useSetMtgoPick = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      matchId,
      deckId,
      format,
    }: {
      matchId: string
      deckId: string | null
      format: MtgoFormat | null
    }) => put<MtgoPick>(`/api/matches/${matchId}/mtgo-pick`, { deck_id: deckId, format }),
    onSuccess: (pick, { matchId }) => {
      queryClient.setQueryData<MtgoPickCandidates>(['mtgo-pick-candidates', matchId], (old) =>
        old ? { ...old, current: pick } : old,
      )
    },
    onSettled: () => {
      queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'live' })
    },
  })
}

/** Every `POST .../narrative` route but the coach's and the RCQ guide's
 *  takes no body — `match_id`/`key` is already in the path, and the
 *  credential and model come from server-side config, never from the
 *  browser (`docs/llm.md`). The coach's route takes an optional `body` that
 *  lets its model dropdown (`useGenerateCoachNarrative`) override the
 *  configured model for one report; the RCQ guide's takes the pasted 75
 *  and the archetypes expected (`useGenerateRcq`). Every other caller
 *  omits it and gets the same bodiless POST as before. */
async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(new URL(path, window.location.origin), {
    method: 'POST',
    headers:
      body !== undefined
        ? { 'Content-Type': 'application/json', ...CLIENT_HEADERS }
        : { ...CLIENT_HEADERS },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? `${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

/** Write this match's "Coach's summary" with Claude, and store it.
 *
 *  The explicit invalidation is required, same reasoning as
 *  `useSetOpponentDeck` above: nothing about a stored narrative changes the
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
 *  every matchup plan it covers into `matchup_brief`
 *  (`brief/from_guide.py`), so the live matchup brief on the Current match
 *  tab needs invalidating too, not just this deck's own narrative. */
export const useGenerateGuideNarrative = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (key: string) =>
      post<GuideNarrativeResponse>(`/api/guide/${encodeURIComponent(key)}/narrative`),
    onSuccess: (_data, key) => {
      queryClient.invalidateQueries({ queryKey: ['guide-narrative', key] })
      queryClient.invalidateQueries({ queryKey: ['current-match-brief'] })
    },
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

/** Write a fresh coach report with Claude — high reasoning effort, web
 *  search enabled, and measured in minutes rather than seconds. No
 *  client-side timeout and no optimistic update: `GenerateCard` already
 *  shows elapsed time while this is pending.
 *
 *  `model` is the Coach tab's dropdown choice: a `REPORT_MODELS` id posts
 *  `{ model }` to override the configured coach model for this one report;
 *  `null` means "leave it alone" and posts no body at all, so the server
 *  keeps using the configured model. */
export const useGenerateCoachNarrative = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (model: string | null) =>
      post<CoachNarrativeResponse>(
        '/api/coach/narrative',
        model !== null ? { model } : undefined,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['coach'] })
      queryClient.invalidateQueries({ queryKey: ['coach-narrative'] })
    },
  })
}
