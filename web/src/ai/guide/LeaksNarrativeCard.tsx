import { useTranslation } from 'react-i18next'
import { useLLMStatus } from '../../api'
import { writerFrom } from '../../lib/writer'
import { GenerateCard } from '../GenerateCard'
import { useGenerateLeaksNarrative, useLeaksNarrative, usePasteLeaksNarrative } from '../hooks'

/** The leak finder's own training plan: over every deck, unscoped
 *  (`ai/routes/leaks.py::_leaks_narrative_spec` calls `find_leaks` with
 *  no `deck_ids`), so it reads the same under whichever deck's guide is
 *  open. It sits here rather than in a view of its own because it is the
 *  same thing the deck's own fix sentence is, prose over the leak finder's
 *  ranked output (`docs/llm.md`). */
export function LeaksNarrativeCard() {
  const { t } = useTranslation()
  const response = useLeaksNarrative()
  const llmStatus = useLLMStatus()
  const generate = useGenerateLeaksNarrative()
  const paste = usePasteLeaksNarrative()

  const body = response.data
  if (response.isSuccess && body?.status === 'no_report') return null

  return (
    <GenerateCard
      title={t('decks.guide.leak.trainingPlan.title')}
      subtitle={t('decks.guide.leak.trainingPlan.subtitle')}
      accent
      writer={writerFrom(llmStatus.data)}
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
      save={(answer) => paste.mutateAsync({ answer })}
    />
  )
}
