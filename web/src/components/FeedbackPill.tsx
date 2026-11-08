import { MessageSquare } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useReportProblem } from '../lib/reportProblem'

/** The quiet way into Report a problem, fixed at the window's bottom right
 *  from 48rem up (under it the bottom bar owns the foot). Drawn only where a
 *  shell sends reports; the shell leaves it out of the welcome's pages and
 *  Live's focus mode. */
export function FeedbackPill() {
  const { t } = useTranslation()
  const report = useReportProblem()
  if (!report) return null
  return (
    <button
      type="button"
      onClick={() => report.open(null)}
      className="fixed right-4 bottom-4 hidden items-center gap-1.5 rounded-full bg-surface3 px-3 py-1.5 text-caption font-medium text-ink2 shadow-lift hover:text-ink md:inline-flex"
    >
      <MessageSquare aria-hidden="true" className="size-3.5" />
      {t('report.feedback')}
    </button>
  )
}
