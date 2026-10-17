import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../api'
import { useShell } from '../bridge'
import { useCopied } from '../lib/clipboard'
import { Button, Card, TextBlock } from './ui'

/** Stores an answer pasted into the card: the card's `PUT`, one of the
 *  `usePaste…` mutations in `api.ts`, closed over everything but the
 *  answer. It resolves once the answer is stored and the card's queries
 *  have refetched; a refusal rejects with `ApiError`, whose message is
 *  the server's sentence, and any other rejection reads as no answer. */
export type SaveAnswer = (answer: string) => Promise<unknown>

/** The no-credential path for every narrative surface, and the only path
 *  for the matchup brief (which has no generate button at all,
 *  `docs/brief.md`). It never fetches prose itself: what the API hands
 *  over is the exact text to write from, framing plus evidence, and the
 *  answer contract the assistant answers in. This card's job is making
 *  that easy to copy into an assistant the user already pays for, and,
 *  given `save`, taking the answer back: a box to paste it into and a
 *  button that stores it through the card's `PUT`, which never calls a
 *  model (`docs/llm.md`). In a browser with no desktop shell, where a
 *  terminal is at hand, the import command is shown too.
 *
 *  `GenerateCard` renders this component whenever nobody writes the
 *  report, passing it the same written note and stored prose it would
 *  otherwise show itself, so nothing stored disappears when the
 *  credential does. See that component for the generate-button half of
 *  this story.
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
  save,
  accent = false,
  children,
}: {
  title: string
  subtitle?: string
  prompt: string | null | undefined
  loading?: boolean
  error?: string | null
  importCommand?: string
  /** The card's `PUT`; without it the card draws no box to paste into. */
  save?: SaveAnswer
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
        save={save}
      >
        {children}
      </CopyPromptBody>
    </Card>
  )
}

/** Why the last save failed: the server refused it, with its sentence, or
 *  the tracker did not answer at all. */
type SaveFailure = { kind: 'refused'; detail: string } | { kind: 'offline' }

/** Everything `CopyPromptCard` draws inside its card, with no card of its
 *  own: `children` first, then the buttons to copy and show the prompt,
 *  the error, the prompt when shown, the box to paste the answer into
 *  (given `save`), and the command that saves the answer (only with no
 *  desktop shell). Use it inside a card that already has its title; use
 *  `CopyPromptCard` when the prompt is a card of its own. */
export function CopyPromptBody({
  prompt,
  loading = false,
  error,
  importCommand,
  save,
  children,
}: {
  prompt: string | null | undefined
  loading?: boolean
  error?: string | null
  importCommand?: string
  /** The card's `PUT`; without it the card draws no box to paste into. */
  save?: SaveAnswer
  children?: React.ReactNode
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const promptCopy = useCopied()
  const commandCopy = useCopied()
  // The installed app has no terminal to hand: the box alone (plan 24, D7).
  // Read here despite `bridge.ts`'s rule that pages pass the shell down:
  // only whether a shell exists matters, never its shape, and a prop
  // through every page that draws a prompt is a lot of plumbing for one
  // boolean.
  const shell = useShell()
  const showCommand = importCommand != null && importCommand !== '' && shell == null

  return (
    <>
      {children}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          onClick={() => prompt && promptCopy.copy(prompt)}
          disabled={!prompt || loading}
        >
          {promptCopy.copied
            ? t('prompts.copy.copied')
            : loading
              ? t('prompts.copy.building')
              : t('prompts.copy.copyPrompt')}
        </Button>
        <Button
          variant="quiet"
          onClick={() => setOpen((v) => !v)}
          disabled={!prompt}
          aria-expanded={open}
        >
          {open ? t('prompts.copy.hidePrompt') : t('prompts.copy.showPrompt')}
        </Button>
      </div>

      {error && <p className="mt-3 text-body text-loss">{error}</p>}

      {open && prompt && (
        <div className="mt-3">
          <TextBlock scroll>{prompt}</TextBlock>
        </div>
      )}

      {save && <PasteBox save={save} />}

      {showCommand && (
        <div className="mt-3">
          <p className="text-caption text-muted">
            {save ? t('prompts.copy.orCommand') : t('prompts.copy.thenSave')}
          </p>
          <div className="mt-1">
            <TextBlock>{importCommand}</TextBlock>
          </div>
          <div className="mt-2">
            <Button variant="secondary" size="sm" onClick={() => commandCopy.copy(importCommand)}>
              {commandCopy.copied ? t('prompts.copy.copied') : t('prompts.copy.copyCommand')}
            </Button>
          </div>
        </div>
      )}
    </>
  )
}

/** The box the assistant's answer is pasted into, and Save. The text
 *  stays in the box until the answer is stored, so a refusal or a tracker
 *  that did not answer loses nothing; once stored the box empties, and the
 *  card's own reads bring the stored answer. */
function PasteBox({ save }: { save: SaveAnswer }) {
  const { t } = useTranslation()
  const id = useId()
  const leadId = `${id}-lead`
  const failureId = `${id}-failure`
  const [answer, setAnswer] = useState('')
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<SaveFailure | null>(null)
  // Only a refusal is the field's error; a tracker that did not answer is not.
  const refused = failure?.kind === 'refused'

  const onSave = async () => {
    setSaving(true)
    setFailure(null)
    try {
      await save(answer)
      setAnswer('')
    } catch (exc) {
      setFailure(exc instanceof ApiError ? { kind: 'refused', detail: exc.message } : { kind: 'offline' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-4 flex min-w-0 flex-col gap-1.5">
      <p id={leadId} className="text-caption text-muted">
        {t('prompts.copy.thenPaste')}
      </p>
      <label htmlFor={id} className="mt-1 text-caption font-medium text-ink2">
        {t('prompts.copy.pasteLabel')}
      </label>
      <textarea
        id={id}
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        placeholder={t('prompts.copy.pastePlaceholder')}
        rows={6}
        spellCheck={false}
        autoComplete="off"
        aria-describedby={failure ? `${leadId} ${failureId}` : leadId}
        aria-invalid={refused ? true : undefined}
        className={`min-h-[44px] w-full rounded-control border bg-surface px-3 py-2 text-body text-ink placeholder:text-muted ${
          refused ? 'border-loss' : 'border-edge'
        }`}
      />
      <div className="mt-1">
        <Button variant="secondary" onClick={() => void onSave()} disabled={saving || answer.trim() === ''}>
          {saving ? t('prompts.copy.saving') : t('prompts.copy.save')}
        </Button>
      </div>
      {failure && (
        <div id={failureId} role="alert" className="mt-1 break-words">
          {failure.kind === 'refused' ? (
            <>
              <p className="text-body text-loss">{t('prompts.copy.notSaved')}</p>
              <p className="mt-1 whitespace-pre-wrap text-caption text-ink2">{failure.detail}</p>
            </>
          ) : (
            <p className="text-body text-loss">{t('prompts.copy.notSavedOffline')}</p>
          )}
        </div>
      )}
    </div>
  )
}
