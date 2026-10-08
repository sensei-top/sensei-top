import { useMemo, useState, useSyncExternalStore } from 'react'
import {
  useGenerateMatchReportNarrative,
  useLLMStatus,
  useMatchReport,
  useReportNarrativePrompt,
  type PositionPoint,
  type ReportEvidence,
  type ReportFinding,
  type SummaryBeat,
  type SummaryGameLine,
} from '../api'
import { writerFrom } from '../lib/writer'
import { GenerateCard } from './GenerateCard'
import { GameCard, type WeighedGame } from './match/GameCard'
import {
  Button,
  Card,
  DataTable,
  Disclosure,
  EmptyState,
  ErrorNote,
  Finding,
  type FindingWeight,
  Loading,
  SectionLabel,
  TwoSidedMeter,
} from './ui'

/** The report's weights, heaviest first. */
const FINDING_WEIGHTS: readonly FindingWeight[] = ['decisive', 'flag', 'notice', 'note']

/** A finding's or a beat's severity as a weight. The report sends only the
 *  four; anything else is a note, so no code ever reaches the page. */
function weightOf(severity: string): FindingWeight {
  return (FINDING_WEIGHTS as readonly string[]).includes(severity) ? (severity as FindingWeight) : 'note'
}

/** The gaps' groups shown before the rest go behind a disclosure. */
const GAPS_SHOWN = 4

/** The width from which the report is two columns: Tailwind's `lg`. */
const WIDE = '(min-width: 64rem)'

function subscribeWide(onChange: () => void): () => void {
  const query = window.matchMedia(WIDE)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

/** Whether the page is at least 64rem wide, read again as the width
 *  crosses it. */
function useWide(): boolean {
  return useSyncExternalStore(
    subscribeWide,
    () => window.matchMedia(WIDE).matches,
    () => false,
  )
}

/** Heaviest first, then by game and turn; the whole match before its
 *  games, and a game's own findings before its turns'. */
function byWeightThenPlace(a: ReportFinding, b: ReportFinding): number {
  const weight =
    FINDING_WEIGHTS.indexOf(weightOf(a.severity)) - FINDING_WEIGHTS.indexOf(weightOf(b.severity))
  if (weight !== 0) return weight
  const game = (a.game_number ?? 0) - (b.game_number ?? 0)
  if (game !== 0) return game
  return (a.turn_number ?? 0) - (b.turn_number ?? 0)
}

function placeText(f: ReportFinding): string {
  let place = 'Whole match'
  if (f.game_number != null) {
    if (f.self_turn_index != null) place = `Game ${f.game_number} · your turn ${f.self_turn_index}`
    else if (f.turn_number != null) place = `Game ${f.game_number} · turn ${f.turn_number}`
    else place = `Game ${f.game_number}`
  }
  return f.confidence === 'partial' ? `${place} · partly hidden` : place
}

/** An evidence row whose raw value already appears, spelled out, in the
 *  finding's own title is not repeated beneath it — not hidden data (the
 *  full finding is still in the API response), just not said a second
 *  time directly beneath the sentence that already said it. A row whose
 *  value never surfaces in prose (a pace, a share) still renders, since
 *  that is the only place it appears at all. */
function evidenceIsRedundant(title: string, value: ReportEvidence['value']): boolean {
  if (value == null || typeof value === 'boolean') return false
  return title.includes(String(value))
}

/** One finding: its weight and place, its title, then its detail, its
 *  caveats, and the numbers behind it that the title does not already say,
 *  behind a disclosure. */
function FindingBlock({ finding }: { finding: ReportFinding }) {
  const caveats = finding.caveats ?? []
  const evidence = (finding.evidence ?? []).filter((e) => !evidenceIsRedundant(finding.title, e.value))
  return (
    <Finding weight={weightOf(finding.severity)} where={placeText(finding)} title={finding.title}>
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
          <Disclosure summary="The numbers behind it">
            <DataTable
              columns={['Detail', 'Value']}
              rows={evidence.map((e) => [
                e.label,
                e.display ?? `${e.value ?? '—'}${e.unit ? ` ${e.unit}` : ''}`,
              ])}
            />
          </Disclosure>
        </div>
      )}
    </Finding>
  )
}

