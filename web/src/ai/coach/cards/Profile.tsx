import { useTranslation } from 'react-i18next'
import type { CoachEvidenceModel } from '../../../api'
import { overallTiles, profileCaption, profileCards } from '../coach'
import { Card, StatTile } from '../../../components/ui'
import { DecksCard } from './DecksCard'
import { PatternsCard } from './PatternsCard'
import { DecksMetCard, FieldRatesCard, RolesAndMulligans } from './RateTables'
import { TurningCard } from './TurningCard'

/** "What these numbers leave out": the server's own sentences, as they
 *  come. */
function LeftOutCard({ gaps }: { gaps: string[] }) {
  const { t } = useTranslation()
  if (gaps.length === 0) return null
  return (
    <Card title={t('coach.profile.leftOut')}>
      <ul className="list-disc space-y-1 pl-5 text-body text-ink2">
        {gaps.map((gap, index) => (
          <li key={index}>{gap}</li>
        ))}
      </ul>
    </Card>
  )
}

/** The body of the "Your numbers" drawer (its heading is the drawer's):
 *  the free, local evidence a report is written from (`GET /api/coach`);
 *  in order, its captions, the six overall tiles, by deck, by role and
 *  mulligans, the decks met, the patterns, where lost games turned, the
 *  field, and what the numbers leave out. `now` places a day's year. */
export function Profile({ evidence, now }: { evidence: CoachEvidenceModel; now: number }) {
  const { t } = useTranslation()
  const cards = new Set(profileCards(evidence, t))
  return (
    <div className="space-y-4">
      <div>
        <p className="text-caption text-muted">{profileCaption(evidence.population, evidence.as_of, now, t)}</p>
        <p className="text-caption text-muted">{t('coach.profile.rangeNote')}</p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {overallTiles(evidence, t).map((tile) => (
          <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} muted={tile.muted} />
        ))}
      </div>
      {cards.has('decks') && <DecksCard decks={evidence.by_deck} />}
      {(cards.has('roles') || cards.has('mulligans')) && (
        <RolesAndMulligans byRole={evidence.by_role} mulligans={evidence.mulligans} />
      )}
      {cards.has('met') && (
        <DecksMetCard matchups={evidence.by_opponent} windowStart={evidence.window_start} now={now} />
      )}
      {cards.has('patterns') && <PatternsCard leaks={evidence.leaks} deckLeaks={evidence.deck_leaks} />}
      {cards.has('turning') && <TurningCard points={evidence.turning_points} />}
      {cards.has('field') && (
        <FieldRatesCard field={evidence.field} latestEvent={evidence.field_latest_event} now={now} />
      )}
      {cards.has('gaps') && <LeftOutCard gaps={evidence.gaps} />}
    </div>
  )
}
