import { archetypeName } from '../../lib/decks'
import { freshnessSentence, type RcqInputs, type RcqPreviewOut } from '../../lib/rcq'
import { formatIsoDateShort, formatPercent, useNow } from '../../lib/time'
import { Callout, Card, Disclosure, ErrorNote, Loading } from '../ui'

/** What the 75 reads as, in one sentence: the classifier's archetype, the
 *  one the player chose, or why there is none. */
function OwnLine({ preview, chosen }: { preview: RcqPreviewOut; chosen: boolean }) {
  if (preview.own_archetype_name) {
    return (
      <p className="text-body text-ink2">
        Your 75 reads as <span className="font-medium text-ink">{archetypeName(preview.own_archetype_name)}</span>
        {chosen ? ', as you chose.' : '.'}
      </p>
    )
  }
  return (
    <p className="text-body text-ink2">
      Your 75 could not be named from the field's lists
      {preview.own_unclassified_reason ? `: ${preview.own_unclassified_reason}` : ''}. Choose its archetype above.
    </p>
  )
}

/** The pasted 75 read back before anything is written: its counts, what
 *  could not be read or found, what it is, how fresh the field is, and
 *  what the archetypes expected have done. `pending` while the first
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
  const now = useNow()
  if (inputs.decklist.trim() === '') {
    return (
      <Card title="What the guide will read">
        <p className="text-body text-muted">Paste your 75 above to see how it reads.</p>
      </Card>
    )
  }
  if (error) return <ErrorNote error={error} />
  if (pending || !preview) return <Loading />

  return (
    <Card title="What the guide will read" subtitle={updating ? 'Reading your changes…' : undefined}>
      <div className="space-y-4">
        <div>
          <p className="font-display text-title text-ink tabular-nums">
            {preview.main_count} / {preview.side_count}
          </p>
          <p className="text-caption text-muted">Maindeck / sideboard</p>
        </div>

        {(preview.warnings.length > 0 || preview.unresolved.length > 0) && (
          <Callout tone="warn" title="Check the list">
            <div className="space-y-2">
              {preview.warnings.map((warning, i) => (
                <p key={`w-${i}`}>{warning}</p>
              ))}
              {preview.unresolved.length > 0 && (
                <p>
                  Not found in the card database, so the guide has no rules text for{' '}
                  {preview.unresolved.length === 1 ? 'it' : 'them'}: {preview.unresolved.join(', ')}.
                </p>
              )}
            </div>
          </Callout>
        )}

        <OwnLine preview={preview} chosen={inputs.own != null} />

        {preview.expected.length > 0 && (
          <div>
            <h3 className="text-caption font-medium text-ink2">Expected at the store</h3>
            <ul className="mt-1 space-y-0.5 text-body text-ink2">
              {preview.expected.map((each) => (
                <li key={each.key}>
                  <span className="text-ink">{archetypeName(each.name)}</span>
                  {each.share != null ? `, ${formatPercent(each.share)}% of the field` : ', not in the field'}
                  {each.wins + each.losses > 0
                    ? `; you are ${each.wins}–${each.losses} against it`
                    : '; you have not played it'}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <h3 className="text-caption font-medium text-ink2">How fresh the field is</h3>
          {preview.freshness.length === 0 ? (
            <p className="mt-1 text-caption text-muted">No tournament source has been fetched.</p>
          ) : (
            <ul className="mt-1 space-y-0.5 text-caption text-muted">
              {preview.freshness.map((entry) => (
                <li key={entry.source}>{freshnessSentence(entry, now)}</li>
              ))}
            </ul>
          )}
        </div>

        {preview.recent_shares.length > 0 && (
          <Disclosure summary="The field over the last 14 days">
            <ul className="space-y-0.5 text-body text-ink2">
              {preview.recent_shares.map((share) => (
                <li key={share.archetype_key ?? share.archetype}>
                  <span className="text-ink">{archetypeName(share.archetype)}</span>{' '}
                  <span className="tabular-nums">
                    {formatPercent(share.share)}%, {share.decks} {share.decks === 1 ? 'deck' : 'decks'}
                  </span>
                </li>
              ))}
            </ul>
          </Disclosure>
        )}

        <Disclosure summary={`Events of the last 7 days (${preview.recent_events.length})`}>
          {preview.recent_events.length === 0 ? (
            <p className="text-caption text-muted">No event in the corpus in the last 7 days.</p>
          ) : (
            <ul className="space-y-2">
              {preview.recent_events.map((event, i) => (
                <li key={`${event.date}-${event.name}-${i}`} className="text-body text-ink2">
                  <p>
                    <span className="text-ink">{event.name}</span>
                  </p>
                  <p className="text-caption text-muted">
                    {formatIsoDateShort(event.date, now) ?? event.date} · {event.source} · Tier {event.tier} ·{' '}
                    {event.decks} {event.decks === 1 ? 'list' : 'lists'}
                  </p>
                  {event.top8.length > 0 && (
                    <p className="text-caption text-ink2">Top 8: {event.top8.map(archetypeName).join(', ')}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Disclosure>
      </div>
    </Card>
  )
}
