import { useTranslation } from 'react-i18next'
import type { MetaPresence } from '../../api'
import type { FieldRecord } from '../../lib/home'
import { formatPercent } from '../../lib/format'
import { rowCaption } from '../../lib/field'
import { formatCount } from '../../lib/time'
import { ManaPips, Meter } from '../ui'

/** One deck of the field, as Home and Field draw it: the pips and the
 *  name, under the name the viewer's record against it ("58% · 35–25" from ten
 *  matches, the record alone, "6–3", under ten, or `notPlayed`),
 *  the share as a bar in the field's colour and its percent, and, where
 *  `lists` is given, how many lists it is. An `li`, for the caller's `ul`. */
export function FieldRow({
  presence,
  record,
  notPlayed,
  lists,
}: {
  presence: MetaPresence
  record: FieldRecord
  notPlayed: string
  lists?: number
}) {
  const { t } = useTranslation()
  const withLists = lists != null
  return (
    // Under 48rem a row is two lines: the name and its record at the row's
    // full width, then the bar, its share and its lists. From 48rem up, one
    // line, the name's column never narrower than its longest word. A name
    // wraps between words, never inside one.
    <li
      className={`grid items-center gap-x-3 gap-y-2 md:gap-y-0 ${
        withLists
          ? 'grid-cols-[minmax(0,1fr)_2.75rem_5rem] md:grid-cols-[minmax(min-content,1fr)_minmax(0,1fr)_2.75rem_5rem]'
          : 'grid-cols-[minmax(0,1fr)_2.75rem] md:grid-cols-[minmax(min-content,1fr)_minmax(0,1fr)_2.75rem]'
      }`}
    >
      <div className={`min-w-0 md:col-span-1 ${withLists ? 'col-span-3' : 'col-span-2'}`}>
        <div className="flex min-w-0 items-center gap-2">
          <ManaPips colors={presence.colors} />
          <span className="min-w-0 text-body font-medium text-ink">{presence.label}</span>
        </div>
        <p className="text-caption text-muted">
          {rowCaption(record, notPlayed, t)}
        </p>
      </div>
      <Meter fraction={presence.share} color="s3" />
      <span className="text-right text-caption text-ink2 tabular-nums">{formatPercent(presence.share)}</span>
      {withLists && (
        <span className="text-right text-caption whitespace-nowrap text-muted tabular-nums">
          {t('field.row.lists', { count: lists, n: formatCount(lists) })}
        </span>
      )}
    </li>
  )
}
