import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { Match } from '../../api'
import type { TFunction } from '../../i18n'
import type { DeckSlot, Field, NextStep, Pattern } from '../../lib/home'
import { opponentNamed, ownScore } from '../../lib/home'
import { deckAddress } from '../../lib/decks'
import { pairingAddress } from '../../lib/pairing'
import type { ArtCard } from '../../lib/matchArt'
import { opponentLabelText } from '../../lib/opponent'
import { patternWords } from '../../lib/patterns'
import { formatPercent, formatRecord } from '../../lib/format'
import { useAiFeatures } from '../../shell/aiFeatures'
import { ago } from '../../lib/time'
import { Button, CardArt, ErrorNote, SectionLabel, Skeleton } from '../ui'

/** One of Home's three cards, the failure of the request one needed, or a
 *  slot whose request has not answered. */
export type Thing =
  | { kind: 'match'; match: Match; art: ArtCard | null }
  | { kind: 'pattern'; pattern: Pattern; art: ArtCard | null }
  | { kind: 'field'; field: Field; art: ArtCard | null }
  | { kind: 'deck'; deck: DeckSlot; art: ArtCard | null }
  | { kind: 'next'; next: NextStep }
  | { kind: 'error'; key: string; error: Error }
  | { kind: 'pending'; slot: 'pattern' | 'field' | 'deck' }

type Drawn = Exclude<Thing, { kind: 'error' | 'pending' }>

function kickerOf(kind: Drawn['kind'], t: TFunction): string {
  const kickers: Record<Drawn['kind'], string> = {
    match: t('home.things.kicker.match'),
    pattern: t('home.things.kicker.pattern'),
    field: t('home.things.kicker.field'),
    deck: t('home.things.kicker.deck'),
    next: t('home.things.kicker.next'),
  }
  return kickers[kind]
}

/** Home's three things worth a look (`lib/home.ts`'s `homeSlots` picks
 *  them), each carrying its place among them in an accent disc. The art
 *  is on top with a fade down; the words stay under it. The action is a
 *  button rather than the whole card, since the art has a control of its
 *  own. With AI features off the pattern card stays, since the
 *  pattern is a core read, but loses its button, which opens the coach. */
