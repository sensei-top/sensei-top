import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import type { MtgoNeedsPick } from '../../api'
import { ownScore } from '../../lib/home'
import { formatCount, formatDayTime, parseTimestamp } from '../../lib/time'
import { Card, TextLink } from '../ui'

/** How many matches the card lists before it says how many more wait. */
const SHOWN = 5

/** The MTGO matches the user has not yet said a deck and a format for,
 *  newest first as the route lists them, each the way into the match page
 *  where the pick is made. Hidden when the queue is empty. */
export function NeedsDeckCard({ matches }: { matches: MtgoNeedsPick[] }) {
  const { t } = useTranslation()
  if (matches.length === 0) return null
  const results: Record<string, string> = {
    win: t('home.needsDeck.win'),
    loss: t('home.needsDeck.loss'),
    draw: t('home.needsDeck.draw'),
  }
  const more = matches.length - SHOWN
  return (
    <Card
      title={t('home.needsDeck.title')}
      subtitle={t('home.needsDeck.subtitle')}
    >
      <ul className="divide-y divide-line">
        {matches.slice(0, SHOWN).map((match) => {
          const start = parseTimestamp(match.started_at)
          const result = match.result ? results[match.result] : undefined
          const score = ownScore(match)
          return (
            <li key={match.match_id} className="py-1 first:pt-0 last:pb-0">
              <Link
                to={`/matches/${encodeURIComponent(match.match_id)}`}
                className="-mx-2 flex min-h-[44px] flex-wrap items-center gap-x-3 gap-y-1 rounded-control px-2 py-2 transition-chrome hover:bg-surface3"
              >
                <span className="text-caption text-muted tabular-nums">
                  {start != null ? formatDayTime(start) : ''}
                </span>
                <span className="text-body text-ink">
                  {result && score
                    ? t('home.needsDeck.resultScore', { result, score })
                    : (result ?? score ?? t('home.needsDeck.resultUnknown'))}
                </span>
                {match.opponent_name && (
                  <span className="min-w-0 break-words text-body text-ink2">{t('home.needsDeck.against', { opponent: match.opponent_name })}</span>
                )}
              </Link>
            </li>
          )
        })}
      </ul>
      {more > 0 && <p className="mt-2 text-caption text-muted">{t('home.andMore', { n: formatCount(more) })}</p>}
      {/* Many at once, grouped by the list each fits; one match
          is quicker on its own page. */}
      {matches.length >= 2 && (
        <p className="mt-2">
          <TextLink href="/mtgo/picks" className="inline-flex min-h-[44px] items-center text-body">
            {t('home.needsDeck.reviewAll', { n: formatCount(matches.length) })}
          </TextLink>
        </p>
      )}
    </Card>
  )
}
