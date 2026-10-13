import { Trans, useTranslation } from 'react-i18next'
import type { RcqPreviewOut } from '../../api'
import { archetypeName } from '../../lib/decks'
import { freshnessSentence, type RcqInputs } from '../../lib/rcq'
import { formatIsoDateShort, formatPercent, useNow } from '../../lib/time'
import { Callout, Card, Disclosure, ErrorNote, Loading } from '../ui'

/** `text` as a sentence of its own: trimmed, its first letter a capital,
 *  a full stop added when it ends in none; `null` when there is nothing. */
function sentence(text: string | null | undefined): string | null {
  const trimmed = text?.trim()
  if (!trimmed) return null
  const capital = trimmed.charAt(0).toUpperCase() + trimmed.slice(1)
  return /[.!?]$/.test(capital) ? capital : `${capital}.`
}

/** One archetype expected at the store: its share of the field, if it has
 *  one, and the player's record against it, if there is one to say. One
 *  whole sentence a case. */
function ExpectedLine({ each }: { each: RcqPreviewOut['expected'][number] }) {
  const values = {
    name: archetypeName(each.name),
    pct: each.share != null ? formatPercent(each.share) : '',
    wins: each.wins ?? 0,
    losses: each.losses ?? 0,
  }
  const components = { name: <span className="text-ink" /> }
  const record = each.wins == null || each.losses == null ? 'none' : each.wins + each.losses > 0 ? 'record' : 'unplayed'
  if (each.share != null) {
    if (record === 'record') return <Trans i18nKey="rcq.preview.expected.shareRecord" values={values} components={components} />
    if (record === 'unplayed') return <Trans i18nKey="rcq.preview.expected.shareNone" values={values} components={components} />
    return <Trans i18nKey="rcq.preview.expected.share" values={values} components={components} />
  }
  if (record === 'record') return <Trans i18nKey="rcq.preview.expected.absentRecord" values={values} components={components} />
  if (record === 'unplayed') return <Trans i18nKey="rcq.preview.expected.absentNone" values={values} components={components} />
  return <Trans i18nKey="rcq.preview.expected.absent" values={values} components={components} />
}

/** What the 75 reads as, in one sentence: the classifier's archetype, the
 *  one the player chose, or why there is none. */
function OwnLine({ preview, chosen }: { preview: RcqPreviewOut; chosen: boolean }) {
  const { t } = useTranslation()
  if (preview.own_archetype_name) {
    return (
      <p className="text-body text-ink2">
        <Trans
          i18nKey={chosen ? 'rcq.preview.readsAsChosen' : 'rcq.preview.readsAs'}
          values={{ name: archetypeName(preview.own_archetype_name) }}
          components={{ name: <span className="font-medium text-ink" /> }}
        />
      </p>
    )
  }
  const reason = sentence(preview.own_unclassified_reason)
  return (
    <p className="text-body text-ink2">
      {t('rcq.preview.unnamed')}
      {reason ? ` ${reason}` : ''} {t('rcq.preview.chooseAbove')}
    </p>
  )
}

/** The pasted 75 read back before anything is written: its counts, what
 *  could not be read or found, what it is, how fresh the field is, and
 *  what the archetypes expected have done. A deck whose format is unknown
 *  (`format` null) has no field: one line says so in place of the expected
 *  archetypes, the freshness and the recent events. `pending` while the first
 *  answer is on its way; `updating` while a newer one is. */
