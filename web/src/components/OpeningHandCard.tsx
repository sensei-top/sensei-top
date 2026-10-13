import { useTranslation } from 'react-i18next'
import type { OpeningHandCardOut, OpeningHandOut } from '../api'
import type { TFunction } from '../i18n'
import { Card, CardTile } from './ui'

/** The verdict's headline word; a verdict this table does not know reads
 *  as nothing, as it always has. */
function verdictLabel(verdict: string, t: TFunction): string | undefined {
  switch (verdict) {
    case 'keep':
      return t('live.hand.verdict.keep')
    case 'mulligan':
      return t('live.hand.verdict.mulligan')
    case 'marginal':
      return t('live.hand.verdict.marginal')
    default:
      return undefined
  }
}

const TILE_WIDTH = 110

/** Whether the card's own cost reduction reaches it sooner than its printed
 *  cost. `reduced_castable_turn` only ever helps (it never overwrites
 *  `castable_turn`, see table/opening_hand.py), so the caption says
 *  "reduced" exactly when it reaches earlier than the printed cost alone
 *  would, whether that cost was reachable at all or not. */
function reducedEarlier(card: OpeningHandCardOut): boolean {
  return (
    card.reduced_castable_turn != null &&
    (card.castable_turn == null || card.reduced_castable_turn < card.castable_turn)
  )
}

/** The caption's first line: the earliest turn this hand's own lands cast
 *  the card, or nothing for a land, whose space stays so the pictures keep
 *  one line. */
function turnCaption(card: OpeningHandCardOut, t: TFunction): string | null {
  if (card.is_land) return null
  if (reducedEarlier(card)) return t('live.hand.turnReduced', { n: card.reduced_castable_turn })
  return card.castable_turn != null ? t('live.hand.turn', { n: card.castable_turn }) : t('live.hand.noTurn')
}

function OpeningHandTile({ card }: { card: OpeningHandCardOut }) {
  const { t } = useTranslation()
  const name = card.name ?? t('live.hand.cardId', { id: card.grp_id })
  const turn = turnCaption(card, t)
  // Our own dealt hand is never hidden from us, so grpId is always known
  // here: this tile always draws the card's picture.
  return (
    <CardTile grpId={card.grp_id} name={name} width={TILE_WIDTH}>
      {turn && <div>{turn}</div>}
      {!card.tags_known && <div className="text-muted">{t('live.textUnknown')}</div>}
    </CardTile>
  )
}

function mulliganRecordLine(hand: OpeningHandOut, t: TFunction): string | null {
  const record = (hand.mulligan_record ?? []).find((r) => r.mulligans === hand.mulligan_count)
  if (!record || record.games === 0) return null
  const label =
    hand.mulligan_count === 0
      ? t('live.hand.keeping7')
      : t('live.hand.mull', { n: hand.mulligan_count })
  return t('live.hand.deckRecord', { wins: record.wins, losses: record.games - record.wins, label })
}

/** The hand actually dealt, read from the log before the keep/mulligan
 *  decision (`table/opening_hand.py`) — the one card on this tab that has
 *  to be readable in the ~5 seconds a real decision window measures at
 *  (median, across a real capture). A verdict headline first, in a plain
 *  color: this app's palette assigns color by entity (self/opponent/field),
 *  not by good/bad, so the word itself — Keep / Mulligan / Marginal — is
 *  what carries the call, backed by the evidence line beneath it. Withheld
 *  (no headline word) rather than guessed whenever an input is unknown; the
 *  gap that caused it becomes the headline instead, never silently dropped.
 */
export function OpeningHandCard({ hand }: { hand: OpeningHandOut | null | undefined }) {
  const { t } = useTranslation()
  if (!hand) return null

  const cards = hand.cards ?? []
  const reasons = hand.reasons ?? []
  const caveats = hand.caveats ?? []

  // The backend appends at most one gap-explaining caveat when verdict is
  // null, always last (the mulligan reminder, if any, is always prepended
  // first) — see table/opening_hand.py's _verdict. Surfaced as the headline
  // instead of a fabricated call, and not repeated below.
  const gapCaveat = hand.verdict == null ? (caveats.at(-1) ?? null) : null
  const headline = hand.verdict ? verdictLabel(hand.verdict, t) : (gapCaveat ?? t('live.hand.noRead'))
  const caveatsToShow = caveats.filter((c) => c !== gapCaveat)

  // The line under the row says once what the captions mean.
  const rowLine = [
    cards.some((card) => !card.is_land)
      ? t('live.hand.earliest')
      : null,
    cards.some((card) => !card.is_land && reducedEarlier(card))
      ? t('live.hand.reducedNote')
      : null,
  ]
    .filter((part): part is string => part != null)
    .join(' ')

  const context = [
    t('live.hand.lands', { count: hand.land_count }),
    hand.land_min != null && hand.land_max != null
      ? t('live.hand.band', { min: hand.land_min, max: hand.land_max })
      : null,
    hand.on_the_play == null
      ? null
      : hand.on_the_play
        ? t('live.onPlay')
        : t('live.onDraw'),
    hand.mulligan_count > 0 ? t('live.hand.mulligan', { n: hand.mulligan_count }) : null,
    mulliganRecordLine(hand, t),
  ]
    .filter((part): part is string => part != null)
    .join(' · ')

  return (
    <Card>
      <p
        className={`font-display text-ink ${
          hand.verdict ? 'text-hero' : 'text-heading'
        }`}
      >
        {headline}
      </p>
      {reasons.length > 0 && <p className="mt-1 text-body text-ink2">{reasons.join(' · ')}</p>}
      {context && <p className="mt-1 text-caption text-muted">{context}</p>}

      <div className="mt-4 flex flex-wrap items-start gap-2">
        {cards.map((card, i) => (
          <OpeningHandTile key={`${card.grp_id}-${i}`} card={card} />
        ))}
      </div>
      {rowLine && <p className="mt-1 text-caption text-muted">{rowLine}</p>}

      {caveatsToShow.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-edge pt-2">
          {caveatsToShow.map((c) => (
            <p key={c} className="text-caption text-muted">
              {c}
            </p>
          ))}
        </div>
      )}
    </Card>
  )
}
