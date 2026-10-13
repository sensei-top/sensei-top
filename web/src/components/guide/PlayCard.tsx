import { useTranslation } from 'react-i18next'
import type { DeckGuideOut, GuideNarrativeOut, LeakOut } from '../../api'
import type { TFunction } from '../../i18n'
import type { BoardCurve, BoardCurveRow, GameLength, KeyCardTiming, MulliganRecord, ZoneCurve } from '../../lib/guide'
import { num, TIMING_BUCKETS, timingLabel, timingRecord, turnsOf, zoneLabel } from '../../lib/guide'
import { formatCount } from '../../lib/time'
import { Card, DataTable, Disclosure, EmptyState, Prose, SectionLabel, StatTile } from '../ui'
import { LeakCard, LeaksNarrativeCard } from './LeakCard'

/** "N game"/"N games". */
const games = (n: number, t: TFunction) => t('decks.count.games', { count: n, n: formatCount(n) })

/** "11 turns", "1 turn", or a dash alone for no median. */
function turnsValue(median: number | null, t: TFunction): string {
  if (median == null) return '—'
  return t('decks.guide.play.turns', { count: median, n: median })
}

function FourTiles({ mulligans, gameLength }: { mulligans: MulliganRecord; gameLength: GameLength }) {
  const { t } = useTranslation()
  if (!mulligans.kept_seven && !mulligans.mulliganed && !gameLength.win && !gameLength.loss) {
    return null
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {mulligans.kept_seven && (
        <StatTile
          label={t('decks.guide.play.keptSeven')}
          value={`${formatCount(mulligans.kept_seven.wins)}–${formatCount(mulligans.kept_seven.losses)}`}
          detail={games(mulligans.kept_seven.games, t)}
        />
      )}
      {mulligans.mulliganed && (
        <StatTile
          label={t('decks.guide.play.mulliganed')}
          value={`${formatCount(mulligans.mulliganed.wins)}–${formatCount(mulligans.mulliganed.losses)}`}
          detail={games(mulligans.mulliganed.games, t)}
        />
      )}
      {gameLength.win && (
        <StatTile
          label={t('decks.guide.play.winTakes')}
          value={turnsValue(gameLength.win.median_turns, t)}
          detail={t('decks.guide.play.medianOf', { count: gameLength.win.games, n: formatCount(gameLength.win.games) })}
        />
      )}
      {gameLength.loss && (
        <StatTile
          label={t('decks.guide.play.lossTakes')}
          value={turnsValue(gameLength.loss.median_turns, t)}
          detail={t('decks.guide.play.medianOf', { count: gameLength.loss.games, n: formatCount(gameLength.loss.games) })}
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
  const { t } = useTranslation()
  const acrossSummary = t('decks.guide.play.across', {
    count: leaksAllDecks.length,
    n: formatCount(leaksAllDecks.length),
  })
  return (
    <div>
      <SectionLabel className="mb-2">{t('decks.guide.play.patterns')}</SectionLabel>
      {fix && (
        <div className="mb-3">
          <Prose text={fix} />
        </div>
      )}
      {leaks.length === 0 ? (
        <EmptyState message={t('decks.guide.play.noPattern')} />
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
  const { t } = useTranslation()
  const cards = Object.keys(timing)
  if (cards.length === 0) return null
  return (
    <div>
      <SectionLabel>{t('decks.guide.play.timing.title')}</SectionLabel>
      <p className="mt-1 mb-2 text-caption text-muted">
        {t('decks.guide.play.timing.subtitle')}
      </p>
      <div className="hidden md:block">
        <DataTable
          columns={[t('decks.guide.play.timing.card'), ...TIMING_BUCKETS.map((bucket) => timingLabel(bucket, t))]}
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
                  <div className="text-caption text-muted">{timingLabel(bucket, t)}</div>
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
  const { t } = useTranslation()
  const turns = Object.keys(curve ?? {}).sort((a, b) => Number(a) - Number(b))
  if (turns.length === 0) return null
  return (
    <div>
      <p className="mb-1 text-body font-medium text-ink">{title}</p>
      <DataTable
        columns={[
          t('decks.guide.play.board.turn'),
          t('decks.guide.play.board.games'),
          t('decks.guide.play.board.hand'),
          t('decks.guide.play.board.life'),
          t('decks.guide.play.board.theirPermanents'),
        ]}
        rows={turns.map((turn) => {
          const row = curve?.[turn]
          return [turn, num(row?.n), num(row?.hand), num(row?.life), num(row?.opp_permanents)]
        })}
      />
    </div>
  )
}

function BoardOnYourTurn({ curve }: { curve: BoardCurve }) {
  const { t } = useTranslation()
  const winTurns = Object.keys(curve.win ?? {})
  const lossTurns = Object.keys(curve.loss ?? {})
  if (winTurns.length === 0 && lossTurns.length === 0) return null
  return (
    <div>
      <SectionLabel>{t('decks.guide.play.board.title')}</SectionLabel>
      <p className="mt-1 mb-2 text-caption text-muted">{t('decks.guide.play.board.subtitle')}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <BoardSide title={t('decks.guide.play.board.won')} curve={curve.win} />
        <BoardSide title={t('decks.guide.play.board.lost')} curve={curve.loss} />
      </div>
    </div>
  )
}

function DivergenceSection({ curve }: { curve: ZoneCurve }) {
  const { t } = useTranslation()
  const combos = Object.keys(curve)
  if (combos.length === 0) return null
  return (
    <div>
      <SectionLabel>{t('decks.guide.play.divergence.title')}</SectionLabel>
      <p className="mt-1 mb-2 text-caption text-muted">
        {t('decks.guide.play.divergence.subtitle')}
      </p>
      <div className="space-y-2">
        {combos.map((combo) => {
          const by = curve[combo]
          const turns = turnsOf(by.win, by.loss)
          return (
            <Disclosure key={combo} summary={zoneLabel(combo, t)}>
              <DataTable
                columns={[
                  t('decks.guide.play.board.turn'),
                  t('decks.guide.play.divergence.won'),
                  t('decks.guide.play.divergence.lost'),
                ]}
                rows={turns.map((turn) => [turn, num(by.win?.[turn]), num(by.loss?.[turn])])}
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
  const { t } = useTranslation()
  const boardCurve = guide.play.board_curve as BoardCurve
  const zoneCurve = guide.play.zone_curve as ZoneCurve
  const keyCardTiming = guide.play.key_card_timing as KeyCardTiming
  const mulligans = guide.play.mulligan_record as MulliganRecord
  const gameLength = guide.play.game_length as GameLength

  return (
    <Card title={t('decks.guide.play.title')} subtitle={t('decks.guide.play.subtitle')}>
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
