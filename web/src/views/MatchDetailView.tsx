import { useMatchDetail, useMatchReport } from '../api'
import { MatchReportPanel } from '../components/MatchReportPanel'
import { MatchHero } from '../components/match/MatchHero'
import { BackLink, ErrorNote, Loading } from '../components/ui'
import { castCards } from '../lib/matchArt'

/** The way back to the list: a link, so Back in the browser does the same
 *  and lands where the list was left. */
function BackToMatches() {
  return (
    <p className="text-caption">
      <BackLink href="/matches">All matches</BackLink>
    </p>
  )
}

/** `/matches/:id`: the match's report. The hero, then the report itself;
 *  the games turn by turn are on the replay's own page. The hero's title
 *  is the report's headline once the report has one and anything to say,
 *  and the result and the games' count from the match until then. */
export function MatchDetailView({ matchId }: { matchId: string }) {
  const detail = useMatchDetail(matchId)
  const report = useMatchReport(matchId)

  if (detail.isPending) return <Loading />
  if (detail.error) {
    return (
      <div className="space-y-4">
        <BackToMatches />
        <ErrorNote error={detail.error} />
      </div>
    )
  }

  const match = detail.data
  const data = report.data
  const hasSomething = data != null && (data.findings.length > 0 || data.gaps.length > 0)
  const headline = hasSomething && data.summary.headline.trim() ? data.summary.headline : null
  const subhead = headline != null ? (data?.summary.subhead ?? null) : null
  // One card on the page: the last the opponent turned to, or the
  // viewer's when the opponent cast nothing.
  const art = castCards(match, 'opponent')[0] ?? castCards(match, 'self')[0] ?? null

  return (
    <div className="space-y-6">
      <BackToMatches />
      <MatchHero
        match={match}
        headline={headline}
        subhead={subhead}
        art={art}
        replayHref={`/matches/${encodeURIComponent(match.match_id)}/replay`}
      />
      <MatchReportPanel matchId={match.match_id} />
    </div>
  )
}
