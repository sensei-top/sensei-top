import { useMemo } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import type { MetagameStatus } from '../api'
import { useFormats, useLive, useMatches, useMetaMatchups, useMetaPresence, useMetaWinrate, useMetagameEvents, useMetagameStatus } from '../api'
import { FieldControls } from '../components/field/FieldControls'
import { FieldTiles } from '../components/field/FieldTiles'
import { EventsCard } from '../components/field/EventsCard'
import { MatchupsCard } from '../components/field/MatchupsCard'
import { ShareCard } from '../components/field/ShareCard'
import { SourcesDisclosure } from '../components/field/SourcesDisclosure'
import { WinrateCard } from '../components/field/WinrateCard'
import { Callout, EmptyState, ErrorNote, Loading, Prose, Select, TextLink } from '../components/ui'
import type { FieldParam, FieldParams, Pairs, Tier } from '../lib/field'
import {
  PAIRS,
  PAIRS_TIERS,
  TIERS,
  anyFormatData,
  defaultPairs,
  defaultTier,
  defaultWindow,
  formatCaption,
  formatChoices,
  formatOf,
  holdLines,
  listCount,
  matchupRows,
  metaWindowOf,
  nextPairs,
  pairsOf,
  paramFor,
  ownCounts,
  resetOf,
  shareAction,
  shareRows,
  tierKind,
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

/** One warn callout per source whose fetch is paused, its words the hold
 *  line's. Nothing when none is. */
function PausedHolds({ status, now }: { status: MetagameStatus; now: number }) {
  const { t } = useTranslation()
  const lines = holdLines(status, 'paused', now, t)
  return (
    <>
      {lines.map((line) => (
        <Callout key={line} tone="warn">
          <Prose text={line} />
        </Callout>
      ))}
    </>
  )
}

/** `/field`: what is being played in tournaments and how it does, in the
 *  format, window and tier the address names (`lib/field.ts`), with the
 *  viewer's own record against each deck. Nothing is read before
 *  `/api/formats` answers, since a bare address means the format it names as
 *  the default. Top to bottom: the format control with its caption (kept
 *  above the empty state too, so a format with nothing in it can be left),
 *  the window and tier controls, three tiles, the
 *  share list, the events card, the win-rate table, the matchups table, a
 *  warn callout for each source whose fetch is paused and, closed, where
 *  the numbers come from. The four metagame reads wait for the status, so
 *  none is asked for with a window guessed ahead of knowing whether a reset
 *  exists; the matchups wait for the lists too when the address does not
 *  name their tiers, since the default depends on them. The viewer's
 *  matches are read as Home reads them, every source and every deck, and
 *  only the selected format's count toward the records. */
export function FieldView({
  params,
  setParam,
}: {
  params: FieldParams
  setParam: (key: FieldParam, value: string | undefined) => void
}) {
  const { t } = useTranslation()
  const now = useNow()
  // The counts move with the minute, not with every second's re-render.
  const minute = Math.floor(now / MINUTE) * MINUTE

  const formats = useFormats()
  // The address's format, else the API's default, which the address never
  // holds. Nothing metagame is asked for before it is known.
  const format = formats.data ? formatOf(params.format, formats.data) : undefined

  const status = useMetagameStatus(format, format !== undefined)
  const reset = resetOf(status.data?.format_reset_start)
  const window = windowOf(params.window, reset)
  const metaWindow = status.data ? metaWindowOf(window, reset) : undefined
  const presence = useMetaPresence(metaWindow, format)
  const winrate = useMetaWinrate(metaWindow, format)

  const presenceRows = presence.data
  const namedPairs: Pairs | null = PAIRS.find((candidate) => candidate === params.pairs) ?? null
  const pairs: Pairs | null = presenceRows ? pairsOf(params.pairs, presenceRows) : namedPairs
  const matchups = useMetaMatchups(pairs ? metaWindow : undefined, pairs ? PAIRS_TIERS[pairs] : undefined, format)

  const live = useLive()
  const matches = useMatches(undefined, 'all', HOME_MATCH_LIMIT)

  // While the lists load, the tier the address names, as for the pairs, so
  // the tier's control stays drawn across a change of window.
  const namedTier = TIERS.find((candidate) => candidate === params.tier) ?? null
  const tier: Tier | null = presenceRows ? tierOf(params.tier, presenceRows) : namedTier
  // The events of the same scope as the share list, once the tier is known.
  const events = useMetagameEvents(tier ? metaWindow : undefined, tier ?? undefined, format)
  const windowStart = windowStartOf(window, reset, minute)
  const words = windowWords(window, reset, minute, t)

  const share = useMemo(() => (presenceRows && tier ? shareRows(presenceRows, tier) : []), [presenceRows, tier])
  // The records move with the minute and the lists, not with every second's
  // re-render.
  const counted = useMemo(() => {
    const rows = matches.data
    if (!rows) return null
    if (!format) return null
    return ownCounts(rows, share, format, windowStart, live.data?.matches)
  }, [matches.data, share, windowStart, live.data?.matches, format])
  const winrates = useMemo(() => winrateRows(winrate.data ?? []), [winrate.data])
  const pairRows = useMemo(() => (matchups.data ? matchupRows(matchups.data) : undefined), [matchups.data])

  if (formats.error) return <ErrorNote error={formats.error} />
  if (!formats.data || !format) return <Loading />

  // Drawn above whatever the page holds, the empty state too, so the viewer
  // can switch away from a format with nothing in it.
  const entry = formats.data.formats.find((candidate) => candidate.format === format)
  const formatControl = anyFormatData(formats.data) ? (
    <div className="space-y-1">
      <Select
        label={t('field.controls.format')}
        placement="beside-from-md"
        size="caption"
        value={format}
        onChange={(value) => setParam('format', paramFor(value, formats.data.default))}
        options={formatChoices(formats.data, format).map((choice) => ({
          value: choice.format,
          label: choice.format,
        }))}
      />
      {entry && <p className="text-caption text-muted">{formatCaption(entry, t)}</p>}
    </div>
  ) : null

  if (status.isPending)
    return (
      <div className="space-y-6">
        {formatControl}
        <Loading />
      </div>
    )
  if (status.error)
    return (
      <div className="space-y-6">
        {formatControl}
        <ErrorNote error={status.error} />
      </div>
    )

  const tierCounts = status.data.corpus_events_by_tier
  if (tierCounts.a + tierCounts.b + tierCounts.c + tierCounts.d === 0) {
    return (
      <div className="space-y-6">
        {formatControl}
        <EmptyState
          icon={placeById('field').icon}
          title={t('field.page.emptyTitle', { format })}
          message={t('field.page.emptyMessage')}
        />
        <PausedHolds status={status.data} now={minute} />
      </div>
    )
  }

  const kind = tier ? tierKind(tier, t) : ''
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
          key={`${format}:${window}:${tier}`}
          rows={share}
          lists={lists}
          records={counted.records}
          kind={kind}
          when={words.when}
          action={shareAction(tier, window, reset, minute, t)}
          short={counted.short}
          league={tier === 'C'}
        />
      </>
    )
  })()
  const eventsPart = (
    <EventsCard
      key={`${format}:${window}:${tier}`}
      rows={events.data}
      isPending={tier == null || events.isPending}
      error={tier == null ? presence.error : events.error}
      kind={kind}
      when={words.when}
      action={tier ? shareAction(tier, window, reset, minute, t) : null}
      now={minute}
    />
  )

  return (
    <div className="space-y-6">
      {formatControl}
      <FieldControls
        window={window}
        reset={reset}
        now={minute}
        tier={tier}
        onWindow={(value) => setParam('window', paramFor(value, String(defaultWindow(reset))))}
        onTier={(value) => setParam('tier', presenceRows ? paramFor(value, defaultTier(presenceRows)) : value)}
      />
      {fieldPart}
      {eventsPart}
      {winrate.error ? (
        <ErrorNote error={winrate.error} />
      ) : winrate.isPending ? (
        <Loading />
      ) : (
        <WinrateCard key={`${format}:${window}`} rows={winrates} when={words.when} action={words.short} />
      )}
      <MatchupsCard
        key={`${format}:${window}:${pairs ?? ''}`}
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
        <PausedHolds status={status.data} now={minute} />
        {/* Outside the disclosure: TopDeck.gg's terms ask for a visible credit. */}
        {status.data.corpus_topdeck_events > 0 && (
          <p className="text-caption text-ink2">
            <Trans
              i18nKey="field.page.topdeckCredit"
              values={{ format }}
              components={{ site: <TextLink href="https://topdeck.gg" /> }}
            />
          </p>
        )}
        <SourcesDisclosure status={status.data} now={minute} />
      </div>
    </div>
  )
}
