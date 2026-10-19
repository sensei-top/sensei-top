import { useTranslation } from 'react-i18next'
import type { HandCardOut, HandReadOut, RevealedCardOut } from '../api'
import type { TFunction } from '../i18n'
import { formatPercent, timesPhrase } from '../lib/format'
import { Card, CardTile, Chip, SectionLabel } from './ui'

/** Why there is no card-by-card estimate, by the read's status. */
function degradedReason(status: string, t: TFunction): string {
  switch (status) {
    case 'unclassified':
      return t('live.opponentHand.unclassified')
    case 'no_consensus':
      return t('live.opponentHand.noConsensus')
    case 'format_unknown':
      return t('live.opponentHand.formatUnknown')
    default:
      return t('live.opponentHand.noReadYet')
  }
}

function RevealedChips({
  title,
  cards,
  struck,
}: {
  title: string
  cards: RevealedCardOut[]
  struck: boolean
}) {
  if (cards.length === 0) return null
  return (
    <div className="mb-3">
      <SectionLabel as="h4">{title}</SectionLabel>
      <ul className={`mt-1 flex flex-wrap ${struck ? 'gap-1' : 'gap-1.5'}`}>
        {cards.map((card) => (
          <li key={card.grp_id ?? card.name}>
            <Chip variant={struck ? 'seen' : 'neutral'} size={struck ? 'sm' : 'md'} emphasis={!struck}>
              {card.name}
            </Chip>
          </li>
        ))}
      </ul>
    </div>
  )
}

const TILE_WIDTH = 110

/** A card the field's list says they could be holding: the chance it is in
 *  their hand under the picture, then `Now` when it is an instant they can
 *  cast with the mana they have open. A null grpId here means a named
 *  consensus card with no picture on file, not a hidden card, so `CardTile`
 *  draws its name in the card's shape. */
function HandCardTile({ card }: { card: HandCardOut }) {
  const { t } = useTranslation()
  return (
    <CardTile grpId={card.grp_id} name={card.name} width={TILE_WIDTH}>
      <div className="flex items-center gap-1.5">
        <span>{formatPercent(card.p_in_hand)}</span>
        {card.castable_now && (
          <Chip size="sm" variant="warn">
            {t('live.opponentHand.now')}
          </Chip>
        )}
      </div>
      {!card.tags_known && <div className="text-muted">{t('live.textUnknown')}</div>}
    </CardTile>
  )
}

/** "Could be holding", with a line under the row saying what the number
 *  and `Now` mean. Where the cards come from is the server's caveat,
 *  drawn below the list. */
function CouldBeHolding({ cards }: { cards: HandCardOut[] }) {
  const { t } = useTranslation()
  if (cards.length === 0) return null
  const rowLine = [
    t('live.opponentHand.chanceInHand'),
    cards.some((card) => card.castable_now)
      ? t('live.opponentHand.nowNote')
      : null,
  ]
    .filter((part): part is string => part != null)
    .join(' ')
  return (
    <div className="mb-3">
      <SectionLabel as="h4">{t('live.opponentHand.couldBeHolding')}</SectionLabel>
      <div className="mt-1.5 flex flex-wrap items-start gap-2">
        {cards.map((card) => (
          <HandCardTile key={`${card.grp_id ?? 'unk'}-${card.name}`} card={card} />
        ))}
      </div>
      <p className="mt-1 text-caption text-muted">{rowLine}</p>
    </div>
  )
}

/** What's actually known about the opponent's hand right now, with the
 *  field's consensus estimate demoted below it rather than sharing top
 *  billing (`table/hand_read.py`). Facts first: hand size, open mana, how
 *  long they've sat on this hand, and every card they've genuinely shown —
 *  all real, all free. Only below that does a short, clearly-speculative
 *  "Could be holding" list appear, capped at 5 and ranked by expected
 *  copies rather than raw probability (a 3-or-4-of and a 1-of used to
 *  cluster to similar-looking percentages once the opponent's hidden pool
 *  got large, which read as noise). The old "Still in their deck" list is
 *  gone: a full-deck-minus-seen guess at cards not even in hand yet was the
 *  least trustworthy number on the tab, and the field's own basics used to
 *  outrank its real spells there before lands were filtered out entirely.
 *
 *  Degrades in stages rather than going blank: with no archetype resolved,
 *  an unknown format, or too thin a corpus for a consensus, the observed
 *  facts above still render — only the estimate list disappears.
 *
 *  `mulligans` is this game's count for the opponent, said in the subtitle
 *  when they took one; the keep guide said it before the first turn.
 *
 *  `estimate={false}` drops the estimate and everything said about it,
 *  leaving the facts: the event rule (`table/queues.py`) keeps the
 *  estimate off the page during an event's game, and the user's switch in
 *  Settings anywhere.
 */
export function OpponentHandCard({
  hand,
  mulligans,
  estimate = true,
}: {
  hand: HandReadOut | null | undefined
  mulligans?: number | null
  estimate?: boolean
}) {
  const { t } = useTranslation()
  if (!hand || hand.status === 'no_game') return null

  const knownInHand = hand.known_in_hand ?? []
  const revealedThisMatch = hand.revealed_this_match ?? []
  const interaction = hand.interaction ?? []
  const caveats = hand.caveats ?? []

  const manaPart =
    hand.open_mana == null
      ? null
      : hand.other_mana_sources
        ? t('live.opponentHand.untappedLands', { open: hand.open_mana, other: hand.other_mana_sources })
        : t('live.opponentHand.untapped', { open: hand.open_mana })

  const subtitleParts = [
    hand.hand_size != null ? t('live.opponentHand.cards', { count: hand.hand_size }) : null,
    manaPart,
    hand.held_turns != null && hand.held_turns > 1
      ? t('live.opponentHand.held', { count: hand.held_turns })
      : null,
    mulligans ? t('live.opponentHand.mulliganed', { times: timesPhrase(mulligans, t) }) : null,
  ].filter((part): part is string => part != null)

  return (
    <Card title={t('live.opponentHand.title')} subtitle={subtitleParts.join(' · ') || undefined} elevation={2}>
      <RevealedChips title={t('live.opponentHand.revealedInHand')} cards={knownInHand} struck={false} />
      <RevealedChips title={t('live.opponentHand.shownSoFar')} cards={revealedThisMatch} struck />

      {estimate && (
        <>
          {hand.status !== 'ok' && (
            <p className="text-body text-ink2">
              {degradedReason(hand.status, t)}
            </p>
          )}

          {hand.status === 'ok' && interaction.length === 0 && (
            <p className="text-body text-ink2">
              {t('live.opponentHand.nothingLive')}
            </p>
          )}

          <CouldBeHolding cards={interaction} />

          {caveats.length > 0 && (
            <p className="mt-2 border-t border-edge pt-2 text-caption text-muted">{caveats[0]}</p>
          )}
        </>
      )}
    </Card>
  )
}
