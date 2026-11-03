import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { CoverageRowOut } from '../../api'
import { coveragePromptNotes } from '../../lib/brief'
import { Button } from '../../components/ui'
import { CopyPromptBody } from '../CopyPromptCard'
import { useGuideCoveragePrompt, usePasteCoverage } from '../hooks'

/** The one prompt for every archetype whose brief is missing or stale: a
 *  button, and on its press the prompt, fetched only then. The caller draws
 *  it only when `rows` holds a gap. */
export function CoveragePrompt({ guideKey, rows }: { guideKey: string; rows: CoverageRowOut[] }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const coveragePrompt = useGuideCoveragePrompt(guideKey, open)
  const paste = usePasteCoverage()
  const multi = coveragePrompt.data

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        {t('matchups.coverage.writeAll')}
      </Button>
    )
  }
  return (
    <>
      <p className="text-body text-ink2">{t('matchups.coverage.writeAllHint')}</p>
      <CopyPromptBody
        prompt={multi?.status === 'ok' ? multi.prompt : undefined}
        loading={coveragePrompt.isLoading}
        error={
          coveragePrompt.error?.message ??
          (multi?.status === 'format_unknown'
            ? t('matchups.brief.formatUnknown')
            : multi?.status === 'no_consensus'
              ? t('matchups.coverage.noneEnough')
              : multi?.status === 'nothing_missing'
                ? t('matchups.coverage.allWritten')
                : undefined)
        }
        save={(answer) => paste.mutateAsync({ key: guideKey, answer })}
      >
        {multi &&
          coveragePromptNotes(multi, rows, t).map((note) => (
            <p key={note} className="mt-2 text-caption text-muted">
              {note}
            </p>
          ))}
      </CopyPromptBody>
    </>
  )
}
