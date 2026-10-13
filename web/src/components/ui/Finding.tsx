import type { ReactNode } from 'react'
import { Chip } from './Chip'
import { severityChip } from './severity'
import { useTranslation } from 'react-i18next'

export type FindingWeight = 'decisive' | 'flag' | 'notice' | 'note'

/** One finding of the match report or the leak finder, as a nested block:
 *  its weight as a tag (the word, with `severityChip`'s colour behind it)
 *  and where it happened on one line, then its title and the body. */
export function Finding({
  weight,
  where,
  title,
  children,
}: {
  weight: FindingWeight
  /** Where it happened: a game, a turn. */
  where?: ReactNode
  title: string
  children: ReactNode
}) {
  const { t } = useTranslation()
  const weightLabel: Record<FindingWeight, string> = {
    decisive: t('common.finding.decisive'),
    flag: t('common.finding.flag'),
    notice: t('common.finding.notice'),
    note: t('common.finding.note'),
  }
  return (
    <article className="rounded-block bg-surface2 px-4.5 py-4 [--art-surface:var(--surface-2)]">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <Chip size="sm" {...severityChip(weight)}>
          {weightLabel[weight]}
        </Chip>
        {where && <span className="text-caption text-muted">{where}</span>}
      </div>
      <h3 className="mt-2.5 font-display text-title text-ink">{title}</h3>
      <div className="mt-1.5 text-body text-ink2">{children}</div>
    </article>
  )
}
