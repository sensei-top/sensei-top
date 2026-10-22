import { Trans, useTranslation } from 'react-i18next'
import type { LibraryCardOut } from '../api'
import { formatPercent } from '../lib/format'
import { groupByManaValue, LANDS_HORIZONS, landsLine, nextDrawChance, UNKNOWN_MANA_VALUE } from '../lib/library'
import { Card, EmptyState, ManaCost, SectionLabel } from './ui'

const TH = 'sticky top-0 border-b border-line2 bg-surface pb-1 text-caption font-medium text-muted'
const CELL = 'whitespace-nowrap py-0.5 align-middle'

/** The lands, above the list: left out of the deck's lands, then the chance
 *  of at least one within the next draw, two and three. */
function LandsStrip({ cards, libraryCount }: { cards: LibraryCardOut[]; libraryCount: number }) {
  const { t } = useTranslation()
  const lands = landsLine(cards, libraryCount)
  return (
    <div className="mb-3 flex items-center gap-5 rounded-block bg-surface2 px-4 py-2">
      <div className="mr-auto text-body tabular-nums text-ink2">
        <Trans
          i18nKey="live.library.landsLeft"
          values={{ left: lands.left, total: lands.total }}
          components={{ strong: <span className="font-semibold text-ink" /> }}
        />
      </div>
      {LANDS_HORIZONS.map((draws, i) => (
        <div key={draws} className="text-right">
          <div className="text-chip font-semibold tracking-label text-muted">
            {draws === 1 ? t('live.library.next') : t('live.library.within', { n: draws })}
          </div>
          <div className="text-lead font-semibold tabular-nums text-ink">{formatPercent(lands.chances[i])}</div>
        </div>
      ))}
    </div>
  )
}

/** The Live page's remaining-library panel: this deck's own decklist, what is
 *  left of it. Sourced from a fresh live replay (`table/live.py`), not the
 *  projected `turns` row (`projector/live_state.py`'s module docstring has the
 *  staleness numbers).
 *
 *  The lands first, in a strip of their own with their chance over the next
 *  three draws. Then one table of the nonlands, grouped by mana value: each
 *  row its cost, its name, its copies left out of its quantity and its
 *  chance of being the next draw. A row whose copies are all seen stays,
 *  greyed, last in its group. The grouping, the lands and every chance are
 *  `lib/library.ts`. No card cap: the fresh replay costs the same either way.
 */
export function LibraryCard({
  cards,
  libraryCount,
}: {
  cards: LibraryCardOut[] | undefined
  libraryCount: number | null | undefined
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

  const groups = groupByManaValue(cards)

  return (
    <Card
      title={t('live.library.title')}
      subtitle={t('live.cardsLeft', { count: libraryCount })}
      className="flex h-full min-h-0 flex-col"
    >
      <LandsStrip cards={cards} libraryCount={libraryCount} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full border-separate border-spacing-0 text-left">
          <thead>
            <tr>
              <th scope="col" className={`${TH} w-px pr-3`}>
                <span className="sr-only">{t('live.library.colCost')}</span>
              </th>
              <th scope="col" className={`${TH} pr-3`}>
                {t('live.library.colCard')}
              </th>
              <th scope="col" className={`${TH} w-px whitespace-nowrap pr-4 text-right`}>
                {t('live.library.colLeft')}
              </th>
              <th scope="col" className={`${TH} w-px whitespace-nowrap text-right`}>
                {t('live.library.colChance')}
              </th>
            </tr>
          </thead>
          {groups.map((group) => (
            <tbody key={group.manaValue}>
              <tr>
                <th scope="rowgroup" colSpan={4} className="pb-0.5 pt-3 text-left">
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
              {group.cards.map((c: LibraryCardOut) => {
                const gone = c.left === 0
                return (
                  <tr key={c.grp_id} className={gone ? 'opacity-45' : undefined}>
                    <td className={`${CELL} pr-3 text-right leading-none`}>
                      <ManaCost cost={c.mana_cost} />
                    </td>
                    <td
                      className={`${CELL} max-w-0 truncate pr-3 text-body font-medium ${gone ? 'text-muted' : 'text-ink'}`}
                      title={c.name ?? t('live.library.unknownCard')}
                    >
                      {c.name ?? t('live.library.unknownCard')}
                    </td>
                    <td className={`${CELL} pr-4 text-right text-caption tabular-nums text-muted`}>
                      <span className={gone ? undefined : 'font-semibold text-ink2'}>{c.left}</span>/{c.quantity}
                    </td>
                    <td className={`${CELL} text-right text-body tabular-nums ${gone ? 'text-muted' : 'text-ink2'}`}>
                      {formatPercent(nextDrawChance(libraryCount, c.left))}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          ))}
        </table>
      </div>
    </Card>
  )
}
