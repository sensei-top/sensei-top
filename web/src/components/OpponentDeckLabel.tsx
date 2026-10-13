import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { useOpponentDeckCandidates, useSetOpponentDeck } from '../api'
import type { OpponentDeckCandidate } from '../api'
import { opponentLabelText } from '../lib/opponent'
import { Button, ManaPips, Meter } from './ui'

/** Magic's own term for a deck with no established archetype — always the
 *  last option, and the only one not sourced from the candidates endpoint. */
const ROGUE = 'Rogue'

export type OpponentDeckFields = {
  match_id: string
  opponent_label?: string | null
  opponent_source?: string | null
  opponent_confidence?: string | null
  opponent_cards_seen?: number
  opponent_colors?: string | null
}

const POPOVER_WIDTH = 288

/** One row in the picker: the label, a fit bar when there is real evidence
 *  behind it, and under them, in two lines at most, why it sits where it
 *  does (`reasons`, from the classifier: matched cards, a missing colour,
 *  or, for the unscored tail, the seen card that ruled it out). */
function CandidateRow({
  candidate,
  onPick,
  pending,
}: {
  candidate: OpponentDeckCandidate
  onPick: () => void
  pending: boolean
}) {
  const { t } = useTranslation()
  const reasons = candidate.reasons ?? []
  return (
    <button
      role="option"
      disabled={pending}
      onClick={onPick}
      className="flex w-full flex-col gap-1 px-3 py-1.5 text-left text-body text-ink hover:bg-plane disabled:opacity-50"
    >
      <span className="flex w-full items-center gap-2">
        <span className="truncate">{candidate.label}</span>
        {candidate.picked && (
          <span className="ml-auto shrink-0 text-chip font-semibold tracking-label text-muted">
            {t('live.picker.pickedMark')}
          </span>
        )}
      </span>
      {candidate.confidence !== 'none' && (
        <span className="block w-full">
          <Meter fraction={candidate.fit} color="s1" height="h-1" />
        </span>
      )}
      {reasons.length > 0 && (
        <span className="line-clamp-2 text-caption text-muted">{reasons.join('; ')}</span>
      )}
    </button>
  )
}

/** The ranked candidate list, portalled to `document.body` so a scrolling
 *  table or card can never clip it — positioned from the button's own
 *  bounding rect and flipped above/below to stay on screen, the same trick
 *  `CardImage`'s hover preview uses.
 *
 *  Every archetype and fallback definition for the match's format is offered,
 *  best-fit first, filterable by name — not only the classifier's own
 *  short shortlist, and not gated on the classifier being unsure: the player
 *  watched the match and a wrong 'medium' guess is exactly as correctable as
 *  a 'low' one. */
