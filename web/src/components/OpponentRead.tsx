import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useOpponentDeckCandidates, useSetOpponentDeck } from '../api'
import type { CurrentMatch, OpponentDeckCandidate } from '../api'
import type { TFunction } from '../i18n'
import { confidenceLabel } from '../lib/opponent'
import { DeckPicker } from './OpponentDeckLabel'
import { Button, Card, Disclosure, Meter } from './ui'

// Enough to show real disagreement without turning into the full candidate
// list — rank_candidates() already orders these best-fit first.
const SHORTLIST_SIZE = 3

function headerText(match: CurrentMatch, t: TFunction): string {
  const label = match.opponent_label ?? t('common.unknownDeck')
  if (match.opponent_source === 'manual') return t('live.opponent.picked', { label })
  // 'corpus' is classify.py's second evidence source (archetypes/corpus.py)
  // naming the same way an 'archetype'/'fallback' rule verdict does —
  // confidence means the same thing across all three, so it reads the same.
  if (
    match.opponent_source === 'archetype' ||
    match.opponent_source === 'fallback' ||
    match.opponent_source === 'corpus'
  ) {
    return t('live.opponent.withConfidence', {
      label,
      confidence: confidenceLabel(match.opponent_confidence ?? 'unknown', t),
    })
  }
  // No candidate cleared the naming bar (see classify.py's choose()): the
  // label here is only the colours-and-signature-card fallback, so it is
  // shown as exactly that, not dressed up as a settled answer.
  return t('live.opponent.unclear', { label })
}

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
  // say — the colours already shown, and up to three real cards, rather
  // than nothing.
  const cards = match.opponent_signature_cards ?? []
  if (!match.opponent_colors && cards.length === 0) return null
  const bits: string[] = []
  if (match.opponent_colors) bits.push(match.opponent_colors)
  if (cards.length > 0) bits.push(cards.join(', '))
  return bits.join(' · ')
}

function CandidateLine({ candidate }: { candidate: OpponentDeckCandidate }) {
  const { t } = useTranslation()
  const unseen = (candidate.signature_cards ?? []).filter((s) => !s.seen).map((s) => s.name)
  const reasons = candidate.reasons ?? []
  const fitPct = Math.round(candidate.fit * 100)
  return (
    <div className="py-2">
      <div className="flex items-center justify-between gap-3">
        <span className="truncate text-body text-ink">{candidate.label}</span>
        <span className="shrink-0 text-caption tabular-nums text-muted">{t('live.opponent.fit', { pct: fitPct })}</span>
      </div>
      <Meter fraction={candidate.fit} color="s1" className="mt-1" />
      {reasons.length > 0 && <p className="mt-1 text-caption text-muted">{reasons.join('; ')}</p>}
      {unseen.length > 0 && <p className="text-caption text-ink2">{t('live.opponent.stillUnseen', { cards: unseen.join(', ') })}</p>}
    </div>
  )
}

/**
 * The opponent's deck read for the match in progress: a state-dependent
 * headline (picked by you / a settled name at some confidence / unclear),
 * the "pick this deck" affordance always available beside it, and — while
 * nothing has clearly won yet — the field of close candidates instead of a
 * single guess dressed up as an answer.
 *
 * Replaces the old "Not sure what they are playing" card, which only
 * appeared below 'medium' confidence and, once shown, offered no more than
 * the winning guess's own name. A real match named "Dimir Harmonizer" off a
 * single generic card for twenty-odd turns while the archetype's own
 * signature creature (green) never matched the colours actually shown (pure
 * Dimir) — this panel is what would have surfaced that disagreement instead
 * of hiding it behind one confident-looking label.
 *
 * `dense` puts the candidate shortlist behind a disclosure for the closing
 * three-card grid — the headline and the "pick this deck" popover (already
 * `fixed`-positioned, so it never clips inside a height-capped rail) stay
 * exactly as they are.
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
  const save = useSetOpponentDeck()
  const buttonRef = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)

  const pick = (candidate: { label: string; archetypeKey: string | null }) => {
    save.mutate(
      { matchId: match.match_id, label: candidate.label, archetypeKey: candidate.archetypeKey },
      { onSuccess: () => setOpen(false) },
    )
  }

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

  return (
    <Card
      title={t('live.opponent.title')}
      subtitle={t('live.cardsSeen', { count: match.opponent_cards_seen })}
      elevation={dense ? 2 : 1}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-display text-title text-ink">{headerText(match, t)}</p>
          {detail && <p className="mt-1 text-caption text-muted">{detail}</p>}
        </div>
        <Button ref={buttonRef} size="sm" onClick={() => setOpen(true)}>
          {t('live.opponent.pick')}
        </Button>
      </div>
      {save.error && <p className="mt-2 text-caption text-s2">{save.error.message}</p>}

      {showShortlist && dense && (
        <div className="mt-3 border-t border-edge/50 pt-2">
          <Disclosure
            summary={t('live.opponent.candidates', { count: shortlist.length })}
          >
            <div className="divide-y divide-edge/50">
              {shortlist.map((c) => (
                <CandidateLine key={c.archetype_key} candidate={c} />
              ))}
            </div>
          </Disclosure>
        </div>
      )}

      {showShortlist && !dense && (
        <div className="mt-3 divide-y divide-edge/50 border-t border-edge/50">
          {shortlist.map((c) => (
            <CandidateLine key={c.archetype_key} candidate={c} />
          ))}
        </div>
      )}

      {open && (
        <DeckPicker
          matchId={match.match_id}
          anchorRef={buttonRef}
          onClose={() => setOpen(false)}
          onPick={pick}
          pending={save.isPending}
        />
      )}
    </Card>
  )
}
