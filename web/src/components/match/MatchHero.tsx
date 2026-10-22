import { Play } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { MatchDetail } from '../../api'
import type { TFunction } from '../../i18n'
import { eventLabel, resultWord } from '../../lib/events'
import { formatRecord } from '../../lib/format'
import type { ArtCard } from '../../lib/matchArt'
import { when } from '../../lib/time'
import { OpponentDeckLabel } from '../OpponentDeckLabel'
import { Button, CardArt, SectionLabel } from '../ui'

/** The match's result and its games' count, the viewer's first; with no
 *  result known, that alone. */
function resultTitle(match: MatchDetail, t: TFunction): string {
  const word = resultWord(match.result, t)
  if (!word) return t('matches.result.unknown')
  return t('matches.hero.resultScore', { word, score: formatRecord(match.games_won ?? 0, match.games_lost ?? 0) })
}

/** The report's lead panel: what the page is, the event and when; the
 *  report's headline and the line under it, or, until the report has
 *  arrived or when it has nothing, the result and the games' count; the
 *  two decks, the opponent's with its correction; and the way to the
 *  replay. Its art is a card the opponent cast, or the viewer's when the
 *  opponent cast nothing: at the right with a fade to the left, and on
 *  top with a fade down under 48rem. The words never sit on the picture.
 *  With no card to show there is no box, and the words take the width. */
export function MatchHero({
  match,
  headline,
  subhead,
  art,
  replayHref,
}: {
  match: MatchDetail
  /** The report's, or `null` while there is none to show. */
  headline: string | null
  subhead: string | null
  art: ArtCard | null
  replayHref: string
}) {
  const { t } = useTranslation()
  const event = eventLabel(match.event_id, t)
  const label = [t('matches.hero.kicker'), event, when(match.started_at)].filter(Boolean).join(' · ')
  return (
    <section className="relative overflow-hidden rounded-hero border border-edge bg-surface shadow-lift [--art-surface:var(--surface-1)]">
      {art && (
        <>
          <CardArt grpId={art.grpId} name={art.name} fade="down" className="h-[140px] md:hidden" />
          <CardArt
            grpId={art.grpId}
            name={art.name}
            fade="left"
            className="absolute inset-y-0 right-0 hidden w-1/2 md:block"
          />
        </>
      )}
      <div
        className={`relative flex flex-col justify-end gap-3 px-5 pb-6 md:px-9 md:py-8 ${
          art ? 'md:min-h-[280px] md:max-w-[55%]' : 'pt-6'
        }`}
      >
        <SectionLabel as="p">{label}</SectionLabel>
        <h2 className="font-display text-heading text-ink md:text-stat">{headline ?? resultTitle(match, t)}</h2>
        {headline != null && subhead && <p className="text-lead text-ink2">{subhead}</p>}
        <dl className="flex flex-wrap gap-x-8 gap-y-3 pt-1">
          {match.deck_id != null && (
            <div className="min-w-0">
              <SectionLabel as="dt">{t('matches.you')}</SectionLabel>
              <dd className={`mt-1 text-body break-words ${match.deck_name ? 'text-ink' : 'text-muted'}`}>
                {match.deck_name ?? t('common.unnamedDeck')}
              </dd>
            </div>
          )}
          <div className="min-w-0">
            <SectionLabel as="dt">{t('matches.opponent')}</SectionLabel>
            <dd className="mt-1 text-body text-ink">
              <OpponentDeckLabel match={match} />
            </dd>
          </div>
        </dl>
        <Button href={replayHref} className="mt-1 self-start">
          <Play size={16} strokeWidth={2} aria-hidden />
          {t('matches.hero.replay')}
        </Button>
      </div>
    </section>
  )
}
