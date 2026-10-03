import type { HandCardOut, HandReadOut, RevealedCardOut } from '../api'
import { percent } from '../theme'
import { Card, CardTile, Chip, SectionLabel } from './ui'

const DEGRADED_REASON: Record<string, string> = {
  unclassified: "Opponent's deck hasn't been identified yet — no card-by-card read until it is.",
  no_consensus:
    'The tournament corpus has too few decks of this archetype to estimate specific cards.',
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
      <ul className="mt-1 flex flex-wrap gap-1.5">
        {cards.map((card) => (
          <li key={card.grp_id ?? card.name}>
            <Chip variant={struck ? 'seen' : 'neutral'} emphasis={!struck}>
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
  return (
    <CardTile grpId={card.grp_id} name={card.name} width={TILE_WIDTH}>
      <div className="flex items-center gap-1.5">
        <span>{percent(card.p_in_hand)}</span>
        {card.castable_now && (
          <Chip size="sm" variant="warn">
            Now
          </Chip>
        )}
      </div>
      {!card.tags_known && <div className="text-muted">Text unknown</div>}
    </CardTile>
  )
}

/** "Could be holding", with a line under the row saying what the number
 *  and `Now` mean. Where the cards come from is the server's caveat,
 *  drawn below the list. */
function CouldBeHolding({ cards }: { cards: HandCardOut[] }) {
  if (cards.length === 0) return null
  const rowLine = [
    'The number is the chance the card is in their hand.',
    cards.some((card) => card.castable_now)
      ? 'Now marks an instant they can cast with the mana they have open.'
      : null,
  ]
    .filter((part): part is string => part != null)
    .join(' ')
  return (
    <div className="mb-3">
      <SectionLabel as="h4">Could be holding</SectionLabel>
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
 *  or too thin a corpus for a consensus, the observed facts above still
 *  render — only the estimate list disappears.
 *
 *  `estimate={false}` drops the estimate and everything said about it,
 *  leaving the facts: the ranked-play rule (`table/ranked.py`) keeps the
 *  estimate off the page during a ranked game.
 */
export function OpponentHandCard({
  hand,
  estimate = true,
}: {
  hand: HandReadOut | null | undefined
  estimate?: boolean
}) {
  if (!hand || hand.status === 'no_game') return null

  const knownInHand = hand.known_in_hand ?? []
  const revealedThisMatch = hand.revealed_this_match ?? []
  const interaction = hand.interaction ?? []
  const caveats = hand.caveats ?? []

  const manaPart =
    hand.open_mana == null
      ? null
      : hand.other_mana_sources
        ? `${hand.open_mana} untapped lands +${hand.other_mana_sources} other`
        : `${hand.open_mana} untapped`

  const subtitleParts = [
    hand.hand_size != null ? `${hand.hand_size} cards` : null,
    manaPart,
    hand.held_turns != null && hand.held_turns > 1 ? `held ${hand.held_turns} turns` : null,
  ].filter((part): part is string => part != null)

  return (
    <Card title="Opponent's hand" subtitle={subtitleParts.join(' · ') || undefined} elevation={2}>
      <RevealedChips title="Revealed in hand" cards={knownInHand} struck={false} />
      <RevealedChips title="Shown so far" cards={revealedThisMatch} struck />

      {estimate && (
        <>
          {hand.status !== 'ok' && (
            <p className="text-body text-ink2">
              {DEGRADED_REASON[hand.status] ?? 'No card-by-card read yet.'}
            </p>
          )}

          {hand.status === 'ok' && interaction.length === 0 && (
            <p className="text-body text-ink2">
              Nothing in this archetype's consensus list still looks live — everything expected has
              already shown up.
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