export function ThreeThings({ things, now }: { things: Thing[]; now: number }) {
  if (things.length === 0) return null
  return (
    <ol className="grid gap-4 md:grid-cols-3">
      {things.map((thing, index) => (
        <li key={thing.kind === 'error' ? thing.key : thing.kind === 'pending' ? thing.slot : thing.kind} className="min-w-0">
          {thing.kind === 'error' ? (
            <ErrorNote error={thing.error} />
          ) : thing.kind === 'pending' ? (
            <PendingCard slot={thing.slot} place={index + 1} />
          ) : (
            <ThingCard thing={thing} place={index + 1} now={now} />
          )}
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

function PendingCard({ slot, place }: { slot: 'pattern' | 'field' | 'deck'; place: number }) {
  const { t } = useTranslation()
  const loading: Record<'pattern' | 'field' | 'deck', string> = {
    pattern: t('home.things.loading.pattern'),
    deck: t('home.things.loading.deck'),
    field: t('home.things.loading.field'),
  }
  return (
    <section
      className="flex h-full min-h-[300px] flex-col overflow-hidden rounded-card border border-edge bg-surface shadow-lift"
      role="status"
      aria-label={t('common.loading')}
    >
      <Skeleton className="h-[104px] rounded-none md:h-[124px]" />
      <div className="flex flex-1 flex-col gap-2 px-5 pt-4 pb-5">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="flex size-6 shrink-0 items-center justify-center rounded-pill bg-accent font-display text-caption font-extrabold text-on-accent"
          >
            {place}
          </span>
          <SectionLabel as="p">{kickerOf(slot, t)}</SectionLabel>
        </div>
        <p className="text-body text-ink2">{loading[slot]}</p>
        <Skeleton className="h-4 w-3/4" />
      </div>
    </section>
  )
}

function ThingCard({ thing, place, now }: { thing: Drawn; place: number; now: number }) {
  const { t } = useTranslation()
  const [aiOn] = useAiFeatures()
  const words = thingWords(thing, now, t)
  // "Next step" has no card to show: the art's wash.
  const art = thing.kind === 'next' ? null : thing.art
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
        {words.href != null && (aiOn || thing.kind !== 'pattern') && (
          <div className="pt-2">
            <Button href={words.href}>{words.action}</Button>
          </div>
        )}
      </div>
    </section>
  )
}

function thingWords(
  thing: Drawn,
  now: number,
  t: TFunction,
): { title: string; body: ReactNode; action: string; href: string | null } {
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
              recordWith: formatRecord(wonWith, leak.n_with - wonWith),
              clause: words.clause,
              recordWithout: formatRecord(wonWithout, leak.n_without - wonWithout),
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
        body: <FieldBody field={thing.field} />,
        action: t('home.things.openField'),
        href: '/field',
      }
    case 'deck':
      return deckWords(thing.deck, now, t)
    case 'next':
      return nextWords(thing.next, t)
  }
}

function deckWords(
  deck: DeckSlot,
  now: number,
  t: TFunction,
): { title: string; body: ReactNode; action: string; href: string } {
  const title = t('home.things.deckTitle', {
    deck: deck.name ?? t('home.unnamedDeckInSentence'),
    record: formatRecord(deck.wins, deck.losses),
  })
  if (deck.unmet) {
    return {
      title,
      body: <p>{t('home.things.deckUnmet', { archetype: deck.unmet.label, format: deck.unmet.format })}</p>,
      action: t('home.things.openMatchup'),
      href: pairingAddress(deck.key, deck.unmet.archetypeKey, deck.unmet.format),
    }
  }
  const when = ago(deck.lastAt, now)
  return {
    title,
    body: when == null ? null : <p>{t('home.things.deckPlayed', { count: deck.played, when })}</p>,
    action: t('home.things.openDeck'),
    href: deckAddress(deck.key),
  }
}

function nextWords(
  next: NextStep,
  t: TFunction,
): { title: string; body: ReactNode; action: string; href: string | null } {
  switch (next.kind) {
    case 'cardData':
      return {
        title: t('home.things.next.cardData.title'),
        body: <p>{t('home.things.next.cardData.body')}</p>,
        action: t('home.things.next.openSources'),
        href: '/settings/sources',
      }
    case 'cardDataRunning':
      return {
        title: t('home.things.next.cardDataRunning.title'),
        body: <p>{t('home.things.next.cardDataRunning.body')}</p>,
        action: t('home.things.next.openSources'),
        href: '/settings/sources',
      }
    case 'secondWeek':
      return {
        title: t('home.things.next.secondWeek.title'),
        body: <p>{t('home.things.next.secondWeek.body')}</p>,
        action: '',
        href: null,
      }
    case 'patterns':
      return {
        title: t('home.things.next.patterns.title'),
        body: <p>{t('home.things.next.patterns.body', { count: next.count })}</p>,
        action: '',
        href: null,
      }
  }
}

/** "Lost 1–2 to {opponent}", the viewer's games first; without a game
 *  count, "Lost to {opponent}". */
function matchTitle(match: Match, t: TFunction): string {
  const opponent = opponentNamed(match) && match.opponent_label
    ? opponentLabelText(match.opponent_label, match.opponent_colors)
    : t('home.unrecognizedDeck')
  const score = ownScore(match)
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
    const share = formatPercent(first.presence.share + second.presence.share)
    return t('home.things.fieldTwo', { share, format: field.format })
  }
  return t('home.things.fieldOne', {
    label: first.presence.label,
    share: formatPercent(first.presence.share),
    format: field.format,
  })
}

function FieldBody({ field }: { field: Field }) {
  const { t } = useTranslation()
  const [first, second] = field.rows
  const { played, won, losses } = field.topTwo
  // With one deck in the field the title names it, and the record is
  // against "it"; with two, against "them" (or "either").
  const when = t('home.field.lastDays', { days: field.days })
  const score = formatRecord(won, losses)
  let record: string
  if (field.deck) {
    const deck = field.deck.name ?? t('home.unnamedDeckInSentence')
    if (second) {
      record =
        played > 0
          ? t('home.things.record.pair.deckPlayed', { deck, record: score })
          : t('home.things.record.pair.deckNone', { deck, when })
    } else {
      record =
        played > 0
          ? t('home.things.record.single.deckPlayed', { deck, record: score })
          : t('home.things.record.single.deckNone', { deck, when })
    }
  } else if (second) {
    record =
      played > 0 ? t('home.things.record.pair.noDeckPlayed', { record: score }) : t('home.things.record.pair.noDeckNone', { when })
  } else {
    record =
      played > 0
        ? t('home.things.record.single.noDeckPlayed', { record: score })
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
