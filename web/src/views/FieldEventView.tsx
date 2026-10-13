import { Trans, useTranslation } from 'react-i18next'
import { isNotFound, useMetagameEvent } from '../api'
import { EventDeckList } from '../components/field/EventDeckList'
import { Card, EmptyState, ErrorNote, Loading, TextLink } from '../components/ui'
import { kindWords, readLine, sourceLines, standing, type SourceLine } from '../lib/fieldEvent'
import { formatIsoDateShort, useNow } from '../lib/time'

/** One line of the source credit: its sentence, with the site's name as the
 *  link when there is an address for it. */
function SourceCredit({ line }: { line: SourceLine }) {
  const siteLink = line.href ? <TextLink href={line.href} /> : <span />
  const values = { site: line.site }
  switch (line.sentence) {
    case 'topdeck':
      return <Trans i18nKey="field.event.sourceTopdeck" values={values} components={{ site: siteLink }} />
    case 'topdeckEvent':
      return <Trans i18nKey="field.event.sourceTopdeckEvent" values={values} components={{ site: siteLink }} />
    case 'results':
      return <Trans i18nKey="field.event.sourceResults" values={values} components={{ site: siteLink }} />
  }
}

/** One stored event, top to bottom: its name, its date, format and kind, the
 *  source line or lines, a league's note (tier C), the read line when one
 *  applies, and every deck in the API's order. An address with no event says
 *  so and points back to the field. */
export function FieldEventView({ eventKey }: { eventKey: string | undefined }) {
  const { t } = useTranslation()
  const query = useMetagameEvent(eventKey)
  const now = useNow()
  if (query.isPending && query.fetchStatus !== 'idle') return <Loading />
  if (!eventKey || isNotFound(query.error)) {
    return (
      <EmptyState
        message={t('field.event.notFound')}
        action={
          <TextLink href="/field" className="inline-flex min-h-[44px] items-center">
            {t('field.event.back')}
          </TextLink>
        }
      />
    )
  }
  if (query.error) return <ErrorNote error={query.error} />
  const event = query.data
  if (!event) return <Loading />

  const date = event.date ? formatIsoDateShort(event.date, now) : null
  const kind = kindWords(event.tier, t)
  const under = [date, event.format, kind].filter(Boolean).join(' · ')
  const read = readLine(event, t)
  const standingsOnly = !event.decks.some((deck) => deck.main.length > 0)

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="font-display text-heading text-ink">{event.name}</h2>
        {under && <p className="text-caption text-muted">{under}</p>}
      </div>
      <div className="space-y-1 text-caption text-ink2">
        {sourceLines(event).map((line, i) => (
          <p key={i}>
            <SourceCredit line={line} />
          </p>
        ))}
        {event.tier === 'C' && <p>{t('field.event.league')}</p>}
        {read && <p>{read}</p>}
      </div>
      {(!standingsOnly || event.decks.some((deck) => standing(deck, t) !== null)) && (
        <Card>
          <ul className="space-y-3">
            {event.decks.map((deck, i) => (
              <EventDeckList key={i} deck={deck} standingsOnly={standingsOnly} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
