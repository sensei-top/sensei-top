import { Trans, useTranslation } from 'react-i18next'
import type { DeckGuideOut } from '../../api'
import { formatCount, formatIsoDateShort, useNow } from '../../lib/time'
import { Callout, Card, StatTile } from '../ui'

/** The evidence's own provenance: the tournament corpus's freshness, how
 *  much of the current 75 has rules text, and the window a detected format
 *  reset scopes everything else to. The deck's record is the strip's over
 *  the tabs, not this card's. The page's title already names the deck, so
 *  this card's own title is just "Scope". Every gap `build_deck_guide` found is the server's own
 *  sentence, shown as sent. */
export function ScopeCard({ guide }: { guide: DeckGuideOut }) {
  const { t } = useTranslation()
  const now = useNow()
  const { provenance } = guide
  const [withText, totalCards] = provenance.oracle_coverage
  const { reset, matches_before_reset: before, classified_decks, corpus_latest_event } = provenance

  const listsLine = corpus_latest_event
    ? t('decks.guide.scope.through', { date: formatIsoDateShort(corpus_latest_event, now) ?? corpus_latest_event })
    : undefined

  const textLine =
    withText === totalCards
      ? t('decks.guide.scope.everyCard')
      : t('decks.guide.scope.cardsWithout', {
          count: totalCards - withText,
          n: formatCount(totalCards - withText),
        })

  const windowValue = reset ? (formatIsoDateShort(reset.date, now) ?? reset.date) : t('decks.guide.scope.allTime')
  const windowLine = reset
    ? before === 0
      ? t('decks.guide.scope.noneOlder')
      : t('decks.guide.scope.olderMatches', { count: before, n: formatCount(before) })
    : t('decks.guide.scope.noReset')

  return (
    <Card title={t('decks.guide.scope.title')} subtitle={t('decks.guide.scope.subtitle')}>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile
          label={t('decks.guide.scope.tournamentLists')}
          value={formatCount(classified_decks)}
          detail={listsLine}
        />
        <StatTile label={t('decks.guide.scope.rulesText')} value={`${withText}/${totalCards}`} detail={textLine} />
        <StatTile label={t('decks.guide.scope.fieldSince')} value={windowValue} detail={windowLine} />
      </div>
      {reset && (
        <p className="mt-3 text-caption text-muted">
          <Trans
            i18nKey="decks.guide.scope.resetOn"
            values={{ date: formatIsoDateShort(reset.date, now) ?? reset.date, detectedFrom: reset.detected_from }}
            components={{ strong: <strong className="text-ink2" /> }}
          />
        </p>
      )}
      {guide.gaps.length > 0 && (
        <div className="mt-3">
          <Callout tone="warn">
            {guide.gaps.map((g) => (
              <p key={g}>{g}</p>
            ))}
          </Callout>
        </div>
      )}
    </Card>
  )
}
