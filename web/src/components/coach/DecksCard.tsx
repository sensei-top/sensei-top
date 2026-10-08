import type { CoachEvidenceModel, RateModel } from '../../api'
import { deckName, rateWords } from '../../lib/coach'
import { archetypeName } from '../../lib/decks'
import { Card } from '../ui'

type DeckLine = CoachEvidenceModel['by_deck'][number]

/** A deck's matches, at the row's right: the percent, and under it in
 *  caption the record and the range; under ten, a dash over the record. */
function MatchesRate({ rate }: { rate: RateModel }) {
  const words = rateWords(rate)
  return (
    <div className="shrink-0 text-right">
      <div className="text-body text-ink tabular-nums">{words.percent ?? '—'}</div>
      {words.record && <div className="text-caption whitespace-nowrap text-muted tabular-nums">{words.record}</div>}
      {words.range && <div className="text-caption whitespace-nowrap text-muted tabular-nums">{words.range}</div>}
    </div>
  )
}

/** One deck: the name the user typed, the field's name under it when it
 *  differs (D10), its matches at the right, then the four splits, each a
 *  label over the percent and the record. No range on a split. */
function DeckRow({ deck }: { deck: DeckLine }) {
  const name = deckName(deck.label)
  const archetype = deck.archetype ? archetypeName(deck.archetype) : null
  const splits: [string, RateModel][] = [
    ['Game 1', deck.g1],
    ['After sideboarding', deck.post_board],
    ['On the play', deck.on_play],
    ['On the draw', deck.on_draw],
  ]
  return (
    <>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 wrap-anywhere">
          <p className="text-body font-medium text-ink">{name}</p>
          {archetype && archetype !== name && <p className="text-caption text-muted">{archetype}</p>}
        </div>
        <MatchesRate rate={deck.matches} />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        {splits.map(([label, rate]) => {
          const words = rateWords(rate)
          return (
            <div key={label}>
              <dt className="text-caption text-muted">{label}</dt>
              <dd className="text-body text-ink tabular-nums">{words.percent ?? '—'}</dd>
              {words.record && <dd className="text-caption text-muted tabular-nums">{words.record}</dd>}
            </div>
          )
        })}
      </dl>
    </>
  )
}

/** "By deck": a deck a row, in the server's order. Two decks may share a
 *  label, so a row is keyed by its place. */
export function DecksCard({ decks }: { decks: DeckLine[] }) {
  if (decks.length === 0) return null
  return (
    <Card
      title="By deck"
      subtitle="Your decks with the most matches. Games on the play and on the draw are counted per game."
    >
      <ul className="divide-y divide-line">
        {decks.map((deck, index) => (
          <li key={index} className="py-3 first:pt-0 last:pb-0">
            <DeckRow deck={deck} />
          </li>
        ))}
      </ul>
    </Card>
  )
}
