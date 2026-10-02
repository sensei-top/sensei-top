import { useState } from 'react'
import { Navigate } from 'react-router'
import {
  useCoach,
  useCoachNarrative,
  useCoachReport,
  useGenerateCoachNarrative,
  useLLMStatus,
  type CoachModelOption,
  type CoachNarrativeResponse,
  type CoachReportSummary,
} from '../api'
import { CoachReport } from '../components/CoachReport'
import { Profile } from '../components/coach/Profile'
import { GenerateCard } from '../components/GenerateCard'
import { Callout, Card, EmptyState, ErrorNote, Loading, Select, TextLink } from '../components/ui'
import {
  historyDetail,
  modelCostNote,
  modelLabel,
  reportByline,
  reportTitle,
  type ReportParam,
} from '../lib/coach'
import { writerFrom } from '../lib/writer'
import { placeById } from '../shell/places'

/** "Every report": one row a report, newest first (`/api/coach`'s order,
 *  so the first row is the latest). A row's title opens that report at
 *  its address, the latest's at `/coach`; the report on screen is not a
 *  link and says so. The title is the row's target, 44 px high. */
function HistoryCard({
  reports,
  models,
  onPage,
  now,
}: {
  reports: CoachReportSummary[]
  models: CoachModelOption[]
  onPage: number | null
  now: number
}) {
  const latestId = reports[0]?.id ?? null
  return (
    <Card title="Every report">
      <ul className="divide-y divide-line">
        {reports.map((r) => {
          const title = reportTitle(r.generated_at, now)
          const isLatest = r.id === latestId
          const isOnPage = r.id === onPage
          return (
            <li key={r.id} className="pb-2">
              <p className="text-body">
                {isOnPage ? (
                  <span aria-current="page" className="inline-flex min-h-[44px] items-center text-ink">
                    {title}
                  </span>
                ) : (
                  <TextLink
                    href={isLatest ? '/coach' : `/coach/${r.id}`}
                    className="inline-flex min-h-[44px] items-center"
                  >
                    {title}
                  </TextLink>
                )}
                {isLatest && <span className="text-muted">{' · latest'}</span>}
                {isOnPage && <span className="text-muted">{' · on this page'}</span>}
              </p>
              <p className="text-caption text-muted">
                {historyDetail({
                  label: modelLabel(r.model, models),
                  costUsd: r.cost_usd,
                  searches: r.web_search_requests,
                })}
              </p>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

/** The model picker, in the writing card's button row (`controls`).
 *  `value === null` means "leave it on the configured default": the
 *  select still shows `defaultModel` then, it just doesn't send it. When
 *  the configured default isn't one of `models` (a model set by hand
 *  outside `REPORT_MODELS`), an extra option stands for it; picking that
 *  option is how you get back to "unset" once you've picked something
 *  else. Each option is the model's label alone. */
function ModelSelect({
  models,
  defaultModel,
  value,
  onChange,
  disabled,
}: {
  models: CoachModelOption[]
  defaultModel: string | null
  value: string | null
  onChange: (model: string | null) => void
  disabled: boolean
}) {
  const knownIds = new Set(models.map((m) => m.id))
  const hasCustomDefault = defaultModel != null && !knownIds.has(defaultModel)
  return (
    <Select
      label="Model"
      value={value ?? defaultModel ?? ''}
      onChange={(next) => onChange(hasCustomDefault && next === defaultModel ? null : next)}
      disabled={disabled}
      options={models.map((m) => ({ value: m.id, label: m.label }))}
    >
      {hasCustomDefault && <option value={defaultModel}>{defaultModel} (from your settings)</option>}
    </Select>
  )
}

/** A report's heading ("Report of Sep 22"), its byline in one caption
 *  line, then the report itself. The byline needs the model that wrote
 *  it, and is left out for a report that names none. */
function ReportDocument({
  report,
  models,
  now,
}: {
  report: CoachNarrativeResponse
  models: CoachModelOption[]
  now: number
}) {
  return (
    <>
      <div>
        <h2 className="font-display text-heading text-ink">{reportTitle(report.generated_at, now)}</h2>
        {report.model && (
          <p className="text-caption text-muted">
            {reportByline({
              label: modelLabel(report.model, models),
              costUsd: report.cost_usd,
              searches: report.web_search_requests,
            })}
          </p>
        )}
      </div>
      {report.narrative && <CoachReport prose={report.narrative} sources={report.sources ?? []} />}
    </>
  )
}

/** `/coach`: the latest report and the way to write the next one, over
 *  the free local evidence it is written from (`docs/coach.md`).
 *
 *  `useCoach` and `useCoachNarrative` are two separate evidence rebuilds
 *  of several seconds each on the real server; neither is
 *  `enabled`-gated on the other, so they run in parallel. Each section
 *  gates on its own query's `isPending`/`error` rather than assuming both
 *  have answered, so a slow load reads as loading skeletons, never an
 *  empty flash of "nothing here yet".
 *
 *  In order: the stale callout, the report's heading and byline, the
 *  report, the writing card, the profile, and the history with two
 *  reports or more. */
function LatestCoach() {
  const llmStatus = useLLMStatus()
  const coach = useCoach()
  const narrative = useCoachNarrative()
  const generate = useGenerateCoachNarrative()
  // The day in a title changes with the year alone: read the clock once.
  const [now] = useState(() => Date.now())
  // null means "the configured default"; see ModelSelect above.
  const [model, setModel] = useState<string | null>(null)

  const reports = coach.data?.reports ?? []
  const models = coach.data?.models ?? []
  const defaultModel = coach.data?.default_model ?? null
  const sufficient = coach.data?.sufficient ?? false
  const evidence = coach.data?.evidence ?? null
  const writer = writerFrom(llmStatus.data, null, 'coach')
  const report = narrative.data?.status === 'ok' ? narrative.data : null

  // Only a coach that answered can say there are too few matches; a failed
  // request says it failed, below.
  const insufficient =
    !coach.isPending &&
    !narrative.isPending &&
    coach.data != null &&
    coach.error == null &&
    !coach.data.sufficient &&
    narrative.data?.status === 'no_report'

  // Too few matches for a report, and none written before: the empty state
  // alone, with nothing about how a report is written.
  if (insufficient) {
    return (
      <EmptyState
        icon={placeById('coach').icon}
        title="Not enough matches for a report yet"
        message="The coach reads your finished constructed matches and needs at least ten of them before it has something to say."
      />
    )
  }

  // A cost is said only of a key's own spend: a plan's is its allowance.
  const costNote = writer.by === 'key' ? modelCostNote(model ?? defaultModel, models, reports) : null

  return (
    <div className="space-y-6">
      {narrative.isPending ? (
        <Loading />
      ) : narrative.error ? (
        <ErrorNote error={narrative.error} />
      ) : (
        <>
          {report?.stale && (
            <Callout tone="warn" title="Written before your latest matches">
              <p>
                You have played since this report was written, so its numbers stop short of your latest matches. A
                new report reads them all.
              </p>
            </Callout>
          )}
          {report && <ReportDocument report={report} models={models} now={now} />}
          {coach.isPending ? (
            <Loading />
          ) : (
            <GenerateCard
              title={report ? 'Write a new report' : 'Write your first report'}
              subtitle="Claude reads the numbers on this page and searches the web for news of the format, then writes the report. It takes a few minutes, and every report is kept."
              writer={writer}
              prompt={narrative.data?.prompt}
              narrative={undefined}
              error={narrative.data?.error}
              onGenerate={() => generate.mutate(model)}
              generating={generate.isPending}
              generateError={generate.error?.message}
              emptyNote={null}
              controls={
                models.length > 0 ? (
                  <ModelSelect
                    models={models}
                    defaultModel={defaultModel}
                    value={model}
                    onChange={setModel}
                    disabled={generate.isPending}
                  />
                ) : undefined
              }
            >
              {costNote && <p className="text-caption text-muted">{costNote}</p>}
            </GenerateCard>
          )}
        </>
      )}

      {coach.isPending ? (
        <Loading />
      ) : coach.error ? (
        <ErrorNote error={coach.error} />
      ) : (
        <>
          {sufficient && evidence && <Profile evidence={evidence} now={now} />}
          {reports.length >= 2 && (
            <HistoryCard reports={reports} models={models} onPage={report?.id ?? null} now={now} />
          )}
        </>
      )}
    </div>
  )
}

/** `/coach/:id`: one report as it was written, with the way back to the
 *  latest, and the history. No writing card and no profile: the profile
 *  is today's numbers, not that report's. `useCoachNarrative` is never
 *  asked here.
 *
 *  A missing report and a failed request both come back from
 *  `useCoachReport` as an error, so "no such report" is decided from
 *  `coach.reports` once `useCoach` answers, and the report's own error
 *  is shown only for an id in the list. The latest report's id goes to
 *  `/coach`, so a report has one address. */
function EarlierCoach({ report: param }: { report: 'unknown' | number }) {
  const coach = useCoach()
  const stored = useCoachReport(typeof param === 'number' ? param : null)
  const [now] = useState(() => Date.now())

  if (coach.isPending) return <Loading />
  if (coach.error) return <ErrorNote error={coach.error} />

  const reports = coach.data.reports
  const models = coach.data.models ?? []
  if (param === 'unknown' || !reports.some((r) => r.id === param)) {
    return (
      <EmptyState
        title="No such report"
        message="There is no report with this number."
        action={
          <TextLink href="/coach" className="inline-flex min-h-[44px] items-center">
            Back to the coach
          </TextLink>
        }
      />
    )
  }
  if (param === reports[0]?.id) return <Navigate to="/coach" replace />

  return (
    <div className="space-y-6">
      <Callout>
        <p>An earlier report, kept as it was written.</p>
        <p>
          <TextLink href="/coach" className="inline-flex min-h-[44px] items-center">
            Go to your latest report
          </TextLink>
        </p>
      </Callout>
      {stored.isPending ? (
        <Loading />
      ) : stored.error ? (
        <ErrorNote error={stored.error} />
      ) : stored.data.status === 'ok' ? (
        <ReportDocument report={stored.data} models={models} now={now} />
      ) : null}
      <HistoryCard reports={reports} models={models} onPage={param} now={now} />
    </div>
  )
}

/** The Coach page: a dated, cross-deck report over every completed
 *  Arena and MTGO constructed match. `report` is what the address names
 *  (`reportParam`): the latest at `/coach`, one report at `/coach/:id`. */
export function CoachView({ report }: { report: ReportParam }) {
  return report === 'latest' ? <LatestCoach /> : <EarlierCoach report={report} />
}
