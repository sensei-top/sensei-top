import { useTranslation } from 'react-i18next'
import { useCurrentMatch, useCurrentMatchRead, useLive } from '../api'
import type { CurrentMatch, IntermissionOut, OpeningHandOut } from '../api'
import type { TFunction } from '../i18n'
import { KeepGuideCard } from '../components/KeepGuideCard'
import { LibraryCard } from '../components/LibraryCard'
import { MatchupBriefCard } from '../components/MatchupBriefCard'
import { OpeningHandCard } from '../components/OpeningHandCard'
import { OpponentHandCard } from '../components/OpponentHandCard'
import { OpponentRead } from '../components/OpponentRead'
import { SideboardOpponentRail, SideboardPlanCard } from '../components/SideboardPlanCard'
import { Callout, Chip, Disclosure, EmptyState, ErrorNote, Loading, ManaPips, StatTile } from '../components/ui'
import { isLikelyAbandoned } from '../lib/liveMatch'
import { type LivePanel, livePanels } from '../lib/livePanels'
import { confidenceLabel, opponentLabelText } from '../lib/opponent'
import { ago, useNow } from '../lib/time'
import { placeById } from '../shell/places'

const CONFIDENCE_CHIP_VARIANT: Record<string, 'neutral' | 'warn'> = {
  high: 'neutral',
  medium: 'neutral',
  low: 'warn',
  unknown: 'warn',
}

// "once" / "twice" reads better than "1 time" / "2 times" for the common
// cases, and every count still gets a grammatical sentence beyond that.
const timesPhrase = (n: number, t: TFunction): string =>
  n === 1 ? t('live.times.once') : n === 2 ? t('live.times.twice') : t('live.times.many', { n })

// Mirrors OpponentRead.tsx's headerText: a real name from any of the four
// sources (manual pick, rule archetype/fallback, or the corpus evidence
// source) reads as itself; anything else is only the colours-and-signature
// fallback, so it says so instead of a name that sounds settled.
function opponentDeckValue(match: CurrentMatch, t: TFunction): string {
  const label = match.opponent_label ?? t('common.unknownDeck')
  const named =
    match.opponent_source === 'manual' ||
    match.opponent_source === 'archetype' ||
    match.opponent_source === 'fallback' ||
    match.opponent_source === 'corpus'
  return named ? label : t('live.opponent.unclear', { label })
}

/** The band at the page's top: game and turn as big display numerals under
 *  small sentence-case labels (the two facts worth reading at a glance from
 *  second-monitor distance), the `·`-joined facts beside them, and the
 *  opponent's identity (pips, name, confidence) at the far end. From 48rem
 *  up that is one line, the facts cut to fit. Under 48rem it is two: game,
 *  turn, pips and confidence on the first; the opponent's name and the
 *  facts on the second, wrapping, none cut. Reads `openingHand` over
 *  `match` for the game/turn phrase whenever a decision is pending — that
 *  can be true even before `match` exists at all, since the read comes
 *  straight from a live replay (table/opening_hand.py) and does not wait
 *  on a projected match row. The rail stays beside the page in focus mode
 *  (`shell/Shell.tsx`), so this strip carries no escape hatch of its own.
 *  A match `lib/liveMatch.ts` calls likely abandoned says so here rather
 *  than rendering under a pulsing "live" dot indefinitely.
 */
