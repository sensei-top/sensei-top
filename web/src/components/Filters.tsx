import { useTranslation } from 'react-i18next'
import { useDecks } from '../api'
import type { Deck } from '../api'
import type { TFunction } from '../i18n'
import type { Source } from '../lib/filters'
import { ago } from '../lib/time'
import { Segmented, Select } from './ui'

/** Which client's matches a page counts. Always shown, unlike the deck
 *  filter: a second source exists whether or not this account has ever
 *  ingested any MTGO logs, and 'arena' (the default) reproduces every
 *  number exactly as it was before the filter existed. */
export function SourceFilter({ value, onChange }: { value: Source; onChange: (source: Source) => void }) {
  const { t } = useTranslation()
  // Arena and MTGO are the clients' own names, the same in every language.
  const options = [
    { value: 'arena' as const, label: 'Arena' },
    { value: 'mtgo' as const, label: 'MTGO' },
    { value: 'all' as const, label: t('common.filters.allSources') },
  ]
  return <Segmented label={t('common.filters.source')} size="sm" value={value} options={options} onChange={onChange} />
}

/** Enough to tell two decks apart at a glance, skipping whatever is unknown
 *  rather than padding the label with dashes. A deck with no name reads
 *  "Unnamed deck", never a piece of its id. */
function deckLabel(deck: Deck, now: number, t: TFunction): string {
  return [
    deck.name ?? t('common.unnamedDeck'),
    deck.format, // Arena's own spelling
    t('common.filters.matches', { count: deck.matches_played }),
    ago(deck.last_played, now),
  ]
    .filter(Boolean)
    .join(' · ')
}

/** One deck, or all of them. Shown even with a single deck: the label
 *  carries its format and record, which is worth reading before a filter
 *  is worth setting. A deck in the address that the list of decks does not
 *  hold is its own option, selected, so the select never reads "All
 *  decks" over a filtered list. Nothing at all while there are no decks
 *  and none is chosen. */
export function DeckFilter({
  value,
  onChange,
}: {
  value: string | undefined
  onChange: (deckId: string | undefined) => void
}) {
  const { t } = useTranslation()
  const decks = useDecks()
  // Read at render, not ticking: an open select would otherwise redraw
  // under the pointer every second. A refetch refreshes it.
  const now = Date.now()
  if (!decks.data || (decks.data.length === 0 && !value)) return null
  const unlisted = value != null && !decks.data.some((deck) => deck.deck_id === value)
  // A select is as wide as its longest option. The label is capped at the
  // row it sits in and the select may shrink inside it, so on a narrow
  // screen the select takes the room there is and cuts off the option it
  // shows, instead of pushing the page sideways.
  return (
    <Select
      label={t('common.filters.deck')}
      size="caption"
      value={value ?? ''}
      onChange={(deckId) => onChange(deckId || undefined)}
      options={decks.data.map((deck) => ({ value: deck.deck_id, label: deckLabel(deck, now, t) }))}
    >
      <option value="">{t('common.filters.allDecks')}</option>
      {unlisted && <option value={value}>{t('common.filters.unlistedDeck')}</option>}
    </Select>
  )
}
