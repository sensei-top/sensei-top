import { useTranslation } from 'react-i18next'
import { useMatchDetail, useMatchReport } from '../api'
import { MatchReportPanel } from '../components/MatchReportPanel'
import { MatchHero } from '../components/match/MatchHero'
import { MtgoDeckPick } from '../components/match/MtgoDeckPick'
import { BackLink, ErrorNote, OutlineCard } from '../components/ui'
import { castCards } from '../lib/matchArt'

/** The way back to the list: a link, so Back in the browser does the same
 *  and lands where the list was left. */
function BackToMatches() {
  const { t } = useTranslation()
  return (
    <p className="text-caption">
      <BackLink href="/matches">{t('matches.detail.all')}</BackLink>
    </p>
  )
}

/** The page's pending state: the back link, drawn for real, then the
 *  frames of the hero, the games row and the report. */
function DetailOutline() {
  const { t } = useTranslation()
  return (
    <div className="space-y-6">
      <BackToMatches />
      <OutlineCard label={t('matches.hero.kicker')} words={t('matches.detail.reading')} height="h-56" />
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,16rem),1fr))] gap-4">
        <OutlineCard label={t('matches.game.title', { n: 1 })} height="h-[27rem]" />
        <OutlineCard label={t('matches.game.title', { n: 2 })} height="h-[27rem]" />
      </div>
      <OutlineCard label={t('matches.report.stoodOut')} height="h-64" />
    </div>
  )
}

/** `/matches/:id`: the match's report. The hero, then the report itself;
 *  the games turn by turn are on the replay's own page. An MTGO match has
 *  its deck's pick between the two. The hero's title
 *  is the report's headline once the report has one and anything to say,
 *  and the result and the games' count from the match until then. */
export function MatchDetailView({ matchId }: { matchId: string }) {
  const detail = useMatchDetail(matchId)
  const report = useMatchReport(matchId)

  if (detail.isPending) return <DetailOutline />
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
    <div className="arrive space-y-6">
      <BackToMatches />
      <MatchHero
        match={match}
        headline={headline}
        subhead={subhead}
        art={art}
        replayHref={`/matches/${encodeURIComponent(match.match_id)}/replay`}
      />
      {match.source === 'mtgo' && <MtgoDeckPick matchId={match.match_id} />}
      <MatchReportPanel matchId={match.match_id} />
    </div>
  )
}
