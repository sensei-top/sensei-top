import { useTranslation } from 'react-i18next'
import { tierKind } from '../../lib/field'
import type { Field } from '../../lib/home'
import { formatCount } from '../../lib/time'
import { FieldRow } from '../field/FieldRow'
import { Card } from '../ui'

/** The field's most played decks from the first tier in rank order with
 *  lists in the window (`homeField`), the tier named in words
 *  (`tierKind`), each with its share as a bar in the field's colour and,
 *  under its name, the viewer's own record against it in the same window. */
export function FieldAgainstYou({ field }: { field: Field }) {
  const { t } = useTranslation()
  const kind = tierKind(field.tier, t)
  const note = t('home.field.noteLastDays', { kind, days: field.days })
  const deck = field.deck ? (field.deck.name ?? t('home.unnamedDeckInSentence')) : null
  return (
    <Card title={t('home.field.title', { format: field.format })} action={<span className="text-caption text-muted">{note}</span>}>
      <ul className="space-y-3">
        {field.rows.map(({ presence, record }) => (
          <FieldRow
            key={presence.archetype_key}
            presence={presence}
            record={record}
            notPlayed={t('home.field.notPlayedLastDays', { days: field.days })}
          />
        ))}
      </ul>
      <div className="mt-4 space-y-1 text-caption text-muted">
        <p>
          {deck
            ? t('home.field.barsWithDeck', { lists: formatCount(field.lists), deck })
            : t('home.field.barsNoDeck', { lists: formatCount(field.lists) })}
        </p>
        {field.listShort && <p>{t('home.field.listShort')}</p>}
      </div>
    </Card>
  )
}
