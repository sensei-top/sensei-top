import { useTranslation } from 'react-i18next'
import type { StageKind, StageRow } from '../lib/stageProgress'

/** The server's stages as a list, drawn as the children of an
 *  `OutlineCard`'s status in place of its line of words. The ticks are
 *  decoration: the current stage is `aria-current`. */
export function StageProgress({ page, rows }: { page: StageKind; rows: StageRow[] }) {
  const { t } = useTranslation()
  return (
    <ol aria-label={t(page === 'guide' ? 'decks.guide.stage.label' : 'coach.stage.label')} className="space-y-1 text-left">
      {rows.map((row) => (
        <li
          key={row.id}
          aria-current={row.state === 'current' ? 'step' : undefined}
          className={row.state === 'current' ? 'text-ink' : undefined}
        >
          <span aria-hidden="true">{row.state === 'done' ? '✓ ' : ''}</span>
          {row.label}
        </li>
      ))}
    </ol>
  )
}
