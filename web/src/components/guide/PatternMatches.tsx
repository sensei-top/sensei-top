import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMatches } from '../../api'
import { HOME_MATCH_LIMIT } from '../../lib/home'
import { patternMatches } from '../../lib/guide'
import { formatCount } from '../../lib/time'
import { MatchRow } from '../MatchRow'
import { Button, ErrorNote, Loading } from '../ui'

const ROW_CUT = 10

/** A pattern's own matches (`leak.match_ids_with`), resolved against the
 *  match list Home and the Guide share — `useMatches(undefined, 'all',
 *  HOME_MATCH_LIMIT)`, the exact key both read, so this never asks for the
 *  list a second time. Newest first, the first ten; a quiet button under
 *  them shows the rest. `withDeck={false}` for a deck's own patterns; the
 *  deck is shown for "Across all of your decks". An id the list does not
 *  hold is never drawn as a piece of an id — it is only counted, in one
 *  sentence under the rows. */
export function PatternMatches({ ids, withDeck }: { ids: string[]; withDeck: boolean }) {
  const { t } = useTranslation()
  const [showAll, setShowAll] = useState(false)
  const matches = useMatches(undefined, 'all', HOME_MATCH_LIMIT)

  if (matches.isPending) return <Loading />
  if (matches.error) return <ErrorNote error={matches.error} />

  const { rows, missing } = patternMatches(ids, matches.data ?? [])
  const visible = showAll ? rows : rows.slice(0, ROW_CUT)
  const rest = rows.length - visible.length

  return (
    <div>
      <ul className="divide-y divide-line">
        {visible.map((match) => (
          <li key={match.match_id} className="py-1 first:pt-0 last:pb-0">
            <MatchRow match={match} withDeck={withDeck} />
          </li>
        ))}
      </ul>
      {rest > 0 && (
        <Button variant="quiet" size="sm" className="mt-2" onClick={() => setShowAll(true)}>
          {t('decks.guide.patterns.showOther', { count: rest, n: formatCount(rest) })}
        </Button>
      )}
      {missing.length > 0 && (
        <p className="mt-2 text-caption text-muted">
          {t('decks.guide.patterns.missing', { count: missing.length, n: formatCount(missing.length) })}
        </p>
      )}
    </div>
  )
}