function MatchStatusStrip({
  match,
  openingHand,
  intermission,
  adviceOff = false,
}: {
  match: CurrentMatch | null
  openingHand: OpeningHandOut | null
  /** A ranked game is under way and the page shows no advice
   *  (`table/ranked.py`); the strip says so, so a missing keep guide never
   *  reads as a broken one. */
  adviceOff?: boolean
  /** Between-games break (S8): takes precedence over every other phase
   *  phrase below, including a pending mulligan decision — Arena cannot
   *  raise both at once, since the next game's opening hand doesn't exist
   *  until sideboarding ends. */
  intermission?: IntermissionOut | null
}) {
  const { t } = useTranslation()
  const now = useNow()
  const game = match?.game
  const latest = match?.turns.at(-1)
  // Falls back to game.turn_count (already selected, already in the model)
  // rather than showing nothing while turns hasn't been written yet — true
  // for Arena in the gap right after a game starts.
  const turnNumber = latest?.turn_number ?? game?.turn_count ?? null
  const likelyAbandoned = isLikelyAbandoned(match?.started_at, now)

  // The turn number now has its own numeral below, so the phase phrase only
  // needs to say something when there is more to say than "it is turn N".
  const phase = intermission
    ? t('live.strip.sideboarding', { game: intermission.next_game })
    : openingHand
      ? openingHand.mulligan_count > 0
        ? t('live.strip.decisionPendingMulligan', { n: openingHand.mulligan_count })
        : t('live.strip.decisionPending')
      : latest
        ? null
        : game
          ? t('live.strip.mulliganPhase')
          : match
            ? t('live.strip.waiting')
            : null

  const parts = [
    match
      ? t('live.strip.record', { won: match.games_won ?? 0, lost: match.games_lost ?? 0 })
      : null,
    game?.on_play == null ? null : game.on_play ? t('live.onPlay') : t('live.onDraw'),
    phase,
    adviceOff ? t('live.strip.rankedAdviceOff') : null,
    match ? t('live.cardsSeen', { count: match.opponent_cards_seen }) : null,
    match?.started_at ? t('live.strip.seen', { ago: ago(match.started_at, now) }) : null,
    likelyAbandoned ? t('live.strip.abandoned') : null,
  ].filter((part): part is string => part != null)

  const opponentName = match?.opponent_label
    ? opponentLabelText(match.opponent_label, match.opponent_colors)
    : null
  const facts = parts.join(' · ') || t('live.title')
  // Under 48rem the name leaves the far end and leads the facts' line.
  const narrowFacts = [opponentName, ...parts].filter((part) => part != null).join(' · ') || t('live.title')

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 rounded-card border border-edge bg-surface px-4 py-3 shadow-lift md:flex-nowrap">
      <div className="flex shrink-0 items-baseline gap-4">
        <div>
          <div className="text-chip font-semibold tracking-label text-muted">{t('live.strip.game')}</div>
          <div className="font-display text-stat leading-none text-ink">
            {game ? game.game_number : '—'}
          </div>
        </div>
        <div>
          <div className="text-chip font-semibold tracking-label text-muted">{t('live.strip.turn')}</div>
          <div className="font-display text-stat leading-none text-ink">
            {turnNumber ?? '—'}
          </div>
        </div>
      </div>

      <div className="order-last flex min-w-0 basis-full items-start gap-2 text-ink2 md:order-none md:flex-1 md:basis-auto md:items-center">
        {/* Never color alone: the dot is decoration, the text is the fact. */}
        <span
          aria-hidden
          className={`mt-1.5 inline-block size-2 shrink-0 rounded-pill md:mt-0 ${
            likelyAbandoned ? 'bg-muted' : 'animate-pulse bg-s3'
          }`}
        />
        <span className="min-w-0 md:hidden">{narrowFacts}</span>
        <span className="hidden truncate md:inline">{facts}</span>
      </div>

      {match?.opponent_label && (
        <div className="ml-auto flex shrink-0 items-center gap-2 md:ml-0">
          <ManaPips colors={match.opponent_colors} size="lg" />
          <span className="hidden truncate text-body text-ink2 md:inline">{opponentName}</span>
          {match.opponent_confidence && (
            <Chip variant={CONFIDENCE_CHIP_VARIANT[match.opponent_confidence] ?? 'neutral'}>
              {confidenceLabel(match.opponent_confidence, t)}
            </Chip>
          )}
        </div>
      )}
    </div>
  )
}

