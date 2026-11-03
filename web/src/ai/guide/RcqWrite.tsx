import { useTranslation } from 'react-i18next'
import { useLLMStatus, useRcqGuide, type RcqGenerateIn } from '../../api'
import { writerFrom } from '../../lib/writer'
import { GenerateCard } from '../GenerateCard'
import { useGenerateRcq, usePasteRcq } from '../hooks'

/** The RCQ page's write and paste-an-answer card. `sent` is the list as
 *  typed with the settled preview's keys, what both the write and the
 *  pasted answer send; `prompt` is the preview's, `undefined` while the
 *  preview is not of the current inputs. */
export function RcqWrite({
  deckKey,
  sent,
  prompt,
  loading,
}: {
  deckKey: string
  sent: RcqGenerateIn
  prompt: string | null | undefined
  loading: boolean
}) {
  const { t } = useTranslation()
  const stored = useRcqGuide(deckKey)
  const llmStatus = useLLMStatus()
  const generate = useGenerateRcq()
  const paste = usePasteRcq()
  const response = stored.data?.status === 'ok' ? stored.data : undefined
  const changed = response?.decklist_text != null && response.decklist_text.trim() !== sent.decklist.trim()
  // The stored answer's own prompt was for another list than the one saved
  // beside it: said even when the box still holds the saved list.
  const answeredElsewhere = response?.answered_for_another_list === true

  return (
    <GenerateCard
      title={response ? t('rcq.view.writeAgain') : t('rcq.view.write')}
      subtitle={t('rcq.view.subtitle')}
      accent
      writer={writerFrom(llmStatus.data)}
      prompt={prompt}
      narrative={undefined}
      model={response?.model}
      generatedAt={response?.generated_at}
      costUsd={response?.cost_usd}
      stale={changed || answeredElsewhere}
      staleNote={answeredElsewhere ? t('rcq.view.answeredForAnotherList') : t('rcq.view.staleNote')}
      loading={loading}
      onGenerate={() => generate.mutate({ key: deckKey, body: sent })}
      generating={generate.isPending}
      generateError={generate.error?.message}
      save={(answer) => paste.mutateAsync({ key: deckKey, inputs: sent, answer })}
    />
  )
}
