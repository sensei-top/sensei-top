import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { Match } from '../../api'
import type { TFunction } from '../../i18n'
import type { Field, Pattern } from '../../lib/home'
import { opponentNamed, winnerScore } from '../../lib/home'
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

function kickerOf(kind: Exclude<Thing['kind'], 'error'>, t: TFunction): string {
  const kickers: Record<Exclude<Thing['kind'], 'error'>, string> = {
    match: t('home.things.kicker.match'),
    pattern: t('home.things.kicker.pattern'),
    field: t('home.things.kicker.field'),
  }
  return kickers[kind]
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
  const { t } = useTranslation()
  return (
    <div className="grid gap-4 md:grid-cols-3" role="status" aria-label={t('common.loading')}>
      {[0, 1, 2].map((index) => (
        <Skeleton key={index} className="h-[300px] rounded-card" />
      ))}
    </div>
  )
}

function ThingCard({ thing, place, now }: { thing: Exclude<Thing, { kind: 'error' }>; place: number; now: number }) {
  const { t } = useTranslation()
  const words = thingWords(thing, now, t)
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
          <SectionLabel as="p">{kickerOf(thing.kind, t)}</SectionLabel>
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
  t: TFunction,
): { title: string; body: ReactNode; action: string; href: string } {
  switch (thing.kind) {
    case 'match':
      return {
        title: matchTitle(thing.match, t),
        body: <p>{matchBody(thing.match, now, t)}</p>,
        action: t('home.things.readReport'),
        href: `/matches/${encodeURIComponent(thing.match.match_id)}`,
      }
    case 'pattern': {
      const { leak, wonWith, wonWithout } = thing.pattern
      const words = patternWords(leak, t)
      return {
        title: words.title,
        body: (
          <p>
            {t('home.things.patternBody', {
              won: formatCount(wonWith),
              with: formatCount(leak.n_with),
              clause: words.clause,
              wonOther: formatCount(wonWithout),
              without: formatCount(leak.n_without),
            })}
          </p>
        ),
        action: t('home.things.seePatterns'),
        href: '/coach',
      }
    }
    case 'field':
      return {
        title: fieldTitle(thing.field, t),
        body: <FieldBody field={thing.field} now={now} />,
        action: t('home.things.openField'),
        href: '/field',
      }
  }
}

/** "Won 2–1 against {opponent}", the winner's games first; without a game
 *  count, "Won against {opponent}". */
function matchTitle(match: Match, t: TFunction): string {
  const opponent = opponentNamed(match) && match.opponent_label
    ? opponentLabelText(match.opponent_label, match.opponent_colors)
    : t('home.unrecognizedDeck')
  const score = winnerScore(match)
  if (match.result === 'win') {
    return score ? t('home.things.wonScore', { score, opponent }) : t('home.things.won', { opponent })
  }
  if (match.result === 'loss') {
    return score ? t('home.things.lostScore', { score, opponent }) : t('home.things.lost', { opponent })
  }
  return score ? t('home.things.drewScore', { score, opponent }) : t('home.things.drew', { opponent })
}

function matchBody(match: Match, now: number, t: TFunction): string | null {
  const when = ago(match.ended_at ?? match.started_at, now)
  if (when == null) return null
  if (match.deck_id == null) return t('home.things.playedAgo', { when })
  return t('home.things.playedWithAgo', { deck: match.deck_name ?? t('home.unnamedDeckInSentence'), when })
}

function fieldTitle(field: Field, t: TFunction): string {
  const [first, second] = field.rows
  if (second) {
    const share = `${formatPercent(first.presence.share + second.presence.share)}%`
    return t('home.things.fieldTwo', { share, format: field.format })
  }
  return t('home.things.fieldOne', {
    label: first.presence.label,
    share: `${formatPercent(first.presence.share)}%`,
    format: field.format,
  })
}

function FieldBody({ field, now }: { field: Field; now: number }) {
  const { t } = useTranslation()
  const [first, second] = field.rows
  const since = field.reset ? formatIsoDateShort(field.reset, now) : null
  const { played, won } = field.topTwo
  // With one deck in the field the title names it, and the record is
  // against "it"; with two, against "them" (or "either").
  const when = since ? t('home.field.sinceDate', { since }) : t('home.field.last90')
  const tally = t('home.things.tally', { won: formatCount(won), played: formatCount(played) })
  let record: string
  if (field.deck) {
    const deck = field.deck.name ?? t('home.unnamedDeckInSentence')
    if (second) {
      record =
        played > 0
          ? t('home.things.record.pair.deckPlayed', { deck, tally })
          : t('home.things.record.pair.deckNone', { deck, when })
    } else {
      record =
        played > 0
          ? t('home.things.record.single.deckPlayed', { deck, tally })
          : t('home.things.record.single.deckNone', { deck, when })
    }
  } else if (second) {
    record =
      played > 0 ? t('home.things.record.pair.noDeckPlayed', { tally }) : t('home.things.record.pair.noDeckNone', { when })
  } else {
    record =
      played > 0
        ? t('home.things.record.single.noDeckPlayed', { tally })
        : t('home.things.record.single.noDeckNone', { when })
  }
  return (
    <>
      {second && (
        <p>{t('home.things.pair', { first: first.presence.label, second: second.presence.label })}</p>
      )}
      <p>{record}</p>
    </>
  )
}