export function PreviewCard({
  preview,
  error,
  pending,
  updating,
  inputs,
}: {
  preview: RcqPreviewOut | undefined
  error: Error | null
  pending: boolean
  updating: boolean
  inputs: RcqInputs
}) {
  const { t } = useTranslation()
  const now = useNow()
  if (inputs.decklist.trim() === '') {
    return (
      <Card title={t('rcq.preview.title')}>
        <p className="text-body text-muted">{t('rcq.preview.pasteFirst')}</p>
      </Card>
    )
  }
  if (error) return <ErrorNote error={error} />
  if (pending || !preview) return <Loading />

  return (
    <Card title={t('rcq.preview.title')} subtitle={updating ? t('rcq.preview.updating') : undefined}>
      <div className="space-y-4">
        <div>
          <p className="font-display text-title text-ink tabular-nums">
            {preview.main_count} / {preview.side_count}
          </p>
          <p className="text-caption text-muted">{t('rcq.preview.counts')}</p>
        </div>

        {(preview.warnings.length > 0 || preview.unresolved.length > 0) && (
          <Callout tone="warn" title={t('rcq.preview.checkTitle')}>
            <div className="space-y-2">
              {preview.warnings.map((warning, i) => (
                <p key={`w-${i}`}>{warning}</p>
              ))}
              {preview.unresolved.length > 0 && (
                <p>
                  {t('rcq.preview.unresolved', { count: preview.unresolved.length, cards: preview.unresolved.join(', ') })}
                </p>
              )}
            </div>
          </Callout>
        )}

        <OwnLine preview={preview} chosen={inputs.own != null} />

        {preview.format === null && (
          <p className="text-caption text-muted">{t('rcq.preview.noFormat')}</p>
        )}

        {preview.format !== null && preview.expected.length > 0 && (
          <div>
            <h3 className="text-caption font-medium text-ink2">{t('rcq.preview.expectedTitle')}</h3>
            <ul className="mt-1 space-y-0.5 text-body text-ink2">
              {preview.expected.map((each) => (
                <li key={each.key}>
                  <ExpectedLine each={each} />
                </li>
              ))}
            </ul>
          </div>
        )}

        {preview.format !== null && (
          <div>
            <h3 className="text-caption font-medium text-ink2">{t('rcq.preview.freshTitle')}</h3>
            {preview.freshness.length === 0 ? (
              <p className="mt-1 text-caption text-muted">{t('rcq.preview.freshNone')}</p>
            ) : (
              <ul className="mt-1 space-y-0.5 text-caption text-muted">
                {preview.freshness.map((entry) => (
                  <li key={entry.source}>{freshnessSentence(entry, now, t)}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {preview.recent_shares.length > 0 && (
          <Disclosure summary={t('rcq.preview.recentShares')}>
            <ul className="space-y-0.5 text-body text-ink2">
              {preview.recent_shares.map((share) => (
                <li key={share.archetype_key ?? share.archetype}>
                  <span className="text-ink">{archetypeName(share.archetype)}</span>{' '}
                  <span className="tabular-nums">
                    {t('rcq.preview.recentShare', { count: share.decks, pct: formatPercent(share.share), n: share.decks })}
                  </span>
                </li>
              ))}
            </ul>
          </Disclosure>
        )}

        {preview.format !== null && (
          <Disclosure summary={t('rcq.preview.eventsSummary', { n: preview.recent_events.length })}>
            {preview.recent_events.length === 0 ? (
              <p className="text-caption text-muted">{t('rcq.preview.noEvents')}</p>
            ) : (
              <ul className="space-y-2">
                {preview.recent_events.map((event, i) => (
                  <li key={`${event.date ?? ''}-${event.name}-${i}`} className="text-body text-ink2">
                    <p>
                      <span className="text-ink">{event.name}</span>
                    </p>
                    <p className="text-caption text-muted">
                      {event.date
                        ? t('rcq.preview.eventDated', {
                            count: event.decks,
                            date: formatIsoDateShort(event.date, now) ?? event.date,
                            source: event.source,
                            tier: event.tier,
                            n: event.decks,
                          })
                        : t('rcq.preview.event', { count: event.decks, source: event.source, tier: event.tier, n: event.decks })}
                    </p>
                    {event.top8.length > 0 && (
                      <p className="text-caption text-ink2">
                        {t('rcq.preview.top8', { decks: event.top8.map(archetypeName).join(', ') })}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Disclosure>
        )}
      </div>
    </Card>
  )
}
