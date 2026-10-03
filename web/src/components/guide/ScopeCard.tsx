import type { DeckGuideOut } from '../../api'
import { formatCount, formatIsoDateShort, useNow } from '../../lib/time'
import { Callout, Card, StatTile } from '../ui'

/** A no-break space: a count and the word after it never part. */
const NBSP = '\u00a0'

/** The evidence's own provenance: the record it is drawn from, the
 *  tournament corpus's freshness, how much of the current 75 has rules
 *  text, and the window a detected format reset scopes everything else
 *  to. The page's title already names the deck, so this card's own title
 *  is just "Scope". Every gap `build_deck_guide` found is the server's own
 *  sentence, shown as sent. */
export function ScopeCard({ guide }: { guide: DeckGuideOut }) {
  const now = useNow()
  const { provenance } = guide
  const [withText, totalCards] = provenance.oracle_coverage
  const { deck, reset, matches_before_reset: before, classified_decks, corpus_latest_event } = provenance

  const listsLine = corpus_latest_event
    ? `through ${formatIsoDateShort(corpus_latest_event, now) ?? corpus_latest_event}`
    : undefined

  const textLine =
    withText === totalCards
      ? 'every card'
      : totalCards - withText === 1
        ? `1${NBSP}card without`
        : `${formatCount(totalCards - withText)}${NBSP}cards without`

  const windowValue = reset ? (formatIsoDateShort(reset.date, now) ?? reset.date) : 'All time'
  const windowLine = reset
    ? before === 0
      ? 'none of your matches is older'
      : before === 1
        ? '1 of your matches is older'
        : `${formatCount(before)} of your matches are older`
    : 'no format reset found'

  return (
    <Card title="Scope" subtitle="What this guide is built from.">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile
          label="Record"
          value={`${formatCount(deck.match_wins)}–${formatCount(deck.match_losses)}`}
          detail={deck.matches === 1 ? `1${NBSP}match` : `${formatCount(deck.matches)}${NBSP}matches`}
        />
        <StatTile label="Tournament lists" value={formatCount(classified_decks)} detail={listsLine} />
        <StatTile label="Rules text" value={`${withText}/${totalCards}`} detail={textLine} />
        <StatTile label="Field since" value={windowValue} detail={windowLine} />
      </div>
      {reset && (
        <p className="mt-3 text-caption text-muted">
          Format reset on{' '}
          <strong className="text-ink2">{formatIsoDateShort(reset.date, now) ?? reset.date}</strong>.{' '}
          {reset.detected_from}.
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
