import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useLLMStatus, type NarrativeResponse } from '../../api'
import { Button, Card } from '../../components/ui'
import { writerFrom } from '../../lib/writer'
import type { CopyPressed } from '../CopyPromptCard'
import { GenerateCard } from '../GenerateCard'
import { notesMissing, useRulesNotesPress } from '../rulesNotes'
import {
  useGenerateMatchReportNarrative,
  usePasteMatchReportNarrative,
  useReportNarrativePrompt,
} from '../hooks'

/** The match report's "Coach's summary": closed until opened, because the
 *  route behind it recomputes the report's context on every call. */
export function ReportNarrativeCard({ matchId }: { matchId: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const prompt = useReportNarrativePrompt(matchId, open)
  const llmStatus = useLLMStatus()
  const generate = useGenerateMatchReportNarrative()
  const paste = usePasteMatchReportNarrative()
  const queryClient = useQueryClient()
  const press = useRulesNotesPress({ feature: 'match', match_id: matchId, expected: [] })
  const beforeCopy = async (): Promise<CopyPressed> => {
    const outcome = await press()
    const key = ['match-report-narrative-prompt', matchId]
    if (outcome.stored > 0) await queryClient.refetchQueries({ queryKey: key })
    return { prompt: queryClient.getQueryData<NarrativeResponse>(key)?.prompt ?? null, missing: notesMissing(outcome) }
  }

  if (!open) {
    return (
      <Card
        title={t('matches.report.coachTitle')}
        subtitle={t('matches.report.coachSubtitle')}
      >
        <Button variant="primary" onClick={() => setOpen(true)}>
          {t('matches.report.coachShow')}
        </Button>
      </Card>
    )
  }

  const body = prompt.data
  return (
    <GenerateCard
      title={t('matches.report.coachTitle')}
      subtitle={t('matches.report.coachSubtitle')}
      writer={writerFrom(llmStatus.data)}
      prompt={body?.prompt}
      narrative={body?.status === 'ok' ? body.narrative : null}
      model={body?.model}
      generatedAt={body?.generated_at}
      costUsd={body?.cost_usd}
      stale={body?.stale}
      loading={prompt.isLoading}
      error={
        body?.status === 'no_report'
          ? t('matches.report.nothingToReview')
          : (prompt.error?.message ?? null)
      }
      onGenerate={() => generate.mutate(matchId)}
      generating={generate.isPending}
      generateError={generate.error?.message}
      save={(answer) => paste.mutateAsync({ matchId, answer })}
      beforeRun={press}
      beforeCopy={beforeCopy}
    />
  )
}
