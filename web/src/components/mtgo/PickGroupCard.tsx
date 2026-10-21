import { X } from 'lucide-react'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from '../../i18n'
import { useSetMtgoPicks } from '../../api'
import type { MtgoFormat, MtgoGroupList, MtgoGroupMatch, MtgoPickGroup } from '../../api'
import { formatList } from '../../lib/format'
import { prefillCaptionIn } from '../../lib/mtgoPick'
import {
  chooseFormat,
  chooseList,
  initialGroupState,
  itemsToSend,
  matchesWord,
  resultWords,
  toggleRemoved,
} from '../../lib/mtgoPicks'
import { formatCount, formatDayTime, formatShortDay, parseTimestamp } from '../../lib/time'
import { Button, Card, ErrorNote, Select } from '../ui'
import type { SelectOption } from '../ui'

/** A list's name, or the one every unnamed deck goes by. */
const listName = (list: { name?: string | null } | undefined, t: TFunction) =>
  list?.name?.trim() || t('common.unnamedDeck')

/** "Sep 27 – Oct 4", or the one day when both ends fall on it. */
function dateRange(
  first: string | null | undefined,
  last: string | null | undefined,
  now: number,
  t: TFunction,
): string | null {
  const [a, b] = [parseTimestamp(first), parseTimestamp(last)].map((ms) => (ms == null ? null : formatShortDay(ms, now)))
  if (a && b) return a === b ? a : t('mtgo.range', { from: a, to: b })
  return a ?? b
}

/** The cards a list holds of the ones played, and, for a partial group, the
 *  ones played that it lacks. */
function ListFacts({ list, partial }: { list: MtgoGroupList; partial: boolean }) {
  const { t } = useTranslation()
  const names = list.card_names ?? []
  const missing = list.missing ?? []
  return (
    <>
      {names.length > 0 && (
        <p className="text-caption text-ink2 break-words">{t('mtgo.group.played', { cards: formatList(names) })}</p>
      )}
      {partial && missing.length > 0 && (
        <p className="text-caption text-ink2 break-words">
          {t('mtgo.group.missing', {
            cards: formatList(
              missing.map((card) => (card.matches > 1 ? `${card.name} (${formatCount(card.matches)})` : card.name)),
            ),
          })}
        </p>
      )}
    </>
  )
}

/** One of the lists tied at the top, to choose for the whole group: the
 *  single pick's choice, pressed while chosen. */
function TieChoice({ list, chosen, onChoose }: { list: MtgoGroupList; chosen: boolean; onChoose: () => void }) {
  const { t } = useTranslation()
  const names = list.card_names ?? []
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
        <span className={`text-body text-ink break-words ${chosen ? 'font-medium' : ''}`}>{listName(list, t)}</span>
        {names.length > 0 && <span className="text-caption text-ink2 break-words">{formatList(names, { type: 'unit' })}</span>}
      </button>
    </li>
  )
}

/** One waiting match in the group: when, how it went, against whom, how
 *  many of its cards the chosen list holds, and the way to leave it out of
 *  this confirm. Left out, it stays, struck through, with the way back. */
function MatchRow({
  match,
  deckId,
  removed,
  onToggle,
}: {
  match: MtgoGroupMatch
  deckId: string | null
  removed: boolean
  onToggle: () => void
}) {
  const { t } = useTranslation()
  const start = parseTimestamp(match.started_at)
  const result = resultWords(match, t)
  const matched = deckId != null ? match.scores[deckId] : undefined
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
      <span
        className={`flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1 ${removed ? 'text-muted line-through' : ''}`}
      >
        <span className="text-caption text-muted tabular-nums">{start != null ? formatDayTime(start) : ''}</span>
        {result && <span className={`text-body ${removed ? '' : 'text-ink'}`}>{result}</span>}
        {match.opponent_name && (
          <span className={`min-w-0 break-words text-body ${removed ? '' : 'text-ink2'}`}>
            {t('mtgo.against', { name: match.opponent_name })}
          </span>
        )}
        {matched != null && (
          <span className="text-caption text-muted tabular-nums">
            {t('mtgo.match.cardsInList', { matched: formatCount(matched), seen: formatCount(match.cards_seen) })}
          </span>
        )}
      </span>
      {removed ? (
        <Button size="sm" variant="quiet" onClick={onToggle}>
          {t('mtgo.match.putBack')}
        </Button>
      ) : (
        <Button size="sm" variant="quiet" iconOnly aria-label={t('mtgo.match.leaveOut')} onClick={onToggle}>
          <X size={16} aria-hidden />
        </Button>
      )}
    </li>
  )
}

