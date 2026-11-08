import { Trans, useTranslation } from 'react-i18next'
import type { DeckGuideOut } from '../../api'
import type { FirstData } from '../../bridge'
import { formatCount, formatIsoDateShort, useNow } from '../../lib/time'
import { cardDataPercent, useCardData } from '../../shell/cardData'
import { Callout, Card, StatTile, TextLink } from '../ui'

/** The gaps whose fix is the card-data download (`gap_codes`). */
const CARD_DATA_GAPS = ['rules_text_missing', 'legality_missing']

/** The gaps as lines. The card-data gaps (`gap_codes`) are one line, at the
 *  first's place: waiting while the download runs, else a link to Settings →
 *  Sources; in a browser (`state` null) each stays the server's sentence. */
export function GapLines({
  gaps,
  codes,
  state,
}: {
  gaps: string[]
  codes: (string | null)[] | undefined
  state: FirstData | null
}) {
  const { t } = useTranslation()
  const isCardData = (i: number) => state !== null && CARD_DATA_GAPS.includes(codes?.[i] ?? '')
  const first = gaps.findIndex((_, i) => isCardData(i))
  return (
    <>
      {gaps.map((g, i) => {
        if (!isCardData(i)) return <p key={g}>{g}</p>
        if (i !== first || state === null) return null
        if (state.state === 'running') {
          const pct = cardDataPercent(state.progress)
          return <p key={g}>{pct === null ? t('decks.guide.scope.waits') : t('decks.guide.scope.waitsPercent', { pct })}</p>
        }
        return (
          <p key={g}>
            <TextLink href="/settings/sources">{t('decks.guide.scope.download')}</TextLink>
          </p>
        )
      })}
    </>
  )
}

/** The evidence's own provenance: the tournament corpus's freshness, how
 *  much of the current 75 has rules text, and the window a detected format
 *  reset scopes everything else to. The deck's record is the strip's over
 *  the tabs, not this card's. The page's title already names the deck, so
 *  this card's own title is just "Scope". Every gap `build_deck_guide` found is the server's own
 *  sentence, shown as sent, except the two card-data gaps (`GapLines`). */
export function ScopeCard({ guide }: { guide: DeckGuideOut }) {
  const { t } = useTranslation()
  const now = useNow()
  const cardData = useCardData()
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
            <GapLines gaps={guide.gaps} codes={guide.gap_codes} state={cardData} />
          </Callout>
        </div>
      )}
    </Card>
  )
}
