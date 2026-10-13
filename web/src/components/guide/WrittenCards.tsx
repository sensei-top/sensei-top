import { useTranslation } from 'react-i18next'
import type { BoardCardOut, GuideNarrativeOut, GuideNarrativeResponse, MatchupPlanOut } from '../../api'
import { archetypeName } from '../../lib/decks'
import { orphanProblems, ownedProblems, problemSentence } from '../../lib/guide'
import { useNow } from '../../lib/time'
import { writtenLine } from '../../lib/written'
import { Callout, Card, Prose, SectionLabel } from '../ui'
import { SectionLink } from './SectionNav'

/** The id of the section that writes the guide, which every link to it
 *  goes to. */
const WRITE_ID = 'guide-write'

/** Drawn after Scope when no guide is written: what the written sections
 *  would hold, and the way to Write and export. */
export function NoWrittenGuide() {
  const { t } = useTranslation()
  return (
    <Callout title={t('decks.guide.written.none.title')}>
      <p>{t('decks.guide.written.none.message')}</p>
      <p className="mt-2">
        <SectionLink id={WRITE_ID}>{t('decks.guide.write.write')}</SectionLink>
      </p>
    </Callout>
  )
}

/** The written guide's account of the deck, under who wrote it and when;
 *  when the list has changed since, a warning first. */
export function HowItWorksCard({
  guide,
  response,
}: {
  guide: GuideNarrativeOut
  response: GuideNarrativeResponse
}) {
  const { t } = useTranslation()
  const now = useNow()
  const line = writtenLine(response.author, response.authored_at, now, t)
  return (
    <Card title={t('decks.guide.sections.howItWorks')} subtitle={line ?? undefined}>
      {response.stale && (
        <div className="mb-4">
          <Callout tone="warn" title={t('decks.guide.written.stale.title')}>
            <p>{t('decks.guide.written.stale.message')}</p>
            <p className="mt-2">
              <SectionLink id={WRITE_ID}>{t('decks.guide.written.stale.again')}</SectionLink>
            </p>
          </Callout>
        </div>
      )}
      <div className="max-w-prose">
        <Prose text={guide.engine} />
      </div>
    </Card>
  )
}

/** One side of a swap: its label, then each card, the count first. */
function SwapSide({ label, cards }: { label: string; cards: BoardCardOut[] }) {
  return (
    <div className="min-w-0">
      <SectionLabel as="h4">{label}</SectionLabel>
      <ul className="mt-1 space-y-0.5">
        {cards.map((card) => (
          <li key={card.card} className="break-words text-body text-ink2">
            <span className="font-medium text-ink tabular-nums">{card.n}</span> {card.card}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** A plan's body: the swap and its problems (`problems`, each already a
 *  sentence), then the prose. From 64rem the prose is the left column and
 *  the swap the right one; under it the swap comes first, as it does in
 *  the document at every width. Drawn under a guide's plan's name and in a
 *  pairing's stored brief alike; it opens with the `mt-3` that parts it
 *  from what is above it. */
export function PlanBody({
  boardIn,
  boardOut,
  prose,
  problems,
}: {
  boardIn: BoardCardOut[]
  boardOut: BoardCardOut[]
  prose: string
  problems: string[]
}) {
  const { t } = useTranslation()
  const swap = boardIn.length > 0 || boardOut.length > 0
  return (
    <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_14rem] lg:gap-6">
      <div className="min-w-0 space-y-3 lg:col-start-2 lg:row-start-1">
        {swap ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            {boardIn.length > 0 && <SwapSide label={t('decks.guide.written.bringIn')} cards={boardIn} />}
            {boardOut.length > 0 && <SwapSide label={t('decks.guide.written.takeOut')} cards={boardOut} />}
          </div>
        ) : (
          <p className="text-caption text-muted">{t('decks.guide.written.noChanges')}</p>
        )}
        {problems.length > 0 && (
          <Callout tone="warn">
            <div className="space-y-2">
              {problems.map((sentence, i) => (
                <p key={i}>{sentence}</p>
              ))}
            </div>
          </Callout>
        )}
      </div>
      <div className="min-w-0 max-w-prose lg:col-start-1 lg:row-start-1">
        <Prose text={prose} />
      </div>
    </div>
  )
}

/** One archetype's plan: its name, then its body (`PlanBody`). */
function PlanCard({ plan, problems }: { plan: MatchupPlanOut; problems: string[] }) {
  return (
    <Card elevation={2}>
      <h3 className="break-words font-display text-title text-ink">{archetypeName(plan.archetype)}</h3>
      <PlanBody boardIn={plan.board_in} boardOut={plan.board_out} prose={plan.prose} problems={problems} />
    </Card>
  )
}

/** The written guide's plan against each archetype, in its own order. A
 *  problem whose archetype has no plan (`guide/plans.py`'s `(sideboard)`
 *  check, or a plan the guide does not hold) is said once, at the top. */
export function SideboardPlansCard({ guide }: { guide: GuideNarrativeOut }) {
  const { t } = useTranslation()
  const orphans = orphanProblems(guide.problems, guide.matchups)
  return (
    <Card
      title={t('decks.guide.sections.sideboardPlans')}
      subtitle={t('decks.guide.written.plansSubtitle')}
    >
      <div className="space-y-3">
        {orphans.length > 0 && (
          <Callout tone="warn" title={t('decks.guide.written.checked')}>
            <div className="space-y-2">
              {orphans.map((problem, i) => (
                <p key={i}>{problemSentence(problem, true, t)}</p>
              ))}
            </div>
          </Callout>
        )}
        {guide.matchups.map((plan, i) => (
          <PlanCard
            key={`${i}-${plan.archetype}`}
            plan={plan}
            problems={ownedProblems(guide.problems, plan.archetype).map((problem) => problemSentence(problem, false, t))}
          />
        ))}
      </div>
    </Card>
  )
}

/** The written guide's checklist between rounds, numbered as written. */
export function BetweenRoundsCard({ guide }: { guide: GuideNarrativeOut }) {
  const { t } = useTranslation()
  return (
    <Card title={t('decks.guide.sections.betweenRounds')}>
      <ol className="max-w-prose list-decimal space-y-2 pl-5 text-body text-ink2">
        {guide.checklist.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ol>
    </Card>
  )
}
