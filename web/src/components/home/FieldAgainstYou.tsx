import { TIER_KIND } from '../../lib/field'
import type { Field } from '../../lib/home'
import { UNNAMED_DECK_IN_SENTENCE } from '../../lib/home'
import { formatCount, formatIsoDateShort } from '../../lib/time'
import { FieldRow } from '../field/FieldRow'
import { Card } from '../ui'

/** The field's most played decks from the first tier in rank order with
 *  lists in the window (`homeField`), the tier named in words
 *  (`TIER_KIND`), each with its share as a bar in the field's colour and,
 *  under its name, the viewer's own record against it in the same window. */
export function FieldAgainstYou({ field, now }: { field: Field; now: number }) {
  const since = field.reset ? formatIsoDateShort(field.reset, now) : null
  const kind = TIER_KIND[field.tier]
  const note = since ? `${kind} since ${since}` : `${kind}, last 90 days`
  const deck = field.deck ? (field.deck.name ?? UNNAMED_DECK_IN_SENTENCE) : null
  return (
    <Card title={`The ${field.format} field, and you against it`} action={<span className="text-caption text-muted">{note}</span>}>
      <ul className="space-y-3">
        {field.rows.map(({ presence, record }) => (
          <FieldRow
            key={presence.archetype_key}
            presence={presence}
            record={record}
            notPlayed={since ? `not played since ${since}` : 'not played in the last 90 days'}
          />
        ))}
      </ul>
      <div className="mt-4 space-y-1 text-caption text-muted">
        <p>
          {deck
            ? `Bars are each deck's share of ${formatCount(field.lists)} tournament lists. The line under each is your own record with ${deck} in the same period.`
            : `Bars are each deck's share of ${formatCount(field.lists)} tournament lists. The line under each is your own record in the same period.`}
        </p>
        {field.listShort && <p>Your record is counted over your last 500 matches.</p>}
      </div>
    </Card>
  )
}
