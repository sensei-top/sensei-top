import { useMemo } from 'react'
import { useLive, useMatches, useMetaMatchups, useMetaPresence, useMetaWinrate, useMetagameStatus } from '../api'
import { FieldControls } from '../components/field/FieldControls'
import { FieldTiles } from '../components/field/FieldTiles'
import { MatchupsCard } from '../components/field/MatchupsCard'
import { ShareCard } from '../components/field/ShareCard'
import { SourcesDisclosure } from '../components/field/SourcesDisclosure'
import { WinrateCard } from '../components/field/WinrateCard'
import { EmptyState, ErrorNote, Loading, TextLink } from '../components/ui'
import type { FieldParam, FieldParams, Pairs, Tier } from '../lib/field'
import {
  PAIRS,
  PAIRS_TIERS,
  TIERS,
  TIER_KIND,
  defaultPairs,
  defaultTier,
  defaultWindow,
  listCount,
  listShort,
  matchupRows,
  metaWindowOf,
  nextPairs,
  pairsOf,
  paramFor,
  recordAgainstRows,
  resetOf,
  shareAction,
  shareRows,
  tierOf,
  windowOf,
  windowStartOf,
  windowWords,
  winrateRows,
} from '../lib/field'
import { HOME_MATCH_LIMIT } from '../lib/home'
import { useNow } from '../lib/time'
import { placeById } from '../shell/places'

const MINUTE = 60_000

/** `/field`: what is being played in tournaments and how it does, in the
 *  window and tier the address names (`lib/field.ts`), with the viewer's own
 *  record against each deck. Top to bottom: the controls, three tiles, the
 *  share list, the win-rate table, the matchups table and, closed, where
 *  the numbers come from. The three metagame reads wait for the status, so
 *  none is asked for with a window guessed ahead of knowing whether a reset
 *  exists; the matchups wait for the lists too when the address does not
 *  name their tiers, since the default depends on them. The viewer's
 *  matches are read as Home reads them, every source and every deck. */
export function FieldView({
  params,
  setParam,
}: {
  params: FieldParams
  setParam: (key: FieldParam, value: string | undefined) => void
}) {
  const now = useNow()
  // The counts move with the minute, not with every second's re-render.
  const minute = Math.floor(now / MINUTE) * MINUTE

  const status = useMetagameStatus()
  const reset = resetOf(status.data?.format_reset_start)
  const window = windowOf(params.window, reset)
  const metaWindow = status.data ? metaWindowOf(window, reset) : undefined
  const presence = useMetaPresence(metaWindow)
  const winrate = useMetaWinrate(metaWindow)

  const presenceRows = presence.data
  const namedPairs: Pairs | null = PAIRS.find((candidate) => candidate === params.pairs) ?? null
  const pairs: Pairs | null = presenceRows ? pairsOf(params.pairs, presenceRows) : namedPairs
  const matchups = useMetaMatchups(pairs ? metaWindow : undefined, pairs ? PAIRS_TIERS[pairs] : undefined)

  const live = useLive()
  const matches = useMatches(undefined, 'all', HOME_MATCH_LIMIT)

  // While the lists load, the tier the address names, as for the pairs, so
  // the tier's control stays drawn across a change of window.
  const namedTier = TIERS.find((candidate) => candidate === params.tier) ?? null
  const tier: Tier | null = presenceRows ? tierOf(params.tier, presenceRows) : namedTier
  const windowStart = windowStartOf(window, reset, minute)
  const words = windowWords(window, reset, minute)

  const share = useMemo(() => (presenceRows && tier ? shareRows(presenceRows, tier) : []), [presenceRows, tier])
  // The records move with the minute and the lists, not with every second's
  // re-render.
  const counted = useMemo(() => {
    const rows = matches.data
    if (!rows) return null
    return {
      records: share.map((row) => recordAgainstRows(rows, [row], windowStart)),
      topTwo: recordAgainstRows(rows, share.slice(0, 2), windowStart),
      short: listShort(rows, live.data?.matches, windowStart),
    }
  }, [matches.data, share, windowStart, live.data?.matches])
  const winrates = useMemo(() => winrateRows(winrate.data ?? []), [winrate.data])
  const pairRows = useMemo(() => (matchups.data ? matchupRows(matchups.data) : undefined), [matchups.data])

  if (status.isPending) return <Loading />
  if (status.error) return <ErrorNote error={status.error} />

  const tierCounts = status.data.corpus_events_by_tier
  if (tierCounts.a + tierCounts.b + tierCounts.c + tierCounts.d === 0) {
    return (
      <EmptyState
        icon={placeById('field').icon}
        title="No tournament results yet"
        message="This page shows what is being played in tournaments and your own record against each deck. It fills in once tournament results are downloaded, which this version does only from the command line."
      />
    )
  }

  const kind = tier ? TIER_KIND[tier] : ''
  const fieldPart = (() => {
    if (presence.error) return <ErrorNote error={presence.error} />
    if (matches.error) return <ErrorNote error={matches.error} />
    if (!presenceRows || !tier || !counted) return <Loading />
    const lists = listCount(share)
    return (
      <>
        {share.length > 0 && (
          <FieldTiles
            rows={share}
            lists={lists}
            kind={kind}
            when={words.when}
            topTwo={counted.topTwo}
          />
        )}
        <ShareCard
          key={`${window}:${tier}`}
          rows={share}
          lists={lists}
          records={counted.records}
          kind={kind}
          when={words.when}
          action={shareAction(tier, window, reset, minute)}
          short={counted.short}
          league={tier === 'C'}
        />
      </>
    )
  })()

  return (
    <div className="space-y-6">
      <FieldControls
        window={window}
        reset={reset}
        now={minute}
        tier={tier}
        onWindow={(value) => setParam('window', paramFor(value, String(defaultWindow(reset))))}
        onTier={(value) => setParam('tier', presenceRows ? paramFor(value, defaultTier(presenceRows)) : value)}
      />
      {fieldPart}
      {winrate.error ? (
        <ErrorNote error={winrate.error} />
      ) : winrate.isPending ? (
        <Loading />
      ) : (
        <WinrateCard key={String(window)} rows={winrates} when={words.when} action={words.short} />
      )}
      <MatchupsCard
        key={`${window}:${pairs ?? ''}`}
        pairs={pairs}
        rows={pairRows}
        isPending={pairs == null || matchups.isPending}
        error={pairs == null ? presence.error : matchups.error}
        next={pairs != null && presenceRows != null ? nextPairs(pairs, presenceRows) : null}
        when={words.when}
        action={words.short}
        onPairs={(value) => setParam('pairs', presenceRows ? paramFor(value, defaultPairs(presenceRows)) : value)}
      />
      <div className="space-y-2">
        {/* Outside the disclosure: TopDeck.gg's terms ask for a visible credit. */}
        {(status.data.corpus_sources ?? []).some((src) => src.source === 'topdeck') && (
          <p className="text-caption text-ink2">
            Standard tournament data from <TextLink href="https://topdeck.gg">TopDeck.gg</TextLink>.
          </p>
        )}
        <SourcesDisclosure status={status.data} />
      </div>
    </div>
  )
}
