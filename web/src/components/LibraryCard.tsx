import { useTranslation } from 'react-i18next'
import type { LibraryCardOut } from '../api'
import { formatPercent } from '../lib/format'
import { groupByManaValue, landsLine, rowChance, UNKNOWN_MANA_VALUE } from '../lib/library'
import { Card, EmptyState, SectionLabel } from './ui'

const TH = 'bg-surface pb-1 text-caption font-medium text-muted'
const CELL = 'whitespace-nowrap py-0.5 align-baseline'

/** The Live page's remaining-library panel: this deck's own decklist, what is
 *  left of it. Sourced from a fresh live replay (`table/live.py`), not the
 *  projected `turns` row (`projector/live_state.py`'s module docstring has the
 *  staleness numbers).
 *
 *  One header row (Left, Card, In 3 draws) sits over one list: a lands line
 *  first, drawn like a card row, then the nonlands grouped by mana value. The
 *  header's last column is what the old footnote said, so each figure is the
 *  chance of at least one copy within the next three draws. The grouping, the
 *  lands line and the chances are `lib/library.ts`. No card cap: the fresh
 *  replay costs the same either way.
 */
export function LibraryCard({
  cards,
  libraryCount,
  deckLands,
}: {
  cards: LibraryCardOut[] | undefined
  libraryCount: number | null | undefined
  /** The deck's land count (`keep.land_count`); null hides the total. */
  deckLands: number | null | undefined
}) {
  const { t } = useTranslation()
  if (!cards) return null
  if (libraryCount == null || (cards.length === 0 && libraryCount > 0)) {
    return (
      <Card
        title={t('live.library.title')}
        subtitle={libraryCount != null ? t('live.cardsLeft', { count: libraryCount }) : undefined}
        className="flex h-full min-h-0 flex-col"
      >
        <EmptyState message={t('live.library.empty')} />
      </Card>
    )
  }

  const lands = landsLine(cards, libraryCount, deckLands)
  const groups = groupByManaValue(cards)

  return (
    <Card
      title={t('live.library.title')}
      subtitle={t('live.cardsLeft', { count: libraryCount })}
      className="flex h-full min-h-0 flex-col"
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full border-separate border-spacing-0 text-left">
          <thead>
            <tr>
              <th scope="col" className={`${TH} sticky top-0 w-14 border-b border-line2 pr-3 text-right`}>
                {t('live.library.colLeft')}
              </th>
              <th scope="col" className={`${TH} sticky top-0 border-b border-line2 pr-3`}>
                {t('live.library.colCard')}
              </th>
              <th scope="col" className={`${TH} sticky top-0 w-px whitespace-nowrap border-b border-line2 text-right`}>
                {t('live.library.colChance')}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className={`${CELL} pr-3 pt-2 text-right text-body tabular-nums text-ink2`}>
                <span className="font-semibold text-ink">{lands.left}</span>
                {lands.total != null && `/${lands.total}`}
              </td>
              <td className={`${CELL} pr-3 pt-2 font-display text-title text-ink`}>
                {t('live.library.lands')}
              </td>
              <td className={`${CELL} pt-2 text-right text-body tabular-nums text-ink2`}>
                {formatPercent(lands.chance)}
              </td>
            </tr>
          </tbody>
          {groups.map((group) => (
            <tbody key={group.manaValue}>
              <tr>
                <th scope="rowgroup" colSpan={3} className="pb-1 pt-3 text-left">
                  <span className="flex items-center gap-2.5">
                    <SectionLabel as="span" className="whitespace-nowrap">
                      {group.manaValue === UNKNOWN_MANA_VALUE
                        ? t('live.library.costUnknown')
                        : t('live.library.mana', { mv: group.manaValue })}
                    </SectionLabel>
                    <span className="h-px flex-1 bg-edge" />
                  </span>
                </th>
              </tr>
              {group.cards.map((c: LibraryCardOut) => (
                <tr key={c.grp_id}>
                  <td className={`${CELL} pr-3 text-right text-body tabular-nums text-ink2`}>
                    <span className="font-semibold text-ink">{c.left}</span>/{c.quantity}
                  </td>
                  <td
                    className={`${CELL} max-w-0 truncate pr-3 font-display text-title text-ink`}
                    title={c.name ?? t('live.library.unknownCard')}
                  >
                    {c.name ?? t('live.library.unknownCard')}
                  </td>
                  <td className={`${CELL} text-right text-body tabular-nums text-ink2`}>
                    {formatPercent(rowChance(libraryCount, c.left))}
                  </td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </Card>
  )
}
