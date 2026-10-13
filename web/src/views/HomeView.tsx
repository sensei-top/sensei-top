import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useGuideDecks,
  useLeaks,
  useLive,
  useMatchArt,
  useMatches,
  useFormats,
  useMetagameStatus,
  useMetaPresence,
  useMtgoNeedsPick,
  type MatchDetail,
  type MetaWindow,
} from '../api'
import { CoachPointer } from '../components/home/CoachPointer'
import { FieldAgainstYou } from '../components/home/FieldAgainstYou'
import { FirstRun } from '../components/home/FirstRun'
import { HomeDecks } from '../components/home/HomeDecks'
import { NeedsDeckCard } from '../components/home/NeedsDeckCard'
import { RecentMatches } from '../components/home/RecentMatches'
import { SessionHero } from '../components/home/SessionHero'
import { ThreeThings, ThreeThingsLoading, type Thing } from '../components/home/ThreeThings'
import { WeeklyWinrate } from '../components/home/WeeklyWinrate'
import { ErrorNote, Skeleton } from '../components/ui'
import {
  firstPattern,
  HOME_MATCH_LIMIT,
  homeDecks,
  homeField,
  isFirstRun,
  lastFinished,
  lastSession,
  lastThirtyDays,
  recentMatches,
  threeThings,
  weeklyWinrate,
  type ThingKind,
} from '../lib/home'
import { castCards, takeUnused, type ArtCard } from '../lib/matchArt'
import { useNow } from '../lib/time'

const MINUTE = 60_000

/** `/`: every source, no filter. First run alone until a match is
 *  recorded; then the last session, three things worth a look, recent
 *  matches beside the weeks, the deck tiles, and the field beside the
 *  coach's pointer. Every count is `lib/home.ts`'s. A request that fails
 *  says so in the card that needed it; one on its way holds that card's
 *  place. */
