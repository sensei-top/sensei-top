import type { MetaEventDeck } from '../../api'
import { groupHeading, sideboardHeading, standing } from '../../lib/fieldEvent'
import { Card, ManaPips } from '../ui'

/** One deck of an event, as the event page draws it: the standing, then, for
 *  a deck with a list, its archetype (the pips and the label, as `FieldRow`
 *  draws one, or "No archetype named") and the list, a group a type and the
 *  sideboard flat. A deck with no list says so, unless `standingsOnly`: no
 *  deck of the event has a list, and the event's read line says it already.
 *  A deck with nothing to show is not drawn. */
export function EventDeckList({ deck, standingsOnly }: { deck: MetaEventDeck; standingsOnly: boolean }) {
  const place = standing(deck)
  const hasList = deck.main.length > 0
  if (standingsOnly && !place) return null
  const sideHeading = sideboardHeading(deck.side)
  return (
    <li>
      <Card elevation={2}>
        {(place || hasList) && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {place && <span className="text-body font-medium text-ink tabular-nums">{place}</span>}
            {hasList &&
              (deck.archetype ? (
                <span className="flex min-w-0 items-center gap-2">
                  <ManaPips colors={deck.archetype.colors} />
                  <span className="min-w-0 text-body font-medium text-ink">{deck.archetype.label}</span>
                </span>
              ) : (
                <span className="text-body text-muted">No archetype named</span>
              ))}
          </div>
        )}
        {!hasList && !standingsOnly && <p className={`${place ? 'mt-2 ' : ''}text-body text-muted`}>No decklist published.</p>}
        {hasList && (
          <div className="mt-3 grid gap-x-6 gap-y-3 sm:grid-cols-2">
            {deck.main.map((group) => (
              <div key={group.type ?? ''}>
                <h3 className="text-caption font-medium text-ink2">{groupHeading(group.type ?? null, group.count)}</h3>
                <ul className="mt-1 space-y-0.5">
                  {group.cards.map((card) => (
                    <li key={card.name} className="text-body text-ink">
                      {card.count} {card.name}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {sideHeading && (
              <div>
                <h3 className="text-caption font-medium text-ink2">{sideHeading}</h3>
                <ul className="mt-1 space-y-0.5">
                  {deck.side.map((card) => (
                    <li key={card.name} className="text-body text-ink">
                      {card.count} {card.name}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Card>
    </li>
  )
}
