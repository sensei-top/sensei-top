import { useTranslation } from 'react-i18next'
import type { CardVerdictOut, DeckGuideOut, GuideNarrativeOut } from '../../api'
import { archetypeName } from '../../lib/decks'
import { copiesLine, differSentence, inLineSummary, listGroups, verdictLabel } from '../../lib/guide'
import { formatCount } from '../../lib/time'
import { Callout, Card, Chip, Disclosure, EmptyState, Prose, SectionLabel } from '../ui'

/** One card of a board: its name, and beside it the verdict's word when
 *  it differs from the field; under it what the viewer and the field play;
 *  under that the written guide's note on the card, when it has one. */
function CardRow({ card, note }: { card: CardVerdictOut; note: string | undefined }) {
  const { t } = useTranslation()
  const label = verdictLabel(card.verdict, t)
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="min-w-0 break-words text-body font-medium text-ink">{card.card}</span>
        {label && <Chip size="sm">{label}</Chip>}
      </div>
      <p className="mt-0.5 text-caption text-muted tabular-nums">{copiesLine(card, t)}</p>
      {note && (
        <div className="mt-2 text-left">
          <Prose text={note} />
        </div>
      )}
    </li>
  )
}

function CardRows({ cards, noteByCard }: { cards: CardVerdictOut[]; noteByCard: Record<string, string> }) {
  return (
    <ul className="divide-y divide-line">
      {cards.map((card) => (
        <CardRow key={card.card} card={card} note={noteByCard[card.card]} />
      ))}
    </ul>
  )
}

/** A board: its label, the sentence counting the cards that differ from
 *  the field, those cards, and the cards in line with the field one click
 *  away. Each group keeps the server's order. */
function Board({
  label,
  cards,
  noteByCard,
}: {
  label: string
  cards: CardVerdictOut[]
  noteByCard: Record<string, string>
}) {
  const { t } = useTranslation()
  const { differing, inLine } = listGroups(cards)
  return (
    <div>
      <SectionLabel>{label}</SectionLabel>
      <p className="mt-1 text-caption text-muted">{differSentence(differing.length, cards.length, t)}</p>
      {differing.length > 0 && <CardRows cards={differing} noteByCard={noteByCard} />}
      {inLine.length > 0 && (
        <div className={differing.length > 0 ? 'mt-1' : 'mt-3'}>
          <Disclosure summary={inLineSummary(inLine.length, t)}>
            <CardRows cards={inLine} noteByCard={noteByCard} />
          </Disclosure>
        </div>
      )}
    </div>
  )
}

/** The deck's 75 against the winning lists of its archetype
 *  (`guide/list_diff.py`), board by board. A card's note is the written
 *  guide's, found by the card's name. */
export function TheListCard({ guide, narrative }: { guide: DeckGuideOut; narrative: GuideNarrativeOut | undefined }) {
  const { t } = useTranslation()
  const diff = guide.list_diff
  const noteByCard: Record<string, string> = {}
  for (const note of narrative?.card_notes ?? []) noteByCard[note.card] = note.why

  let subtitle: string | undefined
  if (diff) {
    const counts = {
      lists: t('decks.guide.list.winningLists', { count: diff.winning_decks, n: formatCount(diff.winning_decks) }),
      archetype: archetypeName(diff.archetype_name),
      wins: t('decks.guide.list.wins', { count: diff.min_wins, n: formatCount(diff.min_wins) }),
    }
    subtitle = guide.provenance.reset
      ? t('decks.guide.list.subtitleReset', counts)
      : t('decks.guide.list.subtitle', counts)
  }

  return (
    <Card title={t('decks.guide.list.title')} subtitle={subtitle}>
      {!diff ? (
        <EmptyState
          title={t('decks.guide.list.noArchetype.title')}
          message={t('decks.guide.list.noArchetype.message')}
        />
      ) : (
        <div className="space-y-6">
          <Board label={t('decks.guide.list.maindeck')} cards={diff.maindeck} noteByCard={noteByCard} />
          <Board label={t('decks.guide.list.sideboard')} cards={diff.sideboard} noteByCard={noteByCard} />
          {diff.duplicate_warnings.length > 0 && (
            <Callout tone="warn" title={t('decks.guide.list.duplicates')}>
              <div className="space-y-2">
                {diff.duplicate_warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            </Callout>
          )}
        </div>
      )}
    </Card>
  )
}