export function DeckPicker({
  matchId,
  anchorRef,
  onClose,
  onPick,
  pending,
}: {
  matchId: string
  anchorRef: RefObject<HTMLButtonElement | null>
  onClose: () => void
  onPick: (candidate: { label: string; archetypeKey: string | null }) => void
  pending: boolean
}) {
  const { t } = useTranslation()
  const { data: candidates, isLoading, error } = useOpponentDeckCandidates(matchId, true)
  const [filter, setFilter] = useState('')
  const [anchor, setAnchor] = useState<DOMRect | null>(
    () => anchorRef.current?.getBoundingClientRect() ?? null,
  )

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    // Follow the button rather than closing on scroll. The listener has to be
    // capture-phase to see scrolling inside any container between here and the
    // window, which means it also sees the candidate list scrolling inside
    // itself — so closing on scroll would have made a long list unreadable as
    // well as losing the popover on any page scroll.
    const reposition = () => setAnchor(anchorRef.current?.getBoundingClientRect() ?? null)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
    }
  }, [anchorRef, onClose])

  const needle = filter.trim().toLowerCase()
  const filtered = useMemo(
    () => (candidates ?? []).filter((c) => c.label.toLowerCase().includes(needle)),
    [candidates, needle],
  )
  const rogueMatches = needle === '' || ROGUE.toLowerCase().includes(needle)

  if (!anchor) return null

  const maxHeight = 360
  const margin = 8
  const showBelow =
    anchor.bottom + margin + maxHeight <= window.innerHeight || anchor.top - margin - maxHeight < 0
  const top = showBelow ? anchor.bottom + margin : undefined
  const bottom = showBelow ? undefined : window.innerHeight - anchor.top + margin
  const left = Math.min(
    Math.max(anchor.left, margin),
    window.innerWidth - POPOVER_WIDTH - margin,
  )

  return createPortal(
    <>
      {/* Transparent click-catcher: closes the popover on any outside click
          without needing a document-level listener that has to ignore the
          anchor button itself. */}
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div
        role="listbox"
        aria-label={t('live.picker.label')}
        className="fixed z-50 flex max-h-96 flex-col overflow-hidden rounded-card border border-edge bg-surface shadow-lift"
        style={{ top, bottom, left, width: POPOVER_WIDTH }}
      >
        {/* Inset from the popover's edge, so the app's focus ring around
            the input is not clipped by the popover. */}
        <div className="border-b border-edge p-2">
          <input
            type="text"
            autoFocus
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder={t('live.picker.filter')}
            className="w-full rounded-control bg-surface2 px-2.5 py-1.5 text-body text-ink placeholder:text-muted"
          />
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {isLoading && (
            <div className="px-3 py-2 text-caption text-muted">{t('live.picker.loading')}</div>
          )}
          {error && <div className="px-3 py-2 text-caption text-loss">{error.message}</div>}
          {!isLoading &&
            !error &&
            filtered.map((c: OpponentDeckCandidate) => (
              <CandidateRow
                key={c.archetype_key}
                candidate={c}
                pending={pending}
                onPick={() => onPick({ label: c.label, archetypeKey: c.archetype_key })}
              />
            ))}
          {!isLoading && !error && filtered.length === 0 && !rogueMatches && (
            <div className="px-3 py-2 text-caption text-muted">{t('live.picker.none', { filter })}</div>
          )}

          {rogueMatches && (
            <>
              <div className="my-1 border-t border-edge/50" />
              <button
                role="option"
                disabled={pending}
                onClick={() => onPick({ label: ROGUE, archetypeKey: null })}
                className="px-3 py-1.5 text-left text-body text-ink hover:bg-plane disabled:opacity-50"
              >
                {ROGUE}
              </button>
            </>
          )}
        </div>
      </div>
    </>,
    document.body,
  )
}

/**
 * The opponent's deck, with a way to correct it.
 *
 * Arena never tells us what they were playing, so the label is inferred from
 * the cards they revealed and is sometimes wrong or absent. Rather than hide
 * that, the component says so and lets the player — who knows exactly what
 * they just played against — pick the real answer from every deck the
 * classifier considered, ranked by how well the evidence fits. The picker is
 * always available, not only when the classifier reports low confidence: a
 * wrong 'medium' or 'high' guess is exactly as correctable as an uncertain
 * one, and hiding the button on anything but a shaky guess would leave a
 * confidently wrong label with no way back.
 */
export function OpponentDeckLabel({ match }: { match: OpponentDeckFields }) {
  const { t } = useTranslation()
  const buttonRef = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const save = useSetOpponentDeck()

  // Stable, so the picker's listeners attach once instead of being torn down
  // and re-registered on every scroll-driven re-render.
  const close = useCallback(() => setOpen(false), [])

  const label = opponentLabelText(
    match.opponent_label ?? t('common.unknownDeck'),
    match.opponent_colors,
  )

  const pick = (candidate: { label: string; archetypeKey: string | null }) => {
    save.mutate(
      { matchId: match.match_id, label: candidate.label, archetypeKey: candidate.archetypeKey },
      { onSuccess: close },
    )
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <ManaPips colors={match.opponent_colors} />
      <span>{label}</span>
      <Button ref={buttonRef} size="sm" onClick={() => setOpen(true)}>
        {t('live.picker.correct')}
      </Button>
      {save.error && <span className="text-caption text-loss">{save.error.message}</span>}
      {open && (
        <DeckPicker
          matchId={match.match_id}
          anchorRef={buttonRef}
          onClose={close}
          onPick={pick}
          pending={save.isPending}
        />
      )}
    </span>
  )
}
