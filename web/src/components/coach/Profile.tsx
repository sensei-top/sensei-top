import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import type { CoachEvidenceModel } from '../../api'
import { overallTiles, profileCaption } from '../../lib/coach'
import { Card, StatTile } from '../ui'
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

/** "Your numbers", the profile under the report: the free, local evidence
 *  a report is written from (`GET /api/coach`). A section labelled by its
 *  heading; in order, the six overall tiles, by deck, by role and
 *  mulligans, the decks met, the patterns, where lost games turned, the
 *  field, and what the numbers leave out. `now` places a day's year. */
export function Profile({ evidence, now }: { evidence: CoachEvidenceModel; now: number }) {
  const { t } = useTranslation()
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="space-y-4">
      <div>
        <h2 id={headingId} className="font-display text-heading text-ink">
          {t('coach.profile.title')}
        </h2>
        <p className="text-caption text-muted">{profileCaption(evidence.population, evidence.as_of, now, t)}</p>
        <p className="text-caption text-muted">{t('coach.profile.rangeNote')}</p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {overallTiles(evidence, t).map((tile) => (
          <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
        ))}
      </div>
      <DecksCard decks={evidence.by_deck} />
      <RolesAndMulligans byRole={evidence.by_role} mulligans={evidence.mulligans} />
      <DecksMetCard matchups={evidence.by_opponent} windowStart={evidence.window_start} now={now} />
      <PatternsCard leaks={evidence.leaks} deckLeaks={evidence.deck_leaks} />
      <TurningCard points={evidence.turning_points} />
      <FieldRatesCard field={evidence.field} latestEvent={evidence.field_latest_event} now={now} />
      <LeftOutCard gaps={evidence.gaps} />
    </section>
  )
}