export function HomeView() {
  const now = useNow()
  // The counts move with the minute, not with every second's re-render.
  const minute = Math.floor(now / MINUTE) * MINUTE

  const live = useLive()
  const matches = useMatches(undefined, 'all', HOME_MATCH_LIMIT)
  const identities = useGuideDecks()
  const leaks = useLeaks()
  // Home reads the field of the default format, named explicitly so the
  // status, the presence and the viewer's record can't drift apart.
  const formats = useFormats()
  const format = formats.data?.default
  const status = useMetagameStatus(format, format !== undefined)
  const resetStart = status.data?.format_reset_start ?? null
  // Undefined until the status says whether a reset exists, so the field is
  // never asked for with a window guessed ahead of it: the same window and
  // the same key as the Field page's default.
  const metaWindow: MetaWindow | undefined = status.data
    ? resetStart
      ? { since: resetStart }
      : { days: 90 }
    : undefined
  const presence = useMetaPresence(metaWindow, format)
  const needsPick = useMtgoNeedsPick()

  const rows = matches.data
  // Cut short only when more matches are recorded than the list holds: with
  // exactly the limit recorded, the list is every match. The heartbeat
  // counts every source, as the list does; without it, a full list is
  // taken as cut short.
  const listFull =
    (rows?.length ?? 0) >= HOME_MATCH_LIMIT && (live.data == null || live.data.matches > (rows?.length ?? 0))

  const counted = useMemo(() => {
    if (!rows) return null
    const session = lastSession(rows)
    return {
      session,
      thirty: lastThirtyDays(rows, session, minute),
      last: lastFinished(rows),
      recent: recentMatches(rows),
    }
  }, [rows, minute])
  // The weeks do not read the time: rebuilt only when the list changes, so
  // the chart's data keeps its identity from one minute to the next.
  const weeks = useMemo(() => (rows ? weeklyWinrate(rows, listFull) : null), [rows, listFull])
  // What the weeks' chart reads of the time: the year alone, so it renders
  // again only when the weeks or the year change.
  const yearStart = new Date(new Date(minute).getFullYear(), 0, 1).getTime()

  const pattern = useMemo(() => (leaks.data ? firstPattern(leaks.data.leaks) : null), [leaks.data])
  const field = useMemo(
    () =>
      rows && presence.data && identities.data && format
        ? homeField(presence.data, rows, identities.data, resetStart, listFull, minute, format)
        : null,
    [rows, presence.data, identities.data, resetStart, listFull, minute, format],
  )
  const decks = useMemo(
    () => (rows && identities.data ? homeDecks(identities.data, rows, minute) : []),
    [rows, identities.data, minute],
  )

  const fieldError = formats.error ?? status.error ?? presence.error ?? identities.error
  const fieldPending = !fieldError && (formats.isPending || status.isPending || presence.isPending || identities.isPending)
  const thingsPending = leaks.isPending || fieldPending

  // A candidate whose request failed still takes its place, as the failure.
  const kinds: ThingKind[] = counted
    ? threeThings({
        match: counted.last != null,
        pattern: leaks.error != null || pattern != null,
        field: fieldError != null || field != null,
      })
    : []

  // The matches whose cards the page shows, seven at most: the newest
  // finished one (the hero, the last match, the pattern), the field's, and
  // each deck's. Read once each and never again.
  const newestId = counted?.last?.match_id ?? null
  const artIds = unique([
    newestId,
    kinds.includes('field') ? (field?.artMatchId ?? null) : null,
    ...decks.map((deck) => deck.artMatchId),
  ])
  const artQueries = useMatchArt(artIds)
  const details = new Map<string, MatchDetail | undefined>(artIds.map((id, index) => [id, artQueries[index]?.data]))

  // One card appears once on the page, taken in the page's order.
  const used = new Set<number>()
  const newest = newestId ? details.get(newestId) : undefined
  const heroArt = counted?.session ? takeUnused(castCards(newest, 'self'), used) : null
  const things: Thing[] = []
  for (const kind of kinds) {
    if (kind === 'match' && counted?.last) {
      things.push({ kind, match: counted.last, art: takeUnused(castCards(newest, 'opponent'), used) })
    } else if (kind === 'pattern') {
      if (leaks.error) things.push({ kind: 'error', key: 'pattern', error: leaks.error })
      else if (pattern) things.push({ kind, pattern, art: takeUnused(castCards(newest, 'self'), used) })
    } else if (kind === 'field') {
      if (fieldError) things.push({ kind: 'error', key: 'field', error: fieldError })
      else if (field) {
        const detail = field.artMatchId ? details.get(field.artMatchId) : undefined
        things.push({ kind, field, art: takeUnused(castCards(detail, 'opponent'), used) })
      }
    }
  }
  const deckArt = new Map<string, ArtCard | null>(
    decks.map((deck) => {
      const detail = deck.artMatchId ? details.get(deck.artMatchId) : undefined
      return [deck.key, takeUnused(castCards(detail, 'self'), used)]
    }),
  )

  // The tracker cannot be reached: the shell's own callout says so.
  if (matches.error && live.isError) return null
  if (matches.isPending) return <HomeLoading />
  if (matches.error) return <ErrorNote error={matches.error} />
  if (!counted) return <HomeLoading />
  if (isFirstRun(rows ?? [])) return <FirstRun live={live.data} />

  // With no finished week the chart draws nothing, and the recent matches
  // take the whole row.
  const showWeeks = weeks != null && weeks.weeks.some((week) => week.played > 0)
  const showField = fieldPending || fieldError != null || field != null
  return (
    <div className="space-y-6 md:space-y-8">
      {counted.session && (
        <SessionHero session={counted.session} thirty={counted.thirty} art={heroArt} now={minute} />
      )}

      {thingsPending ? <ThreeThingsLoading /> : <ThreeThings things={things} now={now} />}

      {/* Hidden while it loads and when the queue is empty; a failed
          request says so here, not by vanishing. */}
      {needsPick.error ? (
        <ErrorNote error={needsPick.error} />
      ) : (
        needsPick.data && <NeedsDeckCard matches={needsPick.data} />
      )}

      {counted.recent.length > 0 && (
        <div className="grid gap-4 md:gap-6 lg:grid-cols-3">
          <div className={`min-w-0 ${showWeeks ? 'lg:col-span-2' : 'lg:col-span-3'}`}>
            <RecentMatches matches={counted.recent} total={live.data?.matches} />
          </div>
          {showWeeks && weeks && (
            <div className="min-w-0">
              <WeeklyWinrate weeks={weeks} yearStart={yearStart} />
            </div>
          )}
        </div>
      )}

      {identities.error ? (
        <ErrorNote error={identities.error} />
      ) : identities.isPending ? (
        <Skeleton className="h-[230px] rounded-card" />
      ) : (
        <HomeDecks decks={decks} art={deckArt} now={minute} />
      )}

      <div className="grid gap-4 md:gap-6 lg:grid-cols-3">
        {showField && (
          <div className="min-w-0 lg:col-span-2">
            {fieldError ? (
              <ErrorNote error={fieldError} />
            ) : fieldPending || !field ? (
              <Skeleton className="h-[360px] rounded-card" />
            ) : (
              <FieldAgainstYou field={field} now={minute} />
            )}
          </div>
        )}
        <div className={`min-w-0 ${showField ? '' : 'lg:col-span-3'}`}>
          <CoachPointer />
        </div>
      </div>
    </div>
  )
}

/** The page's outline while its matches are on their way. */
function HomeLoading() {
  const { t } = useTranslation()
  return (
    <div className="space-y-6 md:space-y-8" role="status" aria-label={t('common.loading')}>
      <Skeleton className="h-[360px] rounded-hero md:h-[304px]" />
      <ThreeThingsLoading />
    </div>
  )
}

function unique(ids: (string | null)[]): string[] {
  return [...new Set(ids.filter((id): id is string => id != null))]
}