/** A list of findings, and under it, when one of them is partial, the one
 *  line that says what "partly hidden" means. */
function FindingList({ findings }: { findings: ReportFinding[] }) {
  const partial = findings.some((f) => f.confidence === 'partial')
  return (
    <div className="space-y-3">
      {findings.map((f, i) => (
        <FindingBlock key={`${f.code}-${i}`} finding={f} />
      ))}
      {partial && (
        <p className="text-caption text-muted">
          Partly hidden: some of what the finding rests on was hidden, not observed, or ambiguous.
        </p>
      )}
    </div>
  )
}

/** "What stood out": the findings that weigh more than a note, and every
 *  other one behind a disclosure under them. */
function StoodOut({ findings }: { findings: ReportFinding[] }) {
  const sorted = findings.slice().sort(byWeightThenPlace)
  const shown = sorted.filter((f) => weightOf(f.severity) !== 'note')
  const rest = sorted.filter((f) => weightOf(f.severity) === 'note')
  return (
    <Card title="What stood out">
      {shown.length > 0 ? (
        <FindingList findings={shown} />
      ) : (
        <p className="text-body text-ink2">Nothing in this match weighed enough to stand out.</p>
      )}
      {rest.length > 0 && (
        <div className="mt-4">
          <Disclosure
            summary={shown.length > 0 ? `Every other finding (${rest.length})` : `Every finding (${rest.length})`}
          >
            <FindingList findings={rest} />
          </Disclosure>
        </div>
      )}
    </Card>
  )
}

/** The matchup's beats: each its label, its meter when it has one, and its
 *  sentence. The weighted ones are findings too, so their weight is said
 *  there, not here. */