/** A group of waiting MTGO matches that share their best-fitting list:
 *  the list, the matches and their dates, the format with its
 *  pre-fill, the proof, the lists that came close, and the one press that
 *  confirms them all. Nothing is written until Confirm. On a
 *  tie no list is chosen and the user chooses one; any other list can be
 *  switched to. `hint` is the archetype read from the user's own cards,
 *  absent until its own request answers. */
export function PickGroupCard({
  group,
  hint,
  formats,
  now,
  onConfirmed,
}: {
  group: MtgoPickGroup
  hint: string | null | undefined
  formats: readonly SelectOption[]
  now: number
  onConfirmed: (written: number, list: string) => void
}) {
  const { t } = useTranslation()
  const save = useSetMtgoPicks()
  const [state, setState] = useState(() => initialGroupState(group))
  const [open, setOpen] = useState(false)
  const tieId = useId()

  const partial = group.fit === 'partial'
  const tied = group.proposed == null
  const chosen = group.lists.find((list) => list.deck_id === state.deckId)
  const items = itemsToSend(group, state)
  const prefillText = prefillCaptionIn(chosen?.format_prefill, chosen?.format_prefill_source, state.format, t)

  // The lists to switch to: every one that came close and, once the group
  // was switched away from it, its own top list, which was on top in every
  // one of its matches.
  const others = group.lists.filter((list) => list.deck_id !== state.deckId && !(tied && list.top))
  const tops = group.lists.filter((list) => list.top)

  const range = dateRange(group.first_started, group.last_started, now, t)
  const subtitle = [matchesWord(group.matches.length, t), range].filter(Boolean).join(' · ')

  const confirm = () => {
    if (!chosen || items.length === 0) return
    const name = listName(chosen, t)
    save.mutate(items, { onSuccess: (written) => onConfirmed(written.written, name) })
  }

  let confirmWords = t('mtgo.group.chooseFirst')
  if (save.isPending) confirmWords = t('mtgo.group.saving')
  else if (chosen) confirmWords = t('mtgo.group.confirm', { matches: matchesWord(items.length, t), list: listName(chosen, t) })

  return (
    <Card title={chosen ? listName(chosen, t) : t('mtgo.group.choose')} subtitle={subtitle}>
      <div className="space-y-4">
        {tied && (
          <div className="space-y-1">
            <p id={tieId} className="text-body text-ink2">
              {t('mtgo.group.tied')}
            </p>
            <ul aria-labelledby={tieId} className="-mx-3 space-y-0.5">
              {tops.map((list) => (
                <TieChoice
                  key={list.deck_id}
                  list={list}
                  chosen={list.deck_id === state.deckId}
                  onChoose={() => setState(chooseList(group, state, list.deck_id))}
                />
              ))}
            </ul>
          </div>
        )}

        {(chosen || (partial && hint)) && (
          <div className="space-y-1">
            {chosen && <ListFacts list={chosen} partial={partial} />}
            {partial && hint && <p className="text-caption text-ink2">{t('mtgo.hint', { hint })}</p>}
          </div>
        )}

        {others.length > 0 && (
          <ul className="space-y-2">
            {others.map((list) => (
              <li key={list.deck_id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <span className="min-w-0 flex-1 space-y-0.5">
                  <span className="block text-body text-ink break-words">
                    {t('mtgo.group.alsoClose', {
                      matches: matchesWord(list.top ? group.matches.length : list.close_in, t),
                      list: listName(list, t),
                    })}
                  </span>
                  {(list.card_names ?? []).length > 0 && (
                    <span className="block text-caption text-muted break-words">{formatList(list.card_names ?? [], { type: 'unit' })}</span>
                  )}
                </span>
                <Button size="sm" onClick={() => setState(chooseList(group, state, list.deck_id))}>
                  {t('mtgo.group.useList')}
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <Select
            label={t('mtgo.group.format')}
            placement="above"
            value={state.format ?? ''}
            onChange={(value) => setState(chooseFormat(state, value === '' ? null : (value as MtgoFormat)))}
            options={formats}
          >
            <option value="">{t('mtgo.group.notConfirmed')}</option>
          </Select>
          {prefillText && <p className="text-caption text-muted">{prefillText}</p>}
        </div>

        <div>
          <Button variant="quiet" size="sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            {open ? t('mtgo.group.hideMatches') : t('mtgo.group.showMatches')}
          </Button>
          {open && (
            <ul className="mt-2 divide-y divide-line">
              {group.matches.map((match) => (
                <MatchRow
                  key={match.match_id}
                  match={match}
                  deckId={state.deckId}
                  removed={state.removed.has(match.match_id)}
                  onToggle={() => setState(toggleRemoved(state, match.match_id))}
                />
              ))}
            </ul>
          )}
        </div>

        <Button variant="primary" disabled={!chosen || items.length === 0 || save.isPending} onClick={confirm}>
          {confirmWords}
        </Button>
        {save.error && <ErrorNote error={save.error} />}
      </div>
    </Card>
  )
}
