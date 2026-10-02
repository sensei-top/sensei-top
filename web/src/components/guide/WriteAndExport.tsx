import { useState } from 'react'
import { useGenerateGuideNarrative, useGuideMarkdown, useLLMStatus } from '../../api'
import type { GuideNarrativeResponse } from '../../api'
import { useCopied } from '../../lib/clipboard'
import { writerFrom } from '../../lib/writer'
import { Button, Card, Loading, TextBlock } from '../ui'
import { GenerateCard } from '../GenerateCard'

/** Write and export: the card that writes the guide (with Claude when a
 *  credential is configured, `docs/llm.md`, or through the prompt and the
 *  import command otherwise), and the guide's evidence as Markdown. */
export function NarrativeAndExport({
  guideKey,
  response,
}: {
  guideKey: string
  response: GuideNarrativeResponse | undefined
}) {
  const [exportOpen, setExportOpen] = useState(false)
  const markdown = useGuideMarkdown(guideKey, exportOpen)
  const markdownCopy = useCopied()
  const llmStatus = useLLMStatus()
  const generate = useGenerateGuideNarrative()

  const importCommand = `sensei-top guide --deck "${guideKey}" --import guide.json`

  return (
    <div className="space-y-6">
      <GenerateCard
        title={response?.status === 'ok' ? 'Rewrite the guide' : 'Write the guide'}
        subtitle="How the deck works, the fix for your costliest pattern, a note on each card, a sideboard plan against each of the most played archetypes and a checklist between rounds."
        accent
        writer={writerFrom(llmStatus.data, null, 'guide')}
        prompt={response?.prompt}
        narrative={undefined}
        model={response?.author}
        generatedAt={response?.authored_at}
        costUsd={response?.cost_usd}
        stale={response?.stale}
        staleNote="The list has changed since."
        error={
          response?.status === 'no_report'
            ? 'No match with this deck is recorded yet, so there is nothing to write about.'
            : null
        }
        onGenerate={() => generate.mutate(guideKey)}
        generating={generate.isPending}
        generateError={generate.error?.message}
        importCommand={importCommand}
      />

      <Card title="Export the evidence" subtitle="The guide's numbers as Markdown, to keep or to paste elsewhere.">
        <Button variant="secondary" onClick={() => setExportOpen((v) => !v)} aria-expanded={exportOpen}>
          {exportOpen ? 'Hide the Markdown' : 'Show the Markdown'}
        </Button>
        {exportOpen && (
          <div className="mt-3">
            {markdown.isLoading ? (
              <Loading />
            ) : markdown.data ? (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  className="mb-2"
                  onClick={() => markdownCopy.copy(markdown.data.markdown)}
                >
                  {markdownCopy.copied ? 'Copied' : 'Copy the Markdown'}
                </Button>
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
