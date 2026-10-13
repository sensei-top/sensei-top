import { type ReactNode, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { MetaEventRow } from '../../api'
import { EVENTS_SHOWN, eventCaption, eventHref, shownRows } from '../../lib/field'
import { formatCount, formatIsoDateShort } from '../../lib/time'
import { Card, EmptyState, ErrorNote, Loading, TextLink } from '../ui'
import { ShowAll } from './ShowAll'

/** "The events": the stored events of the tier in the window, newest first
 *  as the API orders them, twelve and then the rest behind a button. Each
 *  row is its date, the event's name linking to its page, and a caption
 *  line. Loading and failure are drawn inside the card, as the matchups
 *  card does; its action waits for the tier. */
export function EventsCard({
  rows,
  isPending,
  error,
  kind,
  when,
  action,
  now,
}: {
  rows: MetaEventRow[] | undefined
  isPending: boolean
  error: Error | null
  kind: string
  when: string
  action: string | null
  now: number
}) {
  const { t } = useTranslation()
  const [all, setAll] = useState(false)
  const actionNode = action ? <span className="text-caption text-muted">{action}</span> : undefined
  const subtitle = t('field.events.subtitle')
  const frame = (body: ReactNode) => (
    <Card title={t('field.events.title')} action={actionNode} subtitle={subtitle}>
      {body}
    </Card>
  )
  if (error) return frame(<ErrorNote error={error} />)
  if (isPending || !rows) return frame(<Loading />)
  if (rows.length === 0) return frame(<EmptyState message={t('field.events.empty', { kind, when })} />)
  const shown = shownRows(rows, EVENTS_SHOWN, all)
  return frame(
    <>
      <ul className="space-y-3">
        {shown.map((event) => (
          <li key={event.key} className="flex gap-3">
            <span className="w-24 shrink-0 whitespace-nowrap text-caption text-muted">
              {(event.date ? formatIsoDateShort(event.date, now) : null) ?? ''}
            </span>
            <div className="min-w-0">
              <TextLink href={eventHref(event.key)}>{event.name}</TextLink>
              <p className="text-caption text-muted">{eventCaption(event, formatCount, t)}</p>
            </div>
          </li>
        ))}
      </ul>
      {shown.length < rows.length && <ShowAll total={rows.length} onShow={() => setAll(true)} />}
    </>,
  )
}