/** The matchup brief and the four stat tiles — everything demoted off the
 *  base render so the live read fits one screen. Each is a `Disclosure`
 *  that opens over its own content, independently, and scrolls inside
 *  itself rather than the page. The brief has no other
 *  home in the dashboard yet (the deck guide tab doesn't render it), so it
 *  stays here rather than being cut along with the rest of this bar. */
function DisclosureBar({ match, advice }: { match: CurrentMatch; advice: boolean }) {
  const { t } = useTranslation()
  const game = match.game
  const latest = match.turns.at(-1)
  return (
    <div className="flex shrink-0 flex-wrap gap-4 border-t border-edge pt-2 text-caption">
      {/* The brief's play-arounds are advice: off during a ranked game. */}
      {advice && (
        <Disclosure summary={t('live.bar.brief')}>
          <div className="max-h-[55vh] w-[min(28rem,90vw)] overflow-y-auto">
            <MatchupBriefCard match={match} />
          </div>
        </Disclosure>
      )}
      <Disclosure summary={t('live.bar.details')}>
        <div className="grid max-h-[55vh] w-[min(40rem,90vw)] grid-cols-2 gap-3 overflow-y-auto sm:grid-cols-4">
          <StatTile
            label={t('live.bar.opponentDeck')}
            value={opponentDeckValue(match, t)}
            detail={t('live.bar.seenEvent', {
              n: match.opponent_cards_seen,
              event: match.event_id ?? t('live.bar.eventUnknown'),
            })}
          />
          <StatTile
            label={t('live.bar.game')}
            value={game ? String(game.game_number) : '—'}
            detail={t('live.bar.matchScore', { won: match.games_won ?? 0, lost: match.games_lost ?? 0 })}
          />
          <StatTile
            label={t('live.bar.playDraw')}
            value={game?.on_play == null ? '—' : game.on_play ? t('live.bar.play') : t('live.bar.draw')}
            detail={game?.on_play == null ? t('live.bar.undetermined') : t('live.bar.thisGame')}
          />
          <StatTile
            label={t('live.bar.turn')}
            value={latest ? String(latest.turn_number) : '—'}
            detail={t('live.bar.turnNote')}
          />
        </div>
      </Disclosure>
    </div>
  )
}

