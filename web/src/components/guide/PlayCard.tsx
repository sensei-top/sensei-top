import type { DeckGuideOut, GuideNarrativeOut, LeakOut } from '../../api'
import type { BoardCurve, BoardCurveRow, GameLength, KeyCardTiming, MulliganRecord, ZoneCurve } from '../../lib/guide'
import { num, TIMING_BUCKETS, TIMING_LABELS, timingRecord, turnsOf, zoneLabel } from '../../lib/guide'
import { formatCount } from '../../lib/time'
import { Card, DataTable, Disclosure, EmptyState, Prose, SectionLabel, StatTile } from '../ui'
import { LeakCard, LeaksNarrativeCard } from './LeakCard'

/** A no-break space: a count and the word after it never part. */
const NBSP = '\u00a0'

/** "N game"/"N games". */
const games = (n: number) => (n === 1 ? `1${NBSP}game` : `${formatCount(n)}${NBSP}games`)

/** "11 turns", "1 turn", or a dash alone for no median. */
function turnsValue(median: number | null): string {
  if (median == null) return '—'
  return median === 1 ? `1${NBSP}turn` : `${median}${NBSP}turns`
}

function FourTiles({ mulligans, gameLength }: { mulligans: MulliganRecord; gameLength: GameLength }) {
  if (!mulligans.kept_seven && !mulligans.mulliganed && !gameLength.win && !gameLength.loss) {
    return null
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {mulligans.kept_seven && (
        <StatTile
          label="Kept seven"
          value={`${formatCount(mulligans.kept_seven.wins)}–${formatCount(mulligans.kept_seven.losses)}`}
          detail={games(mulligans.kept_seven.games)}
        />
      )}
      {mulligans.mulliganed && (
        <StatTile
          label="Mulliganed"
          value={`${formatCount(mulligans.mulliganed.wins)}–${formatCount(mulligans.mulliganed.losses)}`}
          detail={games(mulligans.mulliganed.games)}
        />
      )}
      {gameLength.win && (
        <StatTile
          label="A win takes"
          value={turnsValue(gameLength.win.median_turns)}
          detail={`median of ${games(gameLength.win.games)}`}
        />
      )}
      {gameLength.loss && (
        <StatTile
          label="A loss takes"
          value={turnsValue(gameLength.loss.median_turns)}
          detail={`median of ${games(gameLength.loss.games)}`}
        />
      )}
    </div>
  )
}

/** This deck's own patterns, then the same rollup across every deck, one
 *  click away — `LeakCard` draws each pattern; `withDeck` tells its
 *  matches whether to repeat the deck the page's own title already
 *  names. */
function PatternsSection({
  leaks,
  leaksAllDecks,
  fix,
}: {
  leaks: LeakOut[]
  leaksAllDecks: LeakOut[]
  fix: string | undefined
}) {
  const acrossSummary =
    leaksAllDecks.length === 1
      ? `Across all of your decks, 1${NBSP}pattern`
      : `Across all of your decks, ${formatCount(leaksAllDecks.length)}${NBSP}patterns`
  return (
    <div>
      <SectionLabel className="mb-2">Patterns in this deck's matches</SectionLabel>
      {fix && (
        <div className="mb-3">
          <Prose text={fix} />
        </div>
      )}
      {leaks.length === 0 ? (
        <EmptyState message="No pattern has enough finished matches with this deck yet." />
      ) : (
        <div className="space-y-3">
          {leaks.map((leak) => (
            <LeakCard key={leak.code} leak={leak} withDeck={false} />
          ))}
        </div>
      )}
      {leaksAllDecks.length > 0 && (
        <div className="mt-3">
          <Disclosure summary={acrossSummary}>
            <div className="space-y-3">
              {leaksAllDecks.map((leak) => (
                <LeakCard key={leak.code} leak={leak} withDeck />
              ))}
            </div>
          </Disclosure>
        </div>
      )}
    </div>
  )
}

