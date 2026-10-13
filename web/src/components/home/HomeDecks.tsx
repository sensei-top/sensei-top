import { useTranslation } from 'react-i18next'
import { deckAddress, deckRecord } from '../../lib/decks'
import type { HomeDeck } from '../../lib/home'
import type { ArtCard } from '../../lib/matchArt'
import { formatShortDay } from '../../lib/time'
import { DeckTile, TextLink } from '../ui'

/** Home's deck tiles: one per deck, not per version (`lib/home.ts`'s
 *  `homeDecks`), each a way into the deck's own page by its key. The
 *  figure and its line are `lib/decks.ts`'s `deckRecord`, as on `/decks`.
 *  Two to a row under 48rem, three from there, five in one row from 64rem. */
export function HomeDecks({
  decks,
  art,
  now,
}: {
  decks: HomeDeck[]
  /** A card for each deck, by its key. */
  art: Map<string, ArtCard | null>
  now: number
}) {
  const { t } = useTranslation()
  if (decks.length === 0) return null
  return (
    <section aria-labelledby="home-decks" className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="home-decks" className="font-display text-title text-ink">
          {t('home.decks.title')}
        </h2>
        <TextLink href="/decks" className="ml-auto text-caption">
          {t('home.decks.all')}
        </TextLink>
      </div>
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4 lg:grid-cols-5">
        {decks.map((deck) => {
          const { figure, line } = deckRecord(deck, t)
          return (
            <li key={deck.key} className="min-w-0">
              <DeckTile
                name={deck.name}
                href={deckAddress(deck.key)}
                figure={figure}
                line={line}
                lastPlayed={deck.lastPlayed != null ? t('home.decks.lastPlayed', { day: formatShortDay(deck.lastPlayed, now) }) : null}
                art={art.get(deck.key) ?? null}
              />
            </li>
          )
        })}
      </ul>
    </section>
  )
}
