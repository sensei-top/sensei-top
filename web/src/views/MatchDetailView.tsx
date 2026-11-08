import { useTranslation } from 'react-i18next'
import { useDeckMatches, useGuideCoverage, useGuideDecks, useMatchDetail, useMatchReport, type MatchDetail } from '../api'
import { useAi } from '../ai/registry'
import { MatchReportPanel } from '../components/MatchReportPanel'
import { MatchHero } from '../components/match/MatchHero'
import { MtgoDeckPick } from '../components/match/MtgoDeckPick'
import { BackLink, Button, Card, ErrorNote, OutlineCard } from '../components/ui'
import { coverageName } from '../lib/brief'
import { formatRecord } from '../lib/format'
import { matchupRowOver } from '../lib/matchups'
import { opponentLabelText } from '../lib/opponent'
import {
  againstLink,
  briefWritten,
  coverageRowOf,
  pairingAddress,
  pairingHeading,
  pairingMatches,
} from '../lib/pairing'

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

/** A lost match's way to its matchup: the opponent's archetype, this deck's
 *  record against it and, with AI features on, whether its brief is
 *  written, over a button to the pairing page. Nothing unless the match was
 *  lost to a named archetype with a deck that resolves (`againstLink`);
 *  each line is left out while its data is unread or when it has none. */
function AgainstCard({ match }: { match: MatchDetail }) {
  const { t } = useTranslation()
  const ai = useAi()
  const identities = useGuideDecks()
  const link = identities.data ? againstLink(match, identities.data) : null
  const identity = link ? identities.data?.find((i) => i.key === link.deckKey) : undefined
  const matches = useDeckMatches(identity?.deck_ids ?? [])
  const coverage = useGuideCoverage(link?.deckKey)
  if (!link) return null

  const against = matches.data ? pairingMatches(link.opponentKey, matches.data, link.format) : []
  const row = matchupRowOver(against)
  const coverageRow = coverage.data ? coverageRowOf(link.opponentKey, coverage.data) : null
  const label = coverageRow && coverage.data ? coverageName(coverageRow, coverage.data.rows) : null
  // The hero's own name for the opponent, so the title does not change as
  // the matches load; the heading's only for a match with no label.
  const name = match.opponent_label
    ? opponentLabelText(match.opponent_label, match.opponent_colors)
    : pairingHeading(link.opponentKey, against, label, t).name
  const written = ai && coverageRow ? briefWritten(coverageRow) : null

  return (
    <Card title={t('matches.report.against.title', { archetype: name })}>
      <div className="space-y-3">
        <div className="space-y-1 text-body text-ink2">
          {row && <p>{t('matches.report.against.record', { record: formatRecord(row.won, row.lost) })}</p>}
          {written != null && (
            <p>{written ? t('matches.report.against.briefWritten') : t('matches.report.against.briefMissing')}</p>
          )}
        </div>
        <Button href={pairingAddress(link.deckKey, link.opponentKey, link.format)}>{t('matches.report.against.open')}</Button>
      </div>
    </Card>
  )
}

/** `/matches/:id`: the match's report, top to bottom: the hero, an MTGO
 *  match's deck pick, `AgainstCard` for a loss, then the report itself; the
 *  games turn by turn are on the replay's own page. The hero's title is the
 *  report's headline once the report has one and anything to say, and the
 *  result and the games' count from the match until then. */
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

  return (
    <div className="arrive space-y-6">
      <BackToMatches />
      <MatchHero
        match={match}
        headline={headline}
        subhead={subhead}
        replayHref={`/matches/${encodeURIComponent(match.match_id)}/replay`}
      />
      {match.source === 'mtgo' && <MtgoDeckPick matchId={match.match_id} />}
      <AgainstCard match={match} />
      <MatchReportPanel matchId={match.match_id} />
    </div>
  )
}