function Pairing({ beats }: { beats: SummaryBeat[] }) {
  if (beats.length === 0) return null
  return (
    <Card title="This pairing">
      <ul className="divide-y divide-line">
        {beats.map((beat, i) => (
          <li key={`${beat.code}-${i}`} className="space-y-1 py-2.5 first:pt-0 last:pb-0">
            <SectionLabel as="p">{beat.label}</SectionLabel>
            {beat.meter && (
              <div className="max-w-40">
                <TwoSidedMeter self={beat.meter[0]} opp={beat.meter[1]} />
              </div>
            )}
            <p className="text-body text-ink">{beat.text}</p>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function GapList({ gapGroups }: { gapGroups: { cause: string; blocked: string[] }[] }) {
  return (
    <ul className="space-y-2 text-body text-ink2">
      {gapGroups.map((g, i) => (
        <li key={i}>
          {g.cause}
          {g.blocked.length > 0 && (
            <ul className="mt-1 ml-4 list-disc space-y-0.5 text-caption text-muted">
              {g.blocked.map((b, j) => (
                <li key={j}>{b}</li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  )
}

/** The report's gaps, collapsed to their causes, each with what it
 *  blocked under it: the first four, and the rest behind a disclosure. */
function Gaps({ gapGroups }: { gapGroups: { cause: string; blocked: string[] }[] }) {
  if (gapGroups.length === 0) return null
  const shown = gapGroups.slice(0, GAPS_SHOWN)
  const rest = gapGroups.slice(GAPS_SHOWN)
  return (
    <Card
      title="What this report could not see"
      subtitle="Not evidence that something was wrong, only that this reader could not tell."
    >
      <GapList gapGroups={shown} />
      {rest.length > 0 && (
        <div className="mt-3">
          <Disclosure summary={rest.length === 1 ? 'Show the other one' : `Show the other ${rest.length}`}>
            <GapList gapGroups={rest} />
          </Disclosure>
        </div>
      )}
    </Card>
  )
}

/** The games in a grid of as many columns as hold 16rem each, and, when
 *  any game has a position line, what the line is and its numbers. */
function Games({
  games,
  track,
  turningPoints,
  matchHref,
}: {
  games: SummaryGameLine[]
  track: PositionPoint[]
  turningPoints: Map<number, number>
  matchHref: string
}) {
  const byGame = useMemo(() => {
    const grouped = new Map<number, PositionPoint[]>()
    for (const point of track) {
      const points = grouped.get(point.game_number) ?? []
      points.push(point)
      grouped.set(point.game_number, points)
    }
    for (const points of grouped.values()) points.sort((a, b) => a.turn_number - b.turn_number)
    return grouped
  }, [track])
  const weighed: WeighedGame[] = useMemo(
    () =>
      games.map((game) => ({
        ...game,
        beats: (game.beats ?? []).map((beat) => ({ ...beat, severity: weightOf(beat.severity) })),
      })),
    [games],
  )

  if (games.length === 0) return null
  const lines = games.filter((game) => (byGame.get(game.game_number)?.length ?? 0) > 0)
  const anyDot = lines.some((game) => {
    const turn = turningPoints.get(game.game_number)
    return turn != null && (byGame.get(game.game_number) ?? []).some((p) => p.turn_number === turn)
  })
  const numbers = [...byGame.entries()].sort((a, b) => a[0] - b[0]).flatMap(([, points]) => points)

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,16rem),1fr))] gap-4">
        {weighed.map((game) => (
          <GameCard
            key={game.game_number}
            game={game}
            points={byGame.get(game.game_number) ?? NO_POINTS}
            turningPointTurn={turningPoints.get(game.game_number) ?? null}
            replayHref={`${matchHref}/replay?game=${game.game_number}`}
          />
        ))}
      </div>
      {lines.length > 0 && (
        <>
          <div className="space-y-1 text-caption text-muted">
            <p>
              The line is your position, turn by turn: life, board, hand and mana weighed into one number. Above
              zero you are ahead.
            </p>
            {anyDot && <p>The dot is the game's largest swing.</p>}
          </div>
          <Disclosure summary="Show the numbers">
            <DataTable
              columns={['Game', 'Turn', 'Position']}
              rows={numbers.map((p) => [String(p.game_number), String(p.turn_number), p.index.toFixed(2)])}
            />
          </Disclosure>
        </>
      )}
    </div>
  )
}

/** One empty list, so a game with no line passes the same array each time. */
const NO_POINTS: PositionPoint[] = []

function ReportNarrativeCard({ matchId }: { matchId: string }) {
  const [open, setOpen] = useState(false)
  const prompt = useReportNarrativePrompt(matchId, open)
  const llmStatus = useLLMStatus()
  const generate = useGenerateMatchReportNarrative()

  if (!open) {
    return (
      <Card
        title="Coach's summary"
        subtitle="Each game's shape turn by turn and this report's findings, written into coaching prose."
      >
        <Button variant="primary" onClick={() => setOpen(true)}>
          Show the coach's summary
        </Button>
      </Card>
    )
  }

  const body = prompt.data
  return (
    <GenerateCard
      title="Coach's summary"
      subtitle="Each game's shape turn by turn and this report's findings, written into coaching prose."
      writer={writerFrom(llmStatus.data)}
      prompt={body?.prompt}
      narrative={body?.status === 'ok' ? body.narrative : null}
      model={body?.model}
      generatedAt={body?.generated_at}
      costUsd={body?.cost_usd}
      stale={body?.stale}
      loading={prompt.isLoading}
      error={
        body?.status === 'no_report'
          ? 'Nothing to review for this match yet.'
          : (prompt.error?.message ?? null)
      }
      onGenerate={() => generate.mutate(matchId)}
      generating={generate.isPending}
      generateError={generate.error?.message}
    />
  )
}

/** The post-game report under the match's hero: local, deterministic
 *  findings computed fresh on every load (review/__init__.py — never
 *  stored, so it is always current with respect to `cards` and deck data),
 *  plus an opt-in narrative over them. A finished match has the whole game
 *  on disk, so every finding can be checked against what happened.
 *
 *  Drawn in the order a player reads a match back: one card per game
 *  (`summary.games`, review/summary.py), then what stood out beside the
 *  pairing, the gaps and the coach's summary; from 64rem up the second
 *  column sits beside the findings, below that under them. When no finding
 *  weighs more than a note, the gaps lead instead (`GapsLead`), and with
 *  no gaps either the report is one column. */
export function MatchReportPanel({ matchId }: { matchId: string }) {
  const report = useMatchReport(matchId)
  const wide = useWide()
  const data = report.data
  const turningPoints = useMemo(() => {
    const turns = new Map<number, number>()
    for (const f of data?.findings ?? []) {
      if (f.code === 'turning_point' && f.game_number != null && f.turn_number != null && !turns.has(f.game_number)) {
        turns.set(f.game_number, f.turn_number)
      }
    }
    return turns
  }, [data])

  if (report.isPending) return <Loading />
  if (report.error) return <ErrorNote error={report.error} />
  if (!data) return null

  const { summary, findings, gaps } = data
  if (findings.length === 0 && gaps.length === 0) {
    return <EmptyState message="Nothing to report for this match: too little of it was recorded." />
  }
  const gapGroups = (summary.gap_groups ?? []).map((g) => ({ cause: g.cause, blocked: g.blocked ?? [] }))
  const matchup = summary.matchup ?? []
  const anyStandsOut = findings.some((f) => weightOf(f.severity) !== 'note')

  return (
    <div className="space-y-6">
      <Games
        games={summary.games ?? []}
        track={data.position_track ?? NO_POINTS}
        turningPoints={turningPoints}
        matchHref={`/matches/${encodeURIComponent(matchId)}`}
      />
      {anyStandsOut ? (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:items-start">
          <StoodOut findings={findings} />
          <div className="space-y-6">
            <Pairing beats={matchup} />
            <Gaps gapGroups={gapGroups} />
            <ReportNarrativeCard matchId={matchId} />
          </div>
        </div>
      ) : gapGroups.length > 0 ? (
        <GapsLead findings={findings} matchup={matchup} gapGroups={gapGroups} matchId={matchId} wide={wide} />
      ) : (
        <div className="space-y-6">
          <StoodOut findings={findings} />
          <Pairing beats={matchup} />
          <ReportNarrativeCard matchId={matchId} />
        </div>
      )}
    </div>
  )
}

/** The report when no finding weighs more than a note, but it has gaps:
 *  from 64rem up the gaps take the wide column, and what stood out heads
 *  the narrow one, above the pairing and the coach's summary; below that,
 *  what stood out comes first, as it does with findings above a note. The
 *  cards are one grid's children, in the order seen at each width, so a
 *  card keeps its state as the width crosses 64rem. The narrow column's
 *  last row takes what height the gaps leave, so its cards stay together
 *  at its top. */
function GapsLead({
  findings,
  matchup,
  gapGroups,
  matchId,
  wide,
}: {
  findings: ReportFinding[]
  matchup: SummaryBeat[]
  gapGroups: { cause: string; blocked: string[] }[]
  matchId: string
  wide: boolean
}) {
  const withPairing = matchup.length > 0
  const gaps = (
    <div
      key="gaps"
      className={`min-w-0 lg:col-start-1 lg:row-start-1 ${withPairing ? 'lg:row-span-4' : 'lg:row-span-3'}`}
    >
      <Gaps gapGroups={gapGroups} />
    </div>
  )
  const stoodOut = (
    <div key="stood-out" className="min-w-0 lg:col-start-2">
      <StoodOut findings={findings} />
    </div>
  )
  const pairing = withPairing ? (
    <div key="pairing" className="min-w-0 lg:col-start-2">
      <Pairing beats={matchup} />
    </div>
  ) : null
  const coach = (
    <div key="coach" className="min-w-0 lg:col-start-2">
      <ReportNarrativeCard matchId={matchId} />
    </div>
  )
  return (
    <div
      className={`grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:items-start ${
        withPairing ? 'lg:grid-rows-[auto_auto_auto_1fr]' : 'lg:grid-rows-[auto_auto_1fr]'
      }`}
    >
      {wide ? [gaps, stoodOut, pairing, coach] : [stoodOut, pairing, gaps, coach]}
    </div>
  )
}
