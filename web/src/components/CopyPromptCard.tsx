import { useState } from 'react'
import { useCopied } from '../lib/clipboard'
import { Button, Card, TextBlock } from './ui'

/** The no-credential path for every narrative surface, and the only path
 *  for the matchup brief (which has no generate button at all,
 *  `docs/brief.md`). It never fetches prose itself and never posts: what
 *  the API hands over is the exact text to write from, framing plus
 *  evidence, and this card's whole job is making that easy to copy into
 *  an assistant the user already pays for, with the command to feed the
 *  answer back shown right beside it.
 *
 *  Deliberately not a textarea to paste the answer *into*: importing is a
 *  CLI job, and a write route here would duplicate the one `POST
 *  .../narrative` already is for the Claude-configured case
 *  (`GenerateCard`, `docs/llm.md`). `GenerateCard` renders this component
 *  whenever nobody writes the report, passing it the same written note
 *  and stored prose it would otherwise show itself, so nothing stored
 *  disappears when the credential does. See that component for
 *  the generate-button half of this story.
 *
 *  Which to use: this card when the prompt is a card of its own;
 *  `CopyPromptBody` when it sits inside a card that already has its title
 *  (a pairing's brief, the Guide's "Matchup coverage"), so that no card
 *  is drawn inside another. */
export function CopyPromptCard({
  title,
  subtitle,
  prompt,
  loading = false,
  error,
  importCommand,
  accent = false,
  children,
}: {
  title: string
  subtitle?: string
  prompt: string | null | undefined
  loading?: boolean
  error?: string | null
  importCommand?: string
  /** A written narrative is an authored/metered artefact even before one
   *  exists here — `GenerateCard` forwards this when nobody writes the
   *  report, so the accent tint marks "this
   *  becomes an authored artifact" consistently whether or not a
   *  credential happens to be configured. */
  accent?: boolean
  children?: React.ReactNode
}) {
  return (
    <Card title={title} subtitle={subtitle} tone={accent ? 'accent' : undefined}>
      <CopyPromptBody
        prompt={prompt}
        loading={loading}
        error={error}
        importCommand={importCommand}
      >
        {children}
      </CopyPromptBody>
    </Card>
  )
}

/** Everything `CopyPromptCard` draws inside its card, with no card of its
 *  own: `children` first, then the buttons to copy and show the prompt,
 *  the error, the command that saves the answer, and the prompt when
 *  shown. Use it inside a card that already has its title; use
 *  `CopyPromptCard` when the prompt is a card of its own. */
export function CopyPromptBody({
  prompt,
  loading = false,
  error,
  importCommand,
  children,
}: {
  prompt: string | null | undefined
  loading?: boolean
  error?: string | null
  importCommand?: string
  children?: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const promptCopy = useCopied()
  const commandCopy = useCopied()

  return (
    <>
      {children}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          onClick={() => prompt && promptCopy.copy(prompt)}
          disabled={!prompt || loading}
        >
          {promptCopy.copied ? 'Copied' : loading ? 'Building the prompt…' : 'Copy the prompt'}
        </Button>
        <Button
          variant="quiet"
          onClick={() => setOpen((v) => !v)}
          disabled={!prompt}
          aria-expanded={open}
        >
          {open ? 'Hide the prompt' : 'Show the prompt'}
        </Button>
      </div>

      {error && <p className="mt-3 text-body text-loss">{error}</p>}

      {importCommand && (
        <div className="mt-3">
          <p className="text-caption text-muted">Then save the answer with this command:</p>
          <div className="mt-1">
            <TextBlock>{importCommand}</TextBlock>
          </div>
          <div className="mt-2">
            <Button variant="secondary" size="sm" onClick={() => commandCopy.copy(importCommand)}>
              {commandCopy.copied ? 'Copied' : 'Copy the command'}
            </Button>
          </div>
        </div>
      )}

      {open && prompt && (
        <div className="mt-3">
          <TextBlock scroll>{prompt}</TextBlock>
        </div>
      )}
    </>
  )
}
