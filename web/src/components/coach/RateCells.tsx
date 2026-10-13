import { useTranslation } from 'react-i18next'
import type { RateModel } from '../../api'
import { rateWords } from '../../lib/coach'

/** A table's "Won" cell: the record, "174 of 385"; a dash with no match. */
export function WonCell({ rate }: { rate: RateModel }) {
  const { t } = useTranslation()
  return <span className="whitespace-nowrap">{rateWords(rate, t).record ?? '—'}</span>
}

/** A table's "Rate" cell: the percent over its range in caption, or the
 *  percent alone when `withRange` is false; a dash under ten matches. */
export function RateCell({ rate, withRange = true }: { rate: RateModel; withRange?: boolean }) {
  const { t } = useTranslation()
  const words = rateWords(rate, t)
  if (words.percent == null) return <span>—</span>
  return (
    <span className="inline-flex flex-col items-end">
      <span className="whitespace-nowrap">{words.percent}</span>
      {withRange && <span className="whitespace-nowrap text-caption text-muted">{words.range}</span>}
    </span>
  )
}
