import { useRcqMarkdown, type RcqGuideOut, type RcqNarrativeOut } from '../../api'
import { useCopied } from '../../lib/clipboard'
import { archetypeName } from '../../lib/decks'
import { orphanProblems, ownedProblems, problemSentence } from '../../lib/guide'
import { markdownFileName } from '../../lib/rcq'
import { useNow } from '../../lib/time'
import { writtenLine } from '../../lib/written'
import { Button, Callout, Card, Chip, Prose, type ChipVariant } from '../ui'
import { PlanBody } from '../guide/WrittenCards'

/** A flex note's role, in a word and its chip's tint; a role not listed
 *  is shown as sent. */
const ROLE: Record<string, { word: string; variant: ChipVariant } | undefined> = {
  core: { word: 'Core', variant: 'neutral' },
  flex: { word: 'Flex', variant: 'neutral' },
  risk: { word: 'Risk', variant: 'warn' },
}

/** One plan per matchup, in the guide's own order: the name, which side
 *  to choose, then the guide's plan body (`PlanBody`), its problems
 *  beside it. A problem no plan owns is said once, at the top, as the
 *  deck guide's plans say it. */
function MatchupsCard({ guide }: { guide: RcqNarrativeOut }) {
  const orphans = orphanProblems(guide.problems, guide.matchups)
  return (
    <Card
      title="Matchups"
      subtitle="Play or draw, and what to bring in and take out from the second game on, for your 75."
    >
      <div className="space-y-3">
        {orphans.length > 0 && (
          <Callout tone="warn" title="Found when the plans were checked">
            <div className="space-y-2">
              {orphans.map((problem, i) => (
                <p key={i}>{problemSentence(problem, true)}</p>
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
              problems={ownedProblems(guide.problems, plan.archetype).map((problem) => problemSentence(problem, false))}
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
  return (
    <Card title="Flex slots">
      <ul className="max-w-prose space-y-3">
        {guide.flex_notes.map((note, i) => (
          <li key={`${i}-${note.card}`}>
            <p className="flex flex-wrap items-center gap-2">
              <span className="break-words text-body font-medium text-ink">{note.card}</span>
              <Chip size="sm" variant={ROLE[note.role]?.variant ?? 'neutral'}>
                {ROLE[note.role]?.word ?? note.role}
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
  return (
    <Card title="Between rounds">
      <ol className="max-w-prose list-decimal space-y-2 pl-5 text-body text-ink2">
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
  const markdown = useRcqMarkdown(deckKey, response.id ?? null)
  const copied = useCopied()
  const text = markdown.data?.markdown

  const download = () => {
    if (!text) return
    const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = markdownFileName(response.generated_at)
    anchor.click()
    // Let go of the file once the browser has started saving it.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <Card title="Take it to the store" subtitle="The guide as Markdown, to read on your phone.">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" onClick={() => text && copied.copy(text)} disabled={!text}>
          {copied.copied ? 'Copied' : 'Copy as Markdown'}
        </Button>
        <Button variant="secondary" onClick={download} disabled={!text}>
          Download .md
        </Button>
      </div>
      {markdown.isPending && <p className="mt-3 text-caption text-muted">Building the Markdown…</p>}
      {markdown.error && <p className="mt-3 text-body text-loss">{markdown.error.message}</p>}
    </Card>
  )
}

/** The latest RCQ guide this deck has: the game plan and the field as
 *  prose, a plan per matchup, the flex slots, the checklist, and the way
 *  to carry it. Nothing when none is stored. */
export function RcqResult({ deckKey, response }: { deckKey: string; response: RcqGuideOut }) {
  const now = useNow()
  const guide = response.guide
  if (response.status !== 'ok' || guide == null) return null
  const line = writtenLine(response.model, response.generated_at, now)

  return (
    <div className="space-y-6">
      <Card title="Game plan" subtitle={line ?? undefined}>
        <div className="max-w-prose">
          <Prose text={guide.game_plan} />
        </div>
      </Card>
      <Card title="The field you will meet">
        <div className="max-w-prose">
          <Prose text={guide.expected_field} />
        </div>
      </Card>
      {(guide.matchups.length > 0 || guide.problems.length > 0) && <MatchupsCard guide={guide} />}
      {guide.flex_notes.length > 0 && <FlexCard guide={guide} />}
      {guide.checklist.length > 0 && <ChecklistCard guide={guide} />}
      <CarryCard deckKey={deckKey} response={response} />
    </div>
  )
}
