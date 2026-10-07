import { useGenerateLeaksNarrative, useLeaksNarrative, useLLMStatus } from '../../api'
import type { LeakOut } from '../../api'
import { categoryLabel, gapPoints, winsOf } from '../../lib/guide'
import { patternSentence, patternWords } from '../../lib/patterns'
import { formatCount } from '../../lib/time'
import { writerFrom } from '../../lib/writer'
import { percent } from '../../theme'
import { Card, Chip, Disclosure, IntervalBar } from '../ui'
import { GenerateCard } from '../GenerateCard'
import { PatternMatches } from './PatternMatches'

/** A no-break space: a count and the word after it never part. */
const NBSP = '\u00a0'

/** One recurring pattern (`review/leaks.py`'s `Leak`): the same title and
 *  sentence Home's pattern card draws (`lib/patterns.ts`'s `patternWords`),
 *  its win rate with and without it as two bars, and its own matches one
 *  click away. `withDeck` is false under a deck's own patterns, whose page
 *  already names the deck; true under "Across all of your decks". */
export function LeakCard({ leak, withDeck }: { leak: LeakOut; withDeck: boolean }) {
  const words = patternWords(leak)
  const winsWith = winsOf(leak.win_rate_with, leak.n_with)
  const winsWithout = winsOf(leak.win_rate_without, leak.n_without)
  const points = gapPoints(leak.gap)
  const matchesSummary =
    leak.n_with === 1
      ? 'The one match with this pattern'
      : `The ${formatCount(leak.n_with)}${NBSP}matches with this pattern`
  return (
    <Card elevation={2}>
      <div className="flex flex-wrap items-center gap-2">
        <Chip>{categoryLabel(leak.category)}</Chip>
        <span className="text-caption text-muted">
          {points === 1 ? `1${NBSP}point apart` : `${points}${NBSP}points apart`}
        </span>
      </div>
      <p className="mt-2 text-body font-medium text-ink">{words.title}</p>
      <p className="mt-1 text-body text-ink2">
        {patternSentence(words.clause, { wins: winsWith, n: leak.n_with }, { wins: winsWithout, n: leak.n_without })}
      </p>
      <div className="mt-3 space-y-2">
        <div>
          <div className="mb-1 flex items-center justify-between text-caption text-muted">
            <span>With it</span>
            <span className="tabular-nums">
              {percent(leak.win_rate_with)} ({percent(leak.ci_with[0])}–{percent(leak.ci_with[1])})
            </span>
          </div>
          <IntervalBar rate={leak.win_rate_with} ci={leak.ci_with} colorClass="s1" />
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between text-caption text-muted">
            <span>Without it</span>
            <span className="tabular-nums">
              {percent(leak.win_rate_without)} ({percent(leak.ci_without[0])}–
              {percent(leak.ci_without[1])})
            </span>
          </div>
          <IntervalBar rate={leak.win_rate_without} ci={leak.ci_without} colorClass="s2" />
        </div>
      </div>
      <div className="mt-3">
        <Disclosure summary={matchesSummary}>
          <PatternMatches ids={[...leak.match_ids_with]} withDeck={withDeck} />
        </Disclosure>
      </div>
    </Card>
  )
}

/** The leak finder's own training plan: over every deck, unscoped
 *  (`api/routes/review.py::_leaks_narrative_spec` calls `find_leaks` with
 *  no `deck_ids`), so it reads the same under whichever deck's guide is
 *  open. It sits here rather than in a view of its own because it is the
 *  same thing the deck's own fix sentence is, prose over the leak finder's
 *  ranked output (`docs/llm.md`). */
export function LeaksNarrativeCard() {
  const response = useLeaksNarrative()
  const llmStatus = useLLMStatus()
  const generate = useGenerateLeaksNarrative()

  const body = response.data
  if (response.isSuccess && body?.status === 'no_report') return null

  return (
    <GenerateCard
      title="Training plan"
      subtitle="Over the leak finder's recurring patterns across every one of your decks, not just this one."
      accent
      writer={writerFrom(llmStatus.data, null, 'leaks')}
      prompt={body?.prompt}
      narrative={body?.status === 'ok' ? body.narrative : null}
      model={body?.model}
      generatedAt={body?.generated_at}
      costUsd={body?.cost_usd}
      stale={body?.stale}
      loading={response.isLoading}
      error={response.error?.message}
      onGenerate={() => generate.mutate()}
      generating={generate.isPending}
      generateError={generate.error?.message}
    />
  )
}
