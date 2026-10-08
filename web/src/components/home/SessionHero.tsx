import type { Session, ThirtyDays } from '../../lib/home'
import { sessionHeadline, UNNAMED_DECK } from '../../lib/home'
import type { ArtCard } from '../../lib/matchArt'
import { formatCount, formatLongDay, formatPercent } from '../../lib/time'
import { CardArt, Chip, SectionLabel } from '../ui'

/** The chips name two decks at most; the rest are counted. */
const DECK_CHIPS = 2

/** Home's lead panel: the last session in one line, the 30 days around it,
 *  and the session's decks. Its art is a card the viewer cast in the
 *  session's newest match: at the right with a fade to the left, and on
 *  top with a fade down under 48rem. The words never sit on the picture. */
export function SessionHero({
  session,
  thirty,
  art,
  now,
}: {
  session: Session
  thirty: ThirtyDays
  art: ArtCard | null
  now: number
}) {
  const shown = session.decks.slice(0, DECK_CHIPS)
  const more = session.decks.length - shown.length
  const count = session.matches.length
  return (
    <section className="relative overflow-hidden rounded-hero border border-edge bg-surface shadow-lift [--art-surface:var(--surface-1)]">
      <CardArt grpId={art?.grpId ?? null} name={art?.name ?? null} fade="down" className="h-[170px] md:hidden" />
      <CardArt
        grpId={art?.grpId ?? null}
        name={art?.name ?? null}
        fade="left"
        className="absolute inset-y-0 right-0 hidden w-3/5 md:block"
      />
      <div className="relative flex flex-col justify-end gap-3 px-5 pb-6 md:min-h-[304px] md:max-w-[42%] md:px-9 md:py-8">
        <SectionLabel as="p">Last session · {formatLongDay(session.start, now)}</SectionLabel>
        <h2 className="font-display text-stat text-ink md:text-display">{sessionHeadline(session.tally)}</h2>
        {thirty.outsideSession && (
          <p className="text-lead text-ink2">
            Over the last 30 days you have won <span className="font-semibold text-ink">{formatCount(thirty.won)}</span>{' '}
            of <span className="font-semibold text-ink">{formatCount(thirty.played)}</span> matches, or{' '}
            <span className="font-semibold text-ink">{formatPercent(thirty.won / thirty.played)}%</span>.
          </p>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          {shown.map((deck) => (
            <Chip key={deck.name ?? ''} muted={deck.name == null}>
              {deck.name ?? UNNAMED_DECK}
            </Chip>
          ))}
          {more > 0 && <Chip>and {formatCount(more)} more</Chip>}
          <Chip muted>{count === 1 ? '1 match' : `${formatCount(count)} matches`}</Chip>
        </div>
      </div>
    </section>
  )
}
