import { useTranslation } from 'react-i18next'
import type { SideboardCardOut, SideboardGameOut } from '../../api'
import { cardName } from '../../lib/cards'
import { CardImage } from '../CardImage'
import { Card, SectionLabel } from '../ui'

/** One list, "In" or "Out": a row per card, its small picture, then the
 *  count and the name. A card with no name on file is `cardName`'s words. */
function BoardedList({ heading, cards }: { heading: string; cards: SideboardCardOut[] }) {
  const { t } = useTranslation()
  return (
    <div>
      <SectionLabel className="mb-2">{heading}</SectionLabel>
      {cards.length === 0 ? (
        <p className="text-body text-muted">{t('matches.sideboarding.nothing')}</p>
      ) : (
        <ul className="space-y-1.5">
          {cards.map((card) => {
            const name = cardName({ card_name: card.card, grp_id: card.grp_id }, t)
            return (
              <li key={card.grp_id} className="flex items-center gap-2 text-body text-ink">
                <CardImage
                  grpId={card.grp_id}
                  name={name}
                  className="block aspect-[488/680] w-8 shrink-0 rounded-control object-contain"
                />
                <span>
                  <span className="tabular-nums">{card.n}</span> {name}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/** What changed in the deck going into one game, as it was played: two
 *  lists in ink, side by side from 48rem and one over the other under it.
 *  Draws nothing for a game with no change. */
export function SideboardingCard({ boarded }: { boarded: SideboardGameOut | undefined }) {
  const { t } = useTranslation()
  if (!boarded || (boarded.cards_in.length === 0 && boarded.cards_out.length === 0)) return null
  return (
    <Card title={t('matches.sideboarding.title')} subtitle={t('matches.sideboarding.subtitle')}>
      <div className="grid gap-4 md:grid-cols-2">
        <BoardedList heading={t('matches.sideboarding.in')} cards={boarded.cards_in} />
        <BoardedList heading={t('matches.sideboarding.out')} cards={boarded.cards_out} />
      </div>
    </Card>
  )
}
