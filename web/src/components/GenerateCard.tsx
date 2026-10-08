import { useEffect, useState } from 'react'
import { useNow } from '../lib/time'
import type { Writer } from '../lib/writer'
import { writtenNote } from '../lib/written'
import { Button, Card, Prose, TextBlock } from './ui'
import { CopyPromptCard } from './CopyPromptCard'

/** A report's card, drawn by who writes the report (`writer`), the
 *  generate-button half of the round trip described in `docs/llm.md`.
 *
 *  When nobody writes it, this renders `CopyPromptCard`, and hands it the
 *  same written note and stored prose the writing branch shows, so a
 *  stored artifact and who wrote it stay visible whoever writes. When a
 *  key of the viewer's writes, it offers a button that calls the matching
 *  `POST .../narrative` route and shows the result, with the same prompt
 *  disclosure `CopyPromptCard` always had, so the user can still see
 *  exactly what got sent. */
export function GenerateCard({
  title,
  subtitle,
  writer,
  prompt,
  narrative,
  model,
  generatedAt,
  costUsd,
  stale = false,
  staleNote,
  loading = false,
  error,
  onGenerate,
  generating = false,
  generateError,
  importCommand,
  accent = false,
  controls,
  emptyNote = 'Nothing written yet.',
  children,
}: {
  title: string
  subtitle?: string
  writer: Writer
  prompt: string | null | undefined
  narrative?: string | null
  model?: string | null
  generatedAt?: string | null
  costUsd?: number | null
  stale?: boolean
  /** The sentence read when `stale` is true, in place of the default
   *  ("The evidence has changed since."). The deck guide passes its own
   *  ("The list has changed since."). */
  staleNote?: string
  loading?: boolean
  error?: string | null
  onGenerate: () => void
  generating?: boolean
  generateError?: string | null
  importCommand?: string
  /** A written narrative is an authored/metered artefact — accent border
   *  tint, with who-wrote-it/when/cost moved into the card's own header
   *  rather than buried in the body. */
  accent?: boolean
  /** A picker the generate button acts on, such as the coach's model
   *  choice, rendered in the writing branch's button row, before the
   *  primary button. The copying branch (`CopyPromptCard`) never
   *  renders it: there's no button for it to act on there. */
  controls?: React.ReactNode
  /** The sentence shown while nothing is written, "Nothing written yet."
   *  by default; `null` shows none. */
  emptyNote?: string | null
  /** Rendered as part of the card's body, in both branches alike: above
   *  the buttons when someone writes, among `CopyPromptCard`'s children
   *  when not. */
  children?: React.ReactNode
}) {
  const [showPrompt, setShowPrompt] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const now = useNow()

  useEffect(() => {
    if (!generating) {
      setElapsed(0)
      return
    }
    const start = Date.now()
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(id)
  }, [generating])

  const note = writtenNote({ author: model, authoredAt: generatedAt, costUsd, stale, staleNote, now })

  // A stored artifact isn't always prose to render inline here — the deck
  // guide's narrative is structured (engine, fix, per-card notes, matchup
  // plans) and already rendered by the tab's other cards, so `narrative`
  // stays undefined for that caller while `generatedAt` still marks that
  // something is stored. Either signal means "written", independently of
  // whether there's a blob of prose to show right here.
  const hasContent = narrative != null || generatedAt != null

  const body = (
    <>
      {note && <p className="text-caption text-muted">{note}</p>}
      {hasContent
        ? narrative && (
            <div className={note ? 'mt-3' : ''}>
              <Prose text={narrative} />
            </div>
          )
        : !generating &&
          emptyNote != null && <p className={`text-body text-muted ${note ? 'mt-3' : ''}`}>{emptyNote}</p>}
      {children}
    </>
  )

  if (writer.by === 'nobody') {
    return (
      <CopyPromptCard
        title={title}
        subtitle={subtitle}
        prompt={prompt}
        loading={loading}
        error={error}
        importCommand={importCommand}
        accent={accent}
      >
        {body}
      </CopyPromptCard>
    )
  }

  return (
    <Card title={title} subtitle={subtitle} tone={accent ? 'accent' : undefined}>
      {body}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        {controls}
        <Button variant="primary" onClick={onGenerate} disabled={generating || !prompt}>
          {generating ? `Writing… ${elapsed} s` : hasContent ? 'Rewrite with Claude' : 'Write it with Claude'}
        </Button>
        <Button
          variant="quiet"
          onClick={() => setShowPrompt((v) => !v)}
          disabled={!prompt}
          aria-expanded={showPrompt}
        >
          {showPrompt ? 'Hide the prompt' : 'Show the prompt'}
        </Button>
      </div>

      {(error || generateError) && (
        <p className="mt-3 text-body text-loss">{generateError ?? error}</p>
      )}

      {showPrompt && prompt && (
        <div className="mt-3">
          <TextBlock scroll>{prompt}</TextBlock>
        </div>
      )}
    </Card>
  )
}
