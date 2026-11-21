import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useMatchReport, type PositionPoint, type ReportFinding, type SummaryBeat, type SummaryGameLine } from '../api'
import { useAi } from '../ai/registry'
import { beatsByFinding, buildTimeline, byWeightThenPlace, routeFindings, weightOf } from '../lib/timeline'
import { FindingList, MatchTimeline } from './match/MatchTimeline'
import { Card, Disclosure, EmptyState, ErrorNote, Loading, SectionLabel, TwoSidedMeter } from './ui'

/** The gaps' groups shown before the rest go behind a disclosure. */
const GAPS_SHOWN = 4

/** The matchup's beats: each its label, its meter when it has one, and its
 *  sentence. The weighted ones are findings too, so their weight is said
 *  there, not here. */
function Pairing({ beats }: { beats: SummaryBeat[] }) {
  const { t } = useTranslation()
  if (beats.length === 0) return null
  return (
    <Card title={t('matches.report.pairing')}>
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
  const { t } = useTranslation()
  if (gapGroups.length === 0) return null
  const shown = gapGroups.slice(0, GAPS_SHOWN)
  const rest = gapGroups.slice(GAPS_SHOWN)
  return (
    <Card
      title={t('matches.report.gapsTitle')}
      subtitle={t('matches.report.gapsSubtitle')}
    >
      <GapList gapGroups={shown} />
      {rest.length > 0 && (
        <div className="mt-3">
          <Disclosure summary={t('matches.report.showOther', { count: rest.length, n: rest.length })}>
            <GapList gapGroups={rest} />
          </Disclosure>
        </div>
      )}
    </Card>
  )
}

/** "About these readings": what the match's findings rest on, said once, and
 *  what each beat's label means. Closed; not drawn when there is neither. */
function AboutReadings({ caveats, definitions }: { caveats: string[]; definitions: Record<string, string> }) {
  const { t } = useTranslation()
  const labels = Object.entries(definitions)
  if (caveats.length === 0 && labels.length === 0) return null
  return (
    <Disclosure summary={t('matches.report.about.title')}>
      <div className="space-y-4">
        {caveats.length > 0 && (
          <section className="space-y-1">
            <SectionLabel as="h3">{t('matches.report.about.caveats')}</SectionLabel>
            <ul className="space-y-1 text-caption text-muted">
              {caveats.map((caveat, i) => (
                <li key={i}>{caveat}</li>
              ))}
            </ul>
          </section>
        )}
        {labels.length > 0 && (
          <section className="space-y-1">
            <SectionLabel as="h3">{t('matches.report.about.labels')}</SectionLabel>
            <dl className="space-y-1 text-caption">
              {labels.map(([label, sentence]) => (
                <div key={label}>
                  <dt className="inline font-semibold text-ink2">{label}</dt>
                  <dd className="inline text-muted">{` ${sentence}`}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
      </div>
    </Disclosure>
  )
}

/** One empty list, so a match with no line passes the same array each time. */
const NO_POINTS: PositionPoint[] = []
const NO_FINDINGS: ReportFinding[] = []
const NO_GAMES: SummaryGameLine[] = []

/** The post-game report under the match's hero: local, deterministic
 *  findings computed fresh on every load (review/__init__.py — never
 *  stored, so it is always current with respect to `cards` and deck data),
 *  plus an opt-in narrative over them. A finished match has the whole game
 *  on disk, so every finding can be checked against what happened.
 *
 *  Drawn in the order a player reads a match back: the findings about the
 *  whole match, the timeline (`MatchTimeline`), what the readings rest on,
 *  then the pairing beside the gaps, and the coach's summary. */
export function MatchReportPanel({ matchId }: { matchId: string }) {
  const { t } = useTranslation()
  const report = useMatchReport(matchId)
  const ai = useAi()
  const data = report.data
  const findings = data?.findings ?? NO_FINDINGS
  const track = data?.position_track ?? NO_POINTS
  const games = data?.summary.games
  const beats = useMemo(
    () => beatsByFinding(findings, (games ?? []).flatMap((game) => game.beats ?? [])),
    [findings, games],
  )
  const timeline = useMemo(() => buildTimeline(track), [track])
  const routed = useMemo(
    () =>
      routeFindings(
        findings.map((f, id) => ({
          id,
          game: f.game_number ?? null,
          turn: f.turn_number ?? null,
          weight: weightOf(f.severity),
          beat: beats.has(id),
        })),
        timeline,
      ),
    [findings, beats, timeline],
  )

  if (report.isPending) return <Loading />
  if (report.error) return <ErrorNote error={report.error} />
  if (!data) return null

  const { summary, gaps } = data
  if (findings.length === 0 && gaps.length === 0) {
    return <EmptyState message={t('matches.report.nothingToReport')} />
  }
  const gapGroups = (summary.gap_groups ?? []).map((g) => ({ cause: g.cause, blocked: g.blocked ?? [] }))
  const definitions = summary.beat_definitions ?? {}
  const matchup = summary.matchup ?? []
  const wholeMatch = routed.wholeMatch.map((s) => findings[s.id]).sort(byWeightThenPlace)
  const rest = routed.rest.map((s) => findings[s.id]).sort(byWeightThenPlace)

  return (
    <div className="space-y-6">
      {wholeMatch.length > 0 && (
        <Card title={t('matches.report.wholeMatch')} subtitle={t('matches.report.wholeMatchSubtitle')}>
          <FindingList findings={wholeMatch} />
        </Card>
      )}
      <MatchTimeline
        findings={findings}
        markers={routed.markers}
        rest={rest}
        othersShown={wholeMatch.length + routed.markers.length > 0}
        beats={beats}
        definitions={definitions}
        games={summary.games ?? NO_GAMES}
        timeline={timeline}
        matchHref={`/matches/${encodeURIComponent(matchId)}`}
      />
      <AboutReadings caveats={data.caveats ?? []} definitions={definitions} />
      {(matchup.length > 0 || gapGroups.length > 0) && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,24rem),1fr))] items-start gap-6">
          <Pairing beats={matchup} />
          <Gaps gapGroups={gapGroups} />
        </div>
      )}
      {ai && <ai.ReportNarrativeCard matchId={matchId} />}
    </div>
  )
}
