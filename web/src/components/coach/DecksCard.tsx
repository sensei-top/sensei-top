import { useTranslation } from 'react-i18next'
import type { CoachEvidenceModel, RateModel } from '../../api'
import { deckName, rateWords } from '../../lib/coach'
import { archetypeName } from '../../lib/decks'
import { RATE_MIN_MATCHES } from '../../lib/sample'
import { Card } from '../ui'

type DeckLine = CoachEvidenceModel['by_deck'][number]

/** A deck's matches, at the row's right: from ten the percent, and under it
 *  in caption the record and the range; under ten the record, muted, over
 *  the "too few" line (D7); a dash only with no match. */
function MatchesRate({ rate }: { rate: RateModel }) {
  const { t } = useTranslation()
  const words = rateWords(rate)
  if (words.record == null) return <div className="shrink-0 text-right text-body text-muted">—</div>
  if (words.percent == null) {
    return (
      <div className="max-w-[50%] shrink-0 text-right">
        <div className="text-body whitespace-nowrap text-muted tabular-nums">{words.record}</div>
        <div className="text-caption text-muted">{t('common.sample.tooFewMatches', { min: RATE_MIN_MATCHES })}</div>
      </div>
    )
  }
  return (
    <div className="shrink-0 text-right">
      <div className="text-body text-ink tabular-nums">{words.percent}</div>
      <div className="text-caption whitespace-nowrap text-muted tabular-nums">{words.record}</div>
      <div className="text-caption whitespace-nowrap text-muted tabular-nums">{words.range}</div>
    </div>
  )
}

/** One deck: the name the user typed, the field's name under it when it
 *  differs (D10), its matches at the right, then the four splits, each a
 *  label over the percent and the record; under ten, the record, muted,
 *  over "too few". No range on a split. */
function DeckRow({ deck }: { deck: DeckLine }) {
  const { t } = useTranslation()
  const name = deckName(deck.label, t)
  const archetype = deck.archetype ? archetypeName(deck.archetype) : null
  const splits: [string, RateModel][] = [
    [t('coach.split.game1'), deck.g1],
    [t('coach.split.postBoard'), deck.post_board],
    [t('coach.split.onPlay'), deck.on_play],
    [t('coach.split.onDraw'), deck.on_draw],
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
              {words.percent != null ? (
                <>
                  <dd className="text-body text-ink tabular-nums">{words.percent}</dd>
                  <dd className="text-caption text-muted tabular-nums">{words.record}</dd>
                </>
              ) : (
                <>
                  <dd className={`text-body tabular-nums ${words.record ? 'whitespace-nowrap text-muted' : 'text-ink'}`}>
                    {words.record ?? '—'}
                  </dd>
                  {words.record && (
                    <dd className="text-caption text-muted">{t('common.sample.tooFewCellGames')}</dd>
                  )}
                </>
              )}
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
  const { t } = useTranslation()
  if (decks.length === 0) return null
  return (
    <Card title={t('coach.byDeck.title')} subtitle={t('coach.byDeck.subtitle')}>
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
