import { useTranslation } from 'react-i18next'
import type { PastBoardingCardOut, PastBoardingGameOut, PastBoardingOut } from '../api'
import type { TFunction } from '../i18n'
import { cardName } from '../lib/cards'
import { formatList } from '../lib/format'
import { SectionLabel } from './ui'

function resultWord(result: string | null | undefined, t: TFunction): string {
  switch (result) {
    case undefined:
    case null:
    case '':
      return t('matchups.sideboard.result.unresolved')
    case 'win':
      return t('matchups.sideboard.result.win')
    case 'loss':
      return t('matchups.sideboard.result.loss')
    case 'draw':
      return t('matchups.sideboard.result.draw')
    default:
      return result
  }
}

/** Never a bare grpId (`lib/cards.ts`'s rule, applied to the differently
 *  named `card` field `PastBoardingCardOut` carries instead of
 *  `card_name`) — plus a dagger flag for a card since cut from the current
 *  75, never dropped (rule 4). */
function pastCardLabel(c: PastBoardingCardOut, t: TFunction): string {
  const name = cardName({ card_name: c.card, grp_id: c.grp_id }, t)
  return c.in_current_75 ? name : `${name}†`
}

function formatDelta(g: PastBoardingGameOut, t: TFunction): string {
  const out = formatList(g.board_out.map((c) => `−${c.n} ${pastCardLabel(c, t)}`), { type: 'unit' })
  const inn = formatList(g.board_in.map((c) => `+${c.n} ${pastCardLabel(c, t)}`), { type: 'unit' })
  return [out, inn].filter(Boolean).join(' ')
}

/** One compact line per prior match: the boarding delta (deduplicated when
 *  a later game's board didn't change from the one before it — the common
 *  case, since most Bo3s only reboard once) followed by every game's own
 *  result. */
function pastBoardingLine(entry: PastBoardingOut, t: TFunction): string {
  const deltas: string[] = []
  let last = ''
  for (const g of entry.games) {
    const d = formatDelta(g, t)
    if (d && d !== last) {
      deltas.push(d)
      last = d
    }
  }
  const results = formatList(
    entry.games.map((g) => t('matchups.sideboard.gameResult', { n: g.game_number, result: resultWord(g.result, t) })),
    { type: 'unit' },
  )
  return [deltas.join('; '), results].filter(Boolean).join(' · ')
}

function hasCutCard(entries: PastBoardingOut[]): boolean {
  return entries.some((e) =>
    e.games.some((g) => [...g.board_in, ...g.board_out].some((c) => !c.in_current_75))
  )
}

/** This deck's own earlier boarding against an archetype, one line per
 *  match, never advice, just a fact from ``game_decks``. `heading` is the
 *  title drawn above the lines (an `h4`); without it the caller's own title
 *  stands above the list. Live passes "Last time vs …"; it is the primary
 *  content under a written plan's absence there (S4/S8). */
export function PastBoardingList({ entries, heading }: { entries: PastBoardingOut[]; heading?: string }) {
  const { t } = useTranslation()
  if (entries.length === 0) return null
  return (
    <div>
      {heading && <SectionLabel as="h4">{heading}</SectionLabel>}
      <ul className="mt-1 space-y-1 text-caption text-ink2">
        {entries.map((entry) => (
          <li key={entry.match_id}>{pastBoardingLine(entry, t)}</li>
        ))}
      </ul>
      <p className="mt-1 text-caption text-muted">
        {hasCutCard(entries) ? t('matchups.sideboard.pastNoteCut') : t('matchups.sideboard.pastNote')}
      </p>
    </div>
  )
}
