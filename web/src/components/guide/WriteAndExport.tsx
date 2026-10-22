import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useGenerateGuideNarrative, useGuideMarkdown, useLLMStatus, usePasteGuideNarrative } from '../../api'
import type { GuideNarrativeResponse } from '../../api'
import { useCopied } from '../../lib/clipboard'
import { saveMarkdown } from '../../lib/download'
import { writerFrom } from '../../lib/writer'
import { Button, Card, Loading, TextBlock } from '../ui'
import { GenerateCard } from '../GenerateCard'

/** Write and export: the card that writes the guide (with Claude when a
 *  credential is configured, `docs/llm.md`, or through the prompt and an
 *  answer pasted into the card and saved there otherwise; the import
 *  command shows only in a browser with no desktop shell), and the guide's evidence as Markdown. */
export function NarrativeAndExport({
  guideKey,
  response,
}: {
  guideKey: string
  response: GuideNarrativeResponse | undefined
}) {
  const { t } = useTranslation()
  const [exportOpen, setExportOpen] = useState(false)
  const markdown = useGuideMarkdown(guideKey, exportOpen)
  const markdownCopy = useCopied()
  const llmStatus = useLLMStatus()
  const generate = useGenerateGuideNarrative()
  const paste = usePasteGuideNarrative()

  const importCommand = `sensei-top guide --deck "${guideKey}" --import guide.json`

  return (
    <div className="space-y-6">
      <GenerateCard
        title={response?.status === 'ok' ? t('decks.guide.write.rewrite') : t('decks.guide.write.write')}
        subtitle={t('decks.guide.write.subtitle')}
        accent
        writer={writerFrom(llmStatus.data)}
        prompt={response?.prompt}
        narrative={undefined}
        model={response?.author}
        generatedAt={response?.authored_at}
        costUsd={response?.cost_usd}
        stale={response?.stale}
        staleNote={t('decks.guide.write.staleNote')}
        error={
          response?.status === 'no_report'
            ? t('decks.guide.write.noMatch')
            : null
        }
        onGenerate={() => generate.mutate(guideKey)}
        generating={generate.isPending}
        generateError={generate.error?.message}
        importCommand={importCommand}
        save={(answer) => paste.mutateAsync({ key: guideKey, answer })}
      />

      <Card title={t('decks.guide.export.title')} subtitle={t('decks.guide.export.subtitle')}>
        <Button variant="secondary" onClick={() => setExportOpen((v) => !v)} aria-expanded={exportOpen}>
          {exportOpen ? t('decks.guide.export.hide') : t('decks.guide.export.show')}
        </Button>
        {exportOpen && (
          <div className="mt-3">
            {markdown.isLoading ? (
              <Loading />
            ) : markdown.data ? (
              <>
                <div className="mb-2 flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => markdownCopy.copy(markdown.data.markdown)}
                  >
                    {markdownCopy.copied ? t('decks.guide.export.copied') : t('decks.guide.export.copy')}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => saveMarkdown(markdown.data.markdown, 'deck-guide.md')}
                  >
                    {t('decks.guide.export.download')}
                  </Button>
                </div>
                <TextBlock scroll>{markdown.data.markdown}</TextBlock>
              </>
            ) : (
              <p className="text-body text-loss">{markdown.error?.message}</p>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
