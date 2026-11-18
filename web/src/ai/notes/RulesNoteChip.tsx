import { useEffect, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Chip, type ChipVariant } from '../../components/ui/Chip'
import { confidenceLabel } from '../../lib/opponent'
import type { RulesNote } from './context'

const VARIANT: Record<string, ChipVariant> = { high: 'win', medium: 'warn', low: 'loss' }

/** The chip for one rules note: its marker, tinted by the note's
 *  confidence, opening a popover with the verdict, the cited rules and the
 *  disclosure line. The disclosure shows in every popover, word for word. */
export function RulesNoteChip({ note }: { note: RulesNote }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const n = note.marker.replace(/^N/, '')

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  const confidence = note.confidence ?? null
  return (
    <span className="relative inline-block align-baseline">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={
          confidence
            ? `${t('prompts.rulesNotes.open', { n })}, ${confidenceLabel(confidence, t)}`
            : t('prompts.rulesNotes.open', { n })
        }
        onClick={() => setOpen((v) => !v)}
        className="cursor-pointer rounded-pill"
      >
        <Chip size="sm" variant={confidence ? (VARIANT[confidence] ?? 'neutral') : 'neutral'}>
          {note.marker}
        </Chip>
      </button>
      <span
        id={panelId}
        role="note"
        hidden={!open}
        className="absolute left-0 top-full z-20 mt-1 block w-72 space-y-2 rounded-card border border-edge bg-surface2 p-3 text-left text-caption font-normal text-ink shadow-lift"
      >
        <span className="block text-label font-semibold">{t('prompts.rulesNotes.title')}</span>
        {confidence && <span className="block text-muted">{confidenceLabel(confidence, t)}</span>}
        <span className="block font-semibold">{note.verdict}</span>
        <span className="block whitespace-pre-wrap">{note.explanation}</span>
        {note.citations && note.citations.length > 0 && (
          <span className="block">
            <span className="block text-muted">{t('prompts.rulesNotes.cited')}</span>
            {note.citations.map((citation, i) => (
              <span key={i} className="block">
                {citation}
              </span>
            ))}
          </span>
        )}
        <span className="block text-muted">{t('prompts.rulesNotes.disclosure')}</span>
      </span>
    </span>
  )
}
