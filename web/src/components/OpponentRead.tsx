import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useOpponentDeckCandidates, useSetOpponentDeck } from '../api'
import type { CurrentMatch, OpponentDeckCandidate } from '../api'
import { formatList, formatPercent } from '../lib/format'
import { DeckPicker } from './OpponentDeckLabel'
import { Button, Card, Disclosure, Meter } from './ui'

// Enough to show real disagreement without turning into the full candidate
// list — rank_candidates() already orders these best-fit first.
const SHORTLIST_SIZE = 3

function unclearDetail(match: CurrentMatch): string | null {
  if (match.opponent_source === 'manual') return null
  if (
    match.opponent_source === 'archetype' ||
    match.opponent_source === 'fallback' ||
    match.opponent_source === 'corpus'
  ) {
    return null
  }
  // Genuinely unnamed: say more than "Unknown deck" when there is more to
  // say — the real cards seen, rather than nothing. The colours are the
  // strip's, drawn once as pips.
  const cards = match.opponent_signature_cards ?? []
  return cards.length > 0 ? formatList(cards) : null
}

function CandidateLine({ candidate }: { candidate: OpponentDeckCandidate }) {
  const { t } = useTranslation()
  const unseen = (candidate.signature_cards ?? []).filter((s) => !s.seen).map((s) => s.name)
  const reasons = candidate.reasons ?? []
  return (
    <div className="py-2">
      <div className="flex items-center justify-between gap-3">
        <span className="truncate text-body text-ink">{candidate.label}</span>
        <span className="shrink-0 text-caption tabular-nums text-muted">{t('live.opponent.fit', { pct: formatPercent(candidate.fit) })}</span>
      </div>
      <Meter fraction={candidate.fit} color="s1" className="mt-1" />
      {reasons.length > 0 && <p className="mt-1 text-caption text-muted">{reasons.join('; ')}</p>}
      {unseen.length > 0 && <p className="text-caption text-ink2">{t('live.opponent.stillUnseen', { cards: formatList(unseen) })}</p>}
    </div>
  )
}

/** "Pick this deck": the user's own correction of the opponent's deck,
 *  in the status strip beside the name it corrects. The popover is
 *  `fixed`-positioned, so it never clips inside the strip. */
export function PickDeckButton({ match }: { match: CurrentMatch }) {
  const { t } = useTranslation()
  const save = useSetOpponentDeck()
  const buttonRef = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)

  const pick = (candidate: { label: string; archetypeKey: string | null }) => {
    save.mutate(
      { matchId: match.match_id, label: candidate.label, archetypeKey: candidate.archetypeKey },
      { onSuccess: () => setOpen(false) },
    )
  }

  return (
    <>
      <Button ref={buttonRef} size="sm" onClick={() => setOpen(true)}>
        {t('live.opponent.pick')}
      </Button>
      {save.error && <span className="text-caption text-s2">{save.error.message}</span>}
      {open && (
        <DeckPicker
          matchId={match.match_id}
          anchorRef={buttonRef}
          onClose={() => setOpen(false)}
          onPick={pick}
          pending={save.isPending}
        />
      )}
    </>
  )
}

/**
 * The opponent's deck read for the match in progress, below what the
 * status strip says: the cards behind an unnamed deck (the name, its
 * confidence, the colours, the cards seen and the pick button are the
 * strip's), and — while nothing has clearly won yet — the field of close
 * candidates instead of a single guess dressed up as an answer. With
 * neither to show, it draws nothing.
 *
 * Replaces the old "Not sure what they are playing" card, which only
 * appeared below 'medium' confidence and, once shown, offered no more than
 * the winning guess's own name. A real match named "Dimir Harmonizer" off a
 * single generic card for twenty-odd turns while the archetype's own
 * signature creature (green) never matched the colours actually shown (pure
 * Dimir) — this panel is what would have surfaced that disagreement instead
 * of hiding it behind one confident-looking label.
 *
 * `dense` puts the candidate shortlist behind a disclosure, for the rail
 * once a game is under way.
 */
export function OpponentRead({
  match,
  dense = false,
}: {
  match: CurrentMatch
  dense?: boolean
}) {
  const { t } = useTranslation()
  const candidates = useOpponentDeckCandidates(match.match_id, true)

  const shortlist = (candidates.data ?? [])
    .filter((c) => c.confidence !== 'none')
    .slice(0, SHORTLIST_SIZE)
  // A 'high' verdict already won decisively; anything less — including a
  // named 'low'/'medium' guess, not only a genuinely unclear read — is worth
  // showing the field behind it, since a settled label still isn't a lock.
  const showShortlist =
    match.opponent_source !== 'manual' &&
    match.opponent_confidence !== 'high' &&
    shortlist.length > 0
  const detail = unclearDetail(match)
  if (!showShortlist && !detail) return null

  return (
    <Card title={t('live.opponent.title')} elevation={dense ? 2 : 1}>
      {detail && <p className="text-caption text-muted">{detail}</p>}

      {showShortlist && dense && (
        <div className={detail ? 'mt-3 border-t border-edge/50 pt-2' : undefined}>
          <Disclosure summary={t('live.opponent.candidates', { count: shortlist.length })}>
            <div className="divide-y divide-edge/50">
              {shortlist.map((c) => (
                <CandidateLine key={c.archetype_key} candidate={c} />
              ))}
            </div>
          </Disclosure>
        </div>
      )}

      {showShortlist && !dense && (
        <div className={`divide-y divide-edge/50 ${detail ? 'mt-3 border-t border-edge/50' : ''}`}>
          {shortlist.map((c) => (
            <CandidateLine key={c.archetype_key} candidate={c} />
          ))}
        </div>
      )}
    </Card>
  )
}
