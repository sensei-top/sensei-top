import { useState } from 'react'
import { useFormats, useMtgoPickCandidates, useSetMtgoPick } from '../../api'
import type { MtgoDeckCandidate, MtgoFormat, MtgoPick } from '../../api'
import { UNNAMED_DECK } from '../../lib/home'
import { bodyDeckId, canConfirm, formatAfterChoosing, mtgoFormatsOf, NO_LIST, prefillCaption } from '../../lib/mtgoPick'
import { Button, Card, ErrorNote, Loading, Select } from '../ui'

const deckName = (candidate: MtgoDeckCandidate) => candidate.name?.trim() || UNNAMED_DECK

/** One deck to choose: its name, how many of the cards played in this match
 *  its list holds, and a few of its cards, since the user's exports are
 *  named by number. The chosen one is pressed. */
function CandidateOption({
  candidate,
  cardsSeen,
  chosen,
  onChoose,
}: {
  candidate: MtgoDeckCandidate
  cardsSeen: number
  chosen: boolean
  onChoose: () => void
}) {
  const names = candidate.card_names ?? []
  return (
    <li>
      <button
        type="button"
        aria-pressed={chosen}
        onClick={onChoose}
        className={`flex min-h-[44px] w-full flex-col gap-0.5 rounded-control px-3 py-2 text-left transition-chrome hover:bg-surface3 ${
          chosen ? 'bg-surface3' : ''
        }`}
      >
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className={`text-body text-ink break-words ${chosen ? 'font-medium' : ''}`}>{deckName(candidate)}</span>
          {cardsSeen > 0 && (
            <span className="text-caption text-muted tabular-nums">
              {candidate.cards_matched} of {cardsSeen} cards played
            </span>
          )}
        </span>
        {names.length > 0 && <span className="text-caption text-ink2 break-words">{names.join(', ')}</span>}
      </button>
    </li>
  )
}

/** The choice itself, mounted once the candidates have arrived so that its
 *  starting state (the existing pick, if any) is read once and never fought
 *  by a refetch. Choosing a deck pre-fills the format from the deck's
 *  `format_prefill` (the store's, else the last one confirmed for the same
 *  deck, else the one inferred from the cards revealed in this match) and
 *  says which of the three it was while it stands; the user can change it,
 *  and confirms with the button. */
function PickForm({
  matchId,
  candidates,
  cardsSeen,
  current,
  onDone,
}: {
  matchId: string
  candidates: MtgoDeckCandidate[]
  cardsSeen: number
  current: MtgoPick | null
  onDone: (() => void) | null
}) {
  const save = useSetMtgoPick()
  const formats = useFormats()
  const [deckId, setDeckId] = useState<string | null>(current?.deck_confirmed ? (current.deck_id ?? NO_LIST) : null)
  const [format, setFormat] = useState<MtgoFormat | null>(current?.format ?? null)

  const choose = (id: string) => {
    setDeckId(id)
    setFormat(formatAfterChoosing(id, candidates.find((c) => c.deck_id === id)?.format_prefill, format))
  }
  const ready = canConfirm(deckId, format)
  const chosenCandidate = candidates.find((c) => c.deck_id === deckId)
  const prefillWords = prefillCaption(chosenCandidate?.format_prefill, chosenCandidate?.format_prefill_source, format)

  const confirm = () => {
    if (!ready || deckId == null) return
    save.mutate({ matchId, deckId: bodyDeckId(deckId), format }, { onSuccess: () => onDone?.() })
  }

  return (
    <div className="space-y-4">
      <ul aria-label="Your deck" className="-mx-3 max-h-80 space-y-0.5 overflow-y-auto">
        {candidates.map((candidate) => (
          <CandidateOption
            key={candidate.deck_id}
            candidate={candidate}
            cardsSeen={cardsSeen}
            chosen={deckId === candidate.deck_id}
            onChoose={() => choose(candidate.deck_id)}
          />
        ))}
        <li>
          <button
            type="button"
            aria-pressed={deckId === NO_LIST}
            onClick={() => choose(NO_LIST)}
            className={`flex min-h-[44px] w-full flex-wrap items-baseline gap-x-2 rounded-control px-3 py-2 text-left transition-chrome hover:bg-surface3 ${
              deckId === NO_LIST ? 'bg-surface3' : ''
            }`}
          >
            <span className={`text-body text-ink ${deckId === NO_LIST ? 'font-medium' : ''}`}>No list</span>
            <span className="text-caption text-muted">confirm the format alone</span>
          </button>
        </li>
      </ul>
      <div className="flex flex-wrap items-end gap-3">
        <Select
          label="Format"
          placement="above"
          value={format ?? ''}
          onChange={(value) => setFormat(value === '' ? null : (value as MtgoFormat))}
          options={mtgoFormatsOf(formats.data).map((f) => ({ value: f, label: f }))}
        >
          <option value="">Not confirmed</option>
        </Select>
        {prefillWords && <p className="text-caption text-muted">{prefillWords}</p>}
        <Button variant="primary" disabled={!ready || save.isPending} onClick={confirm}>
          {save.isPending ? 'Saving…' : 'Confirm'}
        </Button>
        {onDone && (
          <Button variant="quiet" onClick={onDone}>
            Cancel
          </Button>
        )}
      </div>
      {save.error && <p className="text-caption text-loss">{save.error.message}</p>}
    </div>
  )
}

/** An MTGO match's deck and format, as the user confirms them. MTGO's log
 *  never names the deck, so the match waits here until the user says which
 *  of their decks it was (a list MTGO or an export gave us) and in which
 *  format, or confirms the format alone. Until then it is on Home's
 *  "Needs a deck" list and in no deck's matchups. Once confirmed it shows
 *  the answer, with a way to change it. */
export function MtgoDeckPick({ matchId }: { matchId: string }) {
  const { data, isPending, error } = useMtgoPickCandidates(matchId, true)
  const [editing, setEditing] = useState(false)

  if (isPending) return <Loading />
  if (error) return <ErrorNote error={error} />

  const current = data.current ?? null
  const confirmed = current?.deck_confirmed === true
  if (confirmed && !editing) {
    const deck = current.deck_id != null ? data.candidates.find((c) => c.deck_id === current.deck_id) : null
    const parts = [
      current.deck_id == null ? 'No list' : deck ? deckName(deck) : UNNAMED_DECK,
      current.format ?? 'Format not confirmed',
    ]
    return (
      <Card
        title="Your deck"
        action={
          <Button size="sm" onClick={() => setEditing(true)}>
            Change
          </Button>
        }
      >
        <p className="text-body text-ink">{parts.join(' · ')}</p>
      </Card>
    )
  }

  return (
    <Card
      title="Which deck was this?"
      subtitle="MTGO's log does not say which deck you played. Pick yours and its format so this match counts toward it."
    >
      <PickForm
        matchId={matchId}
        candidates={data.candidates}
        cardsSeen={data.cards_seen}
        current={current}
        onDone={confirmed ? () => setEditing(false) : null}
      />
    </Card>
  )
}
