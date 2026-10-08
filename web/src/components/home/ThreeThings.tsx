import type { ReactNode } from 'react'
import type { Match } from '../../api'
import type { Field, Pattern } from '../../lib/home'
import { opponentNamed, UNNAMED_DECK_IN_SENTENCE, winnerScore } from '../../lib/home'
import type { ArtCard } from '../../lib/matchArt'
import { opponentLabelText } from '../../lib/opponent'
import { patternWords } from '../../lib/patterns'
import { ago, formatCount, formatIsoDateShort, formatPercent } from '../../lib/time'
import { Button, CardArt, ErrorNote, SectionLabel, Skeleton } from '../ui'

/** One of Home's three cards, or the failure of the request one needed. */
export type Thing =
  | { kind: 'match'; match: Match; art: ArtCard | null }
  | { kind: 'pattern'; pattern: Pattern; art: ArtCard | null }
  | { kind: 'field'; field: Field; art: ArtCard | null }
  | { kind: 'error'; key: string; error: Error }

const KICKER: Record<Exclude<Thing['kind'], 'error'>, string> = {
  match: 'Last match',
  pattern: 'Pattern',
  field: 'Field',
}

/** Home's three things worth a look (`lib/home.ts`'s `threeThings` picks
 *  them), each carrying its place among them in an accent disc. The art
 *  is on top with a fade down; the words stay under it. The action is a
 *  button rather than the whole card, since the art has a control of its
 *  own. */
export function ThreeThings({ things, now }: { things: Thing[]; now: number }) {
  if (things.length === 0) return null
  return (
    <ol className="grid gap-4 md:grid-cols-3">
      {things.map((thing, index) => (
        <li key={thing.kind === 'error' ? thing.key : thing.kind} className="min-w-0">
          {thing.kind === 'error' ? <ErrorNote error={thing.error} /> : <ThingCard thing={thing} place={index + 1} now={now} />}
        </li>
      ))}
    </ol>
  )
}

/** Three cards' outline while the requests they need are on their way. */
export function ThreeThingsLoading() {
  return (
    <div className="grid gap-4 md:grid-cols-3" role="status" aria-label="Loading">
      {[0, 1, 2].map((index) => (
        <Skeleton key={index} className="h-[300px] rounded-card" />
      ))}
    </div>
  )
}

function ThingCard({ thing, place, now }: { thing: Exclude<Thing, { kind: 'error' }>; place: number; now: number }) {
  const words = thingWords(thing, now)
  const art = thing.art
  return (
    <section className="flex h-full flex-col overflow-hidden rounded-card border border-edge bg-surface shadow-lift [--art-surface:var(--surface-1)]">
      <CardArt grpId={art?.grpId ?? null} name={art?.name ?? null} fade="down" className="h-[104px] md:h-[124px]" />
      <div className="flex flex-1 flex-col gap-2 px-5 pt-4 pb-5">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="flex size-6 shrink-0 items-center justify-center rounded-pill bg-accent font-display text-caption font-extrabold text-on-accent"
          >
            {place}
          </span>
          <SectionLabel as="p">{KICKER[thing.kind]}</SectionLabel>
        </div>
        <h2 className="font-display text-title text-ink">{words.title}</h2>
        <div className="flex-1 space-y-1.5 text-body text-ink2">{words.body}</div>
        <div className="pt-2">
          <Button href={words.href}>{words.action}</Button>
        </div>
      </div>
    </section>
  )
}

function thingWords(
  thing: Exclude<Thing, { kind: 'error' }>,
  now: number,
): { title: string; body: ReactNode; action: string; href: string } {
  switch (thing.kind) {
    case 'match':
      return {
        title: matchTitle(thing.match),
        body: <p>{matchBody(thing.match, now)}</p>,
        action: 'Read the report',
        href: `/matches/${encodeURIComponent(thing.match.match_id)}`,
      }
    case 'pattern': {
      const { leak, wonWith, wonWithout } = thing.pattern
      const words = patternWords(leak)
      return {
        title: words.title,
        body: (
          <p>
            You won {formatCount(wonWith)} of the {formatCount(leak.n_with)} matches {words.clause}, and{' '}
            {formatCount(wonWithout)} of the other {formatCount(leak.n_without)}.
          </p>
        ),
        action: 'See every pattern',
        href: '/coach',
      }
    }
    case 'field':
      return {
        title: fieldTitle(thing.field),
        body: <FieldBody field={thing.field} now={now} />,
        action: 'Open the field',
        href: '/field',
      }
  }
}

/** "Won 2–1 against {opponent}", the winner's games first; without a game
 *  count, "Won against {opponent}". */
function matchTitle(match: Match): string {
  const opponent = opponentNamed(match) && match.opponent_label
    ? opponentLabelText(match.opponent_label, match.opponent_colors)
    : 'an unrecognized deck'
  const score = winnerScore(match)
  if (match.result === 'win') return score ? `Won ${score} against ${opponent}` : `Won against ${opponent}`
  if (match.result === 'loss') return score ? `Lost ${score} to ${opponent}` : `Lost to ${opponent}`
  return score ? `Drew ${score} with ${opponent}` : `Drew with ${opponent}`
}

function matchBody(match: Match, now: number): string | null {
  const when = ago(match.ended_at ?? match.started_at, now)
  if (when == null) return null
  if (match.deck_id == null) return `Played ${when}.`
  return `Played with ${match.deck_name ?? UNNAMED_DECK_IN_SENTENCE}, ${when}.`
}

function fieldTitle(field: Field): string {
  const [first, second] = field.rows
  if (second) return `Two decks are ${formatPercent(first.presence.share + second.presence.share)}% of the ${field.format} field`
  return `${first.presence.label} is ${formatPercent(first.presence.share)}% of the ${field.format} field`
}

function FieldBody({ field, now }: { field: Field; now: number }) {
  const [first, second] = field.rows
  const since = field.reset ? formatIsoDateShort(field.reset, now) : null
  const { played, won } = field.topTwo
  // With one deck in the field the title names it, and the record is
  // against "it"; with two, against "them" (or "either").
  const them = second ? 'them' : 'it'
  const either = second ? 'either' : 'it'
  const when = since ? `since ${since}` : 'in the last 90 days'
  const tally = `${formatCount(won)} of ${formatCount(played)}`
  let record: string
  if (field.deck) {
    const deck = field.deck.name ?? UNNAMED_DECK_IN_SENTENCE
    record =
      played > 0
        ? `With ${deck} you have won ${tally} against ${them}.`
        : `You have not played ${deck} against ${either} ${when}.`
  } else {
    record = played > 0 ? `You have won ${tally} against ${them}.` : `You have not played against ${them} ${when}.`
  }
  return (
    <>
      {second && (
        <p>
          {first.presence.label} and {second.presence.label}.
        </p>
      )}
      <p>{record}</p>
    </>
  )
}
