import { DeckFilter, SourceFilter } from '../components/Filters'
import { useFilters } from '../lib/filters'
import { MatchHistoryView } from '../views/MatchHistoryView'

/** `/matches`: the filters, then the summary band and the list of matches
 *  under them. A match's report is its own address, `/matches/:id`. The
 *  list is keyed on the filters, so a new filter shows its first 50 rows
 *  again. */
export function MatchesPage() {
  const { source, deck, setSource, setDeck } = useFilters()
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center gap-3">
        <SourceFilter value={source} onChange={setSource} />
        <DeckFilter value={deck} onChange={setDeck} />
      </div>
      <MatchHistoryView key={`${source}:${deck ?? ''}`} deckId={deck} source={source} />
    </div>
  )
}
