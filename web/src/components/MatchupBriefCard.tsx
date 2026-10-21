import { useTranslation } from 'react-i18next'
import { useCurrentMatchBrief, usePasteBrief } from '../api'
import type { BoardCardOut, CurrentMatch, MatchupBriefOut, PlanProblemOut, PlayAroundOut } from '../api'
import type { TFunction } from '../i18n'
import { ageText, seenOpponentCards } from '../lib/brief'
import { isPasted } from '../lib/written'
import { CopyPromptCard } from './CopyPromptCard'
import { Card, Chip, EmptyState, Loading, Prose, SectionLabel } from './ui'
import { formatList, formatPercent, formatRecord } from '../lib/format'

function recordText(brief: MatchupBriefOut, t: TFunction): string | null {
  if (brief.personal_matches == null || brief.personal_matches === 0) return null
  const record = formatRecord(brief.personal_wins ?? 0, brief.personal_losses ?? 0)
  return t('matchups.briefCard.record', { record, count: brief.personal_matches })
}

/** The play-around list, each card a `Chip` that turns `seen` (struck
 *  through) once the card has actually shown up this match. Shared
 *  between MatchupBriefCard's own disclosure card and SideboardPlanCard's
 *  break-phase plan. */
export function PlayAroundList({
  playAround,
  seen,
}: {
  playAround: PlayAroundOut[]
  seen: Set<string>
}) {
  const { t } = useTranslation()
  if (playAround.length === 0) return null
  return (
    <div>
      <SectionLabel as="h4">{t('matchups.brief.playAround')}</SectionLabel>
      <ul className="mt-1 space-y-1">
        {playAround.map((p) => (
          <li key={p.card} className="text-body">
            <Chip variant={seen.has(p.card) ? 'seen' : 'neutral'} emphasis={!seen.has(p.card)}>
              {p.card}
            </Chip>
            <span className="ml-2 text-ink2">{p.why}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** The IN/OUT sideboard plan plus any `PlanProblemOut` caught by
 *  `guide.plans.validate_plans`, shown inline rather than hidden. Shared
 *  between MatchupBriefCard's own disclosure card (`size="compact"`, the
 *  default — this component's rendering there is unchanged) and
 *  SideboardPlanCard's break-phase plan (`size="large"`), which needs the
 *  swap readable at a glance beside Arena's own sideboard screen. */
export function BoardPlan({
  boardIn,
  boardOut,
  problems,
  size = 'compact',
  heading,
}: {
  boardIn: BoardCardOut[]
  boardOut: BoardCardOut[]
  problems: PlanProblemOut[]
  size?: 'compact' | 'large'
  heading?: string
}) {
  const { t } = useTranslation()
  if (boardIn.length === 0 && boardOut.length === 0) return null
  const title = heading ?? t('matchups.plan.game2')

  if (size === 'large') {
    return (
      <div>
        <SectionLabel as="h4">{title}</SectionLabel>
        <div className="mt-2 grid grid-cols-2 gap-4">
          <div>
            <div className="text-chip font-semibold tracking-label text-s2">{t('matchups.plan.out')}</div>
            <ul className="mt-1 space-y-1">
              {boardOut.length > 0 ? (
                boardOut.map((c) => (
                  <li key={c.card} className="font-display text-title text-ink">
                    <span className="text-s2">−{c.n}</span> {c.card}
                  </li>
                ))
              ) : (
                <li className="text-body text-muted">—</li>
              )}
            </ul>
          </div>
          <div>
            <div className="text-chip font-semibold tracking-label text-s1">{t('matchups.plan.in')}</div>
            <ul className="mt-1 space-y-1">
              {boardIn.length > 0 ? (
                boardIn.map((c) => (
                  <li key={c.card} className="font-display text-title text-ink">
                    <span className="text-s1">+{c.n}</span> {c.card}
                  </li>
                ))
              ) : (
                <li className="text-body text-muted">—</li>
              )}
            </ul>
          </div>
        </div>
        {problems.map((p) => (
          <p key={p.message} className="mt-2 text-caption text-s2">
            ⚠ {p.message}
          </p>
        ))}
      </div>
    )
  }

  return (
    <div>
      <SectionLabel as="h4">{title}</SectionLabel>
      <p className="mt-1 text-body">
        <span className="font-medium text-s1">{t('matchups.plan.inLabel')}</span>{' '}
        {boardIn.length > 0 ? formatList(boardIn.map((c) => `+${c.n} ${c.card}`), { type: 'unit' }) : '—'}
        <br />
        <span className="font-medium text-s2">{t('matchups.plan.outLabel')}</span>{' '}
        {boardOut.length > 0 ? formatList(boardOut.map((c) => `−${c.n} ${c.card}`), { type: 'unit' }) : '—'}
      </p>
      {problems.map((p) => (
        <p key={p.message} className="mt-1 text-caption text-s2">
          ⚠ {p.message}
        </p>
      ))}
    </div>
  )
}

/** "written by X · age · from a full guide run" — the provenance footer
 *  shared between MatchupBriefCard's own disclosure card and
 *  SideboardPlanCard's break-phase plan. */
export function BriefProvenance({ brief }: { brief: MatchupBriefOut }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-edge pt-2 text-caption text-muted">
      <span>
        {isPasted(brief.model)
          ? t('matchups.briefCard.pasted')
          : t('matchups.briefCard.writtenBy', { model: brief.model })}
      </span>
      <span>{ageText(brief.generated_at, t)}</span>
      {brief.source === 'guide' && <span>{t('matchups.briefCard.fromGuideRun')}</span>}
    </div>
  )
}

function BriefBody({ brief, match }: { brief: MatchupBriefOut; match: CurrentMatch }) {
  const { t } = useTranslation()
  const seen = seenOpponentCards(match)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-body font-semibold text-ink">
          {brief.archetype_label ?? brief.archetype_key}
          {brief.archetype_share != null && (
            <span className="ml-2 font-normal text-muted">
              {t('matchups.briefCard.ofTheField', { share: formatPercent(brief.archetype_share) })}
            </span>
          )}
        </h3>
        <Chip size="sm" muted>
          {t('matchups.briefCard.reasoned')}
        </Chip>
      </div>
      {recordText(brief, t) && <p className="text-caption text-muted">{recordText(brief, t)}</p>}

      <PlayAroundList playAround={brief.play_around} seen={seen} />

      <BoardPlan boardIn={brief.board_in} boardOut={brief.board_out} problems={brief.problems} />

      <Prose text={brief.prose} />

      <BriefProvenance brief={brief} />
    </div>
  )
}

/** What to play around against this match's opponent, and a game-2 plan —
 *  the useful half of the deck guide's §6, reachable while a game is
 *  actually on the clock.
 *
 *  A brief is written once per (deck, archetype) and reused in every future
 *  match against that archetype, so the common case is that one is already
 *  stored — often as a side effect of generating a deck guide — and this
 *  renders instantly. When none is, the card offers the text to write one
 *  from rather than a generate button: unlike the match report and the deck
 *  guide (`docs/llm.md`), this feature deliberately has no button of its
 *  own, since generating a guide already fills the cache for free
 *  (`docs/brief.md`). */
export function MatchupBriefCard({ match }: { match: CurrentMatch }) {
  const { t } = useTranslation()
  const title = t('matchups.brief.title')
  const brief = useCurrentMatchBrief()
  const paste = usePasteBrief()

  if (brief.isPending) return <Loading />
  if (brief.error) return null // fail-soft: OpponentRead and the keep guide still stand below
  const data = brief.data
  if (!data) return null
  // CurrentMatchView's own empty state already covers "no game in progress".
  if (data.status === 'no_match') return null

  if (data.status === 'unclassified') {
    return (
      <Card title={title}>
        <EmptyState message={t('matchups.briefCard.unclassified')} />
      </Card>
    )
  }

  if (data.status === 'format_unknown') {
    return (
      <Card title={title}>
        <EmptyState message={t('matchups.briefCard.formatUnknown')} />
      </Card>
    )
  }

  if (data.status === 'no_consensus') {
    return (
      <Card title={title}>
        <EmptyState message={t('matchups.briefCard.noConsensus')} />
      </Card>
    )
  }

  if (data.status === 'ok' && data.brief) {
    return (
      <Card
        title={title}
        subtitle={data.stale ? t('matchups.briefCard.stale') : undefined}
      >
        <BriefBody brief={data.brief} match={match} />
      </Card>
    )
  }

  // status === 'prompt': nothing imported for this matchup yet. Offer the
  // text to write one from rather than a generate button — this card
  // deliberately has none, unlike the match report and deck guide.
  return (
    <CopyPromptCard
      title={title}
      subtitle={t('matchups.briefCard.noBrief')}
      prompt={data.prompt}
      importCommand={
        data.deck_key && data.archetype_key
          ? `sensei-top brief --deck "${data.deck_key}" ` +
            `--archetype "${data.archetype_key}" --import brief.json`
          : undefined
      }
      save={
        data.deck_key && data.archetype_key
          ? (answer) =>
              paste.mutateAsync({ key: data.deck_key!, archetypeKey: data.archetype_key!, answer })
          : undefined
      }
    />
  )
}