function KeyCardTimingSection({ timing }: { timing: KeyCardTiming }) {
  const cards = Object.keys(timing)
  if (cards.length === 0) return null
  return (
    <div>
      <SectionLabel>When a key card first resolved</SectionLabel>
      <p className="mt-1 mb-2 text-caption text-muted">
        Games won and lost, by the turn of yours on which the card first resolved.
      </p>
      <div className="hidden md:block">
        <DataTable
          columns={['Card', ...TIMING_BUCKETS.map((bucket) => TIMING_LABELS[bucket])]}
          rows={cards.map((card) => [
            card,
            ...TIMING_BUCKETS.map((bucket) => timingRecord(timing[card][bucket])),
          ])}
        />
      </div>
      <div className="space-y-3 md:hidden">
        {cards.map((card) => (
          <div key={card}>
            <p className="text-body font-medium text-ink">{card}</p>
            <div className="mt-1 grid grid-cols-3 gap-2">
              {TIMING_BUCKETS.map((bucket) => (
                <div key={bucket}>
                  <div className="text-caption text-muted">{TIMING_LABELS[bucket]}</div>
                  <div className="text-body text-ink2 tabular-nums">{timingRecord(timing[card][bucket])}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** One side's own turns (never the other side's): "the board on your own
 *  turn" tables are never a nine-column union, since that runs past a
 *  360 px card (S16's measured facts). */
function BoardSide({ title, curve }: { title: string; curve: Record<string, BoardCurveRow> | undefined }) {
  const turns = Object.keys(curve ?? {}).sort((a, b) => Number(a) - Number(b))
  if (turns.length === 0) return null
  return (
    <div>
      <p className="mb-1 text-body font-medium text-ink">{title}</p>
      <DataTable
        columns={['Turn', 'Games', 'Hand', 'Life', 'Their permanents']}
        rows={turns.map((t) => {
          const row = curve?.[t]
          return [t, num(row?.n), num(row?.hand), num(row?.life), num(row?.opp_permanents)]
        })}
      />
    </div>
  )
}

function BoardOnYourTurn({ curve }: { curve: BoardCurve }) {
  const winTurns = Object.keys(curve.win ?? {})
  const lossTurns = Object.keys(curve.loss ?? {})
  if (winTurns.length === 0 && lossTurns.length === 0) return null
  return (
    <div>
      <SectionLabel>The board on your own turn</SectionLabel>
      <p className="mt-1 mb-2 text-caption text-muted">Medians over the games still going at that turn.</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <BoardSide title="Games won" curve={curve.win} />
        <BoardSide title="Games lost" curve={curve.loss} />
      </div>
    </div>
  )
}

function DivergenceSection({ curve }: { curve: ZoneCurve }) {
  const combos = Object.keys(curve)
  if (combos.length === 0) return null
  return (
    <div>
      <SectionLabel>Where won and lost games differ most</SectionLabel>
      <p className="mt-1 mb-2 text-caption text-muted">
        The median count on your own turn, for the three kinds of card and place that differ most between games
        won and games lost.
      </p>
      <div className="space-y-2">
        {combos.map((combo) => {
          const by = curve[combo]
          const turns = turnsOf(by.win, by.loss)
          return (
            <Disclosure key={combo} summary={zoneLabel(combo)}>
              <DataTable
                columns={['Turn', 'Won', 'Lost']}
                rows={turns.map((t) => [t, num(by.win?.[t]), num(by.loss?.[t])])}
              />
            </Disclosure>
          )
        })}
      </div>
    </div>
  )
}

export function YourPlayCard({
  guide,
  narrative,
}: {
  guide: DeckGuideOut
  narrative: GuideNarrativeOut | undefined
}) {
  const boardCurve = guide.play.board_curve as BoardCurve
  const zoneCurve = guide.play.zone_curve as ZoneCurve
  const keyCardTiming = guide.play.key_card_timing as KeyCardTiming
  const mulligans = guide.play.mulligan_record as MulliganRecord
  const gameLength = guide.play.game_length as GameLength

  return (
    <Card title="Your play" subtitle="What this deck's own games show, every version together.">
      <div className="space-y-6">
        <FourTiles mulligans={mulligans} gameLength={gameLength} />

        <PatternsSection leaks={guide.leaks} leaksAllDecks={guide.leaks_all_decks} fix={narrative?.fix} />

        <LeaksNarrativeCard />

        <KeyCardTimingSection timing={keyCardTiming} />
        <BoardOnYourTurn curve={boardCurve} />
        <DivergenceSection curve={zoneCurve} />
      </div>
    </Card>
  )
}
