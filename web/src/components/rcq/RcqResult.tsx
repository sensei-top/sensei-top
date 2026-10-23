import { useTranslation } from 'react-i18next'
import type { TFunction } from '../../i18n'
import { useRcqMarkdown, type RcqGuideOut, type RcqNarrativeOut } from '../../api'
import { useCopied } from '../../lib/clipboard'
import { saveMarkdown } from '../../lib/download'
import { archetypeName } from '../../lib/decks'
import { orphanProblems, ownedProblems, problemSentence } from '../../lib/guide'
import { markdownFileName } from '../../lib/rcq'
import { useNow } from '../../lib/time'
import { writtenLine } from '../../lib/written'
import { Button, Callout, Card, Chip, Prose, type ChipVariant } from '../ui'
import { PlanBody } from '../guide/WrittenCards'

/** A flex note's role, in a word and its chip's tint; a role not listed
 *  is shown as sent. */
const ROLE: Record<string, { word: (t: TFunction) => string; variant: ChipVariant } | undefined> = {
  core: { word: (t) => t('rcq.result.role.core'), variant: 'neutral' },
  flex: { word: (t) => t('rcq.result.role.flex'), variant: 'neutral' },
  risk: { word: (t) => t('rcq.result.role.risk'), variant: 'warn' },
}

/** One plan per matchup, in the guide's own order: the name, which side
 *  to choose, then the guide's plan body (`PlanBody`), its problems
 *  beside it. A problem no plan owns is said once, at the top, as the
 *  deck guide's plans say it. */
function MatchupsCard({ guide }: { guide: RcqNarrativeOut }) {
  const { t } = useTranslation()
  const orphans = orphanProblems(guide.problems, guide.matchups)
  return (
    <Card title={t('rcq.result.matchupsTitle')} subtitle={t('rcq.result.matchupsSubtitle')}>
      <div className="space-y-3">
        {orphans.length > 0 && (
          <Callout tone="warn" title={t('rcq.result.foundTitle')}>
            <div className="space-y-2">
              {orphans.map((problem, i) => (
                <p key={i}>{problemSentence(problem, true, t)}</p>
              ))}
            </div>
          </Callout>
        )}
        {guide.matchups.map((plan, i) => (
          <Card key={`${i}-${plan.archetype}`} elevation={2}>
            <h3 className="break-words font-display text-title text-ink">{archetypeName(plan.archetype)}</h3>
            {plan.play_draw && <p className="mt-1 text-body text-ink2">{plan.play_draw}</p>}
            <PlanBody
              boardIn={plan.board_in}
              boardOut={plan.board_out}
              prose={plan.prose}
              problems={ownedProblems(guide.problems, plan.archetype).map((problem) => problemSentence(problem, false, t))}
            />
          </Card>
        ))}
      </div>
    </Card>
  )
}

/** The guide's notes on the slots that could change, each card's role in
 *  a word. */
function FlexCard({ guide }: { guide: RcqNarrativeOut }) {
  const { t } = useTranslation()
  return (
    <Card title={t('rcq.result.flexTitle')}>
      <ul className="space-y-3">
        {guide.flex_notes.map((note, i) => (
          <li key={`${i}-${note.card}`}>
            <p className="flex flex-wrap items-center gap-2">
              <span className="break-words text-body font-medium text-ink">{note.card}</span>
              <Chip size="sm" variant={ROLE[note.role]?.variant ?? 'neutral'}>
                {ROLE[note.role]?.word(t) ?? note.role}
              </Chip>
            </p>
            <p className="mt-0.5 text-body text-ink2">{note.why}</p>
          </li>
        ))}
      </ul>
    </Card>
  )
}

/** The checklist between rounds, numbered as written (the deck guide's
 *  `BetweenRoundsCard`). */
function ChecklistCard({ guide }: { guide: RcqNarrativeOut }) {
  const { t } = useTranslation()
  return (
    <Card title={t('rcq.result.betweenRounds')}>
      <ol className="list-decimal space-y-2 pl-5 text-body text-ink2">
        {guide.checklist.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ol>
    </Card>
  )
}

/** Take the guide to the store: the server's Markdown, copied or saved
 *  as a file. What a press did is said in its own label. */
function CarryCard({ deckKey, response }: { deckKey: string; response: RcqGuideOut }) {
  const { t } = useTranslation()
  const markdown = useRcqMarkdown(deckKey, response.id ?? null)
  const copied = useCopied()
  const text = markdown.data?.markdown

  const download = () => {
    if (text) saveMarkdown(text, markdownFileName(response.generated_at))
  }

  return (
    <Card title={t('rcq.result.carryTitle')} subtitle={t('rcq.result.carrySubtitle')}>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" onClick={() => text && copied.copy(text)} disabled={!text}>
          {copied.copied ? t('rcq.result.copied') : t('rcq.result.copy')}
        </Button>
        <Button variant="secondary" onClick={download} disabled={!text}>
          {t('rcq.result.download')}
        </Button>
      </div>
      {markdown.isPending && <p className="mt-3 text-caption text-muted">{t('rcq.result.building')}</p>}
      {markdown.error && <p className="mt-3 text-body text-loss">{markdown.error.message}</p>}
    </Card>
  )
}

/** The latest RCQ guide this deck has: the game plan and the field as
 *  prose, a plan per matchup, the flex slots, the checklist, and the way
 *  to carry it. Nothing when none is stored. */
export function RcqResult({ deckKey, response }: { deckKey: string; response: RcqGuideOut }) {
  const { t } = useTranslation()
  const now = useNow()
  const guide = response.guide
  if (response.status !== 'ok' || guide == null) return null
  const line = writtenLine(response.model, response.generated_at, now, t)

  return (
    <div className="space-y-6">
      <Card title={t('rcq.result.gamePlan')} subtitle={line ?? undefined}>
        <Prose text={guide.game_plan} />
      </Card>
      <Card title={t('rcq.result.field')}>
        <Prose text={guide.expected_field} />
      </Card>
      {(guide.matchups.length > 0 || guide.problems.length > 0) && <MatchupsCard guide={guide} />}
      {guide.flex_notes.length > 0 && <FlexCard guide={guide} />}
      {guide.checklist.length > 0 && <ChecklistCard guide={guide} />}
      <CarryCard deckKey={deckKey} response={response} />
    </div>
  )
}