export function CurrentMatchView() {
  const current = useCurrentMatch()
  const read = useCurrentMatchRead()
  const live = useLive()
  const { t } = useTranslation()
  // A watcher that died mid-match leaves the match frozen on screen, and the
  // status pill is hidden on this page from 48rem up: say so above every
  // branch. shrink-0 keeps focus mode's height cap.
  // A watcher that died after starting reads `watching: false` too, so the
  // stopped case is asked first.
  const callout = !live.data
    ? null
    : live.data.watcher_stopped
      ? t('shell.liveStatus.watcherStopped')
      : live.data.watching
        ? null
        : t('shell.liveStatus.notWatching')
  const stopped = live.data?.watcher_stopped ? (
    <div className="shrink-0">
      <Callout tone="warn">{t('shell.liveStatus.watcherStopped')}</Callout>
    </div>
  ) : null

  if (current.isPending) return <Loading />
  if (current.error) return <ErrorNote error={current.error} />

  const openingHand = read.data?.opening_hand ?? null
  // The server's answer, never re-derived (table/ranked.py). Until the read
  // arrives the page assumes a ranked game, as the server does for an
  // unknown queue.
  const advice = read.data?.advice ?? false

  if (!current.data) {
    // opening_hand reads a live replay directly and does not wait on a
    // projected match row (table/opening_hand.py) — a decision can be
    // pending here even though there is nothing else to show yet.
    if (!openingHand) {
      // The live status is hidden from 48rem up here, so while the tracker
      // is not watching the page says so itself.
      return (
        <div className="flex flex-col gap-3">
          {callout && <Callout tone="warn">{callout}</Callout>}
          <EmptyState
            icon={placeById('live').icon}
            title={t('live.empty.title')}
            message={t('live.empty.message')}
          />
        </div>
      )
    }
    // A decision is pending before any match row exists. In a ranked game
    // the hand's read is advice and nothing else is known yet.
    return (
      <div className="flex h-full min-h-0 flex-col gap-3">
        {stopped}
        <MatchStatusStrip match={null} openingHand={openingHand} adviceOff={!advice} />
        <div className="min-h-0 flex-1 overflow-hidden">
          {advice ? (
            <OpeningHandCard hand={openingHand} />
          ) : (
            <EmptyState
              icon={placeById('live').icon}
              title={t('live.ranked.title')}
              message={t('live.ranked.message')}
            />
          )}
        </div>
      </div>
    )
  }

  const match = current.data
  const intermission = read.data?.intermission ?? null

  // The break between games (S8): takes precedence over the "game under
  // way" phase below, same as MatchStatusStrip's own phase-phrase
  // precedence — there is no board to show, no keep guide to run, and no
  // hand to read until the next game's opening hand actually exists.
  if (intermission) {
    return (
      <div className="flex h-full min-h-0 flex-col gap-3">
        {stopped}
        <MatchStatusStrip match={match} openingHand={null} intermission={intermission} />
        <div className="grid min-h-0 flex-1 gap-3 overflow-y-auto sm:grid-cols-[1fr_360px]">
          <div className="min-h-0">
            <SideboardPlanCard intermission={intermission} match={match} />
          </div>
          <div className="min-h-0">
            <SideboardOpponentRail intermission={intermission} match={match} />
          </div>
        </div>
      </div>
    )
  }

  const game = match.game
  const turns = match.turns

  const oppMulliganPhrase =
    game?.opp_mulligans == null ? t('live.times.unknown') : timesPhrase(game.opp_mulligans, t)
  const keepGuideSubtitle = !game
    ? t('live.keepSubtitle.waiting')
    : [
        turns.length === 0 ? t('live.keepSubtitle.firstTurn') : null,
        game.self_mulligans
          ? t('live.keepSubtitle.mulliganed', { times: timesPhrase(game.self_mulligans, t) })
          : t('live.keepSubtitle.kept'),
        t('live.keepSubtitle.opponentMulliganed', { times: oppMulliganPhrase }),
      ]
        .filter((part): part is string => part != null)
        .join(' · ')

  const panels = livePanels({
    decisionPending: openingHand != null,
    mulliganPhase: turns.length === 0,
    advice,
  })

  const panel = (name: LivePanel) => {
    switch (name) {
      case 'opening-hand':
        return <OpeningHandCard key={name} hand={openingHand} />
      case 'keep-guide':
        return <KeepGuideCard key={name} keep={read.data?.keep} subtitle={keepGuideSubtitle} />
      case 'keep-guide-dense':
        return (
          <KeepGuideCard key={name} keep={read.data?.keep} subtitle={keepGuideSubtitle} dense />
        )
      case 'library':
        return (
          <LibraryCard
            key={name}
            cards={read.data?.library}
            libraryCount={read.data?.library_count}
            keep={read.data?.keep}
          />
        )
      case 'opponent-hand':
        return <OpponentHandCard key={name} hand={read.data?.hand} />
      case 'opponent-hand-facts':
        return <OpponentHandCard key={name} hand={read.data?.hand} estimate={false} />
      case 'opponent-read':
        return <OpponentRead key={name} match={match} />
      case 'opponent-read-dense':
        return <OpponentRead key={name} match={match} dense />
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {stopped}
      <MatchStatusStrip match={match} openingHand={openingHand} adviceOff={!advice} />

      <div className="grid min-h-0 flex-1 gap-3 sm:grid-cols-[1fr_360px]">
        <div className="min-h-0 overflow-hidden">{panel(panels.primary)}</div>

        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          {panels.rail.map(panel)}
        </div>
      </div>

      <DisclosureBar match={match} advice={advice} />
    </div>
  )
}
