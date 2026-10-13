import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Match } from '../api'
import { matchesCaption } from '../lib/deckOverview'
import { formatCount } from '../lib/time'
import { MatchRow } from './MatchRow'
import { Button, Card } from './ui'

/** Rows shown at first, and added by each press of the button. */
const FIRST = 10
const STEP = 50

/** A deck's Matches card, read by its Overview and by a pairing's page: the
 *  matches given, newest first, ten at first and fifty more a press, each
 *  row without the deck's own name, which the page's title already gives.
 *  The rows shown are this card's own state, so each page keys the card on
 *  the version and a change of version starts the list again at ten
 *  without rebuilding the page. */
export function DeckMatchesCard({ matches }: { matches: Match[] }) {
  const { t } = useTranslation()
  const [shown, setShown] = useState(FIRST)
  const rows = matches.slice(0, shown)
  const left = matches.length - rows.length
  return (
    <Card title={t('decks.matches.title')} subtitle={matchesCaption(matches.length, rows.length, t)}>
      <ul className="divide-y divide-line">
        {rows.map((match) => (
          <li key={match.match_id} className="py-1 first:pt-0 last:pb-0">
            <MatchRow match={match} withDeck={false} />
          </li>
        ))}
      </ul>
      {left > 0 && (
        <div className="mt-4">
          <Button onClick={() => setShown((count) => count + STEP)}>
            {t('decks.matches.showMore', { n: formatCount(Math.min(STEP, left)) })}
          </Button>
        </div>
      )}
    </Card>
  )
}
