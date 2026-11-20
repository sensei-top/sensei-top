import { memo, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'
import {
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartHover,
  XAxis,
  YAxis,
} from 'recharts'
import type { ReportFinding, SummaryBeat, SummaryGameLine } from '../../api'
import { resultWord } from '../../lib/events'
import { formatNumber } from '../../lib/format'
import {
  barePlace,
  evidenceIsRedundant,
  markerLabel,
  parseFinding,
  placeText,
  weightOf,
  type Marker,
  type Timeline,
} from '../../lib/timeline'
import { useTokens } from '../../theme'
import { ChartTooltip } from '../ChartTooltip'
import { axisProps } from '../chartChrome'
import { Button, Card, DataTable, Disclosure, Finding, type FindingWeight, TextLink, TwoSidedMeter } from '../ui'
import { BeatLabel, GameFacts } from './GameCard'

/** A position, to two decimals, as `toFixed(2)` wrote it. */
const TWO_DIGITS = { minimumFractionDigits: 2, maximumFractionDigits: 2 }

/** The chart's height, in pixels. */
const CHART_HEIGHT = 200

/** Room above the plot for the games' labels, in pixels. */
const LABEL_ROOM = 22

/** A marker's fill on the chart, by weight: the status colours, never the
 *  accent, which is never data. A note is hollow. CSS classes, because an
 *  SVG presentation attribute does not resolve `var()`. */
const MARK_CLASS: Record<FindingWeight, string> = {
  decisive: 'fill-loss',
  flag: 'fill-warn',
  notice: 'fill-ink2',
  note: 'fill-surface',
}

const MARK_RADIUS: Record<FindingWeight, number> = { decisive: 6, flag: 5.5, notice: 5, note: 4.5 }

/** The same weight as a dot in the strip. */
const DOT_CLASS: Record<FindingWeight, string> = {
  decisive: 'bg-loss',
  flag: 'bg-warn',
  notice: 'bg-ink2',
  note: 'border border-muted',
}

function tick(value: number): string {
  return value === 0 ? '0' : formatNumber(value || 0, TWO_DIGITS)
}

function useWeightWords(): Record<FindingWeight, string> {
  const { t } = useTranslation()
  return {
    decisive: t('common.finding.decisive'),
    flag: t('common.finding.flag'),
    notice: t('common.finding.notice'),
    note: t('common.finding.note'),
  }
}

/** One finding: its weight and place, its title, then `lead` (a beat's
 *  label), its detail, its caveats, `children`, and the numbers behind it
 *  that the title does not already say, behind a disclosure. */
export function FindingBlock({
  finding,
  lead,
  children,
}: {
  finding: ReportFinding
  lead?: ReactNode
  children?: ReactNode
}) {
  const { t } = useTranslation()
  const caveats = finding.caveats ?? []
  const evidence = (finding.evidence ?? []).filter((e) => !evidenceIsRedundant(finding.title, e.value))
  return (
    <Finding weight={weightOf(finding.severity)} where={placeText(finding, t)} title={finding.title}>
      {lead}
      <p>{finding.detail}</p>
      {caveats.length > 0 && (
        <ul className="mt-2 space-y-1 text-caption text-muted">
          {caveats.map((caveat, i) => (
            <li key={i}>{caveat}</li>
          ))}
        </ul>
      )}
      {evidence.length > 0 && (
        <div className="mt-3">
          <Disclosure summary={t('matches.report.numbersBehind')}>
            <DataTable
              columns={[t('matches.report.detail'), t('matches.report.value')]}
              rows={evidence.map((e) => [e.label, e.display ?? `${e.value ?? '—'}${e.unit ? ` ${e.unit}` : ''}`])}
            />
          </Disclosure>
        </div>
      )}
      {children}
    </Finding>
  )
}

/** A list of findings, and under it, when one of them is partial, the one
 *  line that says what "partly hidden" means. */
export function FindingList({ findings }: { findings: ReportFinding[] }) {
  const { t } = useTranslation()
  const partial = findings.some((f) => f.confidence === 'partial')
  return (
    <div className="space-y-3">
      {findings.map((f, i) => (
        <FindingBlock key={`${f.code}-${i}`} finding={f} />
      ))}
      {partial && <p className="text-caption text-muted">{t('matches.report.partlyHiddenNote')}</p>}
    </div>
  )
}

/** The match's line across every game, the games' boundaries labelled, and
 *  one dot per placed finding. A dot takes the pointer; the keyboard's way
 *  in is the strip. It renders again on each choice (`selected`, and the
 *  dots' shapes with it); the line's inputs (data, domains, ticks,
 *  formatters, axis props) keep their identity, since new ones would
 *  start the line's motion over. */
const TimelineChart = memo(function TimelineChart({
  timeline,
  markers,
  selected,
  onSelect,
  gameLabels,
  label,
}: {
  timeline: Timeline
  markers: Marker[]
  selected: number | null
  onSelect: (id: number) => void
  gameLabels: Map<number, string>
  label: string
}) {
  const { t } = useTranslation()
  const tokens = useTokens()
  const { slots, reach } = timeline
  const axis = useMemo(() => axisProps(tokens), [tokens])
  const activeDot = useMemo(() => ({ r: 4, strokeWidth: 2, stroke: tokens.surface }), [tokens])
  const yTicks = useMemo(() => [-reach, 0, reach], [reach])
  const yDomain = useMemo(() => [-reach, reach], [reach])
  const xDomain = useMemo(() => [0, Math.max(1, slots.length - 1)], [slots.length])
  const turnTick = useCallback((x: number) => String(slots[x]?.turn ?? ''), [slots])
  const placeOf = useCallback(
    (x: string | number) => {
      const slot = slots[Number(x)]
      return slot && slot.turn != null ? t('matches.report.placeTurn', { game: slot.game, turn: slot.turn }) : ''
    },
    [slots, t],
  )
  return (
    <div role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <LineChart data={slots} margin={{ top: LABEL_ROOM, left: 0, right: 12, bottom: 0 }}>
          <XAxis
            dataKey="x"
            type="number"
            domain={xDomain}
            ticks={timeline.ticks}
            tickFormatter={turnTick}
            allowDecimals={false}
            interval="preserveStartEnd"
            minTickGap={12}
            {...axis}
          />
          <YAxis width={40} domain={yDomain} ticks={yTicks} tickFormatter={tick} {...axis} />
          <ReferenceLine y={0} stroke={tokens.ink2} strokeWidth={1.5} />
          {timeline.segments.map((segment) => (
            <ReferenceLine
              key={segment.game}
              x={segment.boundary}
              stroke={tokens.axis}
              label={({ viewBox }: { viewBox?: { x?: number; y?: number } }) => (
                <text x={(viewBox?.x ?? 0) + 4} y={(viewBox?.y ?? 0) - 8} fill={tokens.muted} fontSize={12}>
                  {gameLabels.get(segment.game) ?? ''}
                </text>
              )}
            />
          ))}
          <ChartHover
            content={({ active, payload, label: x }) => {
              const slot = slots[Number(x)]
              if (!slot || slot.index == null) return null
              return (
                <ChartTooltip
                  active={active}
                  payload={payload}
                  label={x}
                  labelFormat={placeOf}
                  format={(value) => formatNumber(value || 0, TWO_DIGITS)}
                />
              )
            }}
          />
          <Line
            type="monotone"
            dataKey="index"
            name={t('matches.charts.position')}
            stroke={tokens.self}
            strokeWidth={2}
            dot={false}
            activeDot={activeDot}
            connectNulls={false}
          />
          {markers.map((marker) => {
            const place = marker.placement
            if (!place) return null
            const chosen = marker.id === selected
            const r = MARK_RADIUS[marker.weight] + (chosen ? 1.5 : 0)
            const ring = chosen ? 'stroke-ink' : marker.weight === 'note' ? 'stroke-muted' : 'stroke-surface'
            return (
              <ReferenceDot
                key={marker.id}
                x={place.x}
                y={place.y}
                r={r}
                shape={(props: { cx?: number; cy?: number }) => (
                  <circle
                    cx={props.cx}
                    cy={props.cy}
                    r={r}
                    strokeWidth={2}
                    className={`cursor-pointer ${MARK_CLASS[marker.weight]} ${ring}`}
                    onClick={() => onSelect(marker.id)}
                  />
                )}
              />
            )
          })}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
})

/** The markers as a row of buttons in strip order, one tab stop: the arrow
 *  keys, Home and End move between them. Too many for the width scroll the
 *  row sideways, and a marker chosen on the chart is scrolled into view. */
function MarkerStrip({
  markers,
  findings,
  selected,
  onSelect,
  buttons,
}: {
  markers: Marker[]
  findings: readonly ReportFinding[]
  selected: number | null
  onSelect: (id: number) => void
  buttons: RefObject<Map<number, HTMLButtonElement>>
}) {
  const { t, i18n } = useTranslation()
  const words = useWeightWords()
  const row = useRef<HTMLDivElement>(null)
  const [roving, setRoving] = useState<number | null>(null)
  const chosenAt = markers.findIndex((m) => m.id === selected)
  const stop = Math.min(markers.length - 1, roving ?? Math.max(0, chosenAt))

  useEffect(() => {
    const button = selected != null ? buttons.current.get(selected) : undefined
    const container = row.current
    if (!button || !container) return
    const left = button.offsetLeft
    const right = left + button.offsetWidth
    if (left < container.scrollLeft || right > container.scrollLeft + container.clientWidth) {
      container.scrollTo({ left: Math.max(0, left - 8) })
    }
  }, [selected, buttons])

  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const last = markers.length - 1
    const next =
      event.key === 'ArrowRight' ? Math.min(last, stop + 1)
      : event.key === 'ArrowLeft' ? Math.max(0, stop - 1)
      : event.key === 'Home' ? 0
      : event.key === 'End' ? last
      : null
    if (next == null) return
    event.preventDefault()
    setRoving(next)
    buttons.current.get(markers[next].id)?.focus()
  }

  return (
    <div className="space-y-1.5">
      <div
        ref={row}
        role="toolbar"
        aria-label={t('matches.timeline.strip')}
        onKeyDown={move}
        className="relative flex gap-2 overflow-x-auto pb-1.5"
      >
        {markers.map((marker, index) => {
          const finding = findings[marker.id]
          const chosen = marker.id === selected
          const word = words[marker.weight].toLocaleLowerCase(i18n.language)
          return (
            <button
              key={marker.id}
              ref={(node) => {
                if (node) buttons.current.set(marker.id, node)
                else buttons.current.delete(marker.id)
              }}
              type="button"
              tabIndex={index === stop ? 0 : -1}
              aria-pressed={chosen}
              aria-label={markerLabel(finding, word, t)}
              onFocus={() => setRoving(index)}
              onClick={() => onSelect(marker.id)}
              className={`flex min-h-[44px] max-w-64 shrink-0 items-center gap-2.5 rounded-control border px-3 py-1.5 text-left ${
                chosen ? 'border-edge-strong bg-surface3' : 'border-transparent bg-surface2 hover:bg-surface3'
              }`}
            >
              <span aria-hidden="true" className={`size-2.5 shrink-0 rounded-full ${DOT_CLASS[marker.weight]}`} />
              <span className="min-w-0">
                <span className="block text-caption text-muted">{barePlace(finding, t)}</span>
                <span className="block truncate text-body text-ink">{finding.title}</span>
              </span>
            </button>
          )
        })}
      </div>
      {markers.length > 1 && <p className="text-caption text-muted">{t('matches.timeline.keys')}</p>}
    </div>
  )
}

/** A game's replay, at its first beat's turn when a beat has one. */
function gameReplayHref(matchHref: string, game: SummaryGameLine): string {
  const turn = (game.beats ?? []).find((beat) => beat.turn_number != null)?.turn_number
  const base = `${matchHref}/replay?game=${game.game_number}`
  return turn != null ? `${base}&turn=${turn}` : base
}

/** The match report's annotated timeline: one line across every game, a
 *  marker per placed finding (D8/D9), the strip that is the way into them,
 *  the chosen finding's card, a row of facts per game, the notes behind a
 *  disclosure and the line's numbers as a table. The chosen marker is
 *  `?finding=<index into findings>`, written with replace and no scroll. */
export function MatchTimeline({
  findings,
  markers,
  rest,
  othersShown,
  beats,
  definitions,
  games,
  timeline,
  matchHref,
}: {
  findings: readonly ReportFinding[]
  /** In strip order (`routeFindings`). */
  markers: Marker[]
  /** The notes no beat was built from. */
  rest: ReportFinding[]
  /** Whether any finding is shown outside `rest`, which words its label. */
  othersShown: boolean
  /** Each beat by its finding's index (`beatsByFinding`). */
  beats: Map<number, SummaryBeat>
  definitions: Record<string, string>
  games: SummaryGameLine[]
  /** The position track as `buildTimeline` laid it out. */
  timeline: Timeline
  matchHref: string
}) {
  const { t } = useTranslation()
  const [search, setSearch] = useSearchParams()
  const selected = parseFinding(search.get('finding'))
  const buttons = useRef(new Map<number, HTMLButtonElement>())
  const gameLabels = useMemo(() => {
    const labels = new Map<number, string>()
    for (const segment of timeline.segments) {
      const game = games.find((g) => g.game_number === segment.game)
      const result = resultWord(game?.result, t)
      labels.set(
        segment.game,
        result
          ? t('matches.replay.gameResult', { n: segment.game, result })
          : t('matches.game.title', { n: segment.game }),
      )
    }
    return labels
  }, [timeline, games, t])

  const select = useCallback(
    (id: number | null) =>
      setSearch(
        (previous) => {
          const params = new URLSearchParams(previous)
          if (id == null || params.get('finding') === String(id)) params.delete('finding')
          else params.set('finding', String(id))
          return params
        },
        { replace: true, preventScrollReset: true },
      ),
    [setSearch],
  )

  const onChart = markers.filter((m) => m.placement != null).length
  const chosen = markers.find((m) => m.id === selected)
  const hasLine = timeline.segments.length > 0
  const numbers = timeline.slots.filter((slot) => slot.turn != null && slot.index != null)

  const close = () => {
    if (chosen) buttons.current.get(chosen.id)?.focus()
    select(null)
  }

  return (
    <Card title={t('matches.timeline.title')} subtitle={t('matches.timeline.subtitle')}>
      <div className="space-y-4">
        {hasLine ? (
          <div className="space-y-2">
            <TimelineChart
              timeline={timeline}
              markers={markers}
              selected={selected}
              onSelect={select}
              gameLabels={gameLabels}
              label={t('matches.timeline.chartLabel', { count: onChart, n: formatNumber(onChart) })}
            />
            <p className="text-caption text-muted">{t('matches.report.lineNote')}</p>
          </div>
        ) : (
          <p className="text-body text-ink2">{t('matches.timeline.noLine')}</p>
        )}
        {markers.length > 0 ? (
          <MarkerStrip markers={markers} findings={findings} selected={selected} onSelect={select} buttons={buttons} />
        ) : (
          <p className="text-body text-ink2">{t('matches.timeline.nonePlaced')}</p>
        )}
        {chosen && (
          <ChosenFinding
            key={chosen.id}
            finding={findings[chosen.id]}
            marker={chosen}
            beat={beats.get(chosen.id)}
            definitions={definitions}
            matchHref={matchHref}
            onClose={close}
          />
        )}
        {games.length > 0 && (
          <div className="divide-y divide-line border-t border-line pt-4">
            {games.map((game) => (
              <GameFacts key={game.game_number} game={game} replayHref={gameReplayHref(matchHref, game)} />
            ))}
          </div>
        )}
        {rest.length > 0 && (
          <Disclosure
            summary={
              othersShown
                ? t('matches.report.everyOther', { n: rest.length })
                : t('matches.report.every', { n: rest.length })
            }
          >
            <FindingList findings={rest} />
          </Disclosure>
        )}
        {numbers.length > 0 && (
          <Disclosure summary={t('matches.report.showNumbers')}>
            <DataTable
              columns={[t('matches.report.game'), t('matches.report.turn'), t('matches.charts.position')]}
              rows={numbers.map((slot) => [
                String(slot.game),
                String(slot.turn),
                formatNumber(slot.index || 0, TWO_DIGITS),
              ])}
            />
          </Disclosure>
        )}
      </div>
    </Card>
  )
}

/** The chosen marker's finding: the beat built from it when there is one
 *  (its label, explained, and its meter), where the marker sits when its
 *  turn has no point, the way into the replay at its turn, and Close. */
function ChosenFinding({
  finding,
  marker,
  beat,
  definitions,
  matchHref,
  onClose,
}: {
  finding: ReportFinding
  marker: Marker
  beat: SummaryBeat | undefined
  definitions: Record<string, string>
  matchHref: string
  onClose: () => void
}) {
  const { t } = useTranslation()
  const place = marker.placement
  const turn = finding.turn_number
  // The note counts turns as the place line does: the player's own when
  // the finding does and the shown point has one, the game's otherwise.
  const own = finding.self_turn_index != null && place?.kind === 'turn' && place.shownSelfTurn != null
  const lead = beat ? (
    <div className="mb-2 space-y-1">
      <BeatLabel label={beat.label} definition={definitions[beat.label]} />
      {beat.meter && (
        <div className="max-w-40">
          <TwoSidedMeter self={beat.meter[0]} opp={beat.meter[1]} />
        </div>
      )}
      {beat.text !== finding.title && <p className="text-body text-ink">{beat.text}</p>}
    </div>
  ) : undefined
  return (
    <FindingBlock finding={finding} lead={lead}>
      {place?.kind === 'turn' && place.nearest && turn != null && (
        <p className="mt-2 text-caption text-muted">
          {own
            ? t('matches.timeline.nearest', { turn: finding.self_turn_index, shown: place.shownSelfTurn })
            : t('matches.timeline.nearest', { turn, shown: place.shownTurn })}
        </p>
      )}
      {finding.confidence === 'partial' && (
        <p className="mt-2 text-caption text-muted">{t('matches.report.partlyHiddenNote')}</p>
      )}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        {finding.game_number != null && turn != null ? (
          <p className="text-caption">
            <TextLink href={`${matchHref}/replay?game=${finding.game_number}&turn=${turn}`}>
              {t('matches.timeline.replayTurn', { turn })}
            </TextLink>
          </p>
        ) : (
          <span />
        )}
        <Button size="sm" aria-label={t('matches.timeline.closeLabel')} onClick={onClose}>
          {t('matches.timeline.close')}
        </Button>
      </div>
    </FindingBlock>
  )
}
